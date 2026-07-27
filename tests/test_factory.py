"""Storage 工厂测试（T13 [A9]）

覆盖：
- 默认返回 LocalJSONStorage
- 环境变量切换类型
- 单例复用
- reset / configure 行为
- 错误输入处理
"""
import pytest

from ai_pr_review.data.persistence import (
    DEFAULT_TYPE,
    ENV_VAR,
    STORAGE_LOCAL,
    STORAGE_SQLITE,
    LocalJSONStorage,
    SQLiteStorage,
    configure_storage,
    current_storage_type,
    get_storage,
    reset_storage,
)
from ai_pr_review.data.persistence.factory import VALID_TYPES


def test_default_storage_type_is_local(monkeypatch):
    """无环境变量时默认返回 LocalJSONStorage"""
    monkeypatch.delenv(ENV_VAR, raising=False)
    reset_storage()
    s = get_storage()
    assert isinstance(s, LocalJSONStorage)
    assert current_storage_type() == "LocalJSONStorage"


def test_env_var_local_returns_local_json(monkeypatch):
    monkeypatch.setenv(ENV_VAR, STORAGE_LOCAL)
    reset_storage()
    s = get_storage()
    assert isinstance(s, LocalJSONStorage)


def test_env_var_sqlite_returns_sqlite(monkeypatch, tmp_path):
    monkeypatch.setenv(ENV_VAR, STORAGE_SQLITE)
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv("USERPROFILE", str(tmp_path))
    reset_storage()  # 清除 conftest 默认注入的 storage
    s = get_storage()
    assert isinstance(s, SQLiteStorage)


def test_invalid_env_value_raises_value_error(monkeypatch):
    monkeypatch.setenv(ENV_VAR, "redis")
    reset_storage()
    with pytest.raises(ValueError, match="Unknown storage type"):
        get_storage()


def test_singleton_returns_same_instance(monkeypatch):
    monkeypatch.delenv(ENV_VAR, raising=False)
    reset_storage()
    s1 = get_storage()
    s2 = get_storage()
    assert s1 is s2


def test_reset_storage_clears_singleton(monkeypatch):
    monkeypatch.delenv(ENV_VAR, raising=False)
    reset_storage()
    s1 = get_storage()
    reset_storage()
    assert current_storage_type() is None
    s2 = get_storage()
    assert s1 is not s2  # 重建后是新实例


def test_configure_storage_overrides_default(monkeypatch):
    monkeypatch.delenv(ENV_VAR, raising=False)
    reset_storage()
    custom = LocalJSONStorage(base_dir="/tmp/custom-isolated")
    configure_storage(custom)
    s = get_storage()
    assert s is custom


def test_configure_storage_resets_on_reset(monkeypatch):
    """configure 后 reset，下次 get_storage 走默认逻辑"""
    monkeypatch.delenv(ENV_VAR, raising=False)
    reset_storage()
    configure_storage(LocalJSONStorage(base_dir="/tmp/custom-isolated"))
    reset_storage()
    s = get_storage()
    assert not isinstance(s, LocalJSONStorage) or s._base_dir != __import__("pathlib").Path("/tmp/custom-isolated")


def test_valid_types_constant_is_correct():
    assert VALID_TYPES == ("local", "sqlite")


def test_default_type_is_local():
    assert DEFAULT_TYPE == STORAGE_LOCAL


def test_env_var_name_is_stable():
    """env var 名作为稳定 API 暴露给用户文档，不应随意改名"""
    assert ENV_VAR == "AI_PR_REVIEW_STORAGE"


def test_storage_local_and_sqlite_constants_are_strings():
    assert STORAGE_LOCAL == "local"
    assert STORAGE_SQLITE == "sqlite"


def test_current_storage_type_before_init_is_none():
    """未调用 get_storage 前，类型为 None"""
    reset_storage()
    assert current_storage_type() is None