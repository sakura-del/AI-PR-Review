"""tests/test_metrics.py — Metrics 收集模块测试

覆盖：
- Counter / Histogram / Gauge 基础行为
- MetricsRegistry 单例与复用语义
- snapshot / snapshot_json 序列化
- reset 隔离
- AIAnalyzer._call_ai 埋点集成
"""
import json
import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from ai_pr_review.metrics import (
    Counter,
    Histogram,
    Gauge,
    MetricsRegistry,
    get_registry,
)
from ai_pr_review.analyzer import AIAnalyzer
from ai_pr_review.config import AppConfig


@pytest.fixture(autouse=True)
def reset_registry():
    """每个测试前清空 registry，避免单例状态在测试间相互污染"""
    get_registry().reset()
    yield
    get_registry().reset()


def test_counter_inc():
    """Counter.inc 默认 +1，传 value 自定义"""
    counter = Counter("test_counter", "测试计数器")
    counter.inc()
    assert counter.get() == 1.0
    counter.inc()
    assert counter.get() == 2.0
    counter.inc(value=5.0)
    assert counter.get() == 7.0


def test_counter_with_labels():
    """不同 label 值独立计数"""
    counter = Counter("http_requests", labels=("method",))
    counter.inc(method="GET")
    counter.inc(method="GET")
    counter.inc(method="POST")
    assert counter.get(method="GET") == 2.0
    assert counter.get(method="POST") == 1.0


def test_counter_label_validation():
    """传入未声明的 label 抛 ValueError"""
    counter = Counter("http_requests", labels=("method",))
    # 缺少 label
    with pytest.raises(ValueError):
        counter.inc()
    # 多余 label
    with pytest.raises(ValueError):
        counter.inc(method="GET", path="/")
    # get 同样校验
    with pytest.raises(ValueError):
        counter.get()


def test_histogram_observe():
    """observe 更新分桶，sum/count 正确"""
    hist = Histogram("latency")
    hist.observe(0.3)
    hist.observe(0.7)

    snap = hist.snapshot()
    assert snap["count"] == 2
    assert snap["sum"] == pytest.approx(1.0)
    # 0.3 <= 0.5/1/2.5/5/10，0.7 <= 1/2.5/5/10
    # le=0.5 累计：仅 0.3 → count=1
    bucket_05 = next(b for b in snap["buckets"] if b["le"] == 0.5)
    assert bucket_05["count"] == 1
    # le=1 累计：0.3 与 0.7 → count=2
    bucket_1 = next(b for b in snap["buckets"] if b["le"] == 1)
    assert bucket_1["count"] == 2
    # le=0.1：均大于 → count=0
    bucket_01 = next(b for b in snap["buckets"] if b["le"] == 0.1)
    assert bucket_01["count"] == 0


def test_histogram_default_buckets():
    """默认 11 个桶"""
    hist = Histogram("latency")
    assert len(hist.buckets) == 11
    snap = hist.snapshot()
    assert len(snap["buckets"]) == 11
    # 默认分桶首项 0.005，末项 10
    assert snap["buckets"][0]["le"] == 0.005
    assert snap["buckets"][-1]["le"] == 10


def test_gauge_set_inc_dec():
    """set / inc / dec / get 操作"""
    gauge = Gauge("in_flight")
    assert gauge.get() == 0.0
    gauge.set(10.0)
    assert gauge.get() == 10.0
    gauge.inc()
    assert gauge.get() == 11.0
    gauge.inc(4.0)
    assert gauge.get() == 15.0
    gauge.dec()
    assert gauge.get() == 14.0
    gauge.dec(4.0)
    assert gauge.get() == 10.0


def test_registry_singleton():
    """两次 get_registry() 返回同一实例"""
    r1 = get_registry()
    r2 = get_registry()
    assert r1 is r2
    assert MetricsRegistry._instance is r1


def test_registry_counter_reuse():
    """同名 counter 第二次获取返回同一对象"""
    registry = get_registry()
    c1 = registry.counter("reuse_counter", "desc", labels=("op",))
    c2 = registry.counter("reuse_counter")
    assert c1 is c2
    # 复用：第一次 inc 在第二次 get 时也能读到
    c1.inc(op="x")
    assert c2.get(op="x") == 1.0


def test_registry_snapshot_json():
    """snapshot_json 输出可被 json.loads 解析，含 counters/histograms/gauges"""
    registry = get_registry()
    registry.counter("c1", labels=("k",)).inc(k="v")
    registry.histogram("h1").observe(0.2)
    registry.gauge("g1").set(3.0)

    payload = registry.snapshot_json()
    data = json.loads(payload)
    assert "counters" in data
    assert "histograms" in data
    assert "gauges" in data
    assert len(data["counters"]) == 1
    assert data["counters"][0]["name"] == "c1"
    assert data["counters"][0]["labels"] == {"k": "v"}
    assert data["counters"][0]["value"] == 1.0
    assert len(data["histograms"]) == 1
    assert data["histograms"][0]["count"] == 1
    assert len(data["gauges"]) == 1
    assert data["gauges"][0]["value"] == 3.0


def test_registry_reset():
    """reset 后所有指标清空"""
    registry = get_registry()
    registry.counter("c", labels=("k",)).inc(k="v")
    registry.histogram("h").observe(0.1)
    registry.gauge("g").set(1.0)
    assert len(registry.snapshot()["counters"]) == 1

    registry.reset()
    snap = registry.snapshot()
    assert snap["counters"] == []
    assert snap["histograms"] == []
    assert snap["gauges"] == []


def test_histogram_observe_boundary():
    """observe(0.3) 后，le=0.5 与 le=1 都 +1，但 le=0.1 不变"""
    hist = Histogram("latency")
    hist.observe(0.3)
    snap = hist.snapshot()
    bucket_01 = next(b for b in snap["buckets"] if b["le"] == 0.1)
    bucket_05 = next(b for b in snap["buckets"] if b["le"] == 0.5)
    bucket_1 = next(b for b in snap["buckets"] if b["le"] == 1)
    assert bucket_01["count"] == 0
    assert bucket_05["count"] == 1
    assert bucket_1["count"] == 1


@pytest.mark.asyncio
async def test_analyzer_metrics_integration_success():
    """成功路径：_call_ai 调用后 ai_calls_total{status=success} 与 ai_call_duration_seconds 被记录"""
    registry = get_registry()
    config = AppConfig(
        ai=AppConfig.__dataclass_fields__["ai"].default_factory(),
        github=AppConfig.__dataclass_fields__["github"].default_factory(),
        analysis=AppConfig.__dataclass_fields__["analysis"].default_factory(),
        expert=AppConfig.__dataclass_fields__["expert"].default_factory(),
    )

    mock_response = MagicMock()
    mock_response.choices = [MagicMock()]
    mock_response.choices[0].message.content = '{"summary": {}, "findings": [], "suggestions": []}'

    mock_client = MagicMock()
    mock_client.chat.completions.create = AsyncMock(return_value=mock_response)

    with patch("ai_pr_review.analyzer.AsyncOpenAI", return_value=mock_client):
        analyzer = AIAnalyzer(config=config)
        result = await analyzer._call_ai([{"role": "user", "content": "hi"}])

    assert result == '{"summary": {}, "findings": [], "suggestions": []}'

    # 并发 gauge 应回到 0（inc 后 dec）
    assert registry.gauge("ai_concurrent_current").get() == 0.0
    # 成功计数 +1
    assert registry.counter("ai_calls_total", labels=("status",)).get(status="success") == 1.0
    # 失败计数为 0
    assert registry.counter("ai_calls_total", labels=("status",)).get(status="error") == 0.0
    # 耗时 histogram 至少记录 1 次
    hist_snap = registry.histogram("ai_call_duration_seconds").snapshot()
    assert hist_snap["count"] == 1
    assert hist_snap["sum"] >= 0.0


@pytest.mark.asyncio
async def test_analyzer_metrics_integration_error():
    """失败路径：_call_ai 全部重试失败后 ai_calls_total{status=error} 被记录"""
    registry = get_registry()
    config = AppConfig(
        ai=AppConfig.__dataclass_fields__["ai"].default_factory(),
        github=AppConfig.__dataclass_fields__["github"].default_factory(),
        analysis=AppConfig.__dataclass_fields__["analysis"].default_factory(),
        expert=AppConfig.__dataclass_fields__["expert"].default_factory(),
    )

    mock_client = MagicMock()
    # 每次调用都抛异常，触发重试到上限
    mock_client.chat.completions.create = AsyncMock(side_effect=RuntimeError("api down"))

    with patch("ai_pr_review.analyzer.AsyncOpenAI", return_value=mock_client):
        analyzer = AIAnalyzer(config=config)
        # patch sleep 避免测试等待真实退避时间
        with patch("ai_pr_review.analyzer.asyncio.sleep", new=AsyncMock()):
            result = await analyzer._call_ai([{"role": "user", "content": "hi"}])

    assert result == ""
    # 并发 gauge 应回到 0（即使失败也要 dec）
    assert registry.gauge("ai_concurrent_current").get() == 0.0
    # 失败计数 +1
    assert registry.counter("ai_calls_total", labels=("status",)).get(status="error") == 1.0
    assert registry.counter("ai_calls_total", labels=("status",)).get(status="success") == 0.0
    # 耗时 histogram 至少记录 1 次（finally 中始终记录）
    assert registry.histogram("ai_call_duration_seconds").snapshot()["count"] == 1
