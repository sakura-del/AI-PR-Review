"""Web 静态资源 + SPA fallback 测试（v0.10 M5）"""
from fastapi.testclient import TestClient

from ai_pr_review.server.web import create_app


def test_static_files_served_at_static_prefix():
    """FastAPI 应挂载 server/static/ 目录到 /static"""
    app = create_app()
    client = TestClient(app)
    resp = client.get("/static/dashboard.css")
    assert resp.status_code == 200
    assert "text/css" in resp.headers["content-type"]


def test_static_js_served():
    app = create_app()
    client = TestClient(app)
    resp = client.get("/static/dashboard.js")
    assert resp.status_code == 200
    assert "javascript" in resp.headers["content-type"] or "ecmascript" in resp.headers["content-type"]


def test_root_path_serves_index_html():
    """GET / 应返回 SPA 入口 index.html"""
    app = create_app()
    client = TestClient(app)
    resp = client.get("/")
    assert resp.status_code == 200
    # index.html 包含品牌标识
    assert "AI PR Review" in resp.text


def test_index_html_contains_dashboard_root():
    """index.html 含 Dashboard SPA 容器"""
    app = create_app()
    client = TestClient(app)
    resp = client.get("/")
    assert 'id="dashboard-view"' in resp.text


def test_index_html_links_to_static_assets():
    """index.html 引用 CSS 和 JS"""
    app = create_app()
    client = TestClient(app)
    resp = client.get("/")
    assert '/static/dashboard.css' in resp.text
    assert '/static/dashboard.js' in resp.text


def test_dashboard_css_contains_key_classes():
    """.css 含基础布局 class"""
    app = create_app()
    client = TestClient(app)
    resp = client.get("/static/dashboard.css")
    css = resp.text
    assert ".topbar" in css
    assert ".stats-grid" in css
    assert ".data-table" in css


def test_dashboard_js_calls_api_endpoints():
    """JS 引用 /api/* 端点（SPA 数据流）"""
    app = create_app()
    client = TestClient(app)
    resp = client.get("/static/dashboard.js")
    js = resp.text
    assert "/auth/me" in js
    assert "/api/jobs" in js
    assert "/api/history" in js