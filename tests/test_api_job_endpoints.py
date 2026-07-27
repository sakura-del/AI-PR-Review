"""api_server JobQueue 接入测试（T20 [A16]）

覆盖：
- POST /api/review 返回 job_id（不再是 pr_url-only）
- GET /api/jobs/{job_id} 路径参数工作
- job 状态变化反映在 API 响应中
- 健康检查包含 job 计数
- 端到端：submit → 异步处理 → 状态查询
"""
import asyncio
import json

import pytest

from ai_pr_review.server.api_server import (
    _path_to_regex,
    APIRouter,
    build_router,
)
from ai_pr_review.data.job_queue import JobStatus
from ai_pr_review.server.job_queue_runtime import (
    InMemoryJobQueue,
    configure_job_queue,
    get_job_queue,
    reset_job_queue,
)


# ===== 路径参数路由 =====

def test_path_to_regex_simple():
    pattern, names = _path_to_regex("/api/jobs/{job_id}")
    assert names == ["job_id"]
    assert pattern.match("/api/jobs/abc123").groupdict() == {"job_id": "abc123"}


def test_path_to_regex_multiple_params():
    pattern, names = _path_to_regex("/users/{user_id}/posts/{post_id}")
    assert names == ["user_id", "post_id"]
    match = pattern.match("/users/u1/posts/p9")
    assert match.groupdict() == {"user_id": "u1", "post_id": "p9"}


def test_path_to_regex_no_param():
    pattern, names = _path_to_regex("/api/health")
    assert names == []
    assert pattern.match("/api/health")
    assert not pattern.match("/api/health/extra")


def test_router_match_with_path_param():
    async def handler(job_id):
        return 200, {"id": job_id}

    router = APIRouter()
    router.add_route("GET", "/api/jobs/{job_id}", handler)
    h, params = router.match("GET", "/api/jobs/abc")
    assert h is handler
    assert params == {"job_id": "abc"}


def test_router_path_param_does_not_match_extra_segments():
    async def handler(job_id):
        return 200, {"id": job_id}

    router = APIRouter()
    router.add_route("GET", "/api/jobs/{job_id}", handler)
    h, _ = router.match("GET", "/api/jobs/abc/extra")
    assert h is None


# ===== /api/review 返回 job_id =====

@pytest.fixture(autouse=True)
def _reset_singleton():
    reset_job_queue()
    yield
    reset_job_queue()


async def test_review_endpoint_returns_job_id():
    async def review_fn(url):
        return None

    router = build_router(review_fn)
    handler, _ = router.match("POST", "/api/review")

    body = json.dumps({"pr_url": "https://github.com/o/r/pull/1"}).encode()
    status, resp = await handler({}, body)

    assert status == 202
    assert "job_id" in resp
    assert resp["status"] == "pending"
    assert resp["pr_url"] == "https://github.com/o/r/pull/1"

    await get_job_queue().shutdown()


async def test_review_endpoint_invalid_json_no_job_created():
    async def review_fn(url):
        return None

    router = build_router(review_fn)
    handler, _ = router.match("POST", "/api/review")

    status, resp = await handler({}, b"not json")
    assert status == 400
    # 不应创建任何 job
    assert get_job_queue().pending_count == 0

    await get_job_queue().shutdown()


async def test_review_endpoint_missing_pr_url_no_job_created():
    async def review_fn(url):
        return None

    router = build_router(review_fn)
    handler, _ = router.match("POST", "/api/review")

    status, resp = await handler({}, b'{}')
    assert status == 400
    assert get_job_queue().pending_count == 0

    await get_job_queue().shutdown()


# ===== /api/jobs/{job_id} =====

async def test_get_job_returns_pending_state():
    """submit 后立即查应是 PENDING（handler 慢）"""
    block = asyncio.Event()

    async def slow_handler(url):
        await block.wait()
        return None

    router = build_router(slow_handler)
    handler, _ = router.match("POST", "/api/review")

    body = json.dumps({"pr_url": "https://github.com/o/r/pull/1"}).encode()
    status, resp = await handler({}, body)
    job_id = resp["job_id"]

    # 立即查 GET /api/jobs/{job_id}
    get_handler, params = router.match("GET", "/api/jobs/" + job_id)
    status2, resp2 = await get_handler(
        headers={}, body=b"",
        **params,
    )
    assert status2 == 200
    assert resp2["job_id"] == job_id
    assert resp2["status"] in ("pending", "running")
    assert resp2["pr_url"] == "https://github.com/o/r/pull/1"

    # 放行 handler 让它完成
    block.set()
    await asyncio.sleep(0.05)
    await get_job_queue().shutdown()


async def test_get_job_succeeded_includes_result():
    """job 完成后再查应包含 result"""
    async def handler(url):
        await asyncio.sleep(0.01)
        return {"summary": "ok", "findings": []}

    router = build_router(handler)
    handler_post, _ = router.match("POST", "/api/review")
    body = json.dumps({"pr_url": "https://x.com/p/1"}).encode()
    status, resp = await handler_post({}, body)
    job_id = resp["job_id"]

    # 等 worker 处理完
    await asyncio.sleep(0.1)

    get_handler, params = router.match("GET", "/api/jobs/" + job_id)
    status2, resp2 = await get_handler(
        headers={}, body=b"",
        **params,
    )
    assert status2 == 200
    assert resp2["status"] == "succeeded"
    assert resp2["result"] == {"summary": "ok", "findings": []}
    assert resp2["finished_at"] is not None
    assert resp2["started_at"] is not None

    await get_job_queue().shutdown()


async def test_get_job_unknown_returns_404():
    async def review_fn(url):
        return None

    router = build_router(review_fn)
    get_handler, params = router.match("GET", "/api/jobs/never-existed")
    status, resp = await get_handler(headers={}, body=b"", **params)
    assert status == 404
    assert resp["error"] == "job not found"

    await get_job_queue().shutdown()


async def test_get_job_failed_includes_error():
    """handler 抛异常 → job FAILED → API 返回 error 字段"""
    async def failing_handler(url):
        raise ValueError("boom")

    router = build_router(failing_handler)
    handler_post, _ = router.match("POST", "/api/review")
    body = json.dumps({"pr_url": "https://x.com/p/1"}).encode()
    status, resp = await handler_post({}, body)
    job_id = resp["job_id"]

    await asyncio.sleep(0.1)

    get_handler, params = router.match("GET", "/api/jobs/" + job_id)
    status2, resp2 = await get_handler(headers={}, body=b"", **params)
    assert status2 == 200
    assert resp2["status"] == "failed"
    assert "boom" in resp2["error"]

    await get_job_queue().shutdown()


# ===== /api/health 包含 job 计数 =====

async def test_health_includes_pending_and_running_counts():
    block = asyncio.Event()

    async def slow_handler(url):
        await block.wait()
        return None

    try:
        router = build_router(slow_handler)
        handler_post, _ = router.match("POST", "/api/review")

        # 提交 2 个：一个被 worker 占住 RUNNING，一个在 queue 里 PENDING
        await handler_post({}, json.dumps({"pr_url": "https://x.com/p/1"}).encode())
        for _ in range(20):
            await asyncio.sleep(0.005)
            if get_job_queue().running_count == 1:
                break
        await handler_post({}, json.dumps({"pr_url": "https://x.com/p/2"}).encode())

        health_handler, _ = router.match("GET", "/api/health")
        status, resp = await health_handler({}, b"")
        assert status == 200
        assert resp["status"] == "ok"
        assert resp["jobs"]["running"] == 1
        assert resp["jobs"]["pending"] == 1
    finally:
        # 放行 handler + shutdown queue（保证 pytest teardown 不卡）
        block.set()
        await get_job_queue().shutdown()


# ===== 端到端：submit → 处理 → 查询 → 状态流转 =====

async def test_end_to_end_job_lifecycle():
    """完整生命周期：PENDING → RUNNING → SUCCEEDED"""
    states = []

    async def recording_handler(url):
        states.append("running")
        await asyncio.sleep(0.02)
        states.append("done")
        return "ok"

    router = build_router(recording_handler)
    handler_post, _ = router.match("POST", "/api/review")
    body = json.dumps({"pr_url": "https://x.com/p/1"}).encode()
    status, resp = await handler_post({}, body)
    job_id = resp["job_id"]

    # 立即查：应为 PENDING（worker 还没抢到）或 RUNNING
    get_handler, params = router.match("GET", "/api/jobs/" + job_id)
    _, resp_pending = await get_handler(headers={}, body=b"", **params)
    assert resp_pending["status"] in ("pending", "running")

    # 等 worker 处理
    await asyncio.sleep(0.1)

    # 再查：应是 SUCCEEDED
    _, resp_done = await get_handler(headers={}, body=b"", **params)
    assert resp_done["status"] == "succeeded"
    assert resp_done["result"] == "ok"

    assert "running" in states
    assert "done" in states

    await get_job_queue().shutdown()


async def test_uses_provided_job_queue():
    """build_router 应接受外部 job_queue 实例（不创建新队列）"""
    async def handler(url):
        return None

    # 预创建一个 JobQueue 并配置为单例
    queue = InMemoryJobQueue(handler)
    configure_job_queue(queue)

    router = build_router(handler, job_queue=queue)

    # 单例应该是同一个
    assert get_job_queue() is queue

    # 提交后能查
    handler_post, _ = router.match("POST", "/api/review")
    body = json.dumps({"pr_url": "https://x.com/p/1"}).encode()
    status, resp = await handler_post({}, body)
    job_id = resp["job_id"]
    await asyncio.sleep(0.05)
    final = await queue.get(job_id)
    assert final.status == JobStatus.SUCCEEDED

    await queue.shutdown()