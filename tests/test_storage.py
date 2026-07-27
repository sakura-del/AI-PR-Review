"""Storage ABC 接口契约测试（参数化覆盖所有实现）

通过 pytest parametrize 让同一组契约测试对每个 Storage 实现各跑一次：
- memory: 内存版（契约正确性的最低保障，最快）
- local_json: 文件版（验证持久化、原子写入）
- sqlite: 数据库版（验证跨进程/索引场景）

新增实现只需在 STORAGE_IMPLS 列表追加即可被自动覆盖。
"""
import pytest

from ai_pr_review.data.storage import CURRENT_SCHEMA_VERSION, Namespace, Storage


class MemoryStorage(Storage):
    """最小内存实现，用于快速契约验证

    满足 ABC 全部契约：深拷贝语义、命名空间隔离、幂等删除。
    """

    def __init__(self) -> None:
        self._store: dict[str, dict[str, dict]] = {}

    def get(self, namespace, key):
        import copy
        value = self._store.get(namespace, {}).get(key)
        return copy.deepcopy(value) if value is not None else None

    def save(self, namespace, key, value):
        import copy
        self._store.setdefault(namespace, {})[key] = copy.deepcopy(value)

    def delete(self, namespace, key):
        self._store.get(namespace, {}).pop(key, None)

    def list_keys(self, namespace, prefix=""):
        return [k for k in self._store.get(namespace, {}) if k.startswith(prefix)]


def _make_local_json(base_dir):
    from ai_pr_review.data.persistence.local_json import LocalJSONStorage
    return LocalJSONStorage(base_dir=base_dir)


def _make_sqlite(db_path):
    from ai_pr_review.data.persistence.sqlite import SQLiteStorage
    return SQLiteStorage(db_path=db_path)


@pytest.fixture(params=["memory", "local_json", "sqlite"])
def storage(request, tmp_path):
    """参数化 Storage 实现 fixture

    每个测试自动跑 3 次（每个实现一次）。
    """
    impl = request.param
    if impl == "memory":
        return MemoryStorage()
    if impl == "local_json":
        return _make_local_json(tmp_path / "json")
    if impl == "sqlite":
        return _make_sqlite(tmp_path / "test.db")
    raise ValueError(f"Unknown impl: {impl}")


# ===== namespace 常量与 schema 版本 =====

def test_namespace_constants_are_stable():
    """namespace 常量是稳定字符串，避免 typo 与跨模块拼写漂移"""
    assert Namespace.HISTORY == "history"
    assert Namespace.CACHE == "cache"
    assert Namespace.TEAM_RULES == "team_rules"


def test_current_schema_version_is_positive_int():
    assert isinstance(CURRENT_SCHEMA_VERSION, int)
    assert CURRENT_SCHEMA_VERSION >= 1


# ===== 核心 CRUD 契约 =====

def test_save_and_get_roundtrip(storage):
    storage.save(Namespace.CACHE, "k1", {"a": 1, "b": "x"})
    assert storage.get(Namespace.CACHE, "k1") == {"a": 1, "b": "x"}


def test_get_missing_returns_none(storage):
    assert storage.get(Namespace.CACHE, "missing") is None


def test_save_overwrites_existing_key(storage):
    storage.save(Namespace.HISTORY, "k", {"v": 1})
    storage.save(Namespace.HISTORY, "k", {"v": 2})
    assert storage.get(Namespace.HISTORY, "k") == {"v": 2}


def test_delete_existing_key_removes_value(storage):
    storage.save(Namespace.TEAM_RULES, "k", {"x": True})
    storage.delete(Namespace.TEAM_RULES, "k")
    assert storage.get(Namespace.TEAM_RULES, "k") is None


def test_delete_missing_key_is_idempotent(storage):
    """delete 不存在的 key 不抛异常（契约要求）"""
    storage.delete(Namespace.CACHE, "never-existed")


def test_namespaces_are_isolated(storage):
    storage.save(Namespace.CACHE, "shared", {"ns": "cache"})
    storage.save(Namespace.HISTORY, "shared", {"ns": "history"})
    assert storage.get(Namespace.CACHE, "shared")["ns"] == "cache"
    assert storage.get(Namespace.HISTORY, "shared")["ns"] == "history"


def test_list_keys_returns_all_in_namespace(storage):
    storage.save(Namespace.CACHE, "a", {})
    storage.save(Namespace.CACHE, "b", {})
    storage.save(Namespace.CACHE, "c", {})
    assert sorted(storage.list_keys(Namespace.CACHE)) == ["a", "b", "c"]


def test_list_keys_with_prefix_filter(storage):
    storage.save(Namespace.HISTORY, "rec_001", {})
    storage.save(Namespace.HISTORY, "rec_002", {})
    storage.save(Namespace.HISTORY, "other", {})
    assert sorted(storage.list_keys(Namespace.HISTORY, prefix="rec_")) == ["rec_001", "rec_002"]


def test_list_keys_empty_namespace_returns_empty(storage):
    assert storage.list_keys(Namespace.CACHE) == []


def test_list_values_returns_all_values(storage):
    storage.save(Namespace.HISTORY, "k1", {"v": 1})
    storage.save(Namespace.HISTORY, "k2", {"v": 2})
    values = storage.list_values(Namespace.HISTORY)
    assert {"v": 1} in values and {"v": 2} in values
    assert len(values) == 2


def test_list_values_with_prefix(storage):
    storage.save(Namespace.HISTORY, "rec_001", {"v": 1})
    storage.save(Namespace.HISTORY, "rec_002", {"v": 2})
    storage.save(Namespace.HISTORY, "other", {"v": 3})
    values = storage.list_values(Namespace.HISTORY, prefix="rec_")
    assert len(values) == 2
    assert {"v": 1} in values and {"v": 2} in values


def test_exists_returns_true_when_present(storage):
    storage.save(Namespace.CACHE, "k", {})
    assert storage.exists(Namespace.CACHE, "k") is True


def test_exists_returns_false_when_absent(storage):
    assert storage.exists(Namespace.CACHE, "missing") is False


def test_count_returns_total_keys_in_namespace(storage):
    assert storage.count(Namespace.HISTORY) == 0
    storage.save(Namespace.HISTORY, "a", {})
    storage.save(Namespace.HISTORY, "b", {})
    assert storage.count(Namespace.HISTORY) == 2


def test_save_returns_deep_copy_not_reference(storage):
    """save 后修改原 dict 不影响存储（深拷贝语义）"""
    original = {"nested": {"x": 1}}
    storage.save(Namespace.CACHE, "k", original)
    original["nested"]["x"] = 999
    assert storage.get(Namespace.CACHE, "k")["nested"]["x"] == 1


def test_get_returns_copy_not_reference(storage):
    """get 取得的 dict 修改后不影响存储（深拷贝语义）"""
    storage.save(Namespace.CACHE, "k", {"nested": {"x": 1}})
    fetched = storage.get(Namespace.CACHE, "k")
    fetched["nested"]["x"] = 999
    assert storage.get(Namespace.CACHE, "k")["nested"]["x"] == 1