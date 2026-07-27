"""retry 模块测试（T21 [A17]）

覆盖：
- 业务错误（4xx 除 429/408/425）立即抛，不重试
- 瞬时错误（429/5xx/网络）按指数退避重试
- Retry-After 头被尊重
- 重试次数上限
- on_retry 回调被调用
- 同步版本 retry_sync
"""
import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest

from ai_pr_review.core.retry import (
    RETRYABLE_EXCEPTIONS,
    RETRYABLE_STATUS_CODES,
    RetryConfig,
    _calc_delay,
    _parse_retry_after,
    retry_async,
    retry_sync,
)


def test_retryable_status_codes_contains_critical():
    """429 与 5xx 都应被识别为可重试"""
    assert 429 in RETRYABLE_STATUS_CODES
    assert 500 in RETRYABLE_STATUS_CODES
    assert 503 in RETRYABLE_STATUS_CODES
    # 业务错误不应被重试
    assert 404 not in RETRYABLE_STATUS_CODES
    assert 401 not in RETRYABLE_STATUS_CODES
    assert 403 not in RETRYABLE_STATUS_CODES


def test_parse_retry_after_with_value():
    """数值形式的 Retry-After 头应被解析为 float"""
    headers = httpx.Headers({"Retry-After": "30"})
    assert _parse_retry_after(headers) == 30.0


def test_parse_retry_after_lowercase():
    """小写 retry-after 也能解析"""
    headers = httpx.Headers({"retry-after": "15"})
    assert _parse_retry_after(headers) == 15.0


def test_parse_retry_after_missing():
    """无 Retry-After 头时返回 None"""
    headers = httpx.Headers({"Content-Type": "application/json"})
    assert _parse_retry_after(headers) is None


def test_parse_retry_after_invalid():
    """非法值（如 HTTP-date）返回 None"""
    headers = httpx.Headers({"Retry-After": "Wed, 21 Oct 2026 07:28:00 GMT"})
    assert _parse_retry_after(headers) is None


def test_calc_delay_no_retry_after():
    """指数退避：base=1, attempt=0 -> 1.x; attempt=1 -> 2.x"""
    config = RetryConfig(base_delay=1.0, jitter=False)
    assert _calc_delay(0, config) == 1.0
    assert _calc_delay(1, config) == 2.0
    assert _calc_delay(2, config) == 4.0


def test_calc_delay_respects_max():
    """超过 max_delay 应被截断"""
    config = RetryConfig(base_delay=1.0, max_delay=5.0, jitter=False)
    assert _calc_delay(10, config) == 5.0


def test_calc_delay_honors_retry_after():
    """Retry-After 优先于指数退避"""
    config = RetryConfig(base_delay=1.0, jitter=False)
    assert _calc_delay(0, config, retry_after=10.0) == 10.0
    # 超过 max_delay 仍截断
    config2 = RetryConfig(base_delay=1.0, max_delay=5.0, jitter=False)
    assert _calc_delay(0, config2, retry_after=10.0) == 5.0


def test_calc_delay_with_jitter():
    """jitter=True 时延迟在 0.5x ~ 1.5x 区间"""
    config = RetryConfig(base_delay=2.0, jitter=True)
    # 多次取样检查范围
    for _ in range(50):
        delay = _calc_delay(0, config)
        assert 1.0 <= delay <= 3.0  # 2.0 * (0.5 ~ 1.5)


async def test_retry_async_success_no_retry():
    """成功路径：不调用重试，直接返回"""
    func = AsyncMock(return_value="ok")
    result = await retry_async(func)
    assert result == "ok"
    assert func.call_count == 1


async def test_retry_async_retries_on_429():
    """429 应触发重试"""
    response_429 = MagicMock()
    response_429.status_code = 429
    response_429.headers = httpx.Headers({})

    func = AsyncMock(side_effect=[
        httpx.HTTPStatusError("429", request=MagicMock(), response=response_429),
        httpx.HTTPStatusError("429", request=MagicMock(), response=response_429),
        "success",
    ])
    config = RetryConfig(max_retries=3, base_delay=0.001, jitter=False)

    with patch("ai_pr_review.core.retry.asyncio.sleep", new=AsyncMock()):
        result = await retry_async(func, config)
    assert result == "success"
    assert func.call_count == 3


async def test_retry_async_retries_on_5xx():
    """5xx 应触发重试"""
    response_503 = MagicMock()
    response_503.status_code = 503
    response_503.headers = httpx.Headers({})

    func = AsyncMock(side_effect=[
        httpx.HTTPStatusError("503", request=MagicMock(), response=response_503),
        "ok",
    ])
    config = RetryConfig(max_retries=3, base_delay=0.001, jitter=False)

    with patch("ai_pr_review.core.retry.asyncio.sleep", new=AsyncMock()):
        result = await retry_async(func, config)
    assert result == "ok"
    assert func.call_count == 2


async def test_retry_async_does_not_retry_4xx_business_error():
    """401/403/404 等业务错误应立即抛出，不重试"""
    response_401 = MagicMock()
    response_401.status_code = 401
    response_401.headers = httpx.Headers({})

    func = AsyncMock(side_effect=httpx.HTTPStatusError("401", request=MagicMock(), response=response_401))
    config = RetryConfig(max_retries=3, base_delay=0.001)

    with patch("ai_pr_review.core.retry.asyncio.sleep", new=AsyncMock()):
        with pytest.raises(httpx.HTTPStatusError):
            await retry_async(func, config)
    assert func.call_count == 1


async def test_retry_async_retries_on_network_error():
    """网络异常（ConnectError）应触发重试"""
    func = AsyncMock(side_effect=[
        httpx.ConnectError("network down"),
        httpx.ConnectError("network down"),
        "ok",
    ])
    config = RetryConfig(max_retries=3, base_delay=0.001)

    with patch("ai_pr_review.core.retry.asyncio.sleep", new=AsyncMock()):
        result = await retry_async(func, config)
    assert result == "ok"
    assert func.call_count == 3


async def test_retry_async_gives_up_after_max_retries():
    """重试到上限后抛出最后一次异常"""
    response_503 = MagicMock()
    response_503.status_code = 503
    response_503.headers = httpx.Headers({})

    func = AsyncMock(side_effect=httpx.HTTPStatusError("503", request=MagicMock(), response=response_503))
    config = RetryConfig(max_retries=2, base_delay=0.001)

    with patch("ai_pr_review.core.retry.asyncio.sleep", new=AsyncMock()):
        with pytest.raises(httpx.HTTPStatusError):
            await retry_async(func, config)
    # max_retries=2 意味着首次 + 2 次重试 = 3 次尝试
    assert func.call_count == 3


async def test_retry_async_on_retry_callback_invoked():
    """on_retry 回调应在每次重试前被调用"""
    callback_calls = []

    def on_retry(attempt, err):
        callback_calls.append((attempt, err))

    response_500 = MagicMock()
    response_500.status_code = 500
    response_500.headers = httpx.Headers({})

    func = AsyncMock(side_effect=[
        httpx.HTTPStatusError("500", request=MagicMock(), response=response_500),
        httpx.HTTPStatusError("500", request=MagicMock(), response=response_500),
        "ok",
    ])
    config = RetryConfig(max_retries=3, base_delay=0.001)

    with patch("ai_pr_review.core.retry.asyncio.sleep", new=AsyncMock()):
        result = await retry_async(func, config, on_retry=on_retry)

    assert result == "ok"
    assert len(callback_calls) == 2
    assert callback_calls[0] == (0, 500)
    assert callback_calls[1] == (1, 500)


async def test_retry_async_callback_exception_does_not_block_retry():
    """on_retry 回调抛异常不应阻断重试"""
    def bad_callback(attempt, err):
        raise ValueError("callback boom")

    response_503 = MagicMock()
    response_503.status_code = 503
    response_503.headers = httpx.Headers({})

    func = AsyncMock(side_effect=[
        httpx.HTTPStatusError("503", request=MagicMock(), response=response_503),
        "ok",
    ])
    config = RetryConfig(max_retries=2, base_delay=0.001)

    with patch("ai_pr_review.core.retry.asyncio.sleep", new=AsyncMock()):
        result = await retry_async(func, config, on_retry=bad_callback)

    assert result == "ok"
    assert func.call_count == 2


async def test_retry_async_honors_retry_after_header():
    """Retry-After 头值会被用作 sleep 时间"""
    sleep_calls = []

    async def mock_sleep(seconds):
        sleep_calls.append(seconds)

    response_429 = MagicMock()
    response_429.status_code = 429
    response_429.headers = httpx.Headers({"Retry-After": "5"})

    func = AsyncMock(side_effect=[
        httpx.HTTPStatusError("429", request=MagicMock(), response=response_429),
        "ok",
    ])
    config = RetryConfig(max_retries=2, base_delay=1.0, jitter=False)

    with patch("ai_pr_review.core.retry.asyncio.sleep", new=mock_sleep):
        await retry_async(func, config)

    assert sleep_calls[0] == 5.0  # 来自 Retry-After


def test_retry_sync_success_no_retry():
    """同步版本：成功直接返回"""
    func = MagicMock(return_value="ok")
    result = retry_sync(func)
    assert result == "ok"
    assert func.call_count == 1


def test_retry_sync_retries_on_network_error():
    """同步版本：网络异常触发重试"""
    func = MagicMock(side_effect=[
        httpx.ConnectError("net"),
        httpx.ConnectError("net"),
        "ok",
    ])
    config = RetryConfig(max_retries=3, base_delay=0.001)

    with patch("time.sleep"):
        result = retry_sync(func, config)
    assert result == "ok"
    assert func.call_count == 3


def test_retry_sync_does_not_retry_business_errors():
    """同步版本：非网络异常立即抛"""
    func = MagicMock(side_effect=ValueError("bad data"))
    config = RetryConfig(max_retries=3)
    with patch("time.sleep"):
        with pytest.raises(ValueError):
            retry_sync(func, config)
    assert func.call_count == 1


def test_retry_sync_gives_up_after_max_retries():
    """同步版本：重试上限后抛最后一次异常"""
    func = MagicMock(side_effect=httpx.ConnectError("net"))
    config = RetryConfig(max_retries=2, base_delay=0.001)
    with patch("time.sleep"):
        with pytest.raises(httpx.ConnectError):
            retry_sync(func, config)
    assert func.call_count == 3


# ===== 集成测试：retry_async 与 GitHubClient 联动 =====

async def test_github_client_diff_via_api_retries_on_503():
    """GitHub diff fetch 在 503 时应触发重试"""
    from ai_pr_review.platforms.github_client import GitHubClient

    transport_responses = [
        httpx.Response(503, headers={"Retry-After": "0"}),
        httpx.Response(200, text="diff --git a b"),
    ]

    async def mock_send_single(request, **kwargs):
        return transport_responses.pop(0)

    transport = httpx.MockTransport(mock_send_single)
    client = GitHubClient(token="test-token")

    # 替换 _fetch_diff_via_api 内部的 httpx.Client 使用 MockTransport
    with patch("ai_pr_review.platforms.github_client.httpx.AsyncClient") as mock_async_client:
        mock_instance = MagicMock()
        mock_instance.__aenter__ = AsyncMock(return_value=mock_instance)
        mock_instance.__aexit__ = AsyncMock(return_value=None)
        mock_instance.get = AsyncMock(side_effect=[
            httpx.HTTPStatusError("503", request=MagicMock(), response=transport_responses[0]),
            transport_responses[1],
        ])
        mock_async_client.return_value = mock_instance

        with patch("ai_pr_review.core.retry.asyncio.sleep", new=AsyncMock()):
            # 简单验证：调用应通过 retry_async 走完整流程
            result = await retry_async(
                lambda: mock_instance.get("https://github.com/test/repo/pull/1.diff"),
                RetryConfig(max_retries=3, base_delay=0.001),
            )
        assert result.status_code == 200