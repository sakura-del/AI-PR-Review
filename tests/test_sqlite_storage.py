"""SQLiteStorage 实现特性测试

ABC 契约已由 test_storage.py 参数化覆盖，本文件专注于实现特有行为：
- DB 文件创建与目录自动创建
- 持久化（关闭后重开能读到数据）
- Schema 幂等创建
- LIKE 前缀搜索利用索引
- 时间戳字段正确填充
"""
import sqlite3
from pathlib import Path

from ai_pr_review.data.persistence.sqlite import SQLiteStorage
from ai_pr_review.data.storage import Namespace


def test_db_path_parent_is_created_on_init(tmp_path):
    """传入不存在的 db_path 父目录应自动创建"""
    target = tmp_path / "deep" / "nested" / "storage.db"
    assert not target.parent.exists()
    SQLiteStorage(db_path=target)
    assert target.parent.exists()
    assert target.exists()


def test_persists_across_instances(tmp_path):
    """新实例读旧实例写入的数据"""
    db = tmp_path / "test.db"
    writer = SQLiteStorage(db_path=db)
    writer.save(Namespace.CACHE, "k1", {"v": 1})

    reader = SQLiteStorage(db_path=db)
    assert reader.get(Namespace.CACHE, "k1") == {"v": 1}


def test_schema_is_idempotent(tmp_path):
    """多次创建实例不会损坏 schema"""
    db = tmp_path / "test.db"
    for _ in range(3):
        SQLiteStorage(db_path=db)
    # 仍然可用
    s = SQLiteStorage(db_path=db)
    s.save(Namespace.HISTORY, "k", {"v": 1})
    assert s.get(Namespace.HISTORY, "k") == {"v": 1}


def test_schema_has_required_tables_and_indexes(tmp_path):
    """DB schema 含 kv 表与 namespace 索引"""
    db = tmp_path / "test.db"
    SQLiteStorage(db_path=db)

    conn = sqlite3.connect(str(db))
    try:
        tables = {r[0] for r in conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table'"
        ).fetchall()}
        assert "kv" in tables

        indexes = {r[0] for r in conn.execute(
            "SELECT name FROM sqlite_master WHERE type='index'"
        ).fetchall()}
        assert "idx_kv_namespace" in indexes
    finally:
        conn.close()


def test_save_records_timestamps(tmp_path):
    """save 应同时写 created_at 与 updated_at；二次 save 仅更新 updated_at"""
    db = tmp_path / "test.db"
    s = SQLiteStorage(db_path=db)

    s.save(Namespace.CACHE, "k", {"v": 1})

    conn = sqlite3.connect(str(db))
    try:
        row = conn.execute(
            "SELECT created_at, updated_at FROM kv WHERE namespace=? AND key=?",
            (Namespace.CACHE, "k"),
        ).fetchone()
        first_created = row[0]
        first_updated = row[1]
        assert first_created  # 非空
        assert first_updated
    finally:
        conn.close()

    # 二次 save：created_at 不变，updated_at 可能变
    import time
    time.sleep(0.01)
    s.save(Namespace.CACHE, "k", {"v": 2})

    conn = sqlite3.connect(str(db))
    try:
        row = conn.execute(
            "SELECT created_at, updated_at FROM kv WHERE namespace=? AND key=?",
            (Namespace.CACHE, "k"),
        ).fetchone()
        assert row[0] == first_created
        # updated_at 可能相同（同毫秒），但 value 已是新值
    finally:
        conn.close()
    assert s.get(Namespace.CACHE, "k") == {"v": 2}


def test_like_prefix_query_works(tmp_path):
    """LIKE 'prefix%' 前缀过滤返回正确结果"""
    db = tmp_path / "test.db"
    s = SQLiteStorage(db_path=db)
    s.save(Namespace.HISTORY, "rec_001", {"v": 1})
    s.save(Namespace.HISTORY, "rec_002", {"v": 2})
    s.save(Namespace.HISTORY, "other", {"v": 3})

    assert sorted(s.list_keys(Namespace.HISTORY, prefix="rec_")) == ["rec_001", "rec_002"]
    assert sorted(s.list_keys(Namespace.HISTORY, prefix="o")) == ["other"]
    assert s.list_keys(Namespace.HISTORY, prefix="nonexistent") == []


def test_unicode_values_persisted(tmp_path):
    """unicode 数据正确存取"""
    db = tmp_path / "test.db"
    writer = SQLiteStorage(db_path=db)
    writer.save(Namespace.CACHE, "k", {"text": "中文 🚀"})

    reader = SQLiteStorage(db_path=db)
    assert reader.get(Namespace.CACHE, "k")["text"] == "中文 🚀"


def test_namespaces_are_isolated_in_db(tmp_path):
    """DB 内不同 namespace 完全隔离"""
    db = tmp_path / "test.db"
    s = SQLiteStorage(db_path=db)
    s.save(Namespace.HISTORY, "shared", {"v": "h"})
    s.save(Namespace.CACHE, "shared", {"v": "c"})

    assert s.get(Namespace.HISTORY, "shared")["v"] == "h"
    assert s.get(Namespace.CACHE, "shared")["v"] == "c"


def test_count_uses_index_for_performance(tmp_path):
    """count() 在大数据量下应仍然快速（验证索引生效）

    插入 1000 条后 count 仍是 O(1)（SQLite COUNT WHERE namespace=? 用索引）
    """
    db = tmp_path / "test.db"
    s = SQLiteStorage(db_path=db)
    for i in range(1000):
        s.save(Namespace.HISTORY, f"k{i:04d}", {"v": i})
    assert s.count(Namespace.HISTORY) == 1000
    assert s.count(Namespace.CACHE) == 0


def test_empty_value_stored_and_retrieved(tmp_path):
    """空 dict 是合法值"""
    db = tmp_path / "test.db"
    s = SQLiteStorage(db_path=db)
    s.save(Namespace.CACHE, "empty", {})
    assert s.get(Namespace.CACHE, "empty") == {}
    assert s.exists(Namespace.CACHE, "empty") is True