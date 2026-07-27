"""存储抽象层 — 持久化接口定义

设计目标：
- 抽象 Key-Value 存储，让 history / cache / team_rules 等模块与具体实现解耦
- 默认实现仍为本地 JSON（向后兼容），v0.10 Web 化阶段加 SQLite 实现
- 命名空间隔离：history / cache / team_rules 各自独立 key 空间
- Schema 版本支持：未来数据迁移可按版本分支处理

核心抽象：
- Storage：增删改查 + 列表接口
- Namespace：预定义命名空间常量
- CURRENT_SCHEMA_VERSION：当前数据格式版本
"""
import logging
from abc import ABC, abstractmethod
from typing import Optional

logger = logging.getLogger(__name__)


class Namespace:
    """预定义的命名空间常量

    避免散落字符串导致的拼写错误，统一管理 key 空间划分。
    新增命名空间时请在此追加，并在 CHANGELOG 中记录。
    """
    HISTORY = "history"
    CACHE = "cache"
    TEAM_RULES = "team_rules"
    # 未来 v0.10 Web 化新增：USER, REPO, REVIEW, JOB


CURRENT_SCHEMA_VERSION = 1


class Storage(ABC):
    """键值存储抽象基类

    所有方法均为同步，调用方负责异步包装（如需）。
    值以 dict 形式存储，调用方负责序列化/反序列化。

    实现要求（契约）：
    - save() 写入的 dict 在 get() 时原样返回（深拷贝语义，避免引用别名）
    - list_keys() 返回的 key 列表顺序不保证（实现可选择字典序或插入序）
    - delete() 对不存在的 key 不抛异常（幂等）
    - 不同 namespace 之间完全隔离
    """

    @abstractmethod
    def get(self, namespace: str, key: str) -> Optional[dict]:
        """读取单个值

        Args:
            namespace: 命名空间（如 Namespace.HISTORY）
            key: 命名空间内的键

        Returns:
            存储的 dict，不存在或已过期返回 None
        """

    @abstractmethod
    def save(self, namespace: str, key: str, value: dict) -> None:
        """写入/覆盖单个值

        Args:
            namespace: 命名空间
            key: 命名空间内的键
            value: 要存储的 dict（必须可 JSON 序列化）
        """

    @abstractmethod
    def delete(self, namespace: str, key: str) -> None:
        """删除单个值

        对不存在的 key 不抛异常（幂等）。
        """

    @abstractmethod
    def list_keys(self, namespace: str, prefix: str = "") -> list[str]:
        """列出命名空间内的所有 key

        Args:
            namespace: 命名空间
            prefix: 可选 key 前缀过滤

        Returns:
            key 列表（顺序不保证）
        """

    def list_values(self, namespace: str, prefix: str = "") -> list[dict]:
        """列出命名空间内的所有值（便捷方法）

        默认实现遍历 list_keys + get；子类可重写以提升性能（如 SQLite 用 SELECT）。
        """
        values = []
        for key in self.list_keys(namespace, prefix):
            value = self.get(namespace, key)
            if value is not None:
                values.append(value)
        return values

    def exists(self, namespace: str, key: str) -> bool:
        """判断 key 是否存在"""
        return self.get(namespace, key) is not None

    def count(self, namespace: str) -> int:
        """统计命名空间内的条目数"""
        return len(self.list_keys(namespace))