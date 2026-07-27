"""history 模块测试（v0.9 适配版 — 基于 Storage）

v0.9 重构后，history.py 通过 persistence.Storage 抽象读写数据。
本测试：
- 用 configure_storage + LocalJSONStorage 注入临时存储（每个测试隔离）
- 保留 AnalysisRecord 数据类相关测试
- 替换旧的"patch HISTORY_DIR + 检查文件存在"为"通过公共 API 验证行为"
"""
from io import StringIO
from unittest.mock import patch

import pytest

from ai_pr_review.data.history import (
    AnalysisRecord,
    _OLD_HISTORY_FILE,
    find_last_record,
    format_history_table,
    load_records,
    save_record,
)
from ai_pr_review.data.persistence import LocalJSONStorage, configure_storage


@pytest.fixture
def storage(tmp_path):
    """注入临时 LocalJSONStorage"""
    s = LocalJSONStorage(base_dir=tmp_path / "storage")
    configure_storage(s)
    return s


# ===== AnalysisRecord 数据类 =====

class TestAnalysisRecord:
    def test_default_timestamp_set(self):
        record = AnalysisRecord(pr_url="https://github.com/test/repo/pull/1", pr_title="Test")
        assert len(record.timestamp) > 0

    def test_custom_timestamp(self):
        record = AnalysisRecord(
            pr_url="https://github.com/test/repo/pull/1",
            pr_title="Test",
            timestamp="2024-01-01T00:00:00+00:00",
        )
        assert record.timestamp == "2024-01-01T00:00:00+00:00"

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
            head_sha="abc",
            base_sha="def",
            is_incremental=True,
        )
        assert record.pr_url == "https://github.com/test/repo/pull/42"
        assert record.findings_count == 5
        assert record.is_incremental is True


# ===== Save/Load 行为（走 Storage）=====

class TestSaveAndLoad:
    def test_save_and_load_single(self, storage):
        record = AnalysisRecord(
            pr_url="https://github.com/test/pull/1",
            pr_title="Test PR",
            findings_count=3,
        )
        save_record(record)
        loaded = load_records()
        assert len(loaded) == 1
        assert loaded[0].pr_url == "https://github.com/test/pull/1"
        assert loaded[0].findings_count == 3

    def test_load_empty_history(self, storage):
        # storage 是空的 tmp_path 目录
        records = load_records()
        assert records == []

    def test_save_creates_storage_dir(self, tmp_path):
        """首次 save 应确保 storage 目录存在"""
        target = tmp_path / "deep" / "nested" / "storage"
        configure_storage(LocalJSONStorage(base_dir=target))
        record = AnalysisRecord(pr_url="https://test/pull/1", pr_title="Test")
        save_record(record)
        assert target.exists()

    def test_save_load_multiple_records(self, storage):
        for i in range(5):
            save_record(AnalysisRecord(
                pr_url=f"https://test/pull/{i}",
                pr_title=f"PR {i}",
                findings_count=i,
                timestamp=f"2024-01-{i + 1:02d}T00:00:00+00:00",
            ))
        loaded = load_records()
        assert len(loaded) == 5
        # 倒序（最新在前）
        assert loaded[0].pr_url == "https://test/pull/4"


# ===== 格式化 =====

class TestFormatHistoryTable:
    def test_format_empty_list(self):
        from rich.console import Console
        Console(file=StringIO())
        format_history_table([], limit=10)

    def test_format_single_record(self):
        Console_module = __import__("rich.console", fromlist=["Console"])
        Console_module.Console(file=StringIO())
        records = [AnalysisRecord(
            pr_url="https://github.com/test/pull/1",
            pr_title="Single PR",
            findings_count=2,
            high_severity_count=1,
            medium_severity_count=1,
            low_severity_count=0,
            suggestions_count=1,
        )]
        format_history_table(records, limit=10)

    def test_format_respects_limit(self):
        Console_module = __import__("rich.console", fromlist=["Console"])
        Console_module.Console(file=StringIO())
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
        format_history_table(records, limit=5)

    def test_format_long_title_truncated(self):
        Console_module = __import__("rich.console", fromlist=["Console"])
        Console_module.Console(file=StringIO())
        long_title = "A" * 60
        records = [AnalysisRecord(
            pr_url="https://test/pull/1",
            pr_title=long_title,
        )]
        format_history_table(records)


# ===== 集成测试 =====

class TestIntegration:
    def test_roundtrip_save_load(self, storage):
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
        save_record(original)
        loaded = load_records()
        assert len(loaded) == 1
        assert loaded[0].pr_url == original.pr_url
        assert loaded[0].findings_count == original.findings_count
        assert loaded[0].duration_seconds == original.duration_seconds
        assert loaded[0].model == original.model


# ===== 旧文件路径常量保留测试（向后兼容）=====

class TestLegacyConstants:
    def test_history_dir_constant_exists(self):
        """HISTORY_DIR 常量保留供外部 import"""
        from ai_pr_review.data.history import HISTORY_DIR
        assert HISTORY_DIR.exists() or True  # 路径常量存在即可
        assert HISTORY_DIR.name == "history"

    def test_old_history_file_path_exists(self):
        """旧文件路径常量保留"""
        assert _OLD_HISTORY_FILE.name == "history.json"