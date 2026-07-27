"""Storage 工厂 — 集中创建与缓存 Storage 实例

设计目标：
- 单一入口：业务代码只调 get_storage()，不直接 import LocalJSONStorage/SQLiteStorage
- 环境变量切换：AI_PR_REVIEW_STORAGE=local|sqlite
- 单例缓存：避免每次调用都新建实例（特别是 SQLite 连接初始化有开销）
- 默认 local：保持 v0.8.x 行为完全兼容
- 支持测试注入：configure_storage() 可强制设置实例
"""
import logging
import os
import threading
from typing import Optional

from ai_pr_review.data.persistence.local_json import LocalJSONStorage
from ai_pr_review.data.persistence.sqlite import SQLiteStorage
from ai_pr_review.data.storage import Storage

logger = logging.getLogger(__name__)

# 预定义存储类型常量
STORAGE_LOCAL = "local"
STORAGE_SQLITE = "sqlite"
VALID_TYPES = (STORAGE_LOCAL, STORAGE_SQLITE)

DEFAULT_TYPE = STORAGE_LOCAL

ENV_VAR = "AI_PR_REVIEW_STORAGE"

_storage: Optional[Storage] = None
_lock = threading.Lock()


def get_storage() -> Storage:
    """获取 Storage 单例

    首次调用时根据环境变量 AI_PR_REVIEW_STORAGE 决定类型：
        - "local"（默认）：~/.ai-pr-review/storage/ 下的 JSON 文件
        - "sqlite"：~/.ai-pr-review/storage.db

    返回单例；后续调用复用同一实例。

    Raises:
        ValueError: 环境变量值未知
    """
    global _storage
    with _lock:
        if _storage is not None:
            return _storage

        storage_type = os.environ.get(ENV_VAR, DEFAULT_TYPE).lower()
        if storage_type not in VALID_TYPES:
            raise ValueError(
                f"Unknown storage type from {ENV_VAR}: {storage_type!r}. "
                f"Use one of {VALID_TYPES}."
            )

        if storage_type == STORAGE_LOCAL:
            _storage = LocalJSONStorage()
        else:  # STORAGE_SQLITE
            _storage = SQLiteStorage()

        logger.debug(f"Initialized {storage_type} storage singleton")
        return _storage


def configure_storage(storage: Storage) -> None:
    """显式注入 Storage 实例（覆盖默认工厂逻辑）

    主要用于：
    - 测试时注入临时 Storage（tmp_path 隔离）
    - Web 化时让 DI 容器控制生命周期
    """
    global _storage
    with _lock:
        _storage = storage


def reset_storage() -> None:
    """重置单例（仅测试与进程关闭时使用）

    生产代码不应调用；CLI 退出时无需重置（进程自然终止）。
    """
    global _storage
    with _lock:
        _storage = None


def current_storage_type() -> Optional[str]:
    """返回当前 Storage 的实际类型（用于诊断与日志）

    None 表示单例尚未初始化。
    """
    if _storage is None:
        return None
    return type(_storage).__name__