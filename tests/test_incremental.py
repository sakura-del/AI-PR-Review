import pytest
from unittest.mock import MagicMock
from ai_pr_review.history import AnalysisRecord, find_last_record
from ai_pr_review.incremental import IncrementalAnalyzer
from ai_pr_review.models import ParsedDiff, FileDiff, DiffHunk, ChangeType
from ai_pr_review.prompt_templates import build_analysis_prompt, INCREMENTAL_SYSTEM_PROMPT, SYSTEM_PROMPT
from ai_pr_review.expert_knowledge import EXPERT_SKILLS


class TestAnalysisRecordShaFields:
    def test_default_sha_fields(self):
        record = AnalysisRecord(pr_url="https://github.com/o/r/pull/1", pr_title="Test")
        assert record.head_sha == ""
        assert record.base_sha == ""
        assert record.is_incremental is False

    def test_sha_fields_set(self):
        record = AnalysisRecord(
            pr_url="https://github.com/o/r/pull/1",
            pr_title="Test",
            head_sha="abc123",
            base_sha="def456",
            is_incremental=True,
        )
        assert record.head_sha == "abc123"
        assert record.base_sha == "def456"
        assert record.is_incremental is True


class TestFindLastRecord:
    def test_find_last_record_found(self, tmp_path, monkeypatch):
        monkeypatch.setattr("ai_pr_review.history.HISTORY_DIR", tmp_path)
        from ai_pr_review.history import save_record
        record = AnalysisRecord(
            pr_url="https://github.com/o/r/pull/1",
            pr_title="Test",
            head_sha="abc123",
        )
        save_record(record)
        result = find_last_record("https://github.com/o/r/pull/1")
        assert result is not None
        assert result.head_sha == "abc123"

    def test_find_last_record_not_found(self, tmp_path, monkeypatch):
        monkeypatch.setattr("ai_pr_review.history.HISTORY_DIR", tmp_path)
        result = find_last_record("https://github.com/o/r/pull/999")
        assert result is None

    def test_find_last_record_no_sha(self, tmp_path, monkeypatch):
        monkeypatch.setattr("ai_pr_review.history.HISTORY_DIR", tmp_path)
        from ai_pr_review.history import save_record
        record = AnalysisRecord(
            pr_url="https://github.com/o/r/pull/1",
            pr_title="Test",
        )
        save_record(record)
        result = find_last_record("https://github.com/o/r/pull/1")
        assert result is None


class TestIncrementalAnalyzerShouldAnalyze:
    def test_with_record(self):
        gh_mock = MagicMock()
        analyzer = IncrementalAnalyzer(gh_mock)
        last = AnalysisRecord(pr_url="url", pr_title="t", head_sha="abc")
        analyzer.should_analyze_incremental = MagicMock(return_value=last)
        assert analyzer.should_analyze_incremental("url") is not None

    def test_no_record(self):
        gh_mock = MagicMock()
        analyzer = IncrementalAnalyzer(gh_mock)
        analyzer.should_analyze_incremental = MagicMock(return_value=None)
        assert analyzer.should_analyze_incremental("url") is None


class TestGetIncrementalDiff:
    def test_same_sha_returns_empty(self):
        gh_mock = MagicMock()
        analyzer = IncrementalAnalyzer(gh_mock)
        result = analyzer.get_incremental_diff("url", "abc123", "abc123")
        assert result == ""
        gh_mock.get_commit_diff.assert_not_called()

    def test_different_sha_calls_gh(self):
        gh_mock = MagicMock()
        gh_mock.get_commit_diff.return_value = "diff content"
        analyzer = IncrementalAnalyzer(gh_mock)
        result = analyzer.get_incremental_diff("url", "abc123", "def456")
        assert result == "diff content"
        gh_mock.get_commit_diff.assert_called_once_with("url", "abc123", "def456")


class TestBuildIncrementalContext:
    def test_build_context(self):
        gh_mock = MagicMock()
        analyzer = IncrementalAnalyzer(gh_mock)

        full_diff = ParsedDiff(
            files=[
                FileDiff(path="a.py", change_type=ChangeType.MODIFIED, hunks=[], additions=5, deletions=2),
                FileDiff(path="b.py", change_type=ChangeType.MODIFIED, hunks=[], additions=3, deletions=1),
                FileDiff(path="c.py", change_type=ChangeType.MODIFIED, hunks=[], additions=1, deletions=0),
            ],
            total_additions=9,
            total_deletions=3,
        )
        inc_diff = ParsedDiff(
            files=[
                FileDiff(path="a.py", change_type=ChangeType.MODIFIED, hunks=[], additions=3, deletions=1),
            ],
            total_additions=3,
            total_deletions=1,
        )
        last_record = AnalysisRecord(
            pr_url="url", pr_title="t", head_sha="abc123", timestamp="2026-01-01T00:00:00"
        )

        ctx = analyzer.build_incremental_context("url", full_diff, inc_diff, last_record)
        assert ctx["changed_files"] == ["a.py"]
        assert "b.py" in ctx["unchanged_files"]
        assert "c.py" in ctx["unchanged_files"]
        assert ctx["last_sha"] == "abc123"
        assert ctx["is_incremental"] is True


class TestIncrementalPrompt:
    def test_incremental_prompt_contains_context(self):
        experts = [EXPERT_SKILLS["security"]]
        inc_ctx = {
            "changed_files": ["auth.py", "db.py"],
            "unchanged_files": ["utils.py"],
            "last_sha": "abc123def",
            "last_timestamp": "2026-01-01T00:00:00",
            "is_incremental": True,
        }
        messages = build_analysis_prompt(
            pr_context="Test PR",
            diff_context="diff content",
            file_context="",
            experts=experts,
            incremental_context=inc_ctx,
        )
        user_msg = messages[1]["content"]
        assert "增量分析信息" in user_msg
        assert "abc123def" in user_msg
        assert "auth.py" in user_msg

    def test_incremental_prompt_uses_special_system(self):
        experts = [EXPERT_SKILLS["security"]]
        inc_ctx = {
            "changed_files": ["a.py"],
            "unchanged_files": [],
            "last_sha": "abc",
            "last_timestamp": "2026-01-01",
            "is_incremental": True,
        }
        messages = build_analysis_prompt(
            pr_context="Test",
            diff_context="diff",
            file_context="",
            experts=experts,
            incremental_context=inc_ctx,
        )
        assert messages[0]["content"] == INCREMENTAL_SYSTEM_PROMPT

    def test_full_analysis_no_incremental_context(self):
        experts = [EXPERT_SKILLS["security"]]
        messages = build_analysis_prompt(
            pr_context="Test",
            diff_context="diff",
            file_context="",
            experts=experts,
        )
        assert messages[0]["content"] == SYSTEM_PROMPT
        assert "增量分析信息" not in messages[1]["content"]
