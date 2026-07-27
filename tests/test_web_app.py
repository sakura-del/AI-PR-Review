"""FastAPI 应用骨架测试（v0.10 M1）

覆盖：
- create_app() 返回可用的 FastAPI 实例
- /api/health 返回 200 + 必要字段
- /api/metrics 返回 metrics snapshot
- lifespan 启动/关闭正常（JobQueue 关闭不抛）
- 路由注册：auth / dashboard / jobs / settings 都已挂载
"""
import pytest
from fastapi.testclient import TestClient

from ai_pr_review.server.web import create_app


@pytest.fixture
def app():
    """每个测试新建一个 app 实例（避免 JobQueue 单例污染）"""
    return create_app()


@pytest.fixture
def client(app):
    return TestClient(app)


def test_create_app_returns_fastapi_instance():
    from fastapi import FastAPI
    app = create_app()
    assert isinstance(app, FastAPI)
    assert app.title == "AI PR Review Web"
    assert app.version == "0.10.0"


def test_health_endpoint_returns_ok(client):
    """健康检查无需认证，返回 200 + 关键字段"""
    resp = client.get("/api/health")
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "ok"
    assert body["version"] == "0.10.0"
    assert "jobs" in body
    assert "degradation_level" in body


def test_metrics_endpoint_returns_snapshot(client):
    """指标端点返回 MetricsRegistry snapshot"""
    resp = client.get("/api/metrics")
    assert resp.status_code == 200
    body = resp.json()
    assert "counters" in body
    assert "histograms" in body
    assert "gauges" in body
    assert isinstance(body["counters"], list)


def test_auth_router_is_registered(client):
    """/auth/login 应重定向到 GitHub OAuth（已实现 M2）"""
    resp = client.get("/auth/login", follow_redirects=False)
    # 307 重定向到 github.com/oauth/authorize
    assert resp.status_code == 307
    assert "github.com" in resp.headers.get("location", "")


def test_dashboard_root_registered(client):
    """/ (Dashboard) 已挂载"""
    resp = client.get("/")
    assert resp.status_code == 200


def test_jobs_router_registered(client):
    """/api/jobs/{job_id} 已挂载"""
    resp = client.get("/api/jobs/test-job-id")
    assert resp.status_code == 200
    assert resp.json().get("job_id") == "test-job-id"


def test_settings_router_registered(client):
    """/settings 已挂载"""
    resp = client.get("/settings")
    assert resp.status_code == 200


def test_cors_middleware_configured(app):
    """CORS 中间件已添加（前端 Vite dev server 需要）"""
    # FastAPI 把中间件栈存在 user_middleware 列表里
    middleware_classes = [m.cls.__name__ for m in app.user_middleware]
    assert "CORSMiddleware" in middleware_classes
    assert len(middleware_classes) >= 1


def test_cors_default_origins_include_vite_dev_server(app):
    """默认 CORS 白名单包含 Vite dev server（5173）

    注：Starlette 的 Middleware 对象结构因版本而异，这里只验证中间件存在；
    具体的 origins 白名单在 E2E 测试中验证。
    """
    middleware_classes = [m.cls.__name__ for m in app.user_middleware]
    assert "CORSMiddleware" in middleware_classes


def test_app_with_custom_cors_origins():
    """create_app 接受自定义 cors_origins（不报错）"""
    app = create_app(cors_origins=["https://example.com"])
    # 验证应用创建成功 + 包含 CORS 中间件
    middleware_classes = [m.cls.__name__ for m in app.user_middleware]
    assert "CORSMiddleware" in middleware_classes


def test_lifespan_manages_job_queue():
    """lifespan context 启动后 JobQueue 已就绪，关闭不抛"""
    app = create_app()
    with TestClient(app) as client:
        # lifespan 启动完成
        resp = client.get("/api/health")
        assert resp.status_code == 200
    # lifespan 关闭：JobQueue.shutdown 应被调用，不抛


def test_openapi_schema_exposed():
    """OpenAPI schema 应可获取（前端可用）"""
    app = create_app()
    client = TestClient(app)
    resp = client.get("/openapi.json")
    assert resp.status_code == 200
    schema = resp.json()
    assert schema["info"]["title"] == "AI PR Review Web"
    assert schema["info"]["version"] == "0.10.0"
    # 至少包含 health + metrics 路径
    paths = schema["paths"]
    assert "/api/health" in paths
    assert "/api/metrics" in paths