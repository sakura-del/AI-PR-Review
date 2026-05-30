import json
import re
from ai_pr_review.analyzer import _normalize_severity, parse_ai_response, AIAnalyzer
from ai_pr_review.models import (
    Severity,
    AnalysisResult,
    AnalysisSummary,
    Finding,
    Suggestion,
    ParsedDiff,
    FileDiff,
    DiffHunk,
    ChangeType,
    PRMetadata,
)
from ai_pr_review.prompt_templates import OUTPUT_SCHEMA, FEW_SHOT_EXAMPLE
from ai_pr_review.context_builder import ContextBuilder
from ai_pr_review.config import AppConfig, AIConfig, AnalysisConfig, GitHubConfig


def test_normalize_severity_p0():
    assert _normalize_severity("P0") == Severity.HIGH


def test_normalize_severity_p1():
    assert _normalize_severity("P1") == Severity.MEDIUM


def test_normalize_severity_p2():
    assert _normalize_severity("P2") == Severity.MEDIUM


def test_normalize_severity_p3():
    assert _normalize_severity("P3") == Severity.LOW


def test_normalize_severity_high():
    assert _normalize_severity("high") == Severity.HIGH


def test_normalize_severity_medium():
    assert _normalize_severity("medium") == Severity.MEDIUM


def test_normalize_severity_low():
    assert _normalize_severity("low") == Severity.LOW


def test_normalize_severity_unknown():
    assert _normalize_severity("critical") == Severity.LOW


def test_parse_ai_response_p0_finding():
    raw = json.dumps({
        "summary": {"intent": "Fix auth", "scope": "Auth", "key_changes": ["auth.py"]},
        "findings": [
            {
                "type": "security",
                "severity": "P0",
                "confidence": 5,
                "expert": "security",
                "file": "auth.py",
                "line": 10,
                "title": "Hardcoded secret",
                "description": "Secret exposed",
                "suggestion": "Use env var",
                "code_snippet": "secret = 'xxx'",
            }
        ],
        "suggestions": [],
    })
    result = parse_ai_response(raw)
    assert len(result.findings) == 1
    assert result.findings[0].severity == Severity.HIGH


def test_parse_ai_response_p2_finding():
    raw = json.dumps({
        "summary": {"intent": "Refactor", "scope": "Core", "key_changes": ["core.py"]},
        "findings": [
            {
                "type": "quality",
                "severity": "P2",
                "confidence": 3,
                "expert": "readability",
                "file": "core.py",
                "line": 42,
                "title": "Code smell",
                "description": "Long method",
                "suggestion": "Extract method",
                "code_snippet": "def long_method():",
            }
        ],
        "suggestions": [],
    })
    result = parse_ai_response(raw)
    assert len(result.findings) == 1
    assert result.findings[0].severity == Severity.MEDIUM


def test_parse_ai_response_mixed_severity_formats():
    raw = json.dumps({
        "summary": {"intent": "Mixed", "scope": "All", "key_changes": ["a.py", "b.py"]},
        "findings": [
            {
                "type": "security",
                "severity": "P0",
                "confidence": 5,
                "expert": "security",
                "file": "a.py",
                "line": 1,
                "title": "P0 finding",
                "description": "Critical",
                "suggestion": "Fix",
                "code_snippet": "",
            },
            {
                "type": "quality",
                "severity": "high",
                "confidence": 4,
                "expert": "readability",
                "file": "b.py",
                "line": 2,
                "title": "High finding",
                "description": "Important",
                "suggestion": "Fix",
                "code_snippet": "",
            },
            {
                "type": "quality",
                "severity": "P3",
                "confidence": 2,
                "expert": "readability",
                "file": "b.py",
                "line": 3,
                "title": "P3 finding",
                "description": "Optional",
                "suggestion": "Consider",
                "code_snippet": "",
            },
        ],
        "suggestions": [],
    })
    result = parse_ai_response(raw)
    assert len(result.findings) == 3
    assert result.findings[0].severity == Severity.HIGH
    assert result.findings[1].severity == Severity.HIGH
    assert result.findings[2].severity == Severity.LOW


def test_output_schema_has_key_changes():
    assert '"key_changes"' in OUTPUT_SCHEMA


def test_output_schema_not_has_changes_as_key():
    keys_in_schema = re.findall(r'"(\w+)":', OUTPUT_SCHEMA)
    assert "changes" not in keys_in_schema


def test_few_shot_example_has_key_changes():
    assert '"key_changes"' in FEW_SHOT_EXAMPLE


def test_few_shot_example_not_has_changes_as_key():
    keys_in_example = re.findall(r'"(\w+)":', FEW_SHOT_EXAMPLE)
    assert "changes" not in keys_in_example


def _make_parsed_diff(file_count: int, total_additions: int, total_deletions: int) -> ParsedDiff:
    files = []
    additions_per_file = total_additions // max(file_count, 1)
    deletions_per_file = total_deletions // max(file_count, 1)
    for i in range(file_count):
        files.append(FileDiff(
            path=f"file_{i}.py",
            change_type=ChangeType.MODIFIED,
            hunks=[DiffHunk(
                file_path=f"file_{i}.py",
                change_type=ChangeType.MODIFIED,
                old_start=1,
                old_count=1,
                new_start=1,
                new_count=1,
                content="@@ -1,1 +1,1 @@\n-old\n+new",
                header="@@ -1,1 +1,1 @@",
            )],
            additions=additions_per_file,
            deletions=deletions_per_file,
        ))
    return ParsedDiff(
        files=files,
        total_additions=total_additions,
        total_deletions=total_deletions,
    )


def test_should_shard_below_both_thresholds():
    parsed_diff = _make_parsed_diff(file_count=10, total_additions=3000, total_deletions=0)
    assert AIAnalyzer._should_shard(parsed_diff) is False


def test_should_shard_above_file_threshold():
    parsed_diff = _make_parsed_diff(file_count=25, total_additions=3000, total_deletions=0)
    assert AIAnalyzer._should_shard(parsed_diff) is True


def test_should_shard_above_line_threshold():
    parsed_diff = _make_parsed_diff(file_count=10, total_additions=6000, total_deletions=0)
    assert AIAnalyzer._should_shard(parsed_diff) is True


def test_should_shard_above_both_thresholds():
    parsed_diff = _make_parsed_diff(file_count=25, total_additions=6000, total_deletions=0)
    assert AIAnalyzer._should_shard(parsed_diff) is True


def _make_config(context_budget: int = 6000) -> AppConfig:
    return AppConfig(
        github=GitHubConfig(token="fake"),
        ai=AIConfig(api_key="fake", base_url="https://fake.local"),
        analysis=AnalysisConfig(context_budget=context_budget),
    )


def _make_pr_metadata() -> PRMetadata:
    return PRMetadata(
        title="test",
        description="",
        author="test",
        base_branch="main",
        head_branch="feat",
        labels=[],
        url="",
        number=1,
        repo_owner="o",
        repo_name="r",
    )


def test_context_builder_increases_budget_for_large_pr():
    config = _make_config(context_budget=6000)
    builder = ContextBuilder(config)
    parsed_diff = ParsedDiff(
        files=[FileDiff(
            path="big.py",
            change_type=ChangeType.MODIFIED,
            hunks=[DiffHunk(
                file_path="big.py",
                change_type=ChangeType.MODIFIED,
                old_start=1,
                old_count=1,
                new_start=1,
                new_count=1,
                content="@@ -1,1 +1,1 @@\n-old\n+new",
                header="@@ -1,1 +1,1 @@",
            )],
            additions=40000,
            deletions=8000,
        )],
        total_additions=40000,
        total_deletions=8000,
    )
    pr_meta = _make_pr_metadata()
    builder.build_context(pr_meta, parsed_diff)
    assert builder._budget == 12000


def test_context_builder_keeps_budget_for_small_pr():
    config = _make_config(context_budget=6000)
    builder = ContextBuilder(config)
    parsed_diff = ParsedDiff(
        files=[FileDiff(
            path="small.py",
            change_type=ChangeType.MODIFIED,
            hunks=[DiffHunk(
                file_path="small.py",
                change_type=ChangeType.MODIFIED,
                old_start=1,
                old_count=1,
                new_start=1,
                new_count=1,
                content="@@ -1,1 +1,1 @@\n-old\n+new",
                header="@@ -1,1 +1,1 @@",
            )],
            additions=100,
            deletions=50,
        )],
        total_additions=100,
        total_deletions=50,
    )
    pr_meta = _make_pr_metadata()
    builder.build_context(pr_meta, parsed_diff)
    assert builder._budget == 6000


def _make_finding(confidence: int, severity: str = "low") -> Finding:
    return Finding(
        type="quality",
        severity=Severity(severity),
        confidence=confidence,
        expert="",
        file="test.py",
        line=1,
        title="Test finding",
        description="desc",
        suggestion="fix",
        code_snippet="",
    )


def _make_result_with_confidences(*confidences: int) -> AnalysisResult:
    findings = [_make_finding(c) for c in confidences]
    return AnalysisResult(
        summary=AnalysisSummary(intent="", scope="", key_changes=[]),
        findings=findings,
        suggestions=[],
    )


def test_apply_filters_min_confidence_2():
    config = _make_config()
    analyzer = AIAnalyzer.__new__(AIAnalyzer)
    analyzer._config = config
    result = _make_result_with_confidences(1, 2, 3, 4, 5)
    filtered = analyzer._apply_filters(result, "low", None, min_confidence=2)
    assert [f.confidence for f in filtered.findings] == [2, 3, 4, 5]


def test_apply_filters_min_confidence_3():
    config = _make_config()
    analyzer = AIAnalyzer.__new__(AIAnalyzer)
    analyzer._config = config
    result = _make_result_with_confidences(1, 2, 3, 4, 5)
    filtered = analyzer._apply_filters(result, "low", None, min_confidence=3)
    assert [f.confidence for f in filtered.findings] == [3, 4, 5]


def test_apply_filters_min_confidence_1():
    config = _make_config()
    analyzer = AIAnalyzer.__new__(AIAnalyzer)
    analyzer._config = config
    result = _make_result_with_confidences(1, 2, 3, 4, 5)
    filtered = analyzer._apply_filters(result, "low", None, min_confidence=1)
    assert [f.confidence for f in filtered.findings] == [1, 2, 3, 4, 5]
