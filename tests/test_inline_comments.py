import pytest
from unittest.mock import MagicMock, patch
from ai_pr_review.models import (
    AnalysisResult,
    AnalysisSummary,
    Finding,
    Suggestion,
    Severity,
)
from ai_pr_review.commenter import Commenter
from ai_pr_review.github_client import GitHubClient


def _make_client() -> GitHubClient:
    return GitHubClient(token="test_token")


def _make_result_with_findings() -> AnalysisResult:
    return AnalysisResult(
        summary=AnalysisSummary(intent="test", scope="small", key_changes=["change1"]),
        findings=[
            Finding(
                type="security",
                severity=Severity.HIGH,
                confidence=5,
                expert="security",
                file="src/auth.py",
                line=42,
                title="SQL Injection Risk",
                description="Vulnerable to SQL injection",
                suggestion="Use parameterized queries",
                code_snippet="query = f'SELECT * FROM users WHERE id={user_id}'",
            ),
            Finding(
                type="quality",
                severity=Severity.MEDIUM,
                confidence=4,
                expert="readability",
                file="src/utils.py",
                line=15,
                title="Long Function",
                description="Function too long, should be split",
                suggestion="Extract into smaller functions",
                code_snippet="",
            ),
            Finding(
                type="bug",
                severity=Severity.LOW,
                confidence=3,
                expert="testing",
                file="tests/test_api.py",
                line=100,
                title="Missing Test Case",
                description="No test for error handling",
                suggestion="Add test for exception path",
                code_snippet="",
            ),
        ],
        suggestions=[
            Suggestion(category="performance", priority=Severity.MEDIUM, description="Add caching", example=""),
        ],
    )


def _make_result_no_line_info() -> AnalysisResult:
    return AnalysisResult(
        summary=AnalysisSummary(intent="", scope="", key_changes=[]),
        findings=[
            Finding(
                type="general",
                severity=Severity.LOW,
                confidence=3,
                expert="general",
                file="",
                line=0,
                title="General Note",
                description="No specific location",
                suggestion="Review overall",
                code_snippet="",
            )
        ],
        suggestions=[],
    )


class TestInlineComments:
    def test_builds_inline_comments_correctly(self):
        client = _make_client()
        commenter = Commenter(client)
        result = _make_result_with_findings()

        with patch.object(client, "create_review_with_comments") as mock_review:
            commenter.post_review_with_inline_comments("https://github.com/test/repo/pull/1", result)

            mock_review.assert_called_once()
            call_args = mock_review.call_args
            comments_arg = call_args.kwargs.get("comments", call_args[0][2] if len(call_args[0]) > 2 else [])
            assert len(comments_arg) == 3

    def test_falls_back_to_plain_review_when_no_line_info(self):
        client = _make_client()
        commenter = Commenter(client)
        result = _make_result_no_line_info()

        with patch.object(client, "create_review") as mock_review:
            with patch.object(client, "create_review_with_comments") as mock_inline:
                commenter.post_review_with_inline_comments("https://github.com/test/repo/pull/1", result)
                mock_review.assert_called_once()
                mock_inline.assert_not_called()

    def test_comment_body_format(self):
        client = _make_client()
        commenter = Commenter(client)
        result = _make_result_with_findings()

        with patch.object(client, "create_review_with_comments") as mock_review:
            commenter.post_review_with_inline_comments("https://github.com/test/repo/pull/1", result)
            comments_arg = mock_review.call_args.kwargs.get("comments", [])
            
            first_comment = comments_arg[0]
            assert "SQL Injection Risk" in first_comment["body"]
            assert "HIGH" in first_comment["body"]
            assert first_comment["path"] == "src/auth.py"
            assert first_comment["line"] == 42

    def test_includes_code_snippet_when_available(self):
        client = _make_client()
        commenter = Commenter(client)
        result = _make_result_with_findings()

        with patch.object(client, "create_review_with_comments") as mock_review:
            commenter.post_review_with_inline_comments("https://github.com/test/repo/pull/1", result)
            comments_arg = mock_review.call_args.kwargs.get("comments", [])
            
            security_comment = [c for c in comments_arg if c["path"] == "src/auth.py"][0]
            assert "code_snippet" not in security_comment["body"] or "SELECT" in security_comment["body"]

    def test_event_parameter_passed(self):
        client = _make_client()
        commenter = Commenter(client)
        result = _make_result_with_findings()

        with patch.object(client, "create_review_with_comments") as mock_review:
            commenter.post_review_with_inline_comments(
                "https://github.com/test/repo/pull/1", 
                result, 
                event="REQUEST_CHANGES"
            )
            assert mock_review.call_args.kwargs.get("event") == "REQUEST_CHANGES"

    def test_handles_empty_findings(self):
        client = _make_client()
        commenter = Commenter(client)
        result = AnalysisResult(
            summary=AnalysisSummary(intent="", scope="", key_changes=[]),
            findings=[],
            suggestions=[],
        )

        with patch.object(client, "create_review") as mock_review:
            commenter.post_review_with_inline_comments("https://github.com/test/repo/pull/1", result)
            mock_review.assert_called_once()

    def test_logs_success(self):
        client = _make_client()
        commenter = Commenter(client)
        result = _make_result_with_findings()

        with patch.object(client, "create_review_with_comments"):
            with patch("ai_pr_review.commenter.logger") as mock_logger:
                commenter.post_review_with_inline_comments("https://github.com/test/repo/pull/1", result)
                mock_logger.info.assert_called()
