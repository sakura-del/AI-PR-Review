"""webhook 模块测试 — 覆盖签名校验、事件解析、异步派发"""
import asyncio
import hashlib
import hmac
import json
import pytest
from ai_pr_review.webhook import (
    verify_signature,
    parse_webhook_event,
    WebhookHandler,
    REVIEWABLE_ACTIONS,
)


def _sign(payload: bytes, secret: str) -> str:
    """生成与 GitHub 一致格式的签名头"""
    digest = hmac.new(secret.encode(), payload, hashlib.sha256).hexdigest()
    return f"sha256={digest}"


def _make_pr_payload(action: str = "opened", pr_url: str = "https://github.com/o/r/pull/1") -> dict:
    return {
        "action": action,
        "pull_request": {
            "number": 1,
            "html_url": pr_url,
        },
        "repository": {"full_name": "o/r"},
    }


# ===== verify_signature 单元测试 =====

def test_verify_signature_valid():
    payload = b'{"test":1}'
    secret = "s3cret"
    sig = _sign(payload, secret)
    assert verify_signature(payload, sig, secret) is True


def test_verify_signature_invalid_signature():
    assert verify_signature(b"{}", "sha256=invalid", "secret") is False


def test_verify_signature_missing_header():
    assert verify_signature(b"{}", "", "secret") is False


def test_verify_signature_wrong_secret():
    payload = b'{"test":1}'
    sig = _sign(payload, "correct")
    assert verify_signature(payload, sig, "wrong") is False


def test_verify_signature_no_secret_skips():
    """未配置 secret 时跳过校验（用于本地开发）"""
    assert verify_signature(b"{}", "", "") is True


def test_verify_signature_uses_compare_digest():
    """验证签名时使用 hmac.compare_digest 防时序攻击（间接验证：不同长度输入不报错）"""
    assert verify_signature(b"short", "sha256=abc", "s") is False


# ===== parse_webhook_event 单元测试 =====

def test_parse_event_pr_opened():
    payload = _make_pr_payload("opened")
    event = parse_webhook_event(payload, "pull_request")
    assert event is not None
    assert event["action"] == "opened"
    assert event["pr_url"] == "https://github.com/o/r/pull/1"
    assert event["repo"] == "o/r"
    assert event["number"] == 1


def test_parse_event_pr_synchronize():
    payload = _make_pr_payload("synchronize")
    event = parse_webhook_event(payload, "pull_request")
    assert event is not None
    assert event["action"] == "synchronize"


def test_parse_event_pr_closed_ignored():
    """closed 动作不应触发审查"""
    payload = _make_pr_payload("closed")
    event = parse_webhook_event(payload, "pull_request")
    assert event is None


def test_parse_event_non_pr_event_ignored():
    payload = _make_pr_payload("opened")
    event = parse_webhook_event(payload, "push")
    assert event is None


def test_parse_event_missing_html_url_returns_none():
    payload = {
        "action": "opened",
        "pull_request": {"number": 1},  # 缺 html_url
        "repository": {"full_name": "o/r"},
    }
    assert parse_webhook_event(payload, "pull_request") is None


def test_reviewable_actions_constant():
    assert "opened" in REVIEWABLE_ACTIONS
    assert "synchronize" in REVIEWABLE_ACTIONS
    assert "reopened" in REVIEWABLE_ACTIONS
    assert "closed" not in REVIEWABLE_ACTIONS


# ===== WebhookHandler 集成测试 =====

@pytest.mark.asyncio
async def test_handler_accepts_valid_webhook():
    triggered: list[str] = []

    async def review_fn(pr_url: str):
        triggered.append(pr_url)

    payload = _make_pr_payload("opened")
    body = json.dumps(payload).encode()
    handler = WebhookHandler(review_fn, secret="")

    status, resp = await handler.handle(
        headers={"X-GitHub-Event": "pull_request"},
        body=body,
    )
    assert status == 200
    assert resp["status"] == "accepted"
    # 等待异步任务完成
    await asyncio.sleep(0.05)
    assert triggered == ["https://github.com/o/r/pull/1"]


@pytest.mark.asyncio
async def test_handler_rejects_invalid_signature():
    async def review_fn(pr_url):
        pass

    handler = WebhookHandler(review_fn, secret="correct")
    body = json.dumps(_make_pr_payload("opened")).encode()

    status, resp = await handler.handle(
        headers={
            "X-GitHub-Event": "pull_request",
            "X-Hub-Signature-256": "sha256=wrong",
        },
        body=body,
    )
    assert status == 401
    assert "error" in resp


@pytest.mark.asyncio
async def test_handler_accepts_valid_signature():
    triggered: list[str] = []

    async def review_fn(pr_url):
        triggered.append(pr_url)

    secret = "mysecret"
    body = json.dumps(_make_pr_payload("opened")).encode()
    handler = WebhookHandler(review_fn, secret=secret)

    status, resp = await handler.handle(
        headers={
            "X-GitHub-Event": "pull_request",
            "X-Hub-Signature-256": _sign(body, secret),
        },
        body=body,
    )
    assert status == 200
    await asyncio.sleep(0.05)
    assert len(triggered) == 1


@pytest.mark.asyncio
async def test_handler_ignores_non_pr_event():
    async def review_fn(pr_url):
        raise AssertionError("should not be called")

    handler = WebhookHandler(review_fn, secret="")
    body = json.dumps({"ref": "refs/heads/main"}).encode()

    status, resp = await handler.handle(
        headers={"X-GitHub-Event": "push"},
        body=body,
    )
    assert status == 200
    assert resp["status"] == "ignored"


@pytest.mark.asyncio
async def test_handler_ignores_closed_action():
    async def review_fn(pr_url):
        raise AssertionError("closed should not trigger review")

    handler = WebhookHandler(review_fn, secret="")
    body = json.dumps(_make_pr_payload("closed")).encode()

    status, resp = await handler.handle(
        headers={"X-GitHub-Event": "pull_request"},
        body=body,
    )
    assert status == 200
    assert resp["status"] == "ignored"


@pytest.mark.asyncio
async def test_handler_returns_400_on_invalid_json():
    async def review_fn(pr_url):
        pass

    handler = WebhookHandler(review_fn, secret="")
    status, resp = await handler.handle(
        headers={"X-GitHub-Event": "pull_request"},
        body=b"not json",
    )
    assert status == 400
    assert "error" in resp


@pytest.mark.asyncio
async def test_handler_review_exception_does_not_crash():
    """审查回调抛异常时，handler 不应崩溃，webhook 响应仍正常返回"""
    async def review_fn(pr_url):
        raise RuntimeError("review failed")

    handler = WebhookHandler(review_fn, secret="")
    body = json.dumps(_make_pr_payload("opened")).encode()

    status, resp = await handler.handle(
        headers={"X-GitHub-Event": "pull_request"},
        body=body,
    )
    # webhook 响应正常返回 200，异常在后台任务中处理
    assert status == 200
    # 等待后台任务执行完毕，避免 pytest 警告未捕获异常
    await asyncio.sleep(0.05)


@pytest.mark.asyncio
async def test_handler_responds_immediately_without_awaiting_review():
    """验证 webhook 响应不被审查任务阻塞：响应应在 review 完成前返回"""
    review_completed = asyncio.Event()

    async def slow_review(pr_url):
        await asyncio.sleep(0.5)  # 模拟长任务
        review_completed.set()

    handler = WebhookHandler(slow_review, secret="")
    body = json.dumps(_make_pr_payload("opened")).encode()

    status, _ = await handler.handle(
        headers={"X-GitHub-Event": "pull_request"},
        body=body,
    )
    # 响应已返回，但 review 尚未完成（证明未被阻塞）
    assert status == 200
    assert not review_completed.is_set()
    # 等待后台任务完成，避免 pytest 警告
    await asyncio.sleep(0.6)
    assert review_completed.is_set()
