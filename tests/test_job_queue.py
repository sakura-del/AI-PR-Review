"""Job / JobQueue ABC 接口契约测试

策略：定义一个最小内存实现 MemoryJobQueue，对 ABC 的所有方法做行为验证。
T19 [A15] 的 InMemoryJobQueue 应满足同样契约（且多出 worker 调度能力）。

注：pytest 配置 asyncio_mode="auto"，async 测试函数无需 @pytest.mark.asyncio 装饰器。
"""
import asyncio

import pytest

from ai_pr_review.data.job_queue import (
    Job,
    JobQueue,
    JobStatus,
    _new_job_id,
)


class MemoryJobQueue(JobQueue):
    """最小内存实现，验证 ABC 契约

    不含 worker 调度；T19 [A15] 的 InMemoryJobQueue 才有 asyncio worker。
    """

    def __init__(self) -> None:
        self._jobs: dict[str, Job] = {}

    async def submit(self, pr_url: str) -> Job:
        job = Job(pr_url=pr_url)
        self._jobs[job.id] = job
        return job

    async def get(self, job_id: str):
        return self._jobs.get(job_id)

    async def list_jobs(self, limit: int = 50) -> list[Job]:
        # created_at 为唯一主排序；id 作为 tiebreaker 保证同微秒创建时顺序稳定
        return sorted(
            self._jobs.values(),
            key=lambda j: (j.created_at, j.id),
            reverse=True,
        )[:limit]

    async def cancel(self, job_id: str) -> bool:
        job = self._jobs.get(job_id)
        if job is None or job.status.is_terminal:
            return False
        job.mark_cancelled()
        return True

    async def shutdown(self) -> None:
        pass


# ===== JobStatus =====

def test_job_status_terminal_states():
    assert JobStatus.SUCCEEDED.is_terminal is True
    assert JobStatus.FAILED.is_terminal is True
    assert JobStatus.CANCELLED.is_terminal is True


def test_job_status_non_terminal_states():
    assert JobStatus.PENDING.is_terminal is False
    assert JobStatus.RUNNING.is_terminal is False


# ===== Job dataclass =====

def test_job_initial_state_defaults():
    job = Job(pr_url="https://example.com/pr/1")
    assert job.status == JobStatus.PENDING
    assert job.id  # 自动生成
    assert job.created_at  # 自动生成
    assert job.result is None
    assert job.error is None
    assert job.started_at is None
    assert job.finished_at is None


def test_job_lifecycle_pending_to_running_to_succeeded():
    job = Job(pr_url="x")
    assert job.status == JobStatus.PENDING

    job.mark_running()
    assert job.status == JobStatus.RUNNING
    assert job.started_at is not None
    assert job.finished_at is None

    job.mark_succeeded(result=None)
    assert job.status == JobStatus.SUCCEEDED
    assert job.finished_at is not None
    assert isinstance(job.started_at, str) and isinstance(job.finished_at, str)
    # 注：started_at < finished_at 不一定成立（快速调用可能同微秒），
    # 契约只保证时间戳被记录，不保证间隔 > 0。


def test_job_failed_state_records_error():
    job = Job(pr_url="x")
    job.mark_running()
    job.mark_failed("AI API timeout")
    assert job.status == JobStatus.FAILED
    assert job.error == "AI API timeout"
    assert job.finished_at is not None


def test_job_cancelled_state():
    job = Job(pr_url="x")
    job.mark_cancelled()
    assert job.status == JobStatus.CANCELLED
    assert job.finished_at is not None


def test_new_job_id_generates_unique_ids():
    """100 次生成应无碰撞"""
    ids = {_new_job_id() for _ in range(100)}
    assert len(ids) == 100


def test_job_to_from_dict_roundtrip_preserves_fields():
    job = Job(pr_url="https://example.com/pr/1")
    job.mark_running()
    job.mark_succeeded(result=None)

    data = job.to_dict()
    restored = Job.from_dict(data)

    assert restored.id == job.id
    assert restored.pr_url == job.pr_url
    assert restored.status == job.status
    assert restored.started_at == job.started_at
    assert restored.finished_at == job.finished_at


def test_job_to_dict_status_is_string_value():
    """status 字段序列化时用字符串值，便于跨语言/JSON 互操作"""
    job = Job(pr_url="x")
    job.mark_failed("err")
    data = job.to_dict()
    assert data["status"] == "failed"
    assert isinstance(data["status"], str)


def test_job_from_dict_handles_missing_optional_fields():
    """from_dict 对部分字段缺失时用默认值兜底"""
    job = Job.from_dict({"pr_url": "x"})
    assert job.pr_url == "x"
    assert job.id  # 自动生成
    assert job.status == JobStatus.PENDING


# ===== JobQueue ABC =====

async def test_queue_submit_returns_pending_job():
    queue = MemoryJobQueue()
    job = await queue.submit("https://example.com/pr/1")
    assert job.status == JobStatus.PENDING
    assert job.pr_url == "https://example.com/pr/1"


async def test_queue_get_returns_submitted_job():
    queue = MemoryJobQueue()
    job = await queue.submit("https://example.com/pr/1")
    fetched = await queue.get(job.id)
    assert fetched is job


async def test_queue_get_missing_returns_none():
    queue = MemoryJobQueue()
    assert await queue.get("never-existed") is None


async def test_queue_cancel_pending_job_succeeds():
    queue = MemoryJobQueue()
    job = await queue.submit("x")
    ok = await queue.cancel(job.id)
    assert ok is True
    assert (await queue.get(job.id)).status == JobStatus.CANCELLED


async def test_queue_cancel_running_job_succeeds():
    queue = MemoryJobQueue()
    job = await queue.submit("x")
    job.mark_running()
    ok = await queue.cancel(job.id)
    assert ok is True
    assert (await queue.get(job.id)).status == JobStatus.CANCELLED


async def test_queue_cancel_terminal_job_returns_false():
    queue = MemoryJobQueue()
    job = await queue.submit("x")
    job.mark_running()
    job.mark_succeeded(result=None)
    ok = await queue.cancel(job.id)
    assert ok is False


async def test_queue_cancel_missing_job_returns_false():
    queue = MemoryJobQueue()
    ok = await queue.cancel("never-existed")
    assert ok is False


async def test_queue_list_jobs_returns_newest_first():
    queue = MemoryJobQueue()
    # 间隔 2ms 提交确保 created_at 单调递增（同微秒时顺序由 id 决定，不可预测）
    j1 = await queue.submit("a")
    await asyncio.sleep(0.002)
    j3 = await queue.submit("c")
    await asyncio.sleep(0.002)
    j2 = await queue.submit("b")
    jobs = await queue.list_jobs()
    assert len(jobs) == 3
    # 最新创建的是 j2（最后一次 submit）
    assert jobs[0].id == j2.id
    assert jobs[2].id == j1.id


async def test_queue_list_jobs_respects_limit():
    queue = MemoryJobQueue()
    for i in range(10):
        await queue.submit(f"pr{i}")
    assert len(await queue.list_jobs(limit=3)) == 3


async def test_queue_list_jobs_empty():
    queue = MemoryJobQueue()
    assert await queue.list_jobs() == []


async def test_queue_shutdown_is_callable():
    """shutdown 不抛异常即为通过"""
    queue = MemoryJobQueue()
    await queue.shutdown()