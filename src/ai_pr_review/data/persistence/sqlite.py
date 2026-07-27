"""SQLiteStorage — 基于 stdlib sqlite3 的 Storage 实现

适用场景：
- v0.10 Web 化阶段的多用户/多进程部署
- 条目数较多、需要索引查询（>10k）
- 跨进程共享同一份数据

技术选型理由：
- 零额外依赖：stdlib sqlite3 自 Python 2.5 起
- 单文件部署：单个 .db 文件随项目分发/迁移
- 成熟的并发模型：WAL 模式下多读单写不互斥

Schema：
    kv(namespace TEXT, key TEXT, value TEXT, created_at TEXT, updated_at TEXT)
    PRIMARY KEY (namespace, key)
    INDEX idx_kv_namespace ON kv(namespace)

约束与限制：
- v0.9 同步 API；如需 async 用 run_in_executor 包装
- 每次操作新建连接（低开销：sqlite3.connect 单进程下 < 1ms）
- 写操作加进程级锁（threading.Lock）防止短时间内的覆盖竞态
- 读操作不加锁：依赖 SQLite 自身的 MVCC
"""
import copy
import json
import logging
import sqlite3
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from ai_pr_review.data.storage import Storage

logger = logging.getLogger(__name__)

DEFAULT_DB_PATH = Path.home() / ".ai-pr-review" / "storage.db"


def _now() -> str:
    """UTC ISO 时间戳"""
    return datetime.now(timezone.utc).isoformat()


class SQLiteStorage(Storage):
    """sqlite3 版 Storage 实现"""

    _SCHEMA = """
    CREATE TABLE IF NOT EXISTS kv (
        namespace TEXT NOT NULL,
        key TEXT NOT NULL,
        value TEXT NOT NULL,
        created_at TEXT NOT NULL,
        updated_at TEXT NOT NULL,
        PRIMARY KEY (namespace, key)
    );
    CREATE INDEX IF NOT EXISTS idx_kv_namespace ON kv(namespace);
    """

    def __init__(self, db_path: Path | str = DEFAULT_DB_PATH) -> None:
        self._db_path = Path(db_path)
        self._db_path.parent.mkdir(parents=True, exist_ok=True)
        self._write_lock = threading.Lock()
        self._init_schema()

    def _connect(self) -> sqlite3.Connection:
        """新建连接：check_same_thread=False 允许跨线程使用"""
        conn = sqlite3.connect(
            str(self._db_path),
            check_same_thread=False,
            timeout=10.0,
            isolation_level=None,  # autocommit 模式，手动控制事务
        )
        conn.row_factory = sqlite3.Row
        return conn

    def _init_schema(self) -> None:
        """初始化表结构（幂等）"""
        with self._write_lock:
            conn = self._connect()
            try:
                conn.executescript(self._SCHEMA)
            finally:
                conn.close()

    def get(self, namespace: str, key: str) -> Optional[dict]:
        conn = self._connect()
        try:
            row = conn.execute(
                "SELECT value FROM kv WHERE namespace = ? AND key = ?",
                (namespace, key),
            ).fetchone()
            if row is None:
                return None
            return copy.deepcopy(json.loads(row["value"]))
        finally:
            conn.close()

    def save(self, namespace: str, key: str, value: dict) -> None:
        """INSERT OR REPLACE 语义：已存在则覆盖并更新 updated_at"""
        payload = json.dumps(copy.deepcopy(value), ensure_ascii=False)
        now = _now()
        with self._write_lock:
            conn = self._connect()
            try:
                conn.execute(
                    """
                    INSERT INTO kv (namespace, key, value, created_at, updated_at)
                    VALUES (?, ?, ?, ?, ?)
                    ON CONFLICT (namespace, key) DO UPDATE SET
                        value = excluded.value,
                        updated_at = excluded.updated_at
                    """,
                    (namespace, key, payload, now, now),
                )
            finally:
                conn.close()

    def delete(self, namespace: str, key: str) -> None:
        """DELETE 语义：不存在不抛异常（SQL DELETE 本身幂等）"""
        with self._write_lock:
            conn = self._connect()
            try:
                conn.execute(
                    "DELETE FROM kv WHERE namespace = ? AND key = ?",
                    (namespace, key),
                )
            finally:
                conn.close()

    def list_keys(self, namespace: str, prefix: str = "") -> list[str]:
        conn = self._connect()
        try:
            if prefix:
                # LIKE 'prefix%' 可使用 namespace 索引
                rows = conn.execute(
                    "SELECT key FROM kv WHERE namespace = ? AND key LIKE ?",
                    (namespace, prefix + "%"),
                ).fetchall()
            else:
                rows = conn.execute(
                    "SELECT key FROM kv WHERE namespace = ?",
                    (namespace,),
                ).fetchall()
            return [r["key"] for r in rows]
        finally:
            conn.close()

    def list_values(self, namespace: str, prefix: str = "") -> list[dict]:
        conn = self._connect()
        try:
            if prefix:
                rows = conn.execute(
                    "SELECT value FROM kv WHERE namespace = ? AND key LIKE ?",
                    (namespace, prefix + "%"),
                ).fetchall()
            else:
                rows = conn.execute(
                    "SELECT value FROM kv WHERE namespace = ?",
                    (namespace,),
                ).fetchall()
            return [copy.deepcopy(json.loads(r["value"])) for r in rows]
        finally:
            conn.close()