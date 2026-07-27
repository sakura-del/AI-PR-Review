"""JobQueue 运行时 — InMemoryJobQueue 实现 + 单例工厂

设计目标：
- 基于 asyncio.Queue + 后台 worker 协程
- 懒启动 worker：第一次 submit 时启动
- 优雅关闭：shutdown() 等当前任务完成或超时取消
- 单例模式：api_server 复用同一队列

使用模式：
    # 启动时配置一次
    queue = InMemoryJobQueue(handler=review_callback)
    configure_job_queue(queue)

    # 业务代码获取单例
    queue = get_job_queue()
    job = await queue.submit(pr_url)
    status = await queue.get(job.id)
"""
import asyncio
import logging
from typing import Awaitable, Callable, Optional

from ai_pr_review.data.job_queue import Job, JobQueue, JobStatus

logger = logging.getLogger(__name__)

# 处理器类型：接收 pr_url，返回 AnalysisResult（或 None 仅做副作用）
ReviewHandler = Callable[[str], Awaitable[object]]


class InMemoryJobQueue(JobQueue):
    """asyncio.Queue 版 JobQueue 默认实现

    特点：
    - 单进程内运行（无跨进程支持；如需 Redis 版后续另实现）
    - 懒启动 worker：首次 submit 时创建 asyncio.Task
    - 任务状态保存在内存 dict（v0.9 不持久化；进程重启后清空）
    """

    def __init__(
        self,
        handler: ReviewHandler,
        *,
        max_size: int = 100,
        shutdown_timeout: float = 10.0,
    ) -> None:
        self._handler = handler
        self._max_size = max_size
        self._shutdown_timeout = shutdown_timeout

        # 异步原语在 async 上下文内懒创建（asyncio.Queue 需要 event loop）
        self._queue: Optional[asyncio.Queue[Job]] = None
        self._shutdown_event: Optional[asyncio.Event] = None
        self._worker_task: Optional[asyncio.Task] = None

        # 任务存储
        self._jobs: dict[str, Job] = {}

    def _ensure_async_primitives(self) -> None:
        """懒创建 asyncio.Queue / Event（在 async 上下文内首次调用时）"""
        if self._queue is None:
            self._queue = asyncio.Queue(maxsize=self._max_size)
        if self._shutdown_event is None:
            self._shutdown_event = asyncio.Event()

    def _ensure_worker(self) -> None:
        """懒启动 worker 协程：第一次 submit 后运行"""
        if self._worker_task is None or self._worker_task.done():
            try:
                loop = asyncio.get_running_loop()
            except RuntimeError:
                logger.warning("No running event loop; worker not started")
                return
            self._worker_task = loop.create_task(self._run_worker(), name="job_queue_worker")

    async def _run_worker(self) -> None:
        """worker 协程主循环：从队列取 job 并执行"""
        logger.info("JobQueue worker started")
        assert self._queue is not None and self._shutdown_event is not None
        while not self._shutdown_event.is_set():
            try:
                # 短超时轮询：每 1s 检查 shutdown 标志
                job = await asyncio.wait_for(self._queue.get(), timeout=1.0)
            except asyncio.TimeoutError:
                continue
            except asyncio.CancelledError:
                break

            try:
                # PENDING/CANCELLED 都可能从队列取出（cancel 后状态可能变化）
                if job.status == JobStatus.CANCELLED:
                    logger.debug(f"Skipping cancelled job {job.id}")
                    continue
                await self._execute(job)
            except Exception as e:
                logger.error(f"Worker error on job {job.id}: {e}", exc_info=True)
            finally:
                self._queue.task_done()
        logger.info("JobQueue worker stopped")

    async def _execute(self, job: Job) -> None:
        """执行单个 job：调用 handler 并更新状态

        任何 handler 异常都会被捕获并标记 FAILED，不向外抛。
        """
        if job.status != JobStatus.PENDING:
            return
        job.mark_running()
        try:
            result = await self._handler(job.pr_url)
            job.mark_succeeded(result)
            logger.info(f"Job {job.id} succeeded for {job.pr_url}")
        except asyncio.CancelledError:
            job.mark_cancelled()
            raise
        except Exception as e:
            error_msg = f"{type(e).__name__}: {e}"
            job.mark_failed(error_msg)
            logger.error(f"Job {job.id} failed for {job.pr_url}: {error_msg}")

    async def submit(self, pr_url: str) -> Job:
        """提交新任务

        - 首次调用时懒创建 asyncio 原语与 worker
        - queue.put 可能阻塞（max_size 满时）；调用方需自行处理超时
        """
        self._ensure_async_primitives()
        if self._shutdown_event is not None and self._shutdown_event.is_set():
            raise RuntimeError("JobQueue is shut down; cannot submit new jobs")
        job = Job(pr_url=pr_url)
        self._jobs[job.id] = job
        assert self._queue is not None
        await self._queue.put(job)
        self._ensure_worker()
        logger.info(f"Submitted job {job.id} for {pr_url}")
        return job

    async def get(self, job_id: str) -> Optional[Job]:
        return self._jobs.get(job_id)

    async def list_jobs(self, limit: int = 50) -> list[Job]:
        """按 created_at 倒序，id 作为稳定 tiebreaker"""
        return sorted(
            self._jobs.values(),
            key=lambda j: (j.created_at, j.id),
            reverse=True,
        )[:limit]

    async def cancel(self, job_id: str) -> bool:
        """取消任务

        PENDING：立即标记 CANCELLED（worker 取出时会跳过）
        RUNNING：标记 CANCELLED（handler 无法中断；worker 完成时跳过结果记录）
        终态：返回 False
        """
        job = self._jobs.get(job_id)
        if job is None or job.status.is_terminal:
            return False
        job.mark_cancelled()
        logger.info(f"Job {job.id} cancelled (was {job.status})")
        return True

    async def shutdown(self) -> None:
        """优雅关闭

        - 设置 shutdown 标志，worker 主循环退出
        - 等 worker task 完成（最多 shutdown_timeout 秒）
        - 超时则取消 worker task

        注：即使从未 submit 过，调用 shutdown 也应是安全的（懒创建 event 并 set）
        """
        # 懒创建：确保 _shutdown_event 存在（即使从未 submit 过）
        self._ensure_async_primitives()
        assert self._shutdown_event is not None
        self._shutdown_event.set()
        if self._worker_task is not None and not self._worker_task.done():
            try:
                await asyncio.wait_for(self._worker_task, timeout=self._shutdown_timeout)
            except asyncio.TimeoutError:
                logger.warning("Worker shutdown timed out, cancelling")
                self._worker_task.cancel()
                try:
                    await self._worker_task
                except (asyncio.CancelledError, Exception):
                    pass

    @property
    def pending_count(self) -> int:
        """队列中待处理的 job 数（仅 PENDING）"""
        return sum(1 for j in self._jobs.values() if j.status == JobStatus.PENDING)

    @property
    def running_count(self) -> int:
        return sum(1 for j in self._jobs.values() if j.status == JobStatus.RUNNING)


# ===== 单例管理 =====

_singleton: Optional[InMemoryJobQueue] = None


def configure_job_queue(queue: InMemoryJobQueue) -> InMemoryJobQueue:
    """显式注入 JobQueue 实例（api_server 启动时调用）

    返回注入的实例，便于链式调用。
    """
    global _singleton
    _singleton = queue
    return queue


def get_job_queue() -> InMemoryJobQueue:
    """获取 JobQueue 单例

    Raises:
        RuntimeError: 单例未初始化（需先调用 configure_job_queue）
    """
    if _singleton is None:
        raise RuntimeError(
            "JobQueue not initialized. Call configure_job_queue(queue) first."
        )
    return _singleton


def reset_job_queue() -> None:
    """重置 JobQueue 单例（仅测试用）

    生产代码不应调用；进程退出时无需重置。
    """
    global _singleton
    _singleton = None