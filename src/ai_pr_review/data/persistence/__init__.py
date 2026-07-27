"""持久化层 — Storage 抽象的具体实现集合

模块：
- local_json: 基于 JSON 文件的默认实现（CLI 本地使用）
- sqlite: 基于 sqlite3 的实现（Web 化/多进程场景）
- factory: get_storage() 单例工厂（业务代码统一入口）

外部推荐用法：
    from ai_pr_review.data.persistence import get_storage
    storage = get_storage()
    storage.save(namespace, key, value)
"""
from ai_pr_review.data.persistence.factory import (
    DEFAULT_TYPE,
    ENV_VAR,
    STORAGE_LOCAL,
    STORAGE_SQLITE,
    VALID_TYPES,
    configure_storage,
    current_storage_type,
    get_storage,
    reset_storage,
)
from ai_pr_review.data.persistence.local_json import DEFAULT_BASE_DIR, LocalJSONStorage
from ai_pr_review.data.persistence.sqlite import DEFAULT_DB_PATH, SQLiteStorage
from ai_pr_review.data.storage import CURRENT_SCHEMA_VERSION, Namespace, Storage

__all__ = [
    # ABC
    "Storage",
    "Namespace",
    "CURRENT_SCHEMA_VERSION",
    # 实现
    "LocalJSONStorage",
    "SQLiteStorage",
    "DEFAULT_BASE_DIR",
    "DEFAULT_DB_PATH",
    # 工厂
    "get_storage",
    "configure_storage",
    "reset_storage",
    "current_storage_type",
    "STORAGE_LOCAL",
    "STORAGE_SQLITE",
    "VALID_TYPES",
    "DEFAULT_TYPE",
    "ENV_VAR",
]