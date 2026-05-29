from ai_pr_review.formatter import format_terminal, format_github_comment
from ai_pr_review.models import (
    AnalysisResult,
    AnalysisSummary,
    Finding,
    Suggestion,
    Severity,
)


def _make_result() -> AnalysisResult:
    return AnalysisResult(
        summary=AnalysisSummary(
            intent="Add JWT authentication",
            scope="Authentication module",
            key_changes=["New auth.py module", "Updated db.py queries"],
        ),
        findings=[
            Finding(
                type="risk",
                severity=Severity.HIGH,
                confidence=5,
                expert="security",
                file="auth.py",
                line=4,
                title="Hardcoded JWT secret",
                description="JWT secret is hardcoded in source code",
                suggestion="Use environment variable",
                code_snippet="SECRET = 'hardcoded-secret'",
            ),
            Finding(
                type="risk",
                severity=Severity.MEDIUM,
                confidence=3,
                expert="security",
                file="db.py",
                line=15,
                title="SQL Injection risk",
                description="User input concatenated into SQL",
                suggestion="Use parameterized queries",
                code_snippet='query = f"DELETE FROM users WHERE id = {user_id}"',
            ),
        ],
        suggestions=[
            Suggestion(
                category="security",
                priority=Severity.HIGH,
                description="Move all secrets to environment variables",
                example="SECRET = os.environ['JWT_SECRET']",
            )
        ],
    )


def test_format_terminal_contains_summary():
    result = _make_result()
    output = format_terminal(result)
    assert "Add JWT authentication" in output
    assert "auth.py" in output


def test_format_terminal_contains_severity_emoji():
    result = _make_result()
    output = format_terminal(result)
    assert "🔴" in output


def test_format_github_comment_is_markdown():
    result = _make_result()
    output = format_github_comment(result)
    assert "##" in output
    assert "auth.py" in output
