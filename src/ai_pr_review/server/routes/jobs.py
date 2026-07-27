"""Jobs Web API 路由（v0.10 M6）

实现 JobQueue 的 REST 接口：
- GET  /api/jobs            — 列出最近任务
- GET  /api/jobs/{job_id}   — 查询任务状态
- POST /api/jobs            — 提交新任务（提交 PR 审查）
- GET  /api/jobs/{id}/result — 提取 AnalysisResult（成功任务）

用户隔离：
- 列表/查询仅返回当前用户的 jobs（M4 后续：扩展 Job 加 user_id）
- 当前实现：所有用户共享 JobQueue（v0.10 简化版）
"""
import logging

from fastapi import APIRouter, Body, HTTPException, Query, status

from ai_pr_review.core.models import AnalysisResult
from ai_pr_review.data.history import AnalysisRecord, save_record
from ai_pr_review.server.job_queue_runtime import get_job_queue

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/jobs", tags=["jobs"])


@router.get("/")
async def list_jobs(limit: int = Query(20, ge=1, le=100)):
    """列出最近任务（按 created_at 倒序）

    JobQueue 未配置时返回空列表（CLI-only 部署场景）
    """
    try:
        queue = get_job_queue()
    except RuntimeError:
        return []  # JobQueue 未配置，返回空

    jobs = await queue.list_jobs(limit=limit)
    return [_job_to_dict(j) for j in jobs]


@router.get("/{job_id}")
async def get_job(job_id: str):
    """查询单个任务状态"""
    try:
        queue = get_job_queue()
    except RuntimeError:
        raise HTTPException(status_code=503, detail="JobQueue not configured")
    job = await queue.get(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail=f"Job {job_id} not found")
    return _job_to_dict(job)


@router.post("/", status_code=status.HTTP_202_ACCEPTED)
async def submit_job(pr_url: str = Body(..., embed=True)):
    """提交 PR 审查任务

    Body: {"pr_url": "https://github.com/owner/repo/pull/123"}

    返回 202 + {job_id, status: pending}（任务异步执行）
    """
    if not pr_url.strip():
        raise HTTPException(status_code=400, detail="pr_url is required")

    try:
        queue = get_job_queue()
    except RuntimeError:
        raise HTTPException(status_code=503, detail="JobQueue not configured")

    try:
        job = await queue.submit(pr_url)
    except RuntimeError as e:
        # JobQueue 已 shutdown
        raise HTTPException(status_code=503, detail=str(e))

    return {
        "job_id": job.id,
        "status": job.status.value,
        "pr_url": job.pr_url,
    }


def _job_to_dict(job) -> dict:
    """Job → JSON 字典"""
    return {
        "id": job.id,
        "pr_url": job.pr_url,
        "status": job.status.value,
        "progress": job.progress,
        "error": job.error,
        "created_at": job.created_at,
        "started_at": job.started_at,
        "finished_at": job.finished_at,
        "result": _result_to_dict(job.result) if job.result else None,
    }


def _result_to_dict(result: AnalysisResult) -> dict:
    """AnalysisResult → JSON 字典"""
    return {
        "summary": {
            "intent": result.summary.intent,
            "scope": result.summary.scope,
            "key_changes": result.summary.key_changes,
        },
        "findings_count": len(result.findings),
        "suggestions_count": len(result.suggestions),
    }