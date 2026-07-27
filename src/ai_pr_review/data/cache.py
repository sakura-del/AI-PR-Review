"""分析结果缓存 — 基于 Storage 接口

v0.9 重构：
- 数据持久化从独立文件迁移到 Storage 抽象
- 自动迁移旧 ~/.ai-pr-review/cache/*.json（一次性，旧文件保留作回滚备份）
- TTL 机制不变（基于 cached_at 时间戳）

注：CACHE_DIR 常量保留为旧路径（仅迁移代码使用），不再作为运行时路径。
"""
import hashlib
import logging
import time
from typing import Optional

from ai_pr_review.core.models import AnalysisResult, AnalysisSummary, Finding, Suggestion, Severity
from ai_pr_review.data.persistence.factory import get_storage
from ai_pr_review.data.storage import Namespace

logger = logging.getLogger(__name__)

DEFAULT_TTL_SECONDS = 86400  # 24小时

# 旧格式目录（仅用于一次性向后兼容迁移）
_OLD_CACHE_DIR = Path = __import__("pathlib").Path.home() / ".ai-pr-review" / "cache"
# 兼容保留的模块级常量（导出供外部 import；新代码不应直接使用）
CACHE_DIR = _OLD_CACHE_DIR


def _cache_key(pr_url: str, head_sha: str) -> str:
    """生成缓存键的哈希值（pr_url + head_sha 的 sha256 截断）"""
    raw = f"{pr_url}@{head_sha}"
    return hashlib.sha256(raw.encode()).hexdigest()[:16]


def _serialize_result(pr_url: str, head_sha: str, result: AnalysisResult) -> dict:
    """将 AnalysisResult 序列化为 JSON 可存储的字典"""
    return {
        "pr_url": pr_url,
        "head_sha": head_sha,
        "summary": {
            "intent": result.summary.intent,
            "scope": result.summary.scope,
            "key_changes": result.summary.key_changes,
        },
        "findings": [
            {
                "type": f.type, "severity": f.severity.value, "confidence": f.confidence,
                "expert": f.expert, "file": f.file, "line": f.line,
                "title": f.title, "description": f.description,
                "suggestion": f.suggestion, "code_snippet": f.code_snippet,
            }
            for f in result.findings
        ],
        "suggestions": [
            {
                "category": s.category, "priority": s.priority.value,
                "description": s.description, "example": s.example,
            }
            for s in result.suggestions
        ],
        "cached_at": time.time(),
    }


def _deserialize_result(data: dict) -> AnalysisResult:
    """从字典反序列化为 AnalysisResult"""
    summary = AnalysisSummary(
        intent=data["summary"]["intent"],
        scope=data["summary"]["scope"],
        key_changes=data["summary"]["key_changes"],
    )
    findings = [
        Finding(
            type=f["type"], severity=Severity(f["severity"]), confidence=f["confidence"],
            expert=f["expert"], file=f["file"], line=f["line"],
            title=f["title"], description=f["description"],
            suggestion=f["suggestion"], code_snippet=f["code_snippet"],
        )
        for f in data["findings"]
    ]
    suggestions = [
        Suggestion(
            category=s["category"], priority=Severity(s["priority"]),
            description=s["description"], example=s["example"],
        )
        for s in data["suggestions"]
    ]
    return AnalysisResult(summary=summary, findings=findings, suggestions=suggestions)


def _maybe_migrate_from_old(storage) -> None:
    """一次性迁移：从旧 cache 目录扫描所有 .json 文件并写入 Storage"""
    if storage.count(Namespace.CACHE) > 0:
        return
    if not _OLD_CACHE_DIR.exists():
        return

    migrated = 0
    for path in _OLD_CACHE_DIR.glob("*.json"):
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError) as e:
            logger.warning(f"Failed to read old cache file {path}: {e}")
            continue
        key = path.stem  # 文件名去掉 .json 即缓存键
        try:
            storage.save(Namespace.CACHE, key, data)
            migrated += 1
        except Exception as e:
            logger.warning(f"Failed to migrate cache {key}: {e}")
    if migrated:
        logger.info(f"Migrated {migrated} cache entries to Storage (old files retained)")


def get_cached_result(
    pr_url: str, head_sha: str, ttl_seconds: int = DEFAULT_TTL_SECONDS
) -> AnalysisResult | None:
    """获取缓存的分析结果，不存在或已过期返回 None"""
    if not head_sha:
        return None
    storage = get_storage()
    _maybe_migrate_from_old(storage)

    key = _cache_key(pr_url, head_sha)
    data = storage.get(Namespace.CACHE, key)
    if data is None:
        return None

    cached_at = data.get("cached_at", 0)
    if time.time() - cached_at > ttl_seconds:
        logger.info(f"Cache expired for {pr_url}@{head_sha[:7]}")
        return None
    try:
        return _deserialize_result(data)
    except (KeyError, ValueError) as e:
        logger.warning(f"Failed to deserialize cache {pr_url}@{head_sha[:7]}: {e}")
        return None


def save_cached_result(pr_url: str, head_sha: str, result: AnalysisResult) -> None:
    """保存分析结果到缓存"""
    if not head_sha:
        return
    storage = get_storage()
    _maybe_migrate_from_old(storage)

    key = _cache_key(pr_url, head_sha)
    data = _serialize_result(pr_url, head_sha, result)
    storage.save(Namespace.CACHE, key, data)
    logger.info(f"Cached result for {pr_url}@{head_sha[:7]}")


def clear_cache(pr_url: Optional[str] = None) -> int:
    """清除缓存，返回清除的条目数

    - pr_url 为 None：清除全部缓存
    - pr_url 指定：仅清除该 PR 关联的缓存条目
    """
    storage = get_storage()
    _maybe_migrate_from_old(storage)

    keys = storage.list_keys(Namespace.CACHE)
    count = 0
    for key in keys:
        data = storage.get(Namespace.CACHE, key)
        if data is None:
            continue
        if pr_url is None or data.get("pr_url") == pr_url:
            storage.delete(Namespace.CACHE, key)
            count += 1
    return count


# 延迟导入 json（仅迁移用）
import json  # noqa: E402