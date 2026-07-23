"""GitHub Webhook 处理器 — 监听 pull_request 事件自动触发审查

设计目标：
- 纯标准库实现，避免引入 Flask/FastAPI 重依赖
- 仅处理 pull_request 事件中的 opened/synchronize/reopened 动作
- Webhook secret 签名校验（HMAC-SHA256），防止伪造请求
- 触发审查为异步任务，不阻塞 webhook 响应
"""
import asyncio
import hashlib
import hmac
import json
import logging
from typing import Awaitable, Callable

logger = logging.getLogger(__name__)

# 触发审查的 PR 动作白名单（其余动作忽略，避免冗余审查）
REVIEWABLE_ACTIONS = {"opened", "synchronize", "reopened"}


def verify_signature(payload: bytes, signature_header: str, secret: str) -> bool:
    """校验 GitHub Webhook 签名（HMAC-SHA256）

    GitHub 头部格式：sha256=<hex>
    使用 hmac.compare_digest 防止时序攻击
    """
    if not secret:
        logger.warning("Webhook secret not configured, skipping signature verification")
        return True
    if not signature_header or not signature_header.startswith("sha256="):
        return False
    expected = hmac.new(
        secret.encode("utf-8"), payload, hashlib.sha256
    ).hexdigest()
    received = signature_header.removeprefix("sha256=")
    return hmac.compare_digest(expected, received)


def parse_webhook_event(
    payload: dict, event_type: str
) -> dict | None:
    """解析 webhook payload，返回标准化的事件信息

    仅处理 pull_request 事件且动作在白名单内，返回：
      {"pr_url": str, "action": str, "repo": str, "number": int}
    其他事件返回 None
    """
    if event_type != "pull_request":
        return None

    action = payload.get("action", "")
    if action not in REVIEWABLE_ACTIONS:
        return None

    pr = payload.get("pull_request") or {}
    repo = payload.get("repository") or {}
    html_url = pr.get("html_url") or ""
    if not html_url:
        return None

    return {
        "pr_url": html_url,
        "action": action,
        "repo": repo.get("full_name", ""),
        "number": pr.get("number", 0),
    }


class WebhookHandler:
    """Webhook 事件处理器 — 解析事件并异步触发审查回调

    review_fn: 异步回调，接收 pr_url 参数执行实际审查
    """

    def __init__(
        self,
        review_fn: Callable[[str], Awaitable[None]],
        secret: str = "",
    ):
        self._review_fn = review_fn
        self._secret = secret

    async def handle(
        self,
        headers: dict[str, str],
        body: bytes,
    ) -> tuple[int, dict]:
        """处理 webhook 请求

        返回 (status_code, response_body) 供 HTTP server 使用
        """
        event_type = headers.get("X-GitHub-Event", "")
        signature = headers.get("X-Hub-Signature-256", "")

        # 签名校验
        if not verify_signature(body, signature, self._secret):
            logger.warning("Webhook signature verification failed")
            return 401, {"error": "invalid signature"}

        # 解析 payload
        try:
            payload = json.loads(body.decode("utf-8"))
        except (json.JSONDecodeError, UnicodeDecodeError) as e:
            logger.warning(f"Failed to parse webhook payload: {e}")
            return 400, {"error": "invalid payload"}

        event_info = parse_webhook_event(payload, event_type)
        if event_info is None:
            # 非目标事件，返回 200 但不做处理
            return 200, {"status": "ignored", "event": event_type}

        # 异步触发审查（不 await，立即响应 webhook）
        asyncio.create_task(self._dispatch_review(event_info))
        return 200, {
            "status": "accepted",
            "pr_url": event_info["pr_url"],
            "action": event_info["action"],
        }

    async def _dispatch_review(self, event_info: dict) -> None:
        """异步派发审查任务，异常不向外抛（避免 task 被静默销毁）"""
        try:
            await self._review_fn(event_info["pr_url"])
        except Exception as e:
            logger.error(
                f"Webhook-triggered review failed for {event_info['pr_url']}: {e}",
                exc_info=True,
            )
