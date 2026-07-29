"""Web 静态资源 + SPA fallback 测试（v0.10 M5 / M11 React 升级）

SPA 由 Vite + React 构建，输出到 server/static/。
index.html 是 Vite 生成的入口，引用 assets/index-*.js 和 assets/index-*.css。
"""
from fastapi.testclient import TestClient

from ai_pr_review.server.web import create_app


def test_static_files_served_at_static_prefix():
    """FastAPI 应挂载 server/static/ 目录到 /static"""
    app = create_app()
    client = TestClient(app)
    resp = client.get("/static/dashboard.css")
    assert resp.status_code == 200
    assert "text/css" in resp.headers["content-type"]


def test_static_assets_served():
    """Vite 构建产物在 /static/assets/ 下"""
    app = create_app()
    client = TestClient(app)
    # 列出 assets 目录
    resp = client.get("/static/assets/")
    assert resp.status_code == 200
    # 应包含 Vite 生成的 .js 和 .css
    body = resp.text
    assert ".js" in body
    assert ".css" in body


def test_static_assets_served():
    """Vite 构建产物 /static/assets/index-*.js 可访问"""
    app = create_app()
    client = TestClient(app)
    import re
    index_resp = client.get("/")
    m = re.search(r'src="(/static/assets/[^"]+\.js)"', index_resp.text)
    assert m, f"JS asset not found in {index_resp.text}"
    resp = client.get(m.group(1))
    assert resp.status_code == 200


def test_static_js_served():
    """Vite 打包后的 JS 应可访问（路径含 hash）"""
    app = create_app()
    client = TestClient(app)
    # 找到 index.html 引用的 JS 文件
    index_resp = client.get("/")
    # 解析 <script src="...">
    import re
    m = re.search(r'src="(/static/assets/[^"]+\.js)"', index_resp.text)
    assert m, f"JS not found in {index_resp.text}"
    js_path = m.group(1)
    resp = client.get(js_path)
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


def test_index_html_has_react_root():
    """index.html 含 React 根容器 + Vite 脚本"""
    app = create_app()
    client = TestClient(app)
    resp = client.get("/")
    # React 根容器
    assert 'id="root"' in resp.text
    # Vite 注入的入口脚本
    assert "/static/assets/" in resp.text
    assert ".js" in resp.text


def test_index_html_links_to_static_assets():
    """index.html 引用 CSS 和 JS bundle"""
    app = create_app()
    client = TestClient(app)
    resp = client.get("/")
    assert "/static/assets/" in resp.text


def test_dashboard_css_contains_key_classes():
    """打包后的 CSS 含基础布局 class"""
    app = create_app()
    client = TestClient(app)
    # 找 CSS
    import re
    index_resp = client.get("/")
    m = re.search(r'href="(/static/assets/[^"]+\.css)"', index_resp.text)
    assert m, f"CSS not found in {index_resp.text}"
    resp = client.get(m.group(1))
    css = resp.text
    assert ".topbar" in css or "topbar" in css
    assert "stats-grid" in css or "stats_grid" in css
    assert "data-table" in css


def test_bundle_includes_api_endpoints():
    """JS bundle 引用 /api/* 端点（编译时打进去）"""
    app = create_app()
    client = TestClient(app)
    # 找 JS
    import re
    index_resp = client.get("/")
    m = re.search(r'src="(/static/assets/[^"]+\.js)"', index_resp.text)
    assert m
    resp = client.get(m.group(1))
    js = resp.text
    # minified bundle 中路径会被保留
    assert "/auth/me" in js or "/api/" in js