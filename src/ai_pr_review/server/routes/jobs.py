"""Jobs 路由占位 — M6 实现 JobQueue REST API"""
from fastapi import APIRouter

router = APIRouter()


@router.get("/{job_id}")
async def get_job(job_id: str):
    """M6: GET /api/jobs/{job_id} 查询任务状态"""
    return {"status": "not_implemented", "todo": "M6 Jobs API", "job_id": job_id}


@router.get("/")
async def list_jobs():
    """M6: GET /api/jobs 列出最近任务"""
    return {"status": "not_implemented", "todo": "M6 Jobs API"}