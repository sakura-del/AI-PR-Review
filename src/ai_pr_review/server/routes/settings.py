"""Settings 路由占位 — M6 实现 Per-user 配置管理"""
from fastapi import APIRouter

router = APIRouter()


@router.get("/")
async def get_settings():
    """M6: GET /settings 返回当前用户配置"""
    return {"status": "not_implemented", "todo": "M6 Settings"}


@router.post("/")
async def update_settings():
    """M6: POST /settings 更新用户配置"""
    return {"status": "not_implemented", "todo": "M6 Settings"}