"""api_server 模块测试 — 覆盖路由、请求解析、响应构建、端到端 HTTP"""
import asyncio
import json
import pytest
from ai_pr_review.api_server import (
    APIRouter,
    build_router,
    _build_response,
    _parse_request,
    _read_request,
    handle_connection,
    serve,
    DEFAULT_PORT,
)


def _make_request(method: str, path: str, body: bytes = b"", headers: dict = None) -> bytes:
    """构造原始 HTTP 请求字节流"""
    head = f"{method} {path} HTTP/1.1\r\n"
    head += "Host: localhost\r\n"
    if headers:
        for k, v in headers.items():
            head += f"{k}: {v}\r\n"
    if body:
        head += f"Content-Length: {len(body)}\r\n"
    head += "\r\n"
    return head.encode("iso-8859-1") + body


# ===== APIRouter 单元测试 =====

def test_router_add_and_match():
    router = APIRouter()
    router.add_route("GET", "/test", lambda h, b: None)
    assert router.match("GET", "/test") is not None
    assert router.match("POST", "/test") is None
    assert router.match("GET", "/other") is None


def test_router_case_insensitive_method():
    router = APIRouter()
    router.add_route("post", "/x", lambda h, b: None)
    assert router.match("POST", "/x") is not None


def test_router_strips_query_string_by_parse():
    """_parse_request 应去掉 path 中的 query string"""
    req = _make_request("GET", "/api/history?limit=10")
    parsed = _parse_request(req)
    assert parsed is not None
    method, path, headers, body = parsed
    assert path == "/api/history"


# ===== _build_response 单元测试 =====

def test_build_response_json():
    resp = _build_response(200, {"status": "ok"})
    text = resp.decode("utf-8")
    assert "HTTP/1.1 200 OK" in text
    assert "application/json" in text
    assert '{"status": "ok"}' in text


def test_build_response_string():
    resp = _build_response(200, "hello")
    text = resp.decode("utf-8")
    assert "text/plain" in text
    assert "hello" in text


def test_build_response_status_codes():
    for code in [200, 201, 202, 400, 401, 404, 405, 500]:
        resp = _build_response(code, {})
        assert f"{code}" in resp.decode("utf-8")


def test_build_response_includes_content_length():
    resp = _build_response(200, {"k": "v"})
    text = resp.decode("utf-8")
    assert "Content-Length:" in text


# ===== _parse_request 单元测试 =====

def test_parse_request_valid():
    req = _make_request("POST", "/api/review", body=b'{"pr_url":"x"}',
                        headers={"X-GitHub-Event": "pull_request"})
    parsed = _parse_request(req)
    assert parsed is not None
    method, path, headers, body = parsed
    assert method == "POST"
    assert path == "/api/review"
    assert headers.get("X-GitHub-Event") == "pull_request"
    assert b'{"pr_url":"x"}' in body


def test_parse_request_invalid_format():
    assert _parse_request(b"garbage") is None


def test_parse_request_empty_body():
    req = _make_request("GET", "/health")
    parsed = _parse_request(req)
    assert parsed is not None
    _, _, _, body = parsed
    assert body == b""


# ===== _read_request 单元测试 =====

@pytest.mark.asyncio
async def test_read_request_with_body():
    body = b'{"pr_url":"https://github.com/o/r/pull/1"}'
    req = _make_request("POST", "/api/review", body=body)

    reader = asyncio.StreamReader()
    reader.feed_data(req)
    reader.feed_eof()

    result = await _read_request(reader)
    assert result is not None
    assert body in result


@pytest.mark.asyncio
async def test_read_request_empty_body():
    req = _make_request("GET", "/health")
    reader = asyncio.StreamReader()
    reader.feed_data(req)
    reader.feed_eof()

    result = await _read_request(reader)
    assert result is not None


# ===== build_router 集成测试 =====

@pytest.mark.asyncio
async def test_health_endpoint():
    triggered: list[str] = []

    async def review_fn(url):
        triggered.append(url)

    router = build_router(review_fn)
    handler = router.match("GET", "/api/health")
    assert handler is not None

    status, body = await handler({}, b"")
    assert status == 200
    assert body["status"] == "ok"


@pytest.mark.asyncio
async def test_review_endpoint_accepts_pr_url():
    triggered: list[str] = []

    async def review_fn(url):
        triggered.append(url)

    router = build_router(review_fn)
    handler = router.match("POST", "/api/review")

    body = json.dumps({"pr_url": "https://github.com/o/r/pull/2"}).encode()
    status, resp = await handler({}, body)
    assert status == 202
    assert resp["status"] == "accepted"
    # 等待异步任务
    await asyncio.sleep(0.05)
    assert triggered == ["https://github.com/o/r/pull/2"]


@pytest.mark.asyncio
async def test_review_endpoint_rejects_missing_pr_url():
    async def review_fn(url):
        pass

    router = build_router(review_fn)
    handler = router.match("POST", "/api/review")

    status, resp = await handler({}, b'{}')
    assert status == 400
    assert "pr_url" in resp["error"]


@pytest.mark.asyncio
async def test_review_endpoint_rejects_invalid_json():
    async def review_fn(url):
        pass

    router = build_router(review_fn)
    handler = router.match("POST", "/api/review")

    status, resp = await handler({}, b"not json")
    assert status == 400


@pytest.mark.asyncio
async def test_history_endpoint_with_fn():
    async def review_fn(url):
        pass

    def history_fn():
        return [{"pr": "a", "findings": 3}, {"pr": "b", "findings": 1}]

    router = build_router(review_fn, history_fn=history_fn)
    handler = router.match("GET", "/api/history")

    status, body = await handler({}, b"")
    assert status == 200
    assert len(body) == 2


@pytest.mark.asyncio
async def test_history_endpoint_without_fn():
    async def review_fn(url):
        pass

    router = build_router(review_fn, history_fn=None)
    handler = router.match("GET", "/api/history")

    status, body = await handler({}, b"")
    assert status == 200
    assert body == []


@pytest.mark.asyncio
async def test_history_endpoint_handles_fn_exception():
    async def review_fn(url):
        pass

    def history_fn():
        raise RuntimeError("db down")

    router = build_router(review_fn, history_fn=history_fn)
    handler = router.match("GET", "/api/history")

    status, body = await handler({}, b"")
    assert status == 500


@pytest.mark.asyncio
async def test_review_exception_does_not_crash_handler():
    """审查回调抛异常时，API 响应仍正常返回 202"""
    async def review_fn(url):
        raise RuntimeError("review failed")

    router = build_router(review_fn)
    handler = router.match("POST", "/api/review")

    body = json.dumps({"pr_url": "https://github.com/o/r/pull/1"}).encode()
    status, _ = await handler({}, body)
    assert status == 202
    await asyncio.sleep(0.05)  # 等待后台异常处理


# ===== 端到端 TCP 测试 =====

@pytest.mark.asyncio
async def test_end_to_end_health_check():
    """启动真实 server，用 asyncio.open_connection 发请求"""
    triggered: list[str] = []

    async def review_fn(url):
        triggered.append(url)

    router = build_router(review_fn)
    server = await serve(router, host="127.0.0.1", port=0)

    # 获取实际分配的端口
    socket = server.sockets[0]
    port = socket.getsockname()[1]

    async def client():
        reader, writer = await asyncio.open_connection("127.0.0.1", port)
        req = _make_request("GET", "/api/health")
        writer.write(req)
        await writer.drain()
        resp = await reader.read(4096)
        writer.close()
        await writer.wait_closed()
        return resp

    try:
        resp = await asyncio.wait_for(client(), timeout=2.0)
        text = resp.decode("utf-8")
        assert "200 OK" in text
        assert '"status": "ok"' in text
    finally:
        server.close()
        await server.wait_closed()


@pytest.mark.asyncio
async def test_end_to_end_404():
    async def review_fn(url):
        pass

    router = build_router(review_fn)
    server = await serve(router, host="127.0.0.1", port=0)
    port = server.sockets[0].getsockname()[1]

    async def client():
        reader, writer = await asyncio.open_connection("127.0.0.1", port)
        writer.write(_make_request("GET", "/nonexistent"))
        await writer.drain()
        resp = await reader.read(4096)
        writer.close()
        await writer.wait_closed()
        return resp

    try:
        resp = await asyncio.wait_for(client(), timeout=2.0)
        assert "404" in resp.decode("utf-8")
    finally:
        server.close()
        await server.wait_closed()


@pytest.mark.asyncio
async def test_end_to_end_post_review():
    triggered: list[str] = []

    async def review_fn(url):
        triggered.append(url)

    router = build_router(review_fn)
    server = await serve(router, host="127.0.0.1", port=0)
    port = server.sockets[0].getsockname()[1]

    async def client():
        body = json.dumps({"pr_url": "https://github.com/o/r/pull/5"}).encode()
        reader, writer = await asyncio.open_connection("127.0.0.1", port)
        writer.write(_make_request("POST", "/api/review", body=body))
        await writer.drain()
        resp = await reader.read(4096)
        writer.close()
        await writer.wait_closed()
        return resp

    try:
        resp = await asyncio.wait_for(client(), timeout=2.0)
        text = resp.decode("utf-8")
        assert "202" in text
        assert "accepted" in text
        await asyncio.sleep(0.05)
        assert triggered == ["https://github.com/o/r/pull/5"]
    finally:
        server.close()
        await server.wait_closed()


def test_default_port_constant():
    assert DEFAULT_PORT == 8000
