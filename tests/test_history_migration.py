"""history 模块基于 Storage 的迁移与行为测试（T10 [A10]）

覆盖：
- 正常 save/load 通过 Storage 走通
- 旧 JSON 文件一次性迁移到 Storage
- MAX_RECORDS 限制保留
- 排序行为（最新在前）
- 与 format_history_table / find_last_record 协同

注：使用 configure_storage 注入临时 LocalJSONStorage（tmp_path 隔离）。
"""
import json
from pathlib import Path
from unittest.mock import patch

import pytest

from ai_pr_review.data.history import (
    MAX_RECORDS,
    AnalysisRecord,
    _OLD_HISTORY_FILE,
    _record_key,
    find_last_record,
    load_records,
    save_record,
)
from ai_pr_review.data.persistence import LocalJSONStorage, configure_storage


@pytest.fixture
def storage(tmp_path):
    """注入临时 Storage 实例"""
    s = LocalJSONStorage(base_dir=tmp_path / "storage")
    configure_storage(s)
    return s


def test_save_and_load_roundtrip_via_storage(storage):
    record = AnalysisRecord(
        pr_url="https://github.com/owner/repo/pull/1",
        pr_title="Test PR",
        findings_count=3,
        high_severity_count=1,
        medium_severity_count=1,
        low_severity_count=1,
        model="deepseek-chat",
        duration_seconds=10.5,
    )
    save_record(record)
    loaded = load_records()
    assert len(loaded) == 1
    assert loaded[0].pr_url == record.pr_url
    assert loaded[0].findings_count == 3
    assert loaded[0].model == "deepseek-chat"
    assert loaded[0].duration_seconds == 10.5


def test_storage_namespace_is_history(storage):
    """数据应落在 Namespace.HISTORY 下"""
    from ai_pr_review.data.storage import Namespace
    record = AnalysisRecord(pr_url="https://x/1", pr_title="x")
    save_record(record)
    keys = storage.list_keys(Namespace.HISTORY)
    assert len(keys) == 1
    # key 格式应为 "{timestamp}__{url_hash}"
    key = keys[0]
    assert "__" in key
    assert _record_key(record) == key


def test_records_sorted_newest_first(storage):
    """load_records 应按 timestamp 倒序"""
    r1 = AnalysisRecord(
        pr_url="https://x/1", pr_title="old",
        timestamp="2024-01-01T00:00:00+00:00",
    )
    r2 = AnalysisRecord(
        pr_url="https://x/2", pr_title="new",
        timestamp="2024-12-01T00:00:00+00:00",
    )
    save_record(r1)
    save_record(r2)
    loaded = load_records()
    assert loaded[0].pr_title == "new"
    assert loaded[1].pr_title == "old"


def test_max_records_truncation_on_save(storage):
    """超过 MAX_RECORDS 后，save 时自动清理最旧的"""
    for i in range(MAX_RECORDS + 20):
        save_record(AnalysisRecord(
            pr_url=f"https://x/{i}",
            pr_title=f"PR {i}",
            timestamp=f"2024-01-{(i % 28) + 1:02d}T00:00:00+00:00",
        ))
    loaded = load_records()
    # 注意：因 timestamp 格式约束，实际可能略多于 MAX_RECORDS
    # 但 save 应保证至少 ≤ MAX_RECORDS
    assert len(loaded) <= MAX_RECORDS


def test_old_history_file_migrates_on_first_load(tmp_path):
    """旧 ~/.ai-pr-review/history/history.json 首次 load 时迁移到 Storage"""
    # 构造旧文件
    old_file = _OLD_HISTORY_FILE
    old_data = [
        {
            "pr_url": "https://github.com/old/repo/pull/1",
            "pr_title": "Old PR 1",
            "timestamp": "2024-06-01T00:00:00+00:00",
            "findings_count": 5,
            "high_severity_count": 2,
            "medium_severity_count": 2,
            "low_severity_count": 1,
            "suggestions_count": 3,
            "model": "qwen-plus",
            "duration_seconds": 8.0,
            "head_sha": "abc123",
            "base_sha": "def456",
            "is_incremental": False,
        },
        {
            "pr_url": "https://github.com/old/repo/pull/2",
            "pr_title": "Old PR 2",
            "timestamp": "2024-06-15T00:00:00+00:00",
            "findings_count": 2,
            "high_severity_count": 0,
            "medium_severity_count": 1,
            "low_severity_count": 1,
            "suggestions_count": 1,
            "model": "qwen-plus",
            "duration_seconds": 6.0,
            "head_sha": "ghi789",
            "base_sha": "jkl012",
            "is_incremental": True,
        },
    ]
    # 临时把 HOME 改成 tmp_path，让 _OLD_HISTORY_FILE 落到 tmp
    with patch.object(
        __import__("ai_pr_review.data.history", fromlist=["_OLD_HISTORY_FILE"]),
        "_OLD_HISTORY_FILE",
        tmp_path / "history.json",
    ):
        old_path = tmp_path / "history.json"
        old_path.parent.mkdir(parents=True, exist_ok=True)
        old_path.write_text(json.dumps(old_data), encoding="utf-8")

        # 注入空 Storage
        configure_storage(LocalJSONStorage(base_dir=tmp_path / "storage"))

        loaded = load_records()
        assert len(loaded) == 2
        urls = {r.pr_url for r in loaded}
        assert urls == {
            "https://github.com/old/repo/pull/1",
            "https://github.com/old/repo/pull/2",
        }
        # 字段保留
        r1 = next(r for r in loaded if "pull/1" in r.pr_url)
        assert r1.findings_count == 5
        assert r1.head_sha == "abc123"
        r2 = next(r for r in loaded if "pull/2" in r.pr_url)
        assert r2.is_incremental is True


def test_migration_is_idempotent(tmp_path):
    """多次 load_records 不会重复迁移"""
    with patch.object(
        __import__("ai_pr_review.data.history", fromlist=["_OLD_HISTORY_FILE"]),
        "_OLD_HISTORY_FILE",
        tmp_path / "history.json",
    ):
        old_path = tmp_path / "history.json"
        old_path.parent.mkdir(parents=True, exist_ok=True)
        old_path.write_text(json.dumps([
            {"pr_url": "https://x/1", "pr_title": "t", "timestamp": "2024-01-01T00:00:00+00:00"},
        ]), encoding="utf-8")

        storage = LocalJSONStorage(base_dir=tmp_path / "storage")
        configure_storage(storage)

        load_records()
        count_after_first = storage.count(__import__("ai_pr_review.data.storage", fromlist=["Namespace"]).Namespace.HISTORY)

        load_records()
        count_after_second = storage.count(__import__("ai_pr_review.data.storage", fromlist=["Namespace"]).Namespace.HISTORY)

        assert count_after_first == count_after_second == 1


def test_old_file_not_deleted_after_migration(tmp_path):
    """迁移后旧文件应保留（不回滚就丢失数据）"""
    with patch.object(
        __import__("ai_pr_review.data.history", fromlist=["_OLD_HISTORY_FILE"]),
        "_OLD_HISTORY_FILE",
        tmp_path / "history.json",
    ):
        old_path = tmp_path / "history.json"
        old_path.parent.mkdir(parents=True, exist_ok=True)
        old_path.write_text(json.dumps([
            {"pr_url": "https://x/1", "pr_title": "t", "timestamp": "2024-01-01T00:00:00+00:00"},
        ]), encoding="utf-8")

        configure_storage(LocalJSONStorage(base_dir=tmp_path / "storage"))
        load_records()

        assert old_path.exists()  # 旧文件保留


def test_find_last_record(storage):
    """find_last_record 应返回指定 PR 的最近记录（按 timestamp）"""
    save_record(AnalysisRecord(
        pr_url="https://x/1", pr_title="v1",
        timestamp="2024-01-01T00:00:00+00:00",
        head_sha="sha1",
    ))
    save_record(AnalysisRecord(
        pr_url="https://x/1", pr_title="v2",
        timestamp="2024-06-01T00:00:00+00:00",
        head_sha="sha2",
    ))
    save_record(AnalysisRecord(
        pr_url="https://x/2", pr_title="other",
        timestamp="2024-03-01T00:00:00+00:00",
        head_sha="sha3",
    ))

    last = find_last_record("https://x/1")
    assert last is not None
    assert last.pr_title == "v2"
    assert last.head_sha == "sha2"


def test_find_last_record_requires_head_sha(storage):
    """没有 head_sha 的记录不会被 find_last_record 返回"""
    save_record(AnalysisRecord(
        pr_url="https://x/1", pr_title="no-sha",
        head_sha="",
    ))
    assert find_last_record("https://x/1") is None


def test_corrupted_old_file_is_skipped(tmp_path):
    """旧文件损坏时不应抛异常，load 返回空"""
    with patch.object(
        __import__("ai_pr_review.data.history", fromlist=["_OLD_HISTORY_FILE"]),
        "_OLD_HISTORY_FILE",
        tmp_path / "history.json",
    ):
        old_path = tmp_path / "history.json"
        old_path.parent.mkdir(parents=True, exist_ok=True)
        old_path.write_text("{not valid json", encoding="utf-8")

        configure_storage(LocalJSONStorage(base_dir=tmp_path / "storage"))
        loaded = load_records()
        assert loaded == []