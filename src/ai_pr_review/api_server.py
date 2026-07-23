"""轻量 REST API 服务 — 基于 asyncio 原生 HTTP server

设计目标：
- 纯标准库 asyncio.start_server 实现，避免引入 Flask/FastAPI 重依赖
- 提供 REST API 供外部系统（CI/CD、聊天机器人）触发审查
- 同时挂载 webhook 端点，一个服务多用途
- 路由与处理器解耦，便于测试

API 端点：
- POST /api/review        触发 PR 审查（body: {"pr_url": "..."}）
- GET  /api/history       查询审查历史
- GET  /api/health        健康检查
- POST /webhook           GitHub Webhook 入口
"""
import asyncio
import json
import logging
import urllib.parse
from typing import Awaitable, Callable

from ai_pr_review.webhook import WebhookHandler

logger = logging.getLogger(__name__)

# 默认监听端口
DEFAULT_HOST = "0.0.0.0"
DEFAULT_PORT = 8000


class APIRouter:
    """路由分发器 — 将 HTTP 请求分发到对应处理器

    路由键为 (method, path) 元组，处理器签名为 async (headers, body) -> (status, body_dict)
    """

    def __init__(self):
        # 用 dict 而非链表匹配，O(1) 查找（性能优化）
        self._routes: dict[tuple[str, str], Callable] = {}

    def add_route(self, method: str, path: str, handler: Callable):
        self._routes[(method.upper(), path)] = handler

    def match(self, method: str, path: str) -> Callable | None:
        return self._routes.get((method.upper(), path))


def _build_response(status: int, body: dict | list | str) -> bytes:
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
    }.get(status, "OK")

    headers = [
        f"HTTP/1.1 {status} {status_text}",
        f"Content-Type: {content_type}",
        f"Content-Length: {len(payload)}",
        "Connection: close",
    ]
    head = "\r\n".join(headers) + "\r\n\r\n"
    return head.encode("utf-8") + payload


def _parse_request(raw: bytes) -> tuple[str, str, dict[str, str], bytes] | None:
    """解析 HTTP 请求，返回 (method, path, headers, body) 或 None（格式错误）"""
    try:
        # 分割头部与 body
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
    # 先读头部直到 \r\n\r\n
    try:
        head_data = await reader.readuntil(b"\r\n\r\n")
    except (asyncio.IncompleteReadError, ConnectionError):
        return None

    # 解析 Content-Length
    head_str = head_data.decode("iso-8859-1")
    content_length = 0
    for line in head_str.split("\r\n")[1:]:
        if line.lower().startswith("content-length:"):
            try:
                content_length = int(line.split(":", 1)[1].strip())
            except ValueError:
                content_length = 0
            break

    # 读取剩余 body
    body = await reader.readexactly(content_length) if content_length > 0 else b""
    return head_data + body


def build_router(
    review_fn: Callable[[str], Awaitable[None]],
    history_fn: Callable[[], list] | None = None,
    webhook_secret: str = "",
) -> APIRouter:
    """构建 API 路由器

    review_fn: 异步审查回调，接收 pr_url
    history_fn: 可选同步函数，返回历史记录列表
    webhook_secret: GitHub Webhook 签名密钥
    """
    router = APIRouter()

    async def handle_review(headers, body) -> tuple[int, dict]:
        try:
            data = json.loads(body.decode("utf-8"))
        except (json.JSONDecodeError, UnicodeDecodeError):
            return 400, {"error": "invalid JSON body"}

        pr_url = data.get("pr_url", "").strip()
        if not pr_url:
            return 400, {"error": "pr_url is required"}

        # 异步触发审查，立即返回 202
        asyncio.create_task(_safe_review(review_fn, pr_url))
        return 202, {"status": "accepted", "pr_url": pr_url}

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
        return 200, {"status": "ok", "service": "ai-pr-review-api"}

    webhook_handler = WebhookHandler(review_fn, secret=webhook_secret)

    async def handle_webhook(headers, body) -> tuple[int, dict]:
        # 适配大小写 header
        normalized = {k.lower(): v for k, v in headers.items()}
        return await webhook_handler.handle(normalized, body)

    router.add_route("POST", "/api/review", handle_review)
    router.add_route("GET", "/api/history", handle_history)
    router.add_route("GET", "/api/health", handle_health)
    router.add_route("POST", "/webhook", handle_webhook)
    return router


async def _safe_review(review_fn: Callable, pr_url: str) -> None:
    """安全执行审查回调，异常不向外抛"""
    try:
        await review_fn(pr_url)
    except Exception as e:
        logger.error(f"API-triggered review failed for {pr_url}: {e}", exc_info=True)


async def handle_connection(
    reader: asyncio.StreamReader,
    writer: asyncio.StreamWriter,
    router: APIRouter,
) -> None:
    """处理单个 TCP 连接"""
    try:
        raw = await _read_request(reader)
        if raw is None:
            return

        parsed = _parse_request(raw)
        if parsed is None:
            writer.write(_build_response(400, {"error": "bad request"}))
            await writer.drain()
            return

        method, path, headers, body = parsed
        handler = router.match(method, path)
        if handler is None:
            writer.write(_build_response(404, {"error": "not found", "path": path}))
            await writer.drain()
            return

        try:
            status, resp_body = await handler(headers, body)
            writer.write(_build_response(status, resp_body))
        except Exception as e:
            logger.error(f"Handler error for {method} {path}: {e}", exc_info=True)
            writer.write(_build_response(500, {"error": "internal server error"}))
        await writer.drain()
    except (ConnectionError, asyncio.IncompleteReadError):
        pass
    finally:
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
