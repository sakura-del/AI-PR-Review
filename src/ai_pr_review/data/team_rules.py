"""团队规范学习规则存储 — 基于 Storage 接口

v0.9 重构：
- 数据持久化从单文件迁移到 Storage 抽象
- 自动迁移旧 ~/.ai-pr-review/team_rules/*.json（一次性，旧文件保留作回滚备份）
- TTL 机制不变（基于 learned_at 时间戳）

注：TEAM_RULES_DIR 常量保留为旧路径（仅迁移代码使用），不再作为运行时路径。
"""
import json
import logging
from dataclasses import asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from ai_pr_review.platforms.github_client import parse_pr_url
from ai_pr_review.data.persistence.factory import get_storage
from ai_pr_review.data.storage import Namespace
from ai_pr_review.core.team_learner import TeamRule, TeamPattern

logger = logging.getLogger(__name__)

# 旧格式目录（仅用于一次性向后兼容迁移）
_OLD_TEAM_RULES_DIR = Path.home() / ".ai-pr-review" / "team_rules"
# 兼容保留的模块级常量（导出供外部 import；新代码不应直接使用）
TEAM_RULES_DIR = _OLD_TEAM_RULES_DIR


def _repo_key(repo_url: str) -> str:
    """生成 repo 的 storage key（owner_repo 形式）"""
    try:
        owner, repo_name, _ = parse_pr_url(repo_url)
        return f"{owner}_{repo_name}"
    except ValueError:
        return repo_url.replace("/", "_").replace(":", "_")


def _pattern_to_dict(pattern: TeamPattern) -> dict:
    """TeamPattern → dict（rules 转为 dict 列表）"""
    data = asdict(pattern)
    # asdict 不会递归转换 dataclass，需要手动处理 rules 字段
    data["rules"] = [asdict(r) if isinstance(r, TeamRule) else r for r in pattern.rules]
    return data


def _dict_to_pattern(data: dict) -> TeamPattern:
    """dict → TeamPattern"""
    rules = [
        TeamRule(
            category=r.get("category", "custom"),
            description=r.get("description", ""),
            example=r.get("example", ""),
            weight=r.get("weight", 1.0),
            source=r.get("source", ""),
            frequency=r.get("frequency", 1),
        )
        for r in data.get("rules", [])
    ]
    return TeamPattern(
        rules=rules,
        common_terms=data.get("common_terms", []),
        severity_preference=data.get("severity_preference", {}),
        focus_areas=data.get("focus_areas", []),
        repo_url=data.get("repo_url", ""),
        learned_at=data.get("learned_at", ""),
    )


def _maybe_migrate_from_old(storage) -> None:
    """一次性迁移：从旧 team_rules 目录扫描所有 .json 并写入 Storage"""
    if storage.count(Namespace.TEAM_RULES) > 0:
        return
    if not _OLD_TEAM_RULES_DIR.exists():
        return

    migrated = 0
    for path in _OLD_TEAM_RULES_DIR.glob("*.json"):
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError) as e:
            logger.warning(f"Failed to read old team_rules file {path}: {e}")
            continue
        key = path.stem
        try:
            storage.save(Namespace.TEAM_RULES, key, data)
            migrated += 1
        except Exception as e:
            logger.warning(f"Failed to migrate team pattern {key}: {e}")
    if migrated:
        logger.info(f"Migrated {migrated} team patterns to Storage (old files retained)")


def save_team_pattern(pattern: TeamPattern) -> None:
    """保存团队学习模式到 Storage"""
    storage = get_storage()
    if not pattern.learned_at:
        pattern.learned_at = datetime.now(timezone.utc).isoformat()
    data = _pattern_to_dict(pattern)
    storage.save(Namespace.TEAM_RULES, _repo_key(pattern.repo_url), data)
    logger.info(f"Saved team pattern for {pattern.repo_url}")


def load_team_pattern(repo_url: str, ttl_days: int = 0) -> TeamPattern | None:
    """加载团队学习模式，可选 TTL 检查"""
    storage = get_storage()
    _maybe_migrate_from_old(storage)

    data = storage.get(Namespace.TEAM_RULES, _repo_key(repo_url))
    if data is None:
        return None

    if ttl_days > 0 and data.get("learned_at"):
        try:
            learned = datetime.fromisoformat(data["learned_at"])
            age = (datetime.now(timezone.utc) - learned).days
            if age > ttl_days:
                logger.info(f"Team pattern expired (age={age}d, ttl={ttl_days}d)")
                return None
        except (ValueError, TypeError):
            pass

    return _dict_to_pattern(data)


def merge_team_rules(
    team_pattern: TeamPattern | None,
    manual_rules: list[str],
) -> list[TeamRule]:
    """合并团队学习规则与项目手动规则（不变）"""
    merged = []

    if team_pattern:
        for rule in team_pattern.rules:
            merged.append(rule)

    for rule_text in manual_rules:
        merged.append(TeamRule(
            category="custom",
            description=rule_text,
            example="",
            weight=1.5,
            source="manual",
        ))

    merged.sort(key=lambda r: r.weight, reverse=True)
    return merged