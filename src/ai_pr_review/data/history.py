"""分析历史记录 — 基于 Storage 接口的持久化

v0.9 重构：
- 数据持久化从 JSONL 文件迁移到 Storage 抽象（默认 LocalJSONStorage）
- 自动迁移旧 ~/.ai-pr-review/history/history.json（一次性，旧文件保留作回滚备份）
- MAX_RECORDS=100 限制保留（save 时主动清理超出条目）

注：HISTORY_DIR 常量保留为旧路径（仅迁移代码使用），不再作为运行时路径。
"""
import hashlib
import json
import logging
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path

from ai_pr_review.data.persistence.factory import get_storage
from ai_pr_review.data.storage import Namespace

logger = logging.getLogger(__name__)

MAX_RECORDS = 100

# 旧格式文件路径（仅用于一次性向后兼容迁移，不再作为运行时路径）
_OLD_HISTORY_FILE = Path.home() / ".ai-pr-review" / "history" / "history.json"
# 兼容保留的模块级常量（导出供外部 import；新代码不应直接使用）
HISTORY_DIR = _OLD_HISTORY_FILE.parent


@dataclass
class AnalysisRecord:
    pr_url: str
    pr_title: str
    timestamp: str = ""
    findings_count: int = 0
    high_severity_count: int = 0
    medium_severity_count: int = 0
    low_severity_count: int = 0
    suggestions_count: int = 0
    model: str = ""
    duration_seconds: float = 0.0
    head_sha: str = ""
    base_sha: str = ""
    is_incremental: bool = False
    # v0.10 多用户隔离：每个用户独立 history（CLI 场景可为空字符串 = 单用户模式）
    user_id: str = ""

    def __post_init__(self):
        if not self.timestamp:
            self.timestamp = datetime.now(timezone.utc).isoformat()


def _record_key(record: AnalysisRecord) -> str:
    """生成 Storage key：{ISO timestamp}__{user_id}__{url_hash}

    ISO 8601 UTC 时间戳字典序 == 时间顺序（前提：所有 timestamp 都是 UTC）。
    url_hash 防止同毫秒内同 PR 多次保存覆盖。
    user_id 用于多用户隔离（CLI 单用户时为空字符串）。
    """
    url_hash = hashlib.sha1(record.pr_url.encode()).hexdigest()[:8]
    # 双下划线分隔：时间戳、user_id、url_hash
    return f"{record.timestamp}__{record.user_id}__{url_hash}"


def _maybe_migrate_from_old(storage) -> None:
    """一次性迁移：从旧 JSON 文件读取并写入 Storage

    触发条件：
    - Storage 中 history namespace 为空
    - 旧文件存在

    旧文件不删除（保留作为回滚备份，下个版本再清理）。
    """
    if storage.count(Namespace.HISTORY) > 0:
        return
    if not _OLD_HISTORY_FILE.exists():
        return
    try:
        old_data = json.loads(_OLD_HISTORY_FILE.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError) as e:
        logger.warning(f"Failed to read old history file: {e}")
        return
    if not isinstance(old_data, list):
        logger.warning(f"Old history file is not a list, skipping migration")
        return

    known_fields = {f.name for f in AnalysisRecord.__dataclass_fields__.values()}
    migrated = 0
    for item in old_data:
        try:
            filtered = {k: v for k, v in item.items() if k in known_fields}
            record = AnalysisRecord(**filtered)
            storage.save(Namespace.HISTORY, _record_key(record), asdict(record))
            migrated += 1
        except Exception as e:
            logger.warning(f"Failed to migrate history record: {e}")
    if migrated:
        logger.info(f"Migrated {migrated} history records to Storage (old file retained)")


def save_record(record: AnalysisRecord) -> None:
    """保存分析记录

    行为：
    - 写入 Storage
    - 若用户总数 > MAX_RECORDS，删除该用户最旧的超出条目
    """
    storage = get_storage()
    key = _record_key(record)
    storage.save(Namespace.HISTORY, key, asdict(record))

    _enforce_max_records_for_user(storage, record.user_id)


def load_records() -> list[AnalysisRecord]:
    """加载所有历史记录（按 timestamp 倒序，跨用户）

    首次调用时触发一次性迁移（从旧 JSON 文件读取）。
    """
    storage = get_storage()
    _maybe_migrate_from_old(storage)

    items = storage.list_values(Namespace.HISTORY)
    records = [_parse_record(item) for item in items]
    records.sort(key=lambda r: r.timestamp, reverse=True)
    return records


def load_records_for_user(user_id: str) -> list[AnalysisRecord]:
    """加载指定用户的历史记录（按 timestamp 倒序）

    多用户隔离：每个用户只看自己的 history。
    CLI 单用户模式：传空字符串返回所有记录。
    """
    if not user_id:
        return load_records()

    storage = get_storage()
    _maybe_migrate_from_old(storage)

    all_items = storage.list_values(Namespace.HISTORY)
    records = [_parse_record(item) for item in all_items if item.get("user_id") == user_id]
    records.sort(key=lambda r: r.timestamp, reverse=True)
    return records


def _enforce_max_records_for_user(storage, user_id: str) -> None:
    """删除超出 MAX_RECORDS 的最旧记录（按 user 隔离）"""
    if user_id:
        # 仅清理该用户的记录（通过 key 前缀匹配）
        user_prefix = f"__"  # 实际通过 list_values 过滤
        all_items = storage.list_values(Namespace.HISTORY)
        user_items = [it for it in all_items if it.get("user_id") == user_id]
        if len(user_items) > MAX_RECORDS:
            # 按 timestamp 排序，删最旧的
            user_items.sort(key=lambda it: it.get("timestamp", ""))
            excess = len(user_items) - MAX_RECORDS
            for item in user_items[:excess]:
                # 通过 timestamp+user_id+url_hash 还原 key
                ts = item.get("timestamp", "")
                url_hash = hashlib.sha1(item.get("pr_url", "").encode()).hexdigest()[:8]
                key = f"{ts}__{user_id}__{url_hash}"
                storage.delete(Namespace.HISTORY, key)
    else:
        # CLI 单用户：清理所有记录
        keys = storage.list_keys(Namespace.HISTORY)
        if len(keys) > MAX_RECORDS:
            keys.sort()
            for old_key in keys[: len(keys) - MAX_RECORDS]:
                storage.delete(Namespace.HISTORY, old_key)


def _parse_record(item: dict) -> AnalysisRecord:
    known_fields = {f.name for f in AnalysisRecord.__dataclass_fields__.values()}
    filtered = {k: v for k, v in item.items() if k in known_fields}
    return AnalysisRecord(**filtered)


def find_last_record(pr_url: str) -> AnalysisRecord | None:
    """查找指定 PR 的最近一次审查记录"""
    records = load_records()
    for r in records:
        if r.pr_url == pr_url and r.head_sha:
            return r
    return None


def format_history_table(records: list[AnalysisRecord], limit: int = 20) -> str:
    from rich.table import Table
    from rich.console import Console

    console = Console()
    table = Table(title=f"📜 AI PR Review History (showing {min(limit, len(records))} of {len(records)})")
    table.add_column("Time", style="dim", width=20)
    table.add_column("PR", style="cyan")
    table.add_column("Findings", justify="right")
    table.add_column("🔴 H", justify="right")
    table.add_column("🟡 M", justify="right")
    table.add_column("🟢 L", justify="right")
    table.add_column("💡 Sugg", justify="right")

    for r in records[:limit]:
        time_str = r.timestamp[:19].replace("T", " ")
        pr_short = r.pr_title[:40] + ("..." if len(r.pr_title) > 40 else "")
        table.add_row(
            time_str,
            pr_short,
            str(r.findings_count),
            str(r.high_severity_count),
            str(r.medium_severity_count),
            str(r.low_severity_count),
            str(r.suggestions_count),
        )

    console.print(table)
    return ""