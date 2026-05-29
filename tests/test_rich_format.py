import pytest
from io import StringIO
from rich.console import Console
from ai_pr_review.models import (
    AnalysisResult,
    AnalysisSummary,
    Finding,
    Suggestion,
    Severity,
)
from ai_pr_review.formatter import format_rich, format_terminal


def _make_result(findings_count: int = 3, suggestions_count: int = 2) -> AnalysisResult:
    findings = [
        Finding(
            type="bug" if i == 0 else "quality",
            severity=Severity.HIGH if i == 0 else (Severity.MEDIUM if i == 1 else Severity.LOW),
            confidence=4 - i,
            expert=["security", "architecture", "readability"][i],
            file=f"src/module_{i}.py",
            line=(i + 1) * 10,
            title=f"Issue {i+1}",
            description=f"Description for issue {i+1}",
            suggestion=f"Suggestion {i+1}",
            code_snippet=f"code_{i}" if i < 2 else "",
        )
        for i in range(findings_count)
    ]

    suggestions = [
        Suggestion(
            category="performance",
            priority=Severity.MEDIUM,
            description="Optimize this",
            example="example code",
        ),
        Suggestion(
            category="testing",
            priority=Severity.LOW,
            description="Add tests",
            example="",
        ),
    ][:suggestions_count]

    return AnalysisResult(
        summary=AnalysisSummary(
            intent="Add new feature",
            scope="Core module refactoring",
            key_changes=["Refactor auth", "Add caching", "Update API"],
        ),
        findings=findings,
        suggestions=suggestions,
    )


class TestRichFormat:
    def test_format_rich_outputs_content(self):
        console = Console(file=StringIO())
        result = _make_result()
        format_rich(result, console=console)

    def test_format_rich_empty_result(self):
        console = Console(file=StringIO())
        result = AnalysisResult(
            summary=AnalysisSummary(intent="", scope="", key_changes=[]),
            findings=[],
            suggestions=[],
        )
        format_rich(result, console=console)

    def test_format_rich_many_findings(self):
        console = Console(file=StringIO())
        result = _make_result(findings_count=15)
        format_rich(result, console=console)

    def test_format_rich_no_suggestions(self):
        console = Console(file=StringIO())
        result = _make_result(suggestions_count=0)
        format_rich(result, console=console)

    def test_format_rich_only_high_severity(self):
        console = Console(file=StringIO())
        result = AnalysisResult(
            summary=AnalysisSummary(intent="test", scope="small", key_changes=[]),
            findings=[
                Finding(
                    type="security", severity=Severity.HIGH, confidence=5,
                    expert="security", file="auth.py", line=42,
                    title="SQL Injection", description="Vulnerable query", 
                    suggestion="Use parameterized queries", code_snippet="query",
                )
            ],
            suggestions=[],
        )
        format_rich(result, console=console)

    def test_format_terminal_returns_string(self):
        result = _make_result()
        output = format_terminal(result)
        assert isinstance(output, str)
        assert len(output) > 0

    def test_format_terminal_contains_key_info(self):
        result = _make_result()
        output = format_terminal(result)
        assert "PR 变更总结" in output
        assert result.summary.intent in output

    def test_format_terminal_empty(self):
        result = AnalysisResult(
            summary=AnalysisSummary(intent="", scope="", key_changes=[]),
            findings=[],
            suggestions=[],
        )
        output = format_terminal(result)
        assert "PR 变更总结" in output
