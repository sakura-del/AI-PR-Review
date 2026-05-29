import pytest
from unittest.mock import patch
from ai_pr_review.models import (
    AnalysisResult,
    AnalysisSummary,
    Finding,
    Suggestion,
    Severity,
)
from ai_pr_review.commenter import Commenter, LABEL_RULES
from ai_pr_review.github_client import GitHubClient


def _make_result(findings: list[Finding] | None = None) -> AnalysisResult:
    return AnalysisResult(
        summary=AnalysisSummary(intent="test", scope="small", key_changes=[]),
        findings=findings or [],
        suggestions=[],
    )


class TestLabelDetermination:
    def test_high_risk_label_for_high_severity(self):
        result = _make_result([Finding(
            type="bug", severity=Severity.HIGH, confidence=5,
            expert="security", file="x.py", line=1,
            title="High", description="", suggestion="", code_snippet="",
        )])
        labels = Commenter._determine_labels(result)
        assert "ai-review:high-risk" in labels

    def test_no_high_risk_for_low_severity(self):
        result = _make_result([Finding(
            type="style", severity=Severity.LOW, confidence=3,
            expert="readability", file="y.py", line=10,
            title="Style", description="", suggestion="", code_snippet="",
        )])
        labels = Commenter._determine_labels(result)
        assert "ai-review:high-risk" not in labels

    def test_security_label_for_security_finding(self):
        result = _make_result([Finding(
            type="security", severity=Severity.MEDIUM, confidence=4,
            expert="security", file="auth.py", line=42,
            title="Auth Issue", description="", suggestion="", code_snippet="",
        )])
        labels = Commenter._determine_labels(result)
        assert "ai-review:security" in labels

    def test_performance_label_for_performance_finding(self):
        result = _make_result([Finding(
            type="performance", severity=Severity.MEDIUM, confidence=4,
            expert="performance", file="query.py", line=15,
            title="Slow Query", description="", suggestion="", code_snippet="",
        )])
        labels = Commenter._determine_labels(result)
        assert "ai-review:performance" in labels

    def test_needs_review_when_findings_exist(self):
        result = _make_result([Finding(
            type="quality", severity=Severity.LOW, confidence=3,
            expert="readability", file="z.py", line=5,
            title="Minor", description="", suggestion="", code_snippet="",
        )])
        labels = Commenter._determine_labels(result)
        assert "ai-review:needs-review" in labels

    def test_no_labels_when_empty_result(self):
        result = _make_result([])
        labels = Commenter._determine_labels(result)
        assert len(labels) == 0

    def test_multiple_labels_combined(self):
        result = _make_result([
            Finding(
                type="security", severity=Severity.HIGH, confidence=5,
                expert="security", file="a.py", line=1,
                title="Critical", description="", suggestion="", code_snippet="",
            ),
            Finding(
                type="performance", severity=Severity.MEDIUM, confidence=4,
                expert="performance", file="b.py", line=10,
                title="Slow", description="", suggestion="", code_snippet="",
            ),
        ])
        labels = Commenter._determine_labels(result)
        assert "ai-review:high-risk" in labels
        assert "ai-review:security" in labels
        assert "ai-review:performance" in labels
        assert "ai-review:needs-review" in labels


class TestPostLabels:
    def test_calls_add_labels_with_correct_labels(self):
        client = GitHubClient(token="test")
        commenter = Commenter(client)
        result = _make_result([Finding(
            type="security", severity=Severity.HIGH, confidence=5,
            expert="security", file="x.py", line=1,
            title="Test", description="", suggestion="", code_snippet="",
        )])

        with patch.object(client, "add_labels") as mock_add:
            commenter.post_labels("https://github.com/test/repo/pull/1", result)
            mock_add.assert_called_once()
            args = mock_add.call_args[0]
            assert "ai-review:high-risk" in args[1]

    def test_skips_when_no_labels(self):
        client = GitHubClient(token="test")
        commenter = Commenter(client)
        result = _make_result([])

        with patch.object(client, "add_labels") as mock_add:
            commenter.post_labels("https://github.com/test/repo/pull/1", result)
            mock_add.assert_not_called()

    def test_handles_add_labels_error_gracefully(self):
        client = GitHubClient(token="test")
        commenter = Commenter(client)
        result = _make_result([Finding(
            type="bug", severity=Severity.HIGH, confidence=5,
            expert="security", file="x.py", line=1,
            title="Test", description="", suggestion="", code_snippet="",
        )])

        with patch.object(client, "add_labels", side_effect=Exception("API error")):
            commenter.post_labels("https://github.com/test/repo/pull/1", result)


class TestLabelRulesStructure:
    def test_all_rules_have_callable_condition(self):
        for label, condition in LABEL_RULES.items():
            assert callable(condition), f"Rule {label} must be callable"

    def test_rules_are_prefixed(self):
        for label in LABEL_RULES.keys():
            assert label.startswith("ai-review:"), f"Label {label} should have ai-review: prefix"
