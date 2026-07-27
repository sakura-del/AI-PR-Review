"""LocalJSONStorage — 基于本地 JSON 文件的 Storage 默认实现

布局：
  {base_dir}/{namespace}.json
  内容格式：{"key1": {...}, "key2": {...}, ...}

适用场景：
- 默认实现（CLI 本地使用）
- 单用户、单进程
- 条目数 < 10k 的轻量场景

写入策略：
- 原子写入：先写临时文件，再 os.replace 重命名，避免崩溃时残留半截文件
- 每次 save/delete 全量重写命名空间文件（适合条目数小的场景）

线程/进程安全：
- 单进程安全：单线程串行调用
- 跨进程不安全：多进程同时写同一 namespace 可能丢失更新（v0.9 不要求）
"""
import copy
import json
import logging
import os
import tempfile
from pathlib import Path
from typing import Optional

from ai_pr_review.data.storage import Storage

logger = logging.getLogger(__name__)

DEFAULT_BASE_DIR = Path.home() / ".ai-pr-review" / "storage"


class LocalJSONStorage(Storage):
    """JSON 文件版 Storage 实现

    每个 namespace 一个 JSON 文件，结构为 {key: value, ...}。
    读取时全量加载到内存，写入时全量重写（依赖原子 rename 保证一致性）。
    """

    def __init__(self, base_dir: Path | str = DEFAULT_BASE_DIR) -> None:
        self._base_dir = Path(base_dir)
        self._base_dir.mkdir(parents=True, exist_ok=True)

    def _file_for(self, namespace: str) -> Path:
        return self._base_dir / f"{namespace}.json"

    def _load(self, namespace: str) -> dict[str, dict]:
        """加载整个 namespace 文件；不存在或损坏返回空 dict"""
        path = self._file_for(namespace)
        if not path.exists():
            return {}
        try:
            with path.open("r", encoding="utf-8") as f:
                data = json.load(f)
            if not isinstance(data, dict):
                logger.warning(f"{path} is not a dict object, treating as empty")
                return {}
            return data
        except (json.JSONDecodeError, OSError) as e:
            logger.warning(f"Failed to load {path}: {e}")
            return {}

    def _dump(self, namespace: str, data: dict[str, dict]) -> None:
        """原子写入：先写临时文件，再 rename"""
        path = self._file_for(namespace)
        fd, tmp_path = tempfile.mkstemp(
            dir=self._base_dir,
            prefix=f".{namespace}.",
            suffix=".json.tmp",
        )
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
            os.replace(tmp_path, path)
        except Exception:
            # 清理临时文件，避免堆积
            try:
                os.unlink(tmp_path)
            except OSError:
                pass
            raise

    def get(self, namespace: str, key: str) -> Optional[dict]:
        """读取单个值（深拷贝语义）"""
        data = self._load(namespace)
        value = data.get(key)
        if value is None:
            return None
        return copy.deepcopy(value)

    def save(self, namespace: str, key: str, value: dict) -> None:
        """写入/覆盖单个值（深拷贝语义：调用方后续修改不影响存储）"""
        data = self._load(namespace)
        data[key] = copy.deepcopy(value)
        self._dump(namespace, data)

    def delete(self, namespace: str, key: str) -> None:
        """删除单个值（幂等：不存在不抛异常）"""
        data = self._load(namespace)
        if key not in data:
            return
        del data[key]
        # namespace 变空也要保留文件（避免 list_keys 误判）
        # 但若用户希望清空整个 namespace，可手动 unlink
        self._dump(namespace, data)

    def list_keys(self, namespace: str, prefix: str = "") -> list[str]:
        """列出 namespace 内所有 key（带前缀过滤）"""
        data = self._load(namespace)
        return [k for k in data if k.startswith(prefix)]

    def list_values(self, namespace: str, prefix: str = "") -> list[dict]:
        """单次加载 + 深拷贝，避免 list_keys + get 的两次深拷贝开销"""
        data = self._load(namespace)
        return [copy.deepcopy(v) for k, v in data.items() if k.startswith(prefix)]