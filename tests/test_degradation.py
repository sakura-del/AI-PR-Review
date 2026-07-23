"""degradation 模块测试 — 覆盖单例、级别判定、降级结果生成"""
import pytest
from unittest.mock import patch, MagicMock

from ai_pr_review.degradation import (
    DegradationManager,
    get_degradation_manager,
    LEVEL1_THRESHOLD,
    LEVEL2_THRESHOLD,
    LEVEL3_THRESHOLD,
)
from ai_pr_review.models import AnalysisResult, AnalysisSummary


@pytest.fixture(autouse=True)
def reset_manager():
    """每个测试前重置单例状态，保证测试隔离"""
    get_degradation_manager().reset()
    yield
    get_degradation_manager().reset()


def _make_cached_result() -> AnalysisResult:
    """构造一个非空的缓存 AnalysisResult，供 Level 1 测试使用"""
    return AnalysisResult(
        summary=AnalysisSummary(
            intent="原始分析意图",
            scope="auth 模块",
            key_changes=["新增 login.py"],
        ),
        findings=[],
        suggestions=[],
    )


# ===== 单例与基础行为 =====

def test_singleton():
    """两次获取 DegradationManager 应返回同一实例"""
    a = DegradationManager()
    b = get_degradation_manager()
    assert a is b


def test_record_failure_increments_count():
    """多次 record_failure 后 current_level 应上升"""
    mgr = get_degradation_manager()
    assert mgr.current_level() == 0

    # 失败 4 次仍在 Level 0
    for _ in range(4):
        mgr.record_failure(pr_url="https://github.com/o/r/pull/1")
    assert mgr.current_level() == 0

    # 第 5 次失败触发 Level 1
    mgr.record_failure(pr_url="https://github.com/o/r/pull/1")
    assert mgr.current_level() == 1


def test_record_success_resets():
    """record_failure 3 次后 record_success，level 应回到 0"""
    mgr = get_degradation_manager()
    for _ in range(3):
        mgr.record_failure()
    assert mgr.current_level() == 0  # 3 次仍为 Level 0

    mgr.record_failure()
    # 4 次仍 Level 0
    assert mgr.current_level() == 0

    mgr.record_success()
    assert mgr.current_level() == 0


def test_level_thresholds():
    """验证各级别阈值：4 次=0, 5 次=1, 10 次=2, 15 次=3"""
    mgr = get_degradation_manager()

    for _ in range(4):
        mgr.record_failure()
    assert mgr.current_level() == 0

    mgr.record_failure()  # 第 5 次
    assert mgr.current_level() == 1

    for _ in range(LEVEL2_THRESHOLD - LEVEL1_THRESHOLD - 1):
        mgr.record_failure()
    # 累计 9 次，仍为 Level 1
    assert mgr.current_level() == 1

    mgr.record_failure()  # 第 10 次
    assert mgr.current_level() == 2

    for _ in range(LEVEL3_THRESHOLD - LEVEL2_THRESHOLD - 1):
        mgr.record_failure()
    # 累计 14 次，仍为 Level 2
    assert mgr.current_level() == 2

    mgr.record_failure()  # 第 15 次
    assert mgr.current_level() == 3


# ===== Level 1 降级：返回过期缓存 =====

def test_level1_returns_cached_result():
    """Level 1 且缓存存在时，返回缓存结果且 summary.intent 含 [降级模式-缓存]"""
    mgr = get_degradation_manager()
    # 触发 Level 1
    for _ in range(LEVEL1_THRESHOLD):
        mgr.record_failure()
    assert mgr.current_level() == 1

    cached = _make_cached_result()
    with patch("ai_pr_review.cache.get_cached_result", return_value=cached) as mock_get:
        result = mgr.get_degraded_result(
            pr_url="https://github.com/o/r/pull/1",
            sha="abc123",
            reason="ai timeout",
        )
        # 应调用 cache.get_cached_result
        mock_get.assert_called_once()
        args, kwargs = mock_get.call_args
        assert args[0] == "https://github.com/o/r/pull/1"
        assert args[1] == "abc123"

    assert result is not None
    # summary.intent 前应追加 [降级模式-缓存] 标记
    assert result.summary.intent.startswith("[降级模式-缓存]")
    assert "原始分析意图" in result.summary.intent


def test_level1_no_cache_falls_to_level2():
    """Level 1 但缓存为 None 时，应回退到 Level 2 行为返回空结果"""
    mgr = get_degradation_manager()
    for _ in range(LEVEL1_THRESHOLD):
        mgr.record_failure()
    assert mgr.current_level() == 1

    with patch("ai_pr_review.cache.get_cached_result", return_value=None):
        result = mgr.get_degraded_result(
            pr_url="https://github.com/o/r/pull/1",
            sha="abc123",
            reason="no cache",
        )

    assert result is not None
    # 回退到 Level 2 行为：summary.intent 含 [降级模式]
    assert result.summary.intent.startswith("[降级模式]")
    assert "no cache" in result.summary.intent
    assert result.findings == []
    assert result.suggestions == []


# ===== Level 2 降级：空结果 =====

def test_level2_returns_empty_result():
    """Level 2 时返回空 AnalysisResult，findings 为空列表"""
    mgr = get_degradation_manager()
    for _ in range(LEVEL2_THRESHOLD):
        mgr.record_failure()
    assert mgr.current_level() == 2

    result = mgr.get_degraded_result(
        pr_url="https://github.com/o/r/pull/1",
        sha="abc123",
        reason="service down",
    )

    assert result is not None
    assert isinstance(result, AnalysisResult)
    assert result.findings == []
    assert result.suggestions == []
    assert result.summary.key_changes == []
    assert "[降级模式]" in result.summary.intent
    assert "service down" in result.summary.intent


# ===== Level 3 降级：拒绝服务 =====

def test_level3_returns_none():
    """Level 3 时返回 None，调用方应据此返回 503"""
    mgr = get_degradation_manager()
    for _ in range(LEVEL3_THRESHOLD):
        mgr.record_failure()
    assert mgr.current_level() == 3

    result = mgr.get_degraded_result(
        pr_url="https://github.com/o/r/pull/1",
        sha="abc123",
        reason="circuit broken",
    )
    assert result is None


# ===== reset 行为 =====

def test_reset():
    """进入降级后 reset，current_level 应回到 0"""
    mgr = get_degradation_manager()
    for _ in range(LEVEL3_THRESHOLD):
        mgr.record_failure()
    assert mgr.current_level() == 3

    mgr.reset()
    assert mgr.current_level() == 0

    # reset 后再次失败 1 次仍为 Level 0
    mgr.record_failure()
    assert mgr.current_level() == 0
