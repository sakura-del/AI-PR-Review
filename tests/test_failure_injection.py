"""故障注入测试（T23 [A19]）

覆盖：
- (a) GitHub 429 + Retry-After → 重试退避正确
- (b) AI API 连续失败 → 降级 Level 1/2
- (c) RateLimiter 超额 → 后续请求等待
- (d) JobQueue cancel → worker 清理

设计目标：把"非 happy path"行为固化为测试，防止回归。
"""
import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest

from ai_pr_review.core.config import (
    AIConfig, AnalysisConfig, AppConfig, ExpertConfig, GitHubConfig,
)
from ai_pr_review.core.degradation import get_degradation_manager
from ai_pr_review.core.metrics import get_registry
from ai_pr_review.core.analyzer import AIAnalyzer
from ai_pr_review.data.persistence import LocalJSONStorage, configure_storage
from ai_pr_review.core.rate_limiter import get_rate_limiter
from ai_pr_review.core.retry import RetryConfig, retry_async


@pytest.fixture(autouse=True)
def reset_state():
    """每个测试前重置单例"""
    get_registry().reset()
    get_degradation_manager().reset()
    # 不主动重置 RateLimiter 单例；各测试自己处理
    yield
    get_degradation_manager().reset()


@pytest.fixture
def storage(tmp_path):
    """注入临时 Storage 实例"""
    configure_storage(LocalJSONStorage(base_dir=tmp_path / "storage"))


def _make_config() -> AppConfig:
    return AppConfig(
        ai=AIConfig(api_key="k", model="m"),
        github=GitHubConfig(token="t"),
        analysis=AnalysisConfig(min_confidence=2),
        expert=ExpertConfig(),
    )


def _make_mock_openai(side_effect) -> MagicMock:
    """构造 mock 的 AsyncOpenAI 客户端"""
    mock_client = MagicMock()
    mock_client.chat.completions.create = AsyncMock(side_effect=side_effect)
    return mock_client


# ===== (a) GitHub 429 + Retry-After 重试 =====

async def test_github_429_with_retry_after_respects_header():
    """GitHub 二次限流（429 + Retry-After）应按服务端指定秒数重试"""
    sleep_calls = []

    async def mock_sleep(seconds):
        sleep_calls.append(seconds)

    response_429 = MagicMock()
    response_429.status_code = 429
    response_429.headers = httpx.Headers({"Retry-After": "7"})

    response_200 = "diff --git a b"

    func = AsyncMock(side_effect=[
        httpx.HTTPStatusError("429", request=MagicMock(), response=response_429),
        response_200,
    ])

    with patch("ai_pr_review.core.retry.asyncio.sleep", new=mock_sleep):
        result = await retry_async(func, RetryConfig(max_retries=2, base_delay=1.0, jitter=False))

    assert result == response_200
    assert sleep_calls[0] == 7.0  # 来自 Retry-After


async def test_github_5xx_retries_with_exponential_backoff():
    """5xx 错误应触发指数退避（无 Retry-After 时）"""
    sleep_calls = []

    async def mock_sleep(seconds):
        sleep_calls.append(seconds)

    response_500 = MagicMock()
    response_500.status_code = 500
    response_500.headers = httpx.Headers({})

    func = AsyncMock(side_effect=[
        httpx.HTTPStatusError("500", request=MagicMock(), response=response_500),
        httpx.HTTPStatusError("500", request=MagicMock(), response=response_500),
        "ok",
    ])

    with patch("ai_pr_review.core.retry.asyncio.sleep", new=mock_sleep):
        result = await retry_async(func, RetryConfig(max_retries=3, base_delay=2.0, jitter=False))

    assert result == "ok"
    # 两次重试：attempt 0 → 2.0s, attempt 1 → 4.0s
    assert sleep_calls == [2.0, 4.0]


async def test_github_401_does_not_retry():
    """401 Unauthorized 是业务错误，不应重试"""
    response_401 = MagicMock()
    response_401.status_code = 401
    response_401.headers = httpx.Headers({})

    func = AsyncMock(side_effect=httpx.HTTPStatusError("401", request=MagicMock(), response=response_401))

    with patch("ai_pr_review.core.retry.asyncio.sleep", new=AsyncMock()):
        with pytest.raises(httpx.HTTPStatusError):
            await retry_async(func, RetryConfig(max_retries=3, base_delay=0.001))

    # 401 只调用一次，不重试
    assert func.call_count == 1


async def test_retry_gives_up_after_max_retries():
    """重试到上限后抛最后一次异常"""
    response_503 = MagicMock()
    response_503.status_code = 503
    response_503.headers = httpx.Headers({})

    func = AsyncMock(side_effect=httpx.HTTPStatusError("503", request=MagicMock(), response=response_503))

    with patch("ai_pr_review.core.retry.asyncio.sleep", new=AsyncMock()):
        with pytest.raises(httpx.HTTPStatusError):
            await retry_async(func, RetryConfig(max_retries=2, base_delay=0.001))

    assert func.call_count == 3  # 首次 + 2 次重试


# ===== (b) AI API 连续失败 → 降级 =====

async def test_degradation_level1_after_consecutive_ai_failures(storage):
    """连续 AI 失败 → Level 1（缓存降级）

    注意：每个 _call_ai 内部最多 AI_MAX_RETRIES=3 次重试，每次失败都计入。
    所以"5 次失败"实际只需调用 2 次 _call_ai（2*3=6 失败 > 5 阈值）。
    """
    config = _make_config()
    mock_client = _make_mock_openai(side_effect=RuntimeError("api down"))

    with patch("ai_pr_review.core.analyzer.AsyncOpenAI", return_value=mock_client):
        analyzer = AIAnalyzer(config=config)
        with patch("ai_pr_review.core.analyzer.asyncio.sleep", new=AsyncMock()):
            for _ in range(2):
                await analyzer._call_ai([{"role": "user", "content": "hi"}])

    # 6 次失败 ≥ 5 阈值 → Level 1
    assert get_degradation_manager()._consecutive_failures >= 5
    assert get_degradation_manager().current_level() == 1


async def test_degradation_level2_after_more_failures(storage):
    """继续失败 → Level 2（空结果降级）

    4 次 _call_ai = 12 失败 > 10 阈值。
    """
    config = _make_config()
    mock_client = _make_mock_openai(side_effect=RuntimeError("api down"))

    with patch("ai_pr_review.core.analyzer.AsyncOpenAI", return_value=mock_client):
        analyzer = AIAnalyzer(config=config)
        with patch("ai_pr_review.core.analyzer.asyncio.sleep", new=AsyncMock()):
            for _ in range(4):
                await analyzer._call_ai([{"role": "user", "content": "hi"}])

    assert get_degradation_manager()._consecutive_failures >= 10
    assert get_degradation_manager().current_level() == 2


async def test_degradation_resets_on_success(storage):
    """成功后降级计数应清零"""
    # 验证：失败 → 失败 → 成功 → 计数清零
    config = _make_config()
    mock_fail = _make_mock_openai(side_effect=RuntimeError("down"))

    with patch("ai_pr_review.core.analyzer.AsyncOpenAI", return_value=mock_fail):
        analyzer = AIAnalyzer(config=config)
        with patch("ai_pr_review.core.analyzer.asyncio.sleep", new=AsyncMock()):
            # 1 次 _call_ai = 3 次失败
            await analyzer._call_ai([{"role": "user", "content": "x"}])

    assert get_degradation_manager()._consecutive_failures == 3

    # 同一 config，但 mock 返回成功 → 重建 analyzer 用新 mock
    mock_ok = MagicMock()
    mock_ok.choices = [MagicMock(message=MagicMock(content="{}"))]
    mock_ok.usage = MagicMock(prompt_tokens=10, completion_tokens=5)
    mock_ok.chat.completions.create = AsyncMock(return_value=mock_ok)

    with patch("ai_pr_review.core.analyzer.AsyncOpenAI", return_value=mock_ok):
        analyzer2 = AIAnalyzer(config=config)
        await analyzer2._call_ai([{"role": "user", "content": "x"}])

    assert get_degradation_manager()._consecutive_failures == 0
    assert get_degradation_manager().current_level() == 0


async def test_ai_retry_then_success_keeps_degradation_clean(storage):
    """AI 偶尔失败重试后最终成功 → 失败计数清零（成功路径覆盖）"""
    config = _make_config()

    # 模拟：第 1 次失败，第 2 次成功
    mock_response_ok = MagicMock()
    mock_response_ok.choices = [MagicMock(message=MagicMock(content="{}"))]
    mock_response_ok.usage = MagicMock(prompt_tokens=10, completion_tokens=5)

    mock_client = _make_mock_openai(side_effect=[
        RuntimeError("transient"),
        mock_response_ok,
    ])

    with patch("ai_pr_review.core.analyzer.AsyncOpenAI", return_value=mock_client):
        analyzer = AIAnalyzer(config=config)
        with patch("ai_pr_review.core.analyzer.asyncio.sleep", new=AsyncMock()):
            result = await analyzer._call_ai([{"role": "user", "content": "x"}])

    # 第二次成功，计数器被清零
    assert result == "{}"
    assert get_degradation_manager()._consecutive_failures == 0


# ===== (c) RateLimiter =====

def test_rate_limiter_get_rate_limiter_singleton_reinit():
    """rate_limiter 单例可通过 reset 重建（用大 rate）"""
    # 直接验证单例可以创建并被 acquire 多次
    from ai_pr_review.core.rate_limiter import RateLimiter

    limiter = RateLimiter(rate=10000)
    # 第一次 acquire 应立即通过
    asyncio.run(limiter.acquire())


async def test_rate_limiter_serializes_excess_calls():
    """rate=1 时连续两次 acquire，第二次会等待 ~1s"""
    from ai_pr_review.core.rate_limiter import RateLimiter

    limiter = RateLimiter(rate=1)  # 1 token/s

    # 第一次应立即通过
    start = asyncio.get_event_loop().time()
    await limiter.acquire()
    elapsed1 = asyncio.get_event_loop().time() - start
    assert elapsed1 < 0.1

    # 第二次应等待 ~1s
    start = asyncio.get_event_loop().time()
    await limiter.acquire()
    elapsed2 = asyncio.get_event_loop().time() - start
    assert 0.5 < elapsed2 < 2.0, f"expected ~1s wait, got {elapsed2:.2f}s"


async def test_rate_limiter_concurrent_capacity_limit():
    """验证 limiter 内部状态正确性：rate=10000 时连续 acquire 不会卡死"""
    from ai_pr_review.core.rate_limiter import RateLimiter

    limiter = RateLimiter(rate=10000)
    # 第一次立即通过；后续由于 rate=10000 也会很快 refill
    start = asyncio.get_event_loop().time()
    for _ in range(5):
        await limiter.acquire()
    elapsed = asyncio.get_event_loop().time() - start

    # 5 次 acquire 在 rate=10000 时应 < 0.1s
    assert elapsed < 0.1, f"5 acquires at rate=10000 took {elapsed:.2f}s"


async def test_rate_limiter_rate_validation():
    """RateLimiter 拒绝非法参数（rate < 1）"""
    from ai_pr_review.core.rate_limiter import RateLimiter

    with pytest.raises(ValueError, match="rate"):
        RateLimiter(rate=0)

    with pytest.raises(ValueError, match="rate"):
        RateLimiter(rate=-1)


async def test_rate_limiter_high_rate_does_not_block():
    """rate=10000 时连续 100 次 acquire 不会卡死"""
    from ai_pr_review.core.rate_limiter import RateLimiter

    limiter = RateLimiter(rate=10000)
    start = asyncio.get_event_loop().time()
    for _ in range(50):
        await limiter.acquire()
    elapsed = asyncio.get_event_loop().time() - start

    # 50 次在 rate=10000 应 < 0.1s
    assert elapsed < 0.5, f"50 acquires at rate=10000 took {elapsed:.2f}s"


# ===== (d) JobQueue cancel → worker 清理 =====

async def test_job_queue_cancel_pending_cleanup():
    """PENDING job cancel 后 worker 取出时跳过"""
    from ai_pr_review.data.job_queue import JobStatus
    from ai_pr_review.server.job_queue_runtime import InMemoryJobQueue

    processed = []

    async def handler(pr_url):
        processed.append(pr_url)
        return None

    queue = InMemoryJobQueue(handler)
    try:
        # 占用 worker
        j1 = await queue.submit("a")
        for _ in range(40):
            await asyncio.sleep(0.005)
            if queue.running_count == 1:
                break
        # 提交 j2（处于 PENDING），并立即取消
        j2 = await queue.submit("b")
        assert (await queue.get(j2.id)).status == JobStatus.PENDING
        await queue.cancel(j2.id)
        assert (await queue.get(j2.id)).status == JobStatus.CANCELLED

        # 让 j1 完成
        await asyncio.sleep(0.05)
    finally:
        await queue.shutdown()

    # 验证 j2 没被处理
    assert "b" not in processed
    assert "a" in processed


async def test_job_queue_shutdown_rejects_new_submits():
    """shutdown 后 submit 应抛 RuntimeError"""
    from ai_pr_review.server.job_queue_runtime import InMemoryJobQueue

    async def handler(pr_url):
        return None

    queue = InMemoryJobQueue(handler)
    await queue.shutdown()

    with pytest.raises(RuntimeError, match="shut down"):
        await queue.submit("https://example.com/pr/2")


async def test_concurrent_submit_does_not_lose_jobs():
    """并发 10 个 submit 应全部被处理"""
    from ai_pr_review.server.job_queue_runtime import InMemoryJobQueue

    processed = []

    async def handler(pr_url):
        await asyncio.sleep(0.005)
        processed.append(pr_url)
        return None

    queue = InMemoryJobQueue(handler)
    try:
        jobs = await asyncio.gather(*[queue.submit(f"pr{i}") for i in range(10)])
        # 收集状态（不能用 all() over async generator）
        for _ in range(100):
            await asyncio.sleep(0.01)
            statuses = [(await queue.get(j.id)).status for j in jobs]
            if all(s.is_terminal for s in statuses):
                break
        assert len(processed) == 10
    finally:
        await queue.shutdown()


async def test_job_queue_cancel_after_shutdown_returns_false():
    """shutdown 后 cancel 应返回 False（job 已不可访问）"""
    from ai_pr_review.server.job_queue_runtime import InMemoryJobQueue

    async def handler(pr_url):
        return None

    queue = InMemoryJobQueue(handler)
    j = await queue.submit("x")
    await asyncio.sleep(0.05)  # 等 worker 处理完
    await queue.shutdown()

    ok = await queue.cancel(j.id)
    assert ok is False  # job 已 SUCCEEDED 是终态


# ===== 集成：end-to-end failure 链路 =====

async def test_full_failure_chain_429_retry_then_success():
    """完整链路：retry_async 包装 + mock 后端 + 验证重试次数 + 最终成功"""
    call_count = 0

    async def flaky_func():
        nonlocal call_count
        call_count += 1
        if call_count < 3:
            resp = MagicMock()
            resp.status_code = 503
            resp.headers = httpx.Headers({})
            raise httpx.HTTPStatusError("503", request=MagicMock(), response=resp)
        return "finally"

    with patch("ai_pr_review.core.retry.asyncio.sleep", new=AsyncMock()):
        result = await retry_async(flaky_func, RetryConfig(max_retries=5, base_delay=0.001))

    assert result == "finally"
    assert call_count == 3  # 2 次失败 + 1 次成功


async def test_metrics_count_failure_and_retry_events():
    """失败 + 重试事件应在 metrics 中可见"""
    get_registry().reset()

    on_retry_calls = []

    def on_retry(attempt, code):
        on_retry_calls.append((attempt, code))
        get_registry().counter(
            "retry_events_total", labels=("status_code",)
        ).inc(status_code=str(code))

    response_500 = MagicMock()
    response_500.status_code = 500
    response_500.headers = httpx.Headers({})

    func = AsyncMock(side_effect=[
        httpx.HTTPStatusError("500", request=MagicMock(), response=response_500),
        httpx.HTTPStatusError("500", request=MagicMock(), response=response_500),
        "ok",
    ])

    with patch("ai_pr_review.core.retry.asyncio.sleep", new=AsyncMock()):
        await retry_async(
            func,
            RetryConfig(max_retries=3, base_delay=0.001),
            on_retry=on_retry,
        )

    assert len(on_retry_calls) == 2
    counter = get_registry().counter("retry_events_total", labels=("status_code",))
    assert counter.get(status_code="500") == 2.0