"""dashboard 模块测试 — 覆盖统计计算、HTML 渲染、XSS 防护"""
import pytest
from ai_pr_review.dashboard import (
    _escape, _truncate, compute_stats, _render_stat_cards,
    _render_table, render_dashboard,
)
from ai_pr_review.history import AnalysisRecord


def _make_record(
    pr_title: str = "Fix bug", findings: int = 3, high: int = 1,
    medium: int = 1, low: int = 1, duration: float = 5.5,
    incremental: bool = False, model: str = "deepseek",
    pr_url: str = "https://github.com/o/r/pull/1",
) -> AnalysisRecord:
    return AnalysisRecord(
        pr_url=pr_url, pr_title=pr_title,
        findings_count=findings, high_severity_count=high,
        medium_severity_count=medium, low_severity_count=low,
        duration_seconds=duration, is_incremental=incremental,
        model=model,
    )


# ===== _escape / _truncate 单元测试 =====

def test_escape_basic():
    assert _escape("<script>") == "&lt;script&gt;"


def test_escape_empty():
    assert _escape("") == ""
    assert _escape(None) == ""


def test_escape_quotes():
    assert _escape('"x"') == "&quot;x&quot;"


def test_truncate_short_text():
    assert _truncate("short", 60) == "short"


def test_truncate_long_text():
    long_text = "x" * 100
    result = _truncate(long_text, 10)
    assert len(result) == 13  # 10 + "..."
    assert result.endswith("...")


def test_truncate_empty():
    assert _truncate("", 10) == ""


# ===== compute_stats 单元测试 =====

def test_compute_stats_empty():
    stats = compute_stats([])
    assert stats["total"] == 0
    assert stats["high"] == 0
    assert stats["avg_duration"] == 0.0


def test_compute_stats_basic():
    records = [
        _make_record(high=2, medium=3, low=1, duration=10.0),
        _make_record(high=1, medium=0, low=2, duration=6.0),
    ]
    stats = compute_stats(records)
    assert stats["total"] == 2
    assert stats["high"] == 3  # 2 + 1
    assert stats["medium"] == 3
    assert stats["low"] == 3
    assert stats["avg_duration"] == 8.0


def test_compute_stats_incremental_ratio():
    records = [
        _make_record(incremental=True),
        _make_record(incremental=True),
        _make_record(incremental=False),
        _make_record(incremental=False),
    ]
    stats = compute_stats(records)
    assert stats["incremental_count"] == 2
    assert stats["incremental_ratio"] == 0.5


# ===== _render_stat_cards 单元测试 =====

def test_render_stat_cards_includes_all_metrics():
    stats = compute_stats([_make_record()])
    html_output = _render_stat_cards(stats)
    assert "总审查数" in html_output
    assert "HIGH 发现" in html_output
    assert "MEDIUM 发现" in html_output
    assert "LOW 发现" in html_output
    assert "平均耗时" in html_output
    assert "增量审查占比" in html_output


def test_render_stat_cards_empty_stats():
    stats = compute_stats([])
    html_output = _render_stat_cards(stats)
    assert "0" in html_output


# ===== _render_table 单元测试 =====

def test_render_table_empty_records():
    html_output = _render_table([])
    assert "暂无审查记录" in html_output


def test_render_table_includes_record_info():
    records = [_make_record(pr_title="修复登录 bug", high=2, model="deepseek")]
    html_output = _render_table(records)
    assert "修复登录 bug" in html_output
    assert "deepseek" in html_output
    assert "github.com" in html_output  # PR 链接


def test_render_table_shows_incremental_badge():
    records = [_make_record(incremental=True)]
    html_output = _render_table(records)
    assert "增量" in html_output


def test_render_table_escapes_xss():
    """PR 标题含 script 标签时应被转义"""
    records = [_make_record(pr_title="<script>alert(1)</script>")]
    html_output = _render_table(records)
    assert "<script>alert(1)</script>" not in html_output
    assert "&lt;script&gt;" in html_output


def test_render_table_truncates_long_title():
    long_title = "A" * 100
    records = [_make_record(pr_title=long_title)]
    html_output = _render_table(records)
    assert "..." in html_output
    # 原始长标题不应完整出现
    assert long_title not in html_output


# ===== render_dashboard 端到端测试 =====

def test_render_dashboard_full_page():
    records = [_make_record(pr_title="Test PR", high=1)]
    html_output = render_dashboard(records)
    assert "<!DOCTYPE html>" in html_output
    assert "<html" in html_output
    assert "AI PR Review Dashboard" in html_output
    assert "Test PR" in html_output


def test_render_dashboard_empty_records():
    html_output = render_dashboard([])
    assert "<!DOCTYPE html>" in html_output
    assert "暂无审查记录" in html_output
    assert "总审查数" in html_output  # 统计卡片仍渲染


def test_render_dashboard_multiple_records():
    records = [
        _make_record(pr_title="PR1", high=1),
        _make_record(pr_title="PR2", medium=2),
        _make_record(pr_title="PR3", incremental=True),
    ]
    html_output = render_dashboard(records)
    assert "PR1" in html_output
    assert "PR2" in html_output
    assert "PR3" in html_output
    # 统计应汇总
    stats = compute_stats(records)
    assert stats["total"] == 3


def test_render_dashboard_includes_css():
    """内联 CSS 应存在，确保单文件可部署"""
    html_output = render_dashboard([])
    assert "<style>" in html_output
    assert ".stat-card" in html_output
    assert ".history-table" in html_output


def test_render_dashboard_includes_refresh_button():
    html_output = render_dashboard([])
    assert "刷新" in html_output
    assert "location.reload()" in html_output


def test_render_dashboard_accepts_none_loads_from_history():
    """records=None 时应调用 load_records（用空历史验证不报错）"""
    from unittest.mock import patch
    with patch("ai_pr_review.dashboard.load_records", return_value=[]):
        html_output = render_dashboard(None)
    assert "暂无审查记录" in html_output
