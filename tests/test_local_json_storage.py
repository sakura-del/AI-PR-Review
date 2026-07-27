"""LocalJSONStorage 实现特性测试

ABC 契约已由 test_storage.py 参数化覆盖，本文件专注于实现特有行为：
- 持久化（关闭后重开能读到数据）
- 原子写入（崩溃时不应留半截文件）
- 目录自动创建
- 损坏文件的容错
"""
import json
from pathlib import Path

from ai_pr_review.data.persistence.local_json import LocalJSONStorage
from ai_pr_review.data.storage import Namespace


def test_base_dir_is_created_on_init(tmp_path):
    """传入不存在的 base_dir 应自动创建"""
    target = tmp_path / "deep" / "nested" / "storage"
    assert not target.exists()
    LocalJSONStorage(base_dir=target)
    assert target.exists()
    assert target.is_dir()


def test_persists_across_instances(tmp_path):
    """新实例读旧实例写入的数据"""
    base = tmp_path / "storage"
    writer = LocalJSONStorage(base_dir=base)
    writer.save(Namespace.CACHE, "k1", {"v": 1})

    reader = LocalJSONStorage(base_dir=base)
    assert reader.get(Namespace.CACHE, "k1") == {"v": 1}


def test_each_namespace_uses_separate_file(tmp_path):
    """不同 namespace 写入不同文件，互不干扰"""
    base = tmp_path / "storage"
    s = LocalJSONStorage(base_dir=base)
    s.save(Namespace.HISTORY, "k", {"ns": "h"})
    s.save(Namespace.CACHE, "k", {"ns": "c"})

    # 文件应分别存在
    assert (base / "history.json").exists()
    assert (base / "cache.json").exists()

    # 内容互不干扰
    assert s.get(Namespace.HISTORY, "k")["ns"] == "h"
    assert s.get(Namespace.CACHE, "k")["ns"] == "c"


def test_corrupted_file_is_treated_as_empty(tmp_path):
    """namespace 文件被损坏时，save/delete 应能恢复而非崩溃"""
    base = tmp_path / "json_storage"
    base.mkdir()
    (base / "cache.json").write_text("{not valid json", encoding="utf-8")

    s = LocalJSONStorage(base_dir=base)
    # 读取损坏文件应返回 None 而非抛异常
    assert s.get(Namespace.CACHE, "k") is None

    # save 应能写入并覆盖损坏内容
    s.save(Namespace.CACHE, "k", {"recovered": True})
    assert s.get(Namespace.CACHE, "k") == {"recovered": True}


def test_non_dict_root_is_treated_as_empty(tmp_path):
    """namespace 文件根是 list/str 等非 dict 时，按空处理"""
    base = tmp_path / "json_storage"
    base.mkdir()
    (base / "cache.json").write_text(json.dumps([1, 2, 3]), encoding="utf-8")

    s = LocalJSONStorage(base_dir=base)
    assert s.get(Namespace.CACHE, "k") is None
    # 可正常写入恢复
    s.save(Namespace.CACHE, "k", {"ok": 1})
    assert s.get(Namespace.CACHE, "k") == {"ok": 1}


def test_atomic_write_no_partial_file_on_simulated_crash(tmp_path):
    """模拟崩溃：原子写入应保证不会留下半截文件

    验证方法：写入成功后，目录里不应有遗留的 .json.tmp 临时文件。
    """
    base = tmp_path / "storage"
    s = LocalJSONStorage(base_dir=base)
    s.save(Namespace.CACHE, "k1", {"v": 1})
    s.save(Namespace.CACHE, "k2", {"v": 2})
    s.delete(Namespace.CACHE, "k1")

    # 不应有临时文件残留
    tmp_files = list(base.glob(".cache.*.json.tmp"))
    assert tmp_files == []


def test_value_with_unicode_persists(tmp_path):
    """unicode 数据正确存取（ensure_ascii=False 应确保）"""
    base = tmp_path / "storage"
    s = LocalJSONStorage(base_dir=base)
    s.save(Namespace.CACHE, "k", {"text": "中文测试 🚀"})
    # 重新加载验证
    s2 = LocalJSONStorage(base_dir=base)
    assert s2.get(Namespace.CACHE, "k")["text"] == "中文测试 🚀"

    # 文件里也是 UTF-8 直接写入（而非 \\u 转义）
    raw = (base / "cache.json").read_text(encoding="utf-8")
    assert "中文测试" in raw
    assert "\\u" not in raw


def test_delete_then_save_reuses_namespace(tmp_path):
    """删除全部 key 后再写入，namespace 文件应正常复用"""
    base = tmp_path / "storage"
    s = LocalJSONStorage(base_dir=base)
    s.save(Namespace.CACHE, "k1", {"v": 1})
    s.delete(Namespace.CACHE, "k1")
    # 此时 namespace 为空但文件应仍存在
    assert (base / "cache.json").exists()
    assert s.list_keys(Namespace.CACHE) == []

    # 重新写入应正常
    s.save(Namespace.CACHE, "k2", {"v": 2})
    assert s.get(Namespace.CACHE, "k2") == {"v": 2}


def test_empty_value_is_stored_and_retrieved(tmp_path):
    """空 dict 是合法值，能正常存取"""
    base = tmp_path / "storage"
    s = LocalJSONStorage(base_dir=base)
    s.save(Namespace.CACHE, "empty", {})
    assert s.get(Namespace.CACHE, "empty") == {}
    assert s.exists(Namespace.CACHE, "empty") is True


def test_large_value_works(tmp_path):
    """大体积值（如千行 list）能正常存取"""
    base = tmp_path / "storage"
    s = LocalJSONStorage(base_dir=base)
    big = {"items": list(range(10000))}
    s.save(Namespace.CACHE, "big", big)
    assert s.get(Namespace.CACHE, "big") == big