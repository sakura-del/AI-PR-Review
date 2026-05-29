import pytest
from ai_pr_review.models import (
    ParsedDiff,
    FileDiff,
    DiffHunk,
    ChangeType,
)
from ai_pr_review.analyzer import AIAnalyzer, SHARD_FILE_THRESHOLD, SHARD_LINE_THRESHOLD


def _make_file_diff(path: str, additions: int = 100, deletions: int = 50) -> FileDiff:
    return FileDiff(
        path=path,
        change_type=ChangeType.MODIFIED,
        hunks=[DiffHunk(
            file_path=path,
            change_type=ChangeType.MODIFIED,
            old_start=1, old_count=deletions,
            new_start=1, new_count=additions,
            content="dummy content",
            header="@@ -1 +1 @@",
        )],
        additions=additions,
        deletions=deletions,
    )


def _make_parsed_diff(file_count: int, lines_per_file: int = 200) -> ParsedDiff:
    files = [_make_file_diff(f"src/file_{i}.py", lines_per_file, lines_per_file // 2) for i in range(file_count)]
    total_add = sum(f.additions for f in files)
    total_del = sum(f.deletions for f in files)
    return ParsedDiff(files=files, total_additions=total_add, total_deletions=total_del)


class TestShardDetection:
    def test_small_pr_no_shard(self):
        diff = _make_parsed_diff(5, 100)
        assert not AIAnalyzer._should_shard(diff)

    def test_large_file_count_triggers_shard(self):
        diff = _make_parsed_diff(SHARD_FILE_THRESHOLD + 5, 100)
        assert AIAnalyzer._should_shard(diff)

    def test_large_line_count_triggers_shard(self):
        diff = _make_parsed_diff(10, SHARD_LINE_THRESHOLD // 10 + 100)
        assert AIAnalyzer._should_shard(diff)

    def test_boundary_values(self):
        diff_exact_files = _make_parsed_diff(SHARD_FILE_THRESHOLD, 100)
        assert not AIAnalyzer._should_shard(diff_exact_files)

        diff_above_files = _make_parsed_diff(SHARD_FILE_THRESHOLD + 1, 100)
        assert AIAnalyzer._should_shard(diff_above_files)

        diff_below_files = _make_parsed_diff(SHARD_FILE_THRESHOLD - 1, 100)
        assert not AIAnalyzer._should_shard(diff_below_files)


class TestSharding:
    def test_split_into_multiple_shards(self):
        diff = _make_parsed_diff(25, 200)
        shards = AIAnalyzer._shard_diff(diff)
        assert len(shards) > 1

    def test_all_files_distributed(self):
        diff = _make_parsed_diff(30, 150)
        shards = AIAnalyzer._shard_diff(diff)
        all_files = [f for shard in shards for f in shard.files]
        assert len(all_files) == len(diff.files)

    def test_small_pr_returns_single_shard(self):
        diff = _make_parsed_diff(5, 100)
        shards = AIAnalyzer._shard_diff(diff)
        assert len(shards) >= 1

    def test_shard_stats_preserved(self):
        diff = _make_parsed_diff(25, 300)
        shards = AIAnalyzer._shard_diff(diff)
        total_shard_add = sum(s.total_additions for s in shards)
        total_shard_del = sum(s.total_deletions for s in shards)
        assert total_shard_add == diff.total_additions
        assert total_shard_del == diff.total_deletions


class TestMergeResults:
    def test_merge_empty_results(self):
        merged = AIAnalyzer._merge_shard_results([])
        assert len(merged.findings) == 0
        assert len(merged.suggestions) == 0

    def test_merge_combines_findings(self):
        from ai_pr_review.models import AnalysisResult, AnalysisSummary, Finding, Severity

        result1 = AnalysisResult(
            summary=AnalysisSummary(intent="test", scope="a", key_changes=["change1"]),
            findings=[Finding(
                type="bug", severity=Severity.HIGH, confidence=4,
                expert="security", file="a.py", line=10,
                title="Bug A", description="desc", suggestion="fix", code_snippet="code",
            )],
            suggestions=[],
        )
        result2 = AnalysisResult(
            summary=AnalysisSummary(intent="test", scope="b", key_changes=["change2"]),
            findings=[Finding(
                type="style", severity=Severity.LOW, confidence=3,
                expert="readability", file="b.py", line=20,
                title="Style B", description="desc", suggestion="fix", code_snippet="",
            )],
            suggestions=[],
        )
        merged = AIAnalyzer._merge_shard_results([result1, result2])
        assert len(merged.findings) == 2

    def test_merge_deduplicates(self):
        from ai_pr_review.models import AnalysisResult, AnalysisSummary, Finding, Severity

        finding = Finding(
            type="bug", severity=Severity.HIGH, confidence=4,
            expert="security", file="a.py", line=10,
            title="Same Bug", description="desc", suggestion="fix", code_snippet="code",
        )
        result1 = AnalysisResult(
            summary=AnalysisSummary(intent="", scope="", key_changes=[]),
            findings=[finding],
            suggestions=[],
        )
        result2 = AnalysisResult(
            summary=AnalysisSummary(intent="", scope="", key_changes=[]),
            findings=[finding],
            suggestions=[],
        )
        merged = AIAnalyzer._merge_shard_results([result1, result2])
        assert len(merged.findings) == 1

    def test_merge_sorts_by_location(self):
        from ai_pr_review.models import AnalysisResult, AnalysisSummary, Finding, Severity

        result1 = AnalysisResult(
            summary=AnalysisSummary(intent="", scope="", key_changes=[]),
            findings=[Finding(
                type="x", severity=Severity.MEDIUM, confidence=3,
                expert="e", file="z.py", line=100,
                title="Z", description="", suggestion="", code_snippet="",
            )],
            suggestions=[],
        )
        result2 = AnalysisResult(
            summary=AnalysisSummary(intent="", scope="", key_changes=[]),
            findings=[Finding(
                type="x", severity=Severity.MEDIUM, confidence=3,
                expert="e", file="a.py", line=10,
                title="A", description="", suggestion="", code_snippet="",
            )],
            suggestions=[],
        )
        merged = AIAnalyzer._merge_shard_results([result1, result2])
        assert merged.findings[0].file == "a.py"
        assert merged.findings[1].file == "z.py"

    def test_merge_key_changes_capped(self):
        from ai_pr_review.models import AnalysisResult, AnalysisSummary, Suggestion

        results = []
        for i in range(5):
            results.append(AnalysisResult(
                summary=AnalysisSummary(intent=f"intent_{i}", scope=f"scope_{i}", key_changes=[f"change_{i}"] * 5),
                findings=[],
                suggestions=[],
            ))
        merged = AIAnalyzer._merge_shard_results(results)
        assert len(merged.summary.key_changes) <= 10
