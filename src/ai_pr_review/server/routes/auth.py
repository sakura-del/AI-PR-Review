"""GitHub OAuth + Session 管理（v0.10 M2）

设计目标：
- 用 httpx-oauth 简化 OAuth 2.0 流程（authorization code flow）
- 用 itsdangerous 签名 session cookie（无状态，避免服务端 session 存储）
- 登录用户可在后续请求中通过 dependency 拿到

流程：
1. GET /auth/login — 重定向到 GitHub 授权页（含 state 防 CSRF）
2. GET /auth/callback?code=...&state=... — 用 code 换 token，拉用户信息，签名 cookie，重定向到 /
3. GET /auth/me — 返回当前用户信息
4. POST /auth/logout — 清 cookie，重定向到 /auth/login

环境变量：
- GITHUB_OAUTH_CLIENT_ID — GitHub OAuth App 的 Client ID
- GITHUB_OAUTH_CLIENT_SECRET — Client Secret
- SESSION_SECRET_KEY — 签名 cookie 的密钥（生产必须设置）
"""
import logging
import os
from typing import Optional

import httpx
from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from fastapi.responses import RedirectResponse
from httpx_oauth.clients.github import GitHubOAuth2
from itsdangerous import BadSignature, URLSafeSerializer

logger = logging.getLogger(__name__)

router = APIRouter()

# GitHub OAuth client（单例；env var 由 create_app 注入或运行时读取）
GITHUB_OAUTH_CLIENT_ID = os.environ.get("GITHUB_OAUTH_CLIENT_ID", "")
GITHUB_OAUTH_CLIENT_SECRET = os.environ.get("GITHUB_OAUTH_CLIENT_SECRET", "")
SESSION_SECRET_KEY = os.environ.get(
    "SESSION_SECRET_KEY",
    "dev-secret-key-please-change-in-production-32bytes-min",
)

github_oauth = GitHubOAuth2(
    client_id=GITHUB_OAUTH_CLIENT_ID or "dev-client-id",
    client_secret=GITHUB_OAUTH_CLIENT_SECRET or "dev-client-secret",
    scopes=["read:user", "user:email", "repo"],
)

# Session 签名器（itsdangerous URLSafeSerializer）
session_signer = URLSafeSerializer(SESSION_SECRET_KEY, salt="ai-pr-review-session")

# Cookie 名 / 生命周期
SESSION_COOKIE_NAME = "ai_pr_review_session"
SESSION_MAX_AGE = 60 * 60 * 24 * 7  # 7 天


# ===== Session 数据 =====

class SessionData:
    """会话数据结构（简化版，可序列化为 dict）"""
    __slots__ = ("user_id", "github_login", "access_token")

    def __init__(self, user_id: str, github_login: str, access_token: str):
        self.user_id = user_id
        self.github_login = github_login
        self.access_token = access_token

    def to_dict(self) -> dict:
        return {
            "user_id": self.user_id,
            "github_login": self.github_login,
            "access_token": self.access_token,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "SessionData":
        return cls(
            user_id=data["user_id"],
            github_login=data["github_login"],
            access_token=data["access_token"],
        )


def _serialize_session(data: SessionData) -> str:
    return session_signer.dumps(data.to_dict())


def _deserialize_session(token: str) -> Optional[SessionData]:
    try:
        data = session_signer.loads(token)
        return SessionData.from_dict(data)
    except BadSignature:
        return None
    except (KeyError, TypeError):
        return None


# ===== FastAPI dependency =====

async def get_current_session(request: Request) -> Optional[SessionData]:
    """从 cookie 读取当前 session

    用法：
        @router.get("/some-route")
        async def some_route(session: SessionData = Depends(get_current_session)):
            if session is None:
                raise HTTPException(401)
    """
    token = request.cookies.get(SESSION_COOKIE_NAME)
    if not token:
        return None
    return _deserialize_session(token)


async def require_session(session: Optional[SessionData] = Depends(get_current_session)) -> SessionData:
    """要求登录的路由 dependency"""
    if session is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Not authenticated",
            headers={"Location": "/auth/login"},
        )
    return session


# ===== 路由 =====

@router.get("/login")
async def login(request: Request):
    """重定向到 GitHub OAuth 授权页

    生产提示：需设置 GITHUB_OAUTH_CLIENT_ID / GITHUB_OAUTH_CLIENT_SECRET。
    dev 模式：httpx-oauth client 用占位 credentials，会失败但路由能访问。
    """
    # 生成 authorize URL（含 state 防 CSRF）
    authorize_url = await github_oauth.get_authorization_url(
        f"{request.url.scheme}://{request.headers['host']}/auth/callback",
    )
    return RedirectResponse(authorize_url)


@router.get("/callback")
async def callback(request: Request, response: Response):
    """OAuth 回调：换 token + 拉 user info + 设 session cookie

    失败时：
    - code 无效 → 401
    - 拿不到 user info → 502
    """
    code = request.query_params.get("code")
    if not code:
        raise HTTPException(status_code=400, detail="Missing code parameter")

    # 换 access_token
    try:
        token = await github_oauth.get_access_token(code, f"{request.url.scheme}://{request.headers['host']}/auth/callback")
    except Exception as e:
        logger.error(f"OAuth token exchange failed: {e}")
        raise HTTPException(status_code=401, detail=f"OAuth failed: {e}")

    # 拉用户信息（GitHub /user endpoint）
    async with httpx.AsyncClient() as client:
        user_resp = await client.get(
            "https://api.github.com/user",
            headers={
                "Authorization": f"Bearer {token['access_token']}",
                "Accept": "application/json",
            },
        )
    if user_resp.status_code != 200:
        raise HTTPException(status_code=502, detail="Failed to fetch GitHub user info")

    user_data = user_resp.json()
    session = SessionData(
        user_id=str(user_data["id"]),
        github_login=user_data["login"],
        access_token=token["access_token"],
    )

    # 设 cookie 并重定向到首页
    response = RedirectResponse(url="/", status_code=302)
    response.set_cookie(
        key=SESSION_COOKIE_NAME,
        value=_serialize_session(session),
        max_age=SESSION_MAX_AGE,
        httponly=True,
        secure=False,  # 生产环境应 True（HTTPS）
        samesite="lax",
    )
    return response


@router.post("/logout")
async def logout(response: Response):
    """清 session cookie，重定向到 /auth/login"""
    response = RedirectResponse(url="/auth/login", status_code=302)
    response.delete_cookie(SESSION_COOKIE_NAME)
    return response


@router.get("/me")
async def me(session: Optional[SessionData] = Depends(get_current_session)):
    """返回当前登录用户信息（前端 SPA 可用来判断登录状态）"""
    if session is None:
        return {"authenticated": False}
    return {
        "authenticated": True,
        "user_id": session.user_id,
        "github_login": session.github_login,
    }