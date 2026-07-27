"""GitHub OAuth + Session 测试（v0.10 M2）

覆盖：
- /auth/login 重定向到 GitHub 授权 URL
- /auth/me 未登录返回 authenticated=False
- /auth/me 登录后返回用户信息
- /auth/logout 清 cookie
- require_session dependency 未登录返回 401
- session cookie 签名 + 校验
- 完整 OAuth flow mock（callback 路径）
"""
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient

from ai_pr_review.server.routes.auth import (
    SESSION_COOKIE_NAME,
    SessionData,
    _deserialize_session,
    _serialize_session,
    get_current_session,
    require_session,
)
from ai_pr_review.server.web import create_app


@pytest.fixture
def app():
    return create_app()


@pytest.fixture
def client(app):
    return TestClient(app)


# ===== Session cookie 签名/校验 =====

def test_session_serialize_roundtrip():
    """SessionData 序列化后能反序列化"""
    data = SessionData(user_id="12345", github_login="octocat", access_token="gho_xxx")
    token = _serialize_session(data)
    restored = _deserialize_session(token)
    assert restored is not None
    assert restored.user_id == "12345"
    assert restored.github_login == "octocat"
    assert restored.access_token == "gho_xxx"


def test_session_deserialize_rejects_tampered_token():
    """篡改的 token 应返回 None（不抛）"""
    assert _deserialize_session("garbage.invalid.token") is None


def test_session_deserialize_rejects_empty_string():
    """空字符串返回 None"""
    assert _deserialize_session("") is None


# ===== /auth/login 重定向 =====

def test_login_redirects_to_github(client):
    """GET /auth/login 应 307 重定向到 GitHub 授权页"""
    r = client.get("/auth/login", follow_redirects=False)
    assert r.status_code == 307
    location = r.headers.get("location", "")
    assert "github.com" in location
    assert "oauth/authorize" in location
    # client_id 应在 URL 中（httpx-oauth 用 GET 参数而非 state）
    assert "client_id=" in location
    assert "redirect_uri=" in location


# ===== /auth/me 未登录 =====

def test_me_without_session_returns_unauthenticated(client):
    """无 cookie 时 /auth/me 返回 authenticated=False"""
    r = client.get("/auth/me")
    assert r.status_code == 200
    assert r.json() == {"authenticated": False}


def test_me_with_valid_session_returns_user_info(client):
    """带合法 session cookie 时 /auth/me 返回用户信息"""
    session = SessionData(user_id="42", github_login="testuser", access_token="gho_abc")
    token = _serialize_session(session)

    r = client.get("/auth/me", cookies={SESSION_COOKIE_NAME: token})
    assert r.status_code == 200
    body = r.json()
    assert body["authenticated"] is True
    assert body["user_id"] == "42"
    assert body["github_login"] == "testuser"


def test_me_with_invalid_session_returns_unauthenticated(client):
    """带非法 cookie 时 /auth/me 返回 authenticated=False"""
    r = client.get("/auth/me", cookies={SESSION_COOKIE_NAME: "garbage.token.here"})
    assert r.status_code == 200
    assert r.json() == {"authenticated": False}


# ===== /auth/logout =====

def test_logout_clears_cookie(client):
    """POST /auth/logout 应清 cookie"""
    session = SessionData(user_id="1", github_login="x", access_token="t")
    cookie = _serialize_session(session)

    r = client.post("/auth/logout", cookies={SESSION_COOKIE_NAME: cookie}, follow_redirects=False)
    assert r.status_code == 302
    # Set-Cookie 应删除 cookie（Max-Age=0 或 expires=过去）
    set_cookie = r.headers.get("set-cookie", "")
    assert SESSION_COOKIE_NAME in set_cookie
    # cookie 应被标记为过期
    assert "Max-Age=0" in set_cookie or "expires=" in set_cookie.lower()


# ===== /auth/callback mock 流程 =====

async def test_callback_with_valid_code_sets_cookie():
    """完整 callback 流程：code → token → user info → session cookie"""
    app = create_app()
    client = TestClient(app)

    # Mock GitHub OAuth responses
    fake_token_response = {"access_token": "gho_test_token_123", "token_type": "bearer", "scope": "read:user"}
    fake_user = {"id": 999, "login": "testuser", "name": "Test User"}

    # Mock get_access_token + httpx call to /user
    with patch("ai_pr_review.server.routes.auth.github_oauth") as mock_oauth:
        mock_oauth.get_access_token = AsyncMock(return_value=fake_token_response)

        # httpx 已在模块顶部导入
        with patch("ai_pr_review.server.routes.auth.httpx.AsyncClient") as mock_client_cls:
            mock_client = AsyncMock()
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=None)
            mock_response = MagicMock()
            mock_response.status_code = 200
            mock_response.json = MagicMock(return_value=fake_user)
            mock_client.get = AsyncMock(return_value=mock_response)
            mock_client_cls.return_value = mock_client

            r = client.get("/auth/callback?code=test_code", follow_redirects=False)

    assert r.status_code == 302
    # 应设置 session cookie
    set_cookie = r.headers.get("set-cookie", "")
    assert SESSION_COOKIE_NAME in set_cookie


def test_callback_when_github_user_fetch_fails_returns_502():
    """拿不到 GitHub user 信息时返回 502"""
    app = create_app()
    client = TestClient(app)

    with patch("ai_pr_review.server.routes.auth.github_oauth") as mock_oauth:
        mock_oauth.get_access_token = AsyncMock(
            return_value={"access_token": "gho_t", "token_type": "bearer"}
        )
        with patch("ai_pr_review.server.routes.auth.httpx.AsyncClient") as mock_client_cls:
            mock_client = AsyncMock()
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=None)
            mock_response = MagicMock()
            mock_response.status_code = 401  # GitHub 返回 401
            mock_client.get = AsyncMock(return_value=mock_response)
            mock_client_cls.return_value = mock_client

            r = client.get("/auth/callback?code=test_code")

    assert r.status_code == 502


def test_callback_without_code_returns_400(client):
    """无 code 参数返回 400"""
    r = client.get("/auth/callback")
    assert r.status_code == 400


# ===== require_session dependency =====

async def test_require_session_dependency_returns_session_when_authenticated():
    """有 session cookie 时 require_session 返回 SessionData"""
    session = SessionData(user_id="1", github_login="x", access_token="t")
    token = _serialize_session(session)

    # 构造一个带 cookie 的 mock Request
    from starlette.requests import Request
    scope = {
        "type": "http",
        "headers": [(b"cookie", f"{SESSION_COOKIE_NAME}={token}".encode())],
    }
    request = Request(scope)

    result = await require_session(session=await get_current_session(request))
    assert result.user_id == "1"


async def test_require_session_dependency_raises_401_when_unauthenticated():
    """无 session cookie 时 require_session 抛 401"""
    from starlette.requests import Request
    scope = {"type": "http", "headers": []}
    request = Request(scope)

    with pytest.raises(HTTPException) as exc_info:
        await require_session(session=await get_current_session(request))
    assert exc_info.value.status_code == 401