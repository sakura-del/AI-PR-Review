"""Dashboard Web API 路由（v0.10 M6）

为前端 SPA 提供 JSON 数据：
- /api/stats — Dashboard 统计卡片数据（total / high / medium / avg_duration）
- /api/history?limit=N — 最近审查记录
- /api/history/me — 当前用户的审查记录（多用户隔离）

设计选择：
- 用 FastAPI Depends(get_current_session) 注入当前用户
- 未登录返回 401（除 stats 可匿名访问）
- 用户隔离通过 M4 新增的 load_records_for_user 实现
"""
from fastapi import APIRouter, Depends, Query
from fastapi.responses import JSONResponse

from ai_pr_review.core.metrics import get_registry
from ai_pr_review.data.history import (
    AnalysisRecord,
    load_records_for_user,
)
from ai_pr_review.server.routes.auth import (
    SessionData,
    get_current_session,
    require_session,
)

router = APIRouter(prefix="/api")


@router.get("/stats")
async def stats(session: SessionData | None = Depends(get_current_session)):
    """Dashboard 统计卡片数据

    未登录：返回全局统计（CLI 单用户模式兼容）
    已登录：仅返回当前用户的统计
    """
    user_id = session.user_id if session else ""
    records = load_records_for_user(user_id)

    total = len(records)
    high = sum(r.high_severity_count for r in records)
    medium = sum(r.medium_severity_count for r in records)
    durations = [r.duration_seconds for r in records if r.duration_seconds > 0]
    avg_duration = sum(durations) / len(durations) if durations else 0.0

    return {
        "total": total,
        "high": high,
        "medium": medium,
        "low": sum(r.low_severity_count for r in records),
        "avg_duration": round(avg_duration, 2),
    }


@router.get("/history")
async def history(
    limit: int = Query(20, ge=1, le=100),
    session: SessionData | None = Depends(get_current_session),
):
    """最近审查记录（多用户隔离）

    - 未登录：返回所有记录（CLI/legacy 模式）
    - 已登录：仅返回当前用户的记录
    """
    user_id = session.user_id if session else ""
    records = load_records_for_user(user_id)
    # JSON 序列化（dataclass → dict）
    items = [_record_to_dict(r) for r in records[:limit]]
    return items


@router.get("/history/me")
async def my_history(
    limit: int = Query(20, ge=1, le=100),
    session: SessionData = Depends(require_session),
):
    """显式仅返回当前用户的历史（要求登录）"""
    records = load_records_for_user(session.user_id)
    return [_record_to_dict(r) for r in records[:limit]]


def _record_to_dict(record: AnalysisRecord) -> dict:
    """AnalysisRecord → JSON 字典（前端友好字段名）"""
    from dataclasses import asdict
    d = asdict(record)
    # timestamp 转可读字符串
    if d.get("timestamp"):
        d["timestamp_display"] = d["timestamp"][:19].replace("T", " ")
    return d


# ===== Metrics 端点（从 web.py 移过来以便统一 API 前缀）=====

@router.get("/metrics")
async def metrics():
    """指标快照（JSON 格式）"""
    return get_registry().snapshot()