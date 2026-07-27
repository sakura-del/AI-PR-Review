"""Auth 路由占位 — M2 实现 GitHub OAuth"""
from fastapi import APIRouter

router = APIRouter()


@router.get("/login")
async def login():
    """M2: 重定向到 GitHub OAuth 授权页面"""
    return {"status": "not_implemented", "todo": "M2 GitHub OAuth"}


@router.get("/callback")
async def callback():
    """M2: GitHub OAuth 回调，换取 access_token + user info"""
    return {"status": "not_implemented", "todo": "M2 GitHub OAuth"}


@router.post("/logout")
async def logout():
    """M2: 清除 session cookie"""
    return {"status": "not_implemented", "todo": "M2 GitHub OAuth"}


@router.get("/me")
async def me():
    """M2: 返回当前登录用户信息"""
    return {"status": "not_implemented", "todo": "M2 GitHub OAuth"}