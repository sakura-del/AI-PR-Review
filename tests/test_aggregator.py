"""aggregator 模块测试 — 覆盖去重、共识加权、排序、suggestion 合并"""
import pytest
from ai_pr_review.aggregator import (
    _finding_key,
    _merge_findings,
    aggregate_findings,
    aggregate_suggestions,
    aggregate_results,
    CONSENSUS_BOOST_THRESHOLD,
)
from ai_pr_review.models import (
    AnalysisResult, AnalysisSummary, Finding, Suggestion, Severity,
)


def _make_finding(
    file: str = "app.py", line: int = 10, type_: str = "security",
    severity: Severity = Severity.HIGH, confidence: int = 4,
    expert: str = "安全审查", title: str = "硬编码密钥",
    description: str = "存在风险", suggestion: str = "用环境变量",
    code_snippet: str = "SECRET='xxx'",
) -> Finding:
    return Finding(
        type=type_, severity=severity, confidence=confidence,
        expert=expert, file=file, line=line, title=title,
        description=description, suggestion=suggestion,
        code_snippet=code_snippet,
    )


def _make_result(findings: list[Finding] = None, suggestions: list[Suggestion] = None,
                 intent: str = "test", scope: str = "scope") -> AnalysisResult:
    return AnalysisResult(
        summary=AnalysisSummary(intent=intent, scope=scope, key_changes=["c1"]),
        findings=findings or [],
        suggestions=suggestions or [],
    )


# ===== _finding_key 单元测试 =====

def test_finding_key_uses_file_line_type():
    f = _make_finding(file="a.py", line=5, type_="security")
    assert _finding_key(f) == ("a.py", 5, "security")


def test_finding_key_same_position_different_type_not_merged():
    f1 = _make_finding(file="a.py", line=5, type_="security")
    f2 = _make_finding(file="a.py", line=5, type_="performance")
    assert _finding_key(f1) != _finding_key(f2)


# ===== _merge_findings 单元测试 =====

def test_merge_findings_single_returns_unchanged():
    f = _make_finding(title="唯一")
    merged = _merge_findings([f])
    assert merged.title == "唯一"


def test_merge_findings_takes_highest_severity():
    f1 = _make_finding(severity=Severity.LOW, expert="A")
    f2 = _make_finding(severity=Severity.HIGH, expert="B")
    merged = _merge_findings([f1, f2])
    assert merged.severity == Severity.HIGH


def test_merge_findings_consensus_boosts_severity():
    """2 个 Agent 报告同一问题，severity 应被提升一档"""
    f1 = _make_finding(severity=Severity.LOW, expert="A")
    f2 = _make_finding(severity=Severity.LOW, expert="B")
    merged = _merge_findings([f1, f2])
    # LOW → MEDIUM
    assert merged.severity == Severity.MEDIUM


def test_merge_findings_consensus_boosts_confidence():
    f1 = _make_finding(confidence=3, expert="A")
    f2 = _make_finding(confidence=3, expert="B")
    merged = _merge_findings([f1, f2])
    # base 3 + boost 1 = 4
    assert merged.confidence == 4


def test_merge_findings_confidence_capped_at_5():
    f1 = _make_finding(confidence=5, expert="A")
    f2 = _make_finding(confidence=4, expert="B")
    f3 = _make_finding(confidence=5, expert="C")
    merged = _merge_findings([f1, f2, f3])
    assert merged.confidence == 5


def test_merge_findings_takes_longest_title_and_description():
    f1 = _make_finding(title="短", description="a", expert="A")
    f2 = _make_finding(title="这是一个更长的标题", description="详细描述", expert="B")
    merged = _merge_findings([f1, f2])
    assert merged.title == "这是一个更长的标题"
    assert merged.description == "详细描述"


def test_merge_findings_combines_suggestions():
    f1 = _make_finding(suggestion="方案A", expert="A")
    f2 = _make_finding(suggestion="方案B", expert="B")
    merged = _merge_findings([f1, f2])
    assert "方案A" in merged.suggestion
    assert "方案B" in merged.suggestion


def test_merge_findings_dedup_identical_suggestions():
    f1 = _make_finding(suggestion="重复方案", expert="A")
    f2 = _make_finding(suggestion="重复方案", expert="B")
    merged = _merge_findings([f1, f2])
    # 同一 suggestion 只出现一次
    assert merged.suggestion == "重复方案"


def test_merge_findings_combines_expert_names():
    f1 = _make_finding(expert="安全审查")
    f2 = _make_finding(expert="架构审查")
    merged = _merge_findings([f1, f2])
    assert "安全审查" in merged.expert
    assert "架构审查" in merged.expert


def test_merge_findings_high_severity_not_boosted_further():
    """HIGH severity 已是最高，共识提升后仍为 HIGH"""
    f1 = _make_finding(severity=Severity.HIGH, expert="A")
    f2 = _make_finding(severity=Severity.HIGH, expert="B")
    merged = _merge_findings([f1, f2])
    assert merged.severity == Severity.HIGH


# ===== aggregate_findings 集成测试 =====

def test_aggregate_findings_empty():
    assert aggregate_findings([]) == []


def test_aggregate_findings_dedupes_same_position():
    f1 = _make_finding(file="a.py", line=1, expert="A", title="A 视角", severity=Severity.LOW)
    f2 = _make_finding(file="a.py", line=1, expert="B", title="B 视角", severity=Severity.LOW)
    result = aggregate_findings([f1, f2])
    assert len(result) == 1
    # LOW 共识提升后应为 MEDIUM
    assert result[0].severity == Severity.MEDIUM


def test_aggregate_findings_sorts_by_severity_desc():
    f_low = _make_finding(file="a.py", line=1, severity=Severity.LOW, title="low")
    f_high = _make_finding(file="b.py", line=2, severity=Severity.HIGH, title="high")
    f_med = _make_finding(file="c.py", line=3, severity=Severity.MEDIUM, title="med")
    result = aggregate_findings([f_low, f_high, f_med])
    assert [f.severity for f in result] == [Severity.HIGH, Severity.MEDIUM, Severity.LOW]


def test_aggregate_findings_sorts_by_confidence_when_severity_equal():
    f1 = _make_finding(file="a.py", line=1, severity=Severity.MEDIUM, confidence=2)
    f2 = _make_finding(file="b.py", line=2, severity=Severity.MEDIUM, confidence=5)
    result = aggregate_findings([f1, f2])
    assert result[0].confidence == 5


def test_aggregate_findings_keeps_different_positions_separate():
    f1 = _make_finding(file="a.py", line=1)
    f2 = _make_finding(file="a.py", line=2)
    f3 = _make_finding(file="b.py", line=1)
    result = aggregate_findings([f1, f2, f3])
    assert len(result) == 3


# ===== aggregate_suggestions 单元测试 =====

def test_aggregate_suggestions_dedupes():
    s1 = Suggestion(category="security", priority=Severity.LOW, description="use env", example="x")
    s2 = Suggestion(category="security", priority=Severity.LOW, description="use env", example="y")
    result = aggregate_suggestions([s1, s2])
    assert len(result) == 1


def test_aggregate_suggestions_keeps_different():
    s1 = Suggestion(category="security", priority=Severity.LOW, description="A", example="")
    s2 = Suggestion(category="performance", priority=Severity.LOW, description="B", example="")
    result = aggregate_suggestions([s1, s2])
    assert len(result) == 2


# ===== aggregate_results 端到端测试 =====

def test_aggregate_results_merges_everything():
    r1 = _make_result(
        findings=[_make_finding(file="a.py", line=1, expert="A", severity=Severity.LOW)],
        suggestions=[Suggestion(category="sec", priority=Severity.LOW, description="s1", example="")],
        intent="意图A",
    )
    r2 = _make_result(
        findings=[_make_finding(file="a.py", line=1, expert="B", severity=Severity.LOW)],
        suggestions=[Suggestion(category="sec", priority=Severity.LOW, description="s2", example="")],
        intent="意图B更长",
    )
    merged = aggregate_results([r1, r2])
    # 同一位置去重后剩 1 条，且共识提升
    assert len(merged.findings) == 1
    assert merged.findings[0].severity == Severity.MEDIUM
    # suggestions 不去重（描述不同）
    assert len(merged.suggestions) == 2
    # intent 取较长者
    assert merged.summary.intent == "意图B更长"


def test_aggregate_results_empty_list():
    merged = aggregate_results([])
    assert merged.findings == []
    assert merged.suggestions == []
    assert merged.summary.key_changes == []


def test_aggregate_results_key_changes_deduped():
    r1 = _make_result()
    r1.summary.key_changes = ["kc1", "kc2"]
    r2 = _make_result()
    r2.summary.key_changes = ["kc2", "kc3"]
    merged = aggregate_results([r1, r2])
    # kc2 应去重
    assert merged.summary.key_changes == ["kc1", "kc2", "kc3"]


def test_aggregate_results_scope_fallback():
    """无 scope 时应回退到 'Multi-agent review (N experts)'"""
    r1 = AnalysisResult(
        summary=AnalysisSummary(intent="", scope="", key_changes=[]),
        findings=[], suggestions=[],
    )
    merged = aggregate_results([r1])
    assert "Multi-agent" in merged.summary.scope
    assert "1" in merged.summary.scope


def test_consensus_threshold_constant():
    assert CONSENSUS_BOOST_THRESHOLD == 2
