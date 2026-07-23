"""RateLimiter 限流器单元测试

覆盖场景：
1. 限流生效：rate=2 时并发 5 个 acquire，最多 2 个同时进行
2. 排队等待：超出限流的请求最终能获得令牌
3. 并发上限：监控 max concurrent <= rate
4. 默认值：RateLimiter() 默认 rate=5
5. 上下文管理器：async with rate_limiter 用法正常工作
6. 单例：get_rate_limiter() 多次调用返回同一实例
7. 不同 rate 参数：rate=1 和 rate=10 行为差异
8. 令牌补充：释放后令牌可被重新获取
"""
import asyncio

import pytest

from ai_pr_review.rate_limiter import RateLimiter, get_rate_limiter
import ai_pr_review.rate_limiter as rl_module


# ---------- 辅助函数 ----------

async def _run_concurrent(limiter: RateLimiter, n: int, work: float = 0.05):
    """启动 n 个并发任务，返回 (max_concurrent, completed)

    每个任务：acquire → 记录并发数 → 模拟工作 → release

    注意：work 持续时间需远小于 1/rate 秒，避免后台令牌补充协程
    在工作期间补充令牌导致并发数超出 rate。
    """
    current = 0
    max_concurrent = 0
    completed = 0

    async def worker():
        nonlocal current, max_concurrent, completed
        await limiter.acquire()
        try:
            # acquire 返回后、await sleep 前是同步区间，更新计数安全
            current += 1
            if current > max_concurrent:
                max_concurrent = current
            await asyncio.sleep(work)
        finally:
            current -= 1
            completed += 1
            limiter.release()

    tasks = [asyncio.create_task(worker()) for _ in range(n)]
    await asyncio.gather(*tasks)
    return max_concurrent, completed


# ===== 测试用例 =====

@pytest.mark.asyncio
async def test_rate_limit_effective():
    """限流生效：rate=2 时并发 5 个 acquire，最多 2 个同时进行"""
    rl = RateLimiter(rate=2)
    try:
        max_concurrent, completed = await _run_concurrent(rl, 5, work=0.05)
        assert completed == 5, "所有任务应完成"
        assert max_concurrent <= 2, f"并发数应 <= 2，实际 {max_concurrent}"
    finally:
        await rl.close()


@pytest.mark.asyncio
async def test_queuing_waits():
    """排队等待：超出限流的请求最终能获得令牌（wait_for 验证不无限等待）"""
    rl = RateLimiter(rate=2)
    try:
        # 5 个并发请求，rate=2，全部应在合理时间内完成（不无限等待）
        max_concurrent, completed = await asyncio.wait_for(
            _run_concurrent(rl, 5, work=0.05),
            timeout=3.0,
        )
        assert completed == 5, "排队任务最终都应完成"
        assert max_concurrent <= 2
    finally:
        await rl.close()


@pytest.mark.asyncio
async def test_concurrency_cap():
    """并发上限：多个 rate 下监控 max concurrent <= rate"""
    for rate in [1, 2, 3]:
        rl = RateLimiter(rate=rate)
        try:
            # 并发数为 rate 的 3 倍，验证不超限
            max_concurrent, completed = await _run_concurrent(
                rl, rate * 3, work=0.02
            )
            assert completed == rate * 3
            assert max_concurrent <= rate, (
                f"rate={rate}: max_concurrent={max_concurrent} 应 <= {rate}"
            )
        finally:
            await rl.close()


@pytest.mark.asyncio
async def test_default_rate():
    """默认值：RateLimiter() 默认 rate=5"""
    rl = RateLimiter()
    try:
        assert rl.rate == 5
        assert rl.max_capacity == 5
    finally:
        await rl.close()


@pytest.mark.asyncio
async def test_context_manager():
    """上下文管理器：async with rate_limiter 用法正常工作"""
    rl = RateLimiter(rate=2)
    try:
        # 进入前可用令牌 = 2
        assert rl.current_available == 2
        async with rl:
            # 获取 1 个令牌后，可用 = 1
            assert rl.current_available == 1
        # 退出后令牌归还，可用 = 2
        assert rl.current_available == 2
    finally:
        await rl.close()


@pytest.mark.asyncio
async def test_singleton():
    """单例：get_rate_limiter() 多次调用返回同一实例"""
    # 重置全局单例，确保测试隔离
    rl_module._global_rate_limiter = None
    try:
        rl1 = get_rate_limiter()
        rl2 = get_rate_limiter()
        assert rl1 is rl2, "多次调用应返回同一实例"

        # 指定 rate 不影响已创建的实例
        rl3 = get_rate_limiter(rate=100)
        assert rl3 is rl1, "已创建后 rate 参数应被忽略"
        assert rl1.rate == 5, "首次创建时的默认 rate 应保持"
    finally:
        if rl_module._global_rate_limiter is not None:
            await rl_module._global_rate_limiter.close()
        rl_module._global_rate_limiter = None


@pytest.mark.asyncio
async def test_different_rates():
    """不同 rate 参数：rate=1 严格串行，rate=10 允许全部并发"""
    # rate=1：5 个任务严格串行，max_concurrent=1
    rl1 = RateLimiter(rate=1)
    try:
        max_c, completed = await _run_concurrent(rl1, 5, work=0.02)
        assert completed == 5
        assert max_c == 1, f"rate=1 应严格串行，实际 max_concurrent={max_c}"
    finally:
        await rl1.close()

    # rate=10：5 个任务可全部并发，max_concurrent=5
    rl10 = RateLimiter(rate=10)
    try:
        max_c, completed = await _run_concurrent(rl10, 5, work=0.02)
        assert completed == 5
        assert max_c == 5, f"rate=10 应允许 5 并发，实际 max_concurrent={max_c}"
    finally:
        await rl10.close()


@pytest.mark.asyncio
async def test_token_reusable_after_release():
    """令牌补充：释放后令牌可被重新获取"""
    rl = RateLimiter(rate=1)
    try:
        # 获取唯一令牌
        await rl.acquire()
        assert rl.current_available == 0

        # 释放后令牌归还
        rl.release()
        assert rl.current_available == 1

        # 可再次获取（不会无限等待）
        await asyncio.wait_for(rl.acquire(), timeout=1.0)
        assert rl.current_available == 0

        rl.release()
    finally:
        await rl.close()


@pytest.mark.asyncio
async def test_refiller_replenishes_tokens():
    """令牌补充：后台协程定期补充被消耗的令牌"""
    rl = RateLimiter(rate=5)
    try:
        # 消耗所有令牌（不释放，模拟令牌被用尽）
        for _ in range(5):
            await rl.acquire()
        assert rl.current_available == 0

        # 等待后台补充（rate=5，每 0.2s 补充 1 个）
        # 0.5s 后应至少补充 1 个令牌
        await asyncio.sleep(0.5)
        assert rl.current_available >= 1, "后台应已补充令牌"
    finally:
        await rl.close()
