"""Dashboard 路由占位 — M5 实现 Jinja2 模板渲染"""
from fastapi import APIRouter

router = APIRouter()


@router.get("/")
async def index():
    """M5: 返回 Dashboard 首页（统计卡片 + 最近审查）"""
    return {"status": "not_implemented", "todo": "M5 Dashboard"}