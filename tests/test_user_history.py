"""多用户历史隔离测试（v0.10 M4）

覆盖：
- save_record + load_records_for_user 按用户隔离
- 不同用户的记录互不可见
- 同用户的记录按 timestamp 倒序
- MAX_RECORDS 限制按用户独立
- load_records()（不带 user_id）跨用户返回全部
- AnalysisRecord.user_id 字段正确序列化
"""
import pytest

from ai_pr_review.data.history import (
    AnalysisRecord,
    _record_key,
    load_records,
    load_records_for_user,
    save_record,
)
from ai_pr_review.data.storage import Namespace
from ai_pr_review.data.persistence import LocalJSONStorage, configure_storage, reset_storage


@pytest.fixture
def storage(tmp_path):
    """注入临时 Storage 实例"""
    configure_storage(LocalJSONStorage(base_dir=tmp_path / "storage"))
    yield
    reset_storage()


def test_analysis_record_has_user_id_field():
    """AnalysisRecord 含 user_id 字段（v0.10 新增）"""
    record = AnalysisRecord(pr_url="x", pr_title="t", user_id="42")
    assert record.user_id == "42"


def test_default_user_id_is_empty_string():
    """CLI 单用户场景默认 user_id 为空字符串"""
    record = AnalysisRecord(pr_url="x", pr_title="t")
    assert record.user_id == ""


def test_record_key_includes_user_id(storage):
    """_record_key 应包含 user_id 段"""
    r1 = AnalysisRecord(pr_url="https://x.com/1", pr_title="t1", user_id="alice")
    r2 = AnalysisRecord(pr_url="https://x.com/1", pr_title="t2", user_id="bob")
    # 同一 URL，不同 user，key 必须不同
    assert _record_key(r1) != _record_key(r2)
    # key 包含 user_id
    assert "__alice__" in _record_key(r1)
    assert "__bob__" in _record_key(r2)


def test_save_and_load_user_isolation(storage):
    """save_record(user_a) + load_records_for_user(user_b) 不应看到对方记录"""
    rec_a = AnalysisRecord(pr_url="https://x.com/p/1", pr_title="A", user_id="alice")
    rec_b = AnalysisRecord(pr_url="https://x.com/p/2", pr_title="B", user_id="bob")

    save_record(rec_a)
    save_record(rec_b)

    alice_records = load_records_for_user("alice")
    bob_records = load_records_for_user("bob")

    assert len(alice_records) == 1
    assert alice_records[0].user_id == "alice"
    assert alice_records[0].pr_url == "https://x.com/p/1"

    assert len(bob_records) == 1
    assert bob_records[0].user_id == "bob"
    assert bob_records[0].pr_url == "https://x.com/p/2"


def test_load_records_no_user_returns_all(storage):
    """load_records()（无 user_id）跨用户返回全部"""
    for i, uid in enumerate(["alice", "bob", "alice"]):
        save_record(AnalysisRecord(
            pr_url=f"https://x.com/p/{i}",
            pr_title=f"PR {i}",
            user_id=uid,
        ))

    all_records = load_records()
    assert len(all_records) == 3


def test_load_records_for_user_empty_user_id_returns_all(storage):
    """load_records_for_user("") 等同 load_records()（CLI 单用户兼容）"""
    save_record(AnalysisRecord(pr_url="https://x.com/1", pr_title="A", user_id="alice"))
    save_record(AnalysisRecord(pr_url="https://x.com/2", pr_title="B", user_id="bob"))

    cli_records = load_records_for_user("")  # CLI 场景
    assert len(cli_records) == 2


def test_records_sorted_by_timestamp_desc_per_user(storage):
    """每个用户的记录应按 timestamp 倒序"""
    import time
    for i in range(3):
        rec = AnalysisRecord(
            pr_url=f"https://x.com/{i}",
            pr_title=f"PR {i}",
            user_id="alice",
        )
        save_record(rec)
        time.sleep(0.01)  # 确保 timestamp 不同

    records = load_records_for_user("alice")
    timestamps = [r.timestamp for r in records]
    assert timestamps == sorted(timestamps, reverse=True)


def test_max_records_enforced_per_user(storage):
    """MAX_RECORDS 限制应按用户独立"""
    from ai_pr_review.data.history import MAX_RECORDS

    # Alice 保存 MAX_RECORDS + 5 条（共 105 条）
    for i in range(MAX_RECORDS + 5):
        save_record(AnalysisRecord(
            pr_url=f"https://x.com/a/{i}",
            pr_title=f"A{i}",
            user_id="alice",
        ))

    # Bob 保存 3 条（应全部保留）
    for i in range(3):
        save_record(AnalysisRecord(
            pr_url=f"https://x.com/b/{i}",
            pr_title=f"B{i}",
            user_id="bob",
        ))

    alice_records = load_records_for_user("alice")
    bob_records = load_records_for_user("bob")

    assert len(alice_records) == MAX_RECORDS
    assert len(bob_records) == 3


def test_old_records_without_user_id_loaded_for_empty_user(storage):
    """迁移过来的旧记录（无 user_id）应能被 load_records_for_user("") 加载"""
    # 直接存一个无 user_id 的记录（模拟旧数据）
    from dataclasses import asdict
    storage = configure_storage.__self__ if False else None  # noqa: keep linter happy
    save_record(AnalysisRecord(pr_url="https://x.com/legacy", pr_title="Legacy", user_id=""))

    records = load_records_for_user("")  # CLI/legacy 模式
    assert len(records) == 1
    assert records[0].user_id == ""

    # alice 不应看到 legacy
    alice_records = load_records_for_user("alice")
    assert len(alice_records) == 0