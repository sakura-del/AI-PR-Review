"""轻量 REST API 服务 — 基于 asyncio 原生 HTTP server

设计目标：
- 纯标准库 asyncio.start_server 实现，避免引入 Flask/FastAPI 重依赖
- 提供 REST API 供外部系统（CI/CD、聊天机器人）触发审查
- 同时挂载 webhook 端点，一个服务多用途
- 路由与处理器解耦，便于测试
- 支持路径参数（如 /api/jobs/{job_id}）

API 端点：
- POST /api/review            提交 PR 审查，返回 job_id
- GET  /api/jobs/{job_id}     查询任务状态与结果
- GET  /api/history           查询审查历史
- GET  /api/health            健康检查
- POST /webhook               GitHub Webhook 入口
"""
import asyncio
import json
import re
import time
import logging
import urllib.parse
from typing import Awaitable, Callable, Optional

from ai_pr_review.data.job_queue import JobStatus
from ai_pr_review.server.job_queue_runtime import InMemoryJobQueue, configure_job_queue
from ai_pr_review.core.metrics import get_registry
from ai_pr_review.core.degradation import get_degradation_manager
from ai_pr_review.server.webhook import WebhookHandler

logger = logging.getLogger(__name__)

# 默认监听端口
DEFAULT_HOST = "0.0.0.0"
DEFAULT_PORT = 8000


class APIRouter:
    """路由分发器 — 将 HTTP 请求分发到对应处理器

    支持路径参数：
    - add_route("GET", "/api/jobs/{job_id}", handler) 中 {job_id} 视为命名捕获组
    - match 返回 (handler, path_params) 元组，path_params 是 dict
    - 路径参数会作为 kwargs 传给 handler（与 headers、body 一起）
    """

    def __init__(self):
        # 按注册顺序存储（精确路径优先于含参路径可由注册顺序控制）
        self._routes: list[tuple[str, re.Pattern, Callable, list[str]]] = []

    def add_route(self, method: str, path: str, handler: Callable) -> None:
        pattern, param_names = _path_to_regex(path)
        self._routes.append((method.upper(), pattern, handler, param_names))

    def match(self, method: str, path: str) -> tuple[Optional[Callable], dict]:
        """返回 (handler, path_params)；未匹配返回 (None, {})"""
        for m, pattern, handler, param_names in self._routes:
            if m != method.upper():
                continue
            match = pattern.match(path)
            if match:
                return handler, match.groupdict()
        return None, {}


def _path_to_regex(path: str) -> tuple[re.Pattern, list[str]]:
    """将 '/api/jobs/{id}' 转成正则 + 命名捕获组

    策略：
    1. 用 split 拆出静态片段与参数名
    2. 静态片段 re.escape；参数位置替换为 (?P<name>[^/]+)
    3. 拼接为完整正则

    Returns:
        (compiled pattern, param_names in declaration order)
    """
    # split 出 [static, param, static, param, ...]；偶数下标是静态片段
    parts = re.split(r"\{(\w+)\}", path)
    param_names = parts[1::2]
    regex_parts = []
    for i, segment in enumerate(parts):
        if i % 2 == 0:
            # 静态片段需转义
            regex_parts.append(re.escape(segment))
        else:
            # 参数位置：命名捕获组
            regex_parts.append(f"(?P<{segment}>[^/]+)")
    return re.compile("^" + "".join(regex_parts) + "$"), param_names


def _build_response(
    status: int,
    body: dict | list | str,
    extra_headers: list[str] | None = None,
) -> bytes:
    """构造 HTTP 响应字节流"""
    if isinstance(body, str):
        payload = body.encode("utf-8")
        content_type = "text/plain; charset=utf-8"
    else:
        payload = json.dumps(body, ensure_ascii=False).encode("utf-8")
        content_type = "application/json; charset=utf-8"

    status_text = {
        200: "OK", 201: "Created", 202: "Accepted",
        400: "Bad Request", 401: "Unauthorized", 404: "Not Found",
        405: "Method Not Allowed", 500: "Internal Server Error",
        503: "Service Unavailable",
    }.get(status, "OK")

    headers = [
        f"HTTP/1.1 {status} {status_text}",
        f"Content-Type: {content_type}",
        f"Content-Length: {len(payload)}",
        "Connection: close",
    ]
    if extra_headers:
        headers.extend(extra_headers)
    head = "\r\n".join(headers) + "\r\n\r\n"
    return head.encode("utf-8") + payload


def _parse_request(raw: bytes) -> tuple[str, str, dict[str, str], bytes] | None:
    """解析 HTTP 请求，返回 (method, path, headers, body) 或 None（格式错误）"""
    try:
        header_end = raw.find(b"\r\n\r\n")
        if header_end == -1:
            return None
        head_part = raw[:header_end].decode("iso-8859-1")
        body = raw[header_end + 4:]

        lines = head_part.split("\r\n")
        request_line = lines[0]
        parts = request_line.split(" ")
        if len(parts) < 2:
            return None
        method, path = parts[0], parts[1]
        # 去掉 query string（路由只匹配 path 部分）
        path = path.split("?", 1)[0]

        headers: dict[str, str] = {}
        for line in lines[1:]:
            if ":" in line:
                key, _, value = line.partition(":")
                headers[key.strip()] = value.strip()
        return method, path, headers, body
    except (UnicodeDecodeError, IndexError):
        return None


async def _read_request(reader: asyncio.StreamReader) -> bytes | None:
    """读取完整 HTTP 请求（含 body）

    通过 Content-Length 判断 body 边界，避免 hang 住
    """
    try:
        head_data = await reader.readuntil(b"\r\n\r\n")
    except (asyncio.IncompleteReadError, ConnectionError):
        return None

    head_str = head_data.decode("iso-8859-1")
    content_length = 0
    for line in head_str.split("\r\n")[1:]:
        if line.lower().startswith("content-length:"):
            try:
                content_length = int(line.split(":", 1)[1].strip())
            except ValueError:
                content_length = 0
            break

    body = await reader.readexactly(content_length) if content_length > 0 else b""
    return head_data + body


def _job_to_response_dict(job_dict: dict) -> dict:
    """把 Job.to_dict() 转为 API 响应字典（保留 result 字段原样）"""
    return {
        "job_id": job_dict.get("id"),
        "pr_url": job_dict.get("pr_url"),
        "status": job_dict.get("status"),
        "progress": job_dict.get("progress"),
        "error": job_dict.get("error"),
        "created_at": job_dict.get("created_at"),
        "started_at": job_dict.get("started_at"),
        "finished_at": job_dict.get("finished_at"),
        "result": job_dict.get("result"),
    }


def build_router(
    review_fn: Callable[[str], Awaitable[object]],
    history_fn: Callable[[], list] | None = None,
    webhook_secret: str = "",
    job_queue: InMemoryJobQueue | None = None,
) -> APIRouter:
    """构建 API 路由器

    Args:
        review_fn: 异步审查回调，接收 pr_url，返回 AnalysisResult 或 None
        history_fn: 可选同步函数，返回历史记录列表
        webhook_secret: GitHub Webhook 签名密钥
        job_queue: 可选外部 JobQueue 实例；不传则内部创建一个并 configure 为单例

    Returns:
        APIRouter 实例
    """
    router = APIRouter()

    # JobQueue：复用外部传入或内部创建
    if job_queue is None:
        job_queue = InMemoryJobQueue(handler=review_fn)
        configure_job_queue(job_queue)

    async def handle_review(headers, body) -> tuple[int, dict] | tuple[int, dict, list[str]]:
        # Level 3 降级：AI 服务不可用，直接拒绝新请求
        if get_degradation_manager().current_level() >= 3:
            logger.warning("Reject /api/review due to degradation level 3")
            return 503, {"error": "AI service degraded, please retry later", "level": 3}, ["Retry-After: 60"]

        try:
            data = json.loads(body.decode("utf-8"))
        except (json.JSONDecodeError, UnicodeDecodeError):
            return 400, {"error": "invalid JSON body"}

        pr_url = data.get("pr_url", "").strip()
        if not pr_url:
            return 400, {"error": "pr_url is required"}

        # 通过 JobQueue 提交，立即返回 202 + job_id
        job = await job_queue.submit(pr_url)
        return 202, {
            "job_id": job.id,
            "status": job.status.value,
            "pr_url": job.pr_url,
        }

    async def handle_job_status(job_id: str, **_) -> tuple[int, dict]:
        """GET /api/jobs/{job_id} — 查询任务状态

        接收 _ 占位 kwargs（headers/body 等由 router 统一传入）
        """
        job = await job_queue.get(job_id)
        if job is None:
            return 404, {"error": "job not found", "job_id": job_id}
        return 200, _job_to_response_dict(job.to_dict())

    async def handle_history(headers, body) -> tuple[int, dict | list]:
        if history_fn is None:
            return 200, []
        try:
            records = history_fn()
            return 200, records
        except Exception as e:
            logger.error(f"Failed to load history: {e}")
            return 500, {"error": "failed to load history"}

    async def handle_health(headers, body) -> tuple[int, dict]:
        return 200, {
            "status": "ok",
            "service": "ai-pr-review-api",
            "jobs": {
                "pending": job_queue.pending_count,
                "running": job_queue.running_count,
            },
        }

    webhook_handler = WebhookHandler(job_queue.submit, secret=webhook_secret)

    async def handle_webhook(headers, body) -> tuple[int, dict]:
        normalized = {k.lower(): v for k, v in headers.items()}
        return await webhook_handler.handle(normalized, body)

    router.add_route("POST", "/api/review", handle_review)
    router.add_route("GET", "/api/jobs/{job_id}", handle_job_status)
    router.add_route("GET", "/api/history", handle_history)
    router.add_route("GET", "/api/health", handle_health)
    router.add_route("POST", "/webhook", handle_webhook)
    return router


async def handle_connection(
    reader: asyncio.StreamReader,
    writer: asyncio.StreamWriter,
    router: APIRouter,
) -> None:
    """处理单个 TCP 连接

    路由匹配后调用 handler；handler 接收 path params (kwargs) + headers + body
    """
    registry = get_registry()
    start_time = time.perf_counter()
    method, path, status = "", "", 0
    try:
        raw = await _read_request(reader)
        if raw is None:
            return

        parsed = _parse_request(raw)
        if parsed is None:
            status = 400
            writer.write(_build_response(status, {"error": "bad request"}))
            await writer.drain()
            return

        method, path, headers, body = parsed
        handler, path_params = router.match(method, path)
        if handler is None:
            status = 404
            writer.write(_build_response(status, {"error": "not found", "path": path}))
            await writer.drain()
            return

        try:
            # 调用约定：
            # - 无 path params：handler(headers, body) 位置参数（旧 handlers 兼容）
            # - 有 path params：handler(headers=..., body=..., **path_params)（新 handlers）
            if path_params:
                result = await handler(headers=headers, body=body, **path_params)
            else:
                result = await handler(headers, body)
            if len(result) == 3:
                status, resp_body, extra_headers = result
            else:
                status, resp_body = result
                extra_headers = None
            writer.write(_build_response(status, resp_body, extra_headers=extra_headers))
        except TypeError as e:
            # handler 签名不匹配
            status = 500
            logger.error(f"Handler signature error for {method} {path}: {e}")
            writer.write(_build_response(status, {"error": "internal server error"}))
        except Exception as e:
            status = 500
            logger.error(f"Handler error for {method} {path}: {e}", exc_info=True)
            writer.write(_build_response(status, {"error": "internal server error"}))
        await writer.drain()
    except (ConnectionError, asyncio.IncompleteReadError):
        pass
    finally:
        if method and path and status:
            duration = time.perf_counter() - start_time
            registry.counter(
                "http_requests_total", labels=("method", "path", "status")
            ).inc(method=method, path=path, status=str(status))
            registry.histogram("http_request_duration_seconds").observe(duration)
        writer.close()
        try:
            await writer.wait_closed()
        except (ConnectionError, OSError):
            pass


async def serve(
    router: APIRouter,
    host: str = DEFAULT_HOST,
    port: int = DEFAULT_PORT,
) -> asyncio.base_events.Server:
    """启动 HTTP 服务器，返回 Server 对象（可被 await/cancel）

    用法：
        server = await serve(router, port=8000)
        await server.serve_forever()
    """
    server = await asyncio.start_server(
        lambda r, w: handle_connection(r, w, router),
        host=host,
        port=port,
    )
    logger.info(f"API server listening on {host}:{port}")
    return server