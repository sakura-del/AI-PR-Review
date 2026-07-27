"""任务队列抽象 — Web 化与异步评审的基础设施

设计目标：
- 抽象 Job 生命周期（PENDING → RUNNING → SUCCEEDED/FAILED/CANCELLED）
- 抽象 JobQueue 接口，允许实现替换（内存版/Redis版/DB版）
- 序列化/反序列化方法，便于后续持久化（v0.10 SQLite 存储）

使用场景：
- api_server 接收 POST /api/review 后 submit，返回 job_id
- 客户端轮询 GET /api/jobs/{id} 获取状态与结果
- 后台 worker 消费队列并执行审查
"""
import logging
import uuid
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Optional

from ai_pr_review.core.models import AnalysisResult

logger = logging.getLogger(__name__)


class JobStatus(str, Enum):
    """任务状态枚举

    状态机：
        PENDING → RUNNING → SUCCEEDED
        PENDING → RUNNING → FAILED
        PENDING/RUNNING → CANCELLED

    终态：SUCCEEDED / FAILED / CANCELLED，不再转换。
    """
    PENDING = "pending"
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    CANCELLED = "cancelled"

    @property
    def is_terminal(self) -> bool:
        """是否为终态（不再转换）"""
        return self in (JobStatus.SUCCEEDED, JobStatus.FAILED, JobStatus.CANCELLED)


def _now_iso() -> str:
    """UTC ISO 时间戳，统一时区"""
    return datetime.now(timezone.utc).isoformat()


def _new_job_id() -> str:
    """生成短作业 ID（12 字符，足够去重）

    用 uuid4 hex 截断，碰撞概率 ~10^-12（百万次提交）。
    """
    return uuid.uuid4().hex[:12]


@dataclass
class Job:
    """单个审查任务的状态对象

    id 为短 UUID，pr_url 为 GitHub/GitLab PR URL。
    result 仅在 SUCCEEDED 时有值；error 仅在 FAILED 时有值。

    非 frozen：worker 需要在状态转换时标记时间戳与状态。
    """
    pr_url: str
    id: str = field(default_factory=_new_job_id)
    status: JobStatus = JobStatus.PENDING
    progress: str = ""
    result: Optional[AnalysisResult] = None
    error: Optional[str] = None
    created_at: str = field(default_factory=_now_iso)
    started_at: Optional[str] = None
    finished_at: Optional[str] = None

    def mark_running(self) -> None:
        """状态转换：PENDING/CANCELLED → RUNNING"""
        self.status = JobStatus.RUNNING
        self.started_at = _now_iso()

    def mark_succeeded(self, result: Optional[AnalysisResult]) -> None:
        """状态转换：RUNNING → SUCCEEDED"""
        self.status = JobStatus.SUCCEEDED
        self.result = result
        self.finished_at = _now_iso()

    def mark_failed(self, error: str) -> None:
        """状态转换：RUNNING → FAILED"""
        self.status = JobStatus.FAILED
        self.error = error
        self.finished_at = _now_iso()

    def mark_cancelled(self) -> None:
        """状态转换：PENDING/RUNNING → CANCELLED"""
        self.status = JobStatus.CANCELLED
        self.finished_at = _now_iso()

    def to_dict(self) -> dict:
        """序列化为可 JSON 化的字典

        result 字段若是 AnalysisResult 对象，由调用方在持久化前自行 to_dict。
        这里不做耦合（Job 不关心 AnalysisResult 的序列化方式）。
        """
        return {
            "id": self.id,
            "pr_url": self.pr_url,
            "status": self.status.value,
            "progress": self.progress,
            "error": self.error,
            "created_at": self.created_at,
            "started_at": self.started_at,
            "finished_at": self.finished_at,
            "result": self.result,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "Job":
        """从字典反序列化

        result 字段若是 dict，调用方需要自行转为 AnalysisResult 后传入。
        这里不做耦合。
        """
        return cls(
            id=data.get("id", _new_job_id()),
            pr_url=data.get("pr_url", ""),
            status=JobStatus(data.get("status", JobStatus.PENDING.value)),
            progress=data.get("progress", ""),
            result=data.get("result"),
            error=data.get("error"),
            created_at=data.get("created_at", _now_iso()),
            started_at=data.get("started_at"),
            finished_at=data.get("finished_at"),
        )


class JobQueue(ABC):
    """任务队列抽象基类

    所有方法均为 async；具体实现可基于 asyncio.Queue、Redis、DB 等。
    实现要求：
    - submit() 必须返回 PENDING 状态的 Job
    - get() / cancel() 对不存在的 job_id 返回 None / False
    - cancel() 对终态 job 返回 False
    - shutdown() 必须等待所有 RUNNING 任务结束或超时取消
    """

    @abstractmethod
    async def submit(self, pr_url: str) -> Job:
        """提交新任务

        返回的 Job 状态为 PENDING；具体何时转为 RUNNING 由实现决定。
        """

    @abstractmethod
    async def get(self, job_id: str) -> Optional[Job]:
        """按 ID 查询任务

        不存在返回 None。
        """

    @abstractmethod
    async def list_jobs(self, limit: int = 50) -> list[Job]:
        """列出最近任务（按 created_at 倒序）

        实现可截断到 limit 条。
        """

    @abstractmethod
    async def cancel(self, job_id: str) -> bool:
        """取消任务

        PENDING/RUNNING 状态可被取消；终态返回 False。
        返回 True 表示取消成功。
        """

    @abstractmethod
    async def shutdown(self) -> None:
        """优雅关闭

        等待所有 RUNNING 任务结束或超时取消；不接受新 submit。
        """