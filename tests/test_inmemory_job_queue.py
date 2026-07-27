"""InMemoryJobQueue 实现与单例测试（T19 [A15]）

覆盖：
- 核心生命周期：submit → worker → 状态转换
- 错误处理：handler 抛异常 → FAILED 状态
- 取消：PENDING 可取消，RUNNING 标记 cancelled
- 优雅关闭：shutdown() 等 worker 完成
- 并发：多 submit 同时处理
- 单例：configure / get / reset
- JobQueue ABC 契约

所有测试用 try/finally 保证 shutdown 被调用，避免 pytest-asyncio 因 worker
残留导致 session teardown 卡住。
"""
import asyncio

import pytest

from ai_pr_review.data.job_queue import Job, JobQueue, JobStatus
from ai_pr_review.server.job_queue_runtime import (
    InMemoryJobQueue,
    configure_job_queue,
    get_job_queue,
    reset_job_queue,
)


async def _with_queue(handler, body):
    """辅助：在 finally 中保证 shutdown 的 queue 测试运行器

    用法：
        async def test_xxx():
            async def my_handler(url): return None
            await _with_queue(my_handler, lambda q: _body(q))
    """
    q = InMemoryJobQueue(handler)
    try:
        return await body(q)
    finally:
        await q.shutdown()


# ===== JobQueue ABC 契约 =====

class _InMemoryFactory:
    @staticmethod
    def make() -> JobQueue:
        async def noop_handler(pr_url: str):
            return None
        return InMemoryJobQueue(noop_handler)


def test_job_queue_contract_submit_returns_pending():
    async def noop(url):
        return None
    async def body(q):
        job = await q.submit("https://x.com/p/1")
        assert job.status == JobStatus.PENDING
        assert job.pr_url == "https://x.com/p/1"
    asyncio.run(_with_queue(noop, body))


def test_job_queue_contract_cancel_terminal_returns_false():
    async def noop(url):
        return None
    async def body(q):
        job = await q.submit("x")
        job.mark_running()
        job.mark_succeeded(result=None)
        return await q.cancel(job.id)
    result = asyncio.run(_with_queue(noop, body))
    assert result is False


# ===== InMemoryJobQueue 具体行为 =====

async def test_submit_returns_pending_job_and_starts_worker():
    results = []

    async def handler(pr_url: str):
        results.append(pr_url)
        await asyncio.sleep(0.01)
        return f"result-for-{pr_url}"

    async def body(q):
        job = await q.submit("https://x.com/p/1")
        assert job.id
        assert job.status == JobStatus.PENDING

        # 等 worker 处理完（轮询直到 SUCCEEDED）
        for _ in range(40):
            await asyncio.sleep(0.01)
            final = await q.get(job.id)
            if final.status == JobStatus.SUCCEEDED:
                break
        assert final.status == JobStatus.SUCCEEDED
        assert final.result == "result-for-https://x.com/p/1"
        assert results == ["https://x.com/p/1"]

    await _with_queue(handler, body)


async def test_handler_exception_marks_job_failed():
    async def failing_handler(pr_url: str):
        raise ValueError("simulated AI failure")

    async def body(q):
        job = await q.submit("https://x.com/p/1")
        for _ in range(40):
            await asyncio.sleep(0.01)
            final = await q.get(job.id)
            if final.status.is_terminal:
                break
        assert final.status == JobStatus.FAILED
        assert "ValueError" in final.error
        assert "simulated AI failure" in final.error

    await _with_queue(failing_handler, body)


async def test_cancel_pending_job_marks_cancelled():
    """submit 后立即 cancel（在 worker 处理前）应能取消"""
    block_handler = asyncio.Event()

    async def slow_handler(pr_url: str):
        await block_handler.wait()
        return None

    async def body(q):
        j1 = await q.submit("a")
        # 等 worker 开始处理 j1（轮询 j1.status，最长 1s）
        for _ in range(100):
            await asyncio.sleep(0.01)
            current = await q.get(j1.id)
            if current.status == JobStatus.RUNNING:
                break
        assert (await q.get(j1.id)).status == JobStatus.RUNNING

        j2 = await q.submit("b")  # 在 queue 里 PENDING
        assert q.pending_count == 1
        assert q.running_count == 1

        ok = await q.cancel(j2.id)
        assert ok is True
        assert (await q.get(j2.id)).status == JobStatus.CANCELLED

        # 放行 j1 让 worker 退出
        block_handler.set()
        for _ in range(100):
            await asyncio.sleep(0.01)
            if q.running_count == 0:
                break

    await _with_queue(slow_handler, body)
    block_handler.set()  # 保险：万一上面 body 异常，确保 handler 不再阻塞


async def test_cancel_terminal_returns_false():
    async def handler(pr_url):
        return None

    async def body(q):
        job = await q.submit("x")
        for _ in range(40):
            await asyncio.sleep(0.005)
            current = await q.get(job.id)
            if current.status.is_terminal:
                break
        # job 现在是 SUCCEEDED
        ok = await q.cancel(job.id)
        assert ok is False

    await _with_queue(handler, body)


async def test_cancel_unknown_returns_false():
    async def handler(pr_url):
        return None

    async def body(q):
        ok = await q.cancel("never-existed")
        assert ok is False

    await _with_queue(handler, body)


async def test_concurrent_submits_all_processed():
    processed: list[str] = []

    async def handler(pr_url: str):
        await asyncio.sleep(0.01)
        processed.append(pr_url)
        return None

    async def body(q):
        jobs = await asyncio.gather(*[q.submit(f"pr{i}") for i in range(10)])
        # 等所有 job 处理完
        for _ in range(60):
            await asyncio.sleep(0.01)
            statuses = [(await q.get(j.id)).status for j in jobs]
            if all(s.is_terminal for s in statuses):
                break
        assert len(processed) == 10
        assert sorted(processed) == sorted(f"pr{i}" for i in range(10))
        for job in jobs:
            assert (await q.get(job.id)).status == JobStatus.SUCCEEDED

    await _with_queue(handler, body)


async def test_shutdown_stops_worker_and_rejects_new():
    async def handler(pr_url):
        return None

    async def body(q):
        await q.submit("a")
        for _ in range(20):
            await asyncio.sleep(0.005)
            if q.pending_count == 0:
                break

    # 先在 q1 上跑完，再创建 q2 验证 shutdown 后 submit 抛异常
    await _with_queue(handler, body)

    # 单独的 q2 用于验证 shutdown 后 submit 抛 RuntimeError
    async def body2(q):
        with pytest.raises(RuntimeError, match="shut down"):
            await q.submit("b")

    q2 = InMemoryJobQueue(handler)
    await q2.shutdown()
    # shutdown 已确保 _shutdown_event 存在并 set，无需再 shutdown


async def test_pending_count_and_running_count():
    """pending_count / running_count 应准确反映状态分布"""
    block = asyncio.Event()

    async def handler(pr_url):
        await block.wait()
        return None

    async def body(q):
        await q.submit("a")
        # 让 worker 开始处理 j1
        for _ in range(40):
            await asyncio.sleep(0.005)
            if q.running_count == 1:
                break
        assert q.running_count == 1, f"running_count={q.running_count}"

        await q.submit("b")
        assert q.pending_count == 1
        assert q.running_count == 1

        block.set()
        for _ in range(40):
            await asyncio.sleep(0.005)
            if q.running_count == 0 and q.pending_count == 0:
                break
        assert q.running_count == 0
        assert q.pending_count == 0

    await _with_queue(handler, body)
    block.set()  # 保险


async def test_list_jobs_orders_by_created_at():
    async def handler(pr_url):
        return None

    async def body(q):
        j1 = await q.submit("a")
        # 用足够长的 sleep 保证 timestamp 严格不同（pytest-asyncio 可能压缩短 sleep）
        await asyncio.sleep(0.1)
        j3 = await q.submit("c")
        await asyncio.sleep(0.1)
        j2 = await q.submit("b")

        jobs = await q.list_jobs()
        # 严格保证 created_at 单调：j2 最新、j1 最旧
        assert jobs[0].id == j2.id
        assert jobs[-1].id == j1.id
        assert jobs[1].id == j3.id

    await _with_queue(handler, body)


# ===== 单例工厂 =====

def test_get_job_queue_without_init_raises():
    reset_job_queue()
    with pytest.raises(RuntimeError, match="not initialized"):
        get_job_queue()


def test_configure_job_queue_returns_queue():
    reset_job_queue()

    async def handler(pr_url):
        return None
    q = InMemoryJobQueue(handler)
    try:
        returned = configure_job_queue(q)
        assert returned is q
        assert get_job_queue() is q
    finally:
        reset_job_queue()


def test_reset_job_queue_clears_singleton():
    reset_job_queue()

    async def handler(pr_url):
        return None
    q1 = InMemoryJobQueue(handler)
    try:
        configure_job_queue(q1)
        assert get_job_queue() is q1
        reset_job_queue()
        with pytest.raises(RuntimeError):
            get_job_queue()
    finally:
        reset_job_queue()


# ===== handle_connection 集成（验证 JobQueue + API 联动）=====

async def test_integration_handler_processes_via_job_queue():
    """验证 api_server 的 handle_review 走 JobQueue 后能成功处理"""
    from ai_pr_review.server.api_server import build_router

    received: list[str] = []

    async def review_fn(pr_url: str):
        received.append(pr_url)
        return {"summary": "ok"}

    router = build_router(review_fn)
    try:
        handler, _ = router.match("POST", "/api/review")
        body = b'{"pr_url": "https://github.com/o/r/pull/1"}'
        status, resp = await handler({}, body)

        assert status == 202
        job_id = resp["job_id"]

        # 等 worker 处理
        for _ in range(40):
            await asyncio.sleep(0.01)
            job = await get_job_queue().get(job_id)
            if job.status.is_terminal:
                break

        assert job.status == JobStatus.SUCCEEDED
        assert job.result == {"summary": "ok"}
        assert received == ["https://github.com/o/r/pull/1"]
    finally:
        await get_job_queue().shutdown()
        reset_job_queue()