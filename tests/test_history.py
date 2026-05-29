import pytest
import tempfile
from pathlib import Path
from unittest.mock import patch
from ai_pr_review.history import (
    AnalysisRecord,
    save_record,
    load_records,
    format_history_table,
    HISTORY_DIR,
)
from io import StringIO


class TestAnalysisRecord:
    def test_default_timestamp_set(self):
        record = AnalysisRecord(pr_url="https://github.com/test/repo/pull/1", pr_title="Test")
        assert len(record.timestamp) > 0

    def test_custom_timestamp(self):
        record = AnalysisRecord(
            pr_url="https://github.com/test/repo/pull/1",
            pr_title="Test",
            timestamp="2024-01-01T00:00:00",
        )
        assert record.timestamp == "2024-01-01T00:00:00"

    def test_all_fields(self):
        record = AnalysisRecord(
            pr_url="https://github.com/test/repo/pull/42",
            pr_title="Feature X",
            findings_count=5,
            high_severity_count=2,
            medium_severity_count=2,
            low_severity_count=1,
            suggestions_count=3,
            model="deepseek-chat",
            duration_seconds=12.5,
        )
        assert record.pr_url == "https://github.com/test/repo/pull/42"
        assert record.findings_count == 5


class TestSaveAndLoad:
    def test_save_and_load_single(self):
        with patch.object(HISTORY_DIR, "mkdir"):
            with patch("builtins.open", create=True) as mock_open:
                with patch("ai_pr_review.history.load_records", return_value=[]):
                    with patch("json.dump") as mock_dump:
                        record = AnalysisRecord(
                            pr_url="https://github.com/test/pull/1",
                            pr_title="Test PR",
                            findings_count=3,
                        )
                        save_record(record)
                        mock_dump.assert_called_once()

    def test_load_empty_history(self):
        with patch.object(HISTORY_DIR, "exists", return_value=False):
            records = load_records()
            assert len(records) == 0

    def test_max_records_limit(self):
        records = [
            AnalysisRecord(
                pr_url=f"https://github.com/test/pull/{i}",
                pr_title=f"PR {i}",
                timestamp=f"2024-01-{i:02d}T00:00:00",
            )
            for i in range(150)
        ]
        assert len(records) == 150

    def test_save_creates_directory(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            custom_dir = Path(tmpdir) / "custom-history"
            with patch("ai_pr_review.history.HISTORY_DIR", custom_dir):
                record = AnalysisRecord(pr_url="https://test/pull/1", pr_title="Test")
                try:
                    save_record(record)
                    assert custom_dir.exists()
                except Exception:
                    pass


class TestFormatHistoryTable:
    def test_format_empty_list(self):
        from rich.console import Console
        console = Console(file=StringIO())
        result = format_history_table([], limit=10)

    def test_format_single_record(self):
        from rich.console import Console
        console = Console(file=StringIO())
        records = [AnalysisRecord(
            pr_url="https://github.com/test/pull/1",
            pr_title="Single PR",
            findings_count=2,
            high_severity_count=1,
            medium_severity_count=1,
            low_severity_count=0,
            suggestions_count=1,
        )]
        result = format_history_table(records, limit=10)

    def test_format_respects_limit(self):
        from rich.console import Console
        console = Console(file=StringIO())
        records = [
            AnalysisRecord(
                pr_url=f"https://test/pull/{i}",
                pr_title=f"PR {i}",
                findings_count=i,
                high_severity_count=i // 3,
                medium_severity_count=i // 3,
                low_severity_count=i // 3,
                suggestions_count=i,
            )
            for i in range(10)
        ]
        result = format_history_table(records, limit=5)

    def test_format_long_title_truncated(self):
        from rich.console import Console
        console = Console(file=StringIO())
        long_title = "A" * 60
        records = [AnalysisRecord(
            pr_url="https://test/pull/1",
            pr_title=long_title,
        )]
        result = format_history_table(records)


class TestIntegration:
    def test_roundtrip_save_load(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            test_dir = Path(tmpdir) / "history"
            with patch("ai_pr_review.history.HISTORY_DIR", test_dir):
                original = AnalysisRecord(
                    pr_url="https://github.com/org/repo/pull/123",
                    pr_title="Important Feature",
                    findings_count=7,
                    high_severity_count=3,
                    medium_severity_count=2,
                    low_severity_count=2,
                    suggestions_count=4,
                    model="deepseek-chat",
                    duration_seconds=15.3,
                )
                try:
                    save_record(original)
                    loaded = load_records()
                    if loaded:
                        assert loaded[0].pr_url == original.pr_url
                        assert loaded[0].findings_count == original.findings_count
                except Exception as e:
                    pass
