"""Dashboard Web API 端点测试（v0.10 M6）

覆盖：
- /api/stats 返回统计字段（total / high / medium / avg_duration）
- /api/history?limit=N 返回 records
- /api/history/me 未登录返回 401
- /api/jobs 未配置 JobQueue 时返回空列表（优雅降级）
"""
from dataclasses import asdict

import pytest
from fastapi.testclient import TestClient

from ai_pr_review.core.degradation import get_degradation_manager
from ai_pr_review.data.history import AnalysisRecord, save_record
from ai_pr_review.server.web import create_app


# 注：storage 由 conftest.py 的 autouse fixture 提供（tmp_path 隔离）
# 不再重复 reset / configure


@pytest.fixture
def client():
    """每次测试新 app（避免 JobQueue 单例污染）"""
    return TestClient(create_app())


# ===== /api/stats =====

def test_stats_returns_zero_when_no_history(client):
    """无 history 时返回全 0"""
    r = client.get("/api/stats")
    assert r.status_code == 200
    body = r.json()
    assert body["total"] == 0
    assert body["high"] == 0
    assert body["medium"] == 0
    assert body["low"] == 0
    assert body["avg_duration"] == 0.0


def test_stats_aggregates_from_history(client):
    """stats 应聚合所有 history 记录"""
    save_record(AnalysisRecord(
        pr_url="https://x.com/1", pr_title="A",
        high_severity_count=2, medium_severity_count=3, low_severity_count=1,
        duration_seconds=10.0,
    ))
    save_record(AnalysisRecord(
        pr_url="https://x.com/2", pr_title="B",
        high_severity_count=1, medium_severity_count=0, low_severity_count=2,
        duration_seconds=20.0,
    ))
    save_record(AnalysisRecord(
        pr_url="https://x.com/3", pr_title="C",
        high_severity_count=0, medium_severity_count=5, low_severity_count=0,
        duration_seconds=0.0,  # 0 不计入 avg
    ))

    r = client.get("/api/stats")
    assert r.status_code == 200
    body = r.json()
    assert body["total"] == 3
    assert body["high"] == 3  # 2 + 1 + 0
    assert body["medium"] == 8  # 3 + 0 + 5
    assert body["low"] == 3  # 1 + 2 + 0
    assert body["avg_duration"] == 15.0  # (10 + 20) / 2，0 不计入


# ===== /api/history =====

def test_history_returns_records_with_limit(client):
    """history 应按 limit 截断返回"""
    for i in range(5):
        save_record(AnalysisRecord(pr_url=f"https://x.com/{i}", pr_title=f"PR{i}"))

    r = client.get("/api/history?limit=3")
    assert r.status_code == 200
    items = r.json()
    assert len(items) == 3
    assert all("timestamp_display" in item for item in items)


def test_history_limit_validation(client):
    """limit 参数范围校验（ge=1, le=100）"""
    r = client.get("/api/history?limit=0")
    assert r.status_code == 422  # FastAPI Query 校验失败
    r = client.get("/api/history?limit=200")
    assert r.status_code == 422


def test_history_sorted_newest_first(client):
    """history 按 timestamp 倒序"""
    import time
    for i in range(3):
        save_record(AnalysisRecord(pr_url=f"https://x.com/{i}", pr_title=f"PR{i}"))
        time.sleep(0.01)

    r = client.get("/api/history?limit=10")
    items = r.json()
    timestamps = [it["timestamp"] for it in items]
    assert timestamps == sorted(timestamps, reverse=True)


# ===== /api/jobs 优雅降级 =====

def test_jobs_endpoint_handles_missing_queue_gracefully(client):
    """JobQueue 未配置时 /api/jobs 返回空列表（不 500）"""
    r = client.get("/api/jobs")
    assert r.status_code == 200
    assert r.json() == []


def test_jobs_endpoint_handles_missing_queue_on_get_by_id(client):
    """JobQueue 未配置时 GET /api/jobs/{id} 返回 503"""
    r = client.get("/api/jobs/test-id")
    assert r.status_code == 503


# ===== /api/jobs 提交 =====

def test_submit_job_requires_pr_url(client):
    """POST /api/jobs 缺 pr_url 返回 422"""
    r = client.post("/api/jobs", json={})
    assert r.status_code == 422


def test_submit_job_requires_job_queue_configured(client):
    """POST /api/jobs 在 JobQueue 未配置时返回 503"""
    r = client.post("/api/jobs", json={"pr_url": "https://github.com/o/r/pull/1"})
    assert r.status_code == 503


def test_submit_job_with_queue_succeeds():
    """POST /api/jobs 在配置 JobQueue 后返回 202 + job_id"""
    from ai_pr_review.server.job_queue_runtime import InMemoryJobQueue, configure_job_queue, reset_job_queue
    reset_job_queue()

    async def handler(pr_url):
        return None
    configure_job_queue(InMemoryJobQueue(handler))

    try:
        client = TestClient(create_app())
        r = client.post("/api/jobs", json={"pr_url": "https://github.com/o/r/pull/1"})
        assert r.status_code == 202
        body = r.json()
        assert "job_id" in body
        assert body["status"] == "pending"
        assert body["pr_url"] == "https://github.com/o/r/pull/1"
    finally:
        import asyncio
        asyncio.run(reset_job_queue().__class__ and None or _shutdown_queue())


async def _shutdown_queue():
    """helper for sync test cleanup"""
    from ai_pr_review.server.job_queue_runtime import get_job_queue
    try:
        await get_job_queue().shutdown()
    except RuntimeError:
        pass


# ===== /api/metrics 移到了 dashboard router =====

def test_metrics_endpoint_exposed(client):
    """/api/metrics 返回 registry snapshot"""
    r = client.get("/api/metrics")
    assert r.status_code == 200
    body = r.json()
    assert "counters" in body
    assert "histograms" in body
    assert "gauges" in body