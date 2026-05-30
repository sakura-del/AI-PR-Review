import json
import logging
from datetime import datetime, timezone
from pathlib import Path
from dataclasses import asdict

from ai_pr_review.team_learner import TeamRule, TeamPattern
from ai_pr_review.github_client import parse_pr_url

logger = logging.getLogger(__name__)

TEAM_RULES_DIR = Path.home() / ".ai-pr-review" / "team_rules"


def _repo_key(repo_url: str) -> str:
    try:
        owner, repo_name, _ = parse_pr_url(repo_url)
        return f"{owner}_{repo_name}"
    except ValueError:
        return repo_url.replace("/", "_").replace(":", "_")


def _pattern_file(repo_url: str) -> Path:
    TEAM_RULES_DIR.mkdir(parents=True, exist_ok=True)
    return TEAM_RULES_DIR / f"{_repo_key(repo_url)}.json"


def save_team_pattern(pattern: TeamPattern) -> None:
    TEAM_RULES_DIR.mkdir(parents=True, exist_ok=True)
    if not pattern.learned_at:
        pattern.learned_at = datetime.now(timezone.utc).isoformat()
    data = asdict(pattern)
    path = _pattern_file(pattern.repo_url)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)
    logger.info(f"Saved team pattern to {path}")


def load_team_pattern(repo_url: str, ttl_days: int = 0) -> TeamPattern | None:
    path = _pattern_file(repo_url)
    if not path.exists():
        return None

    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
    except (json.JSONDecodeError, TypeError) as e:
        logger.warning(f"Failed to load team pattern: {e}")
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

    rules = []
    for r in data.get("rules", []):
        rules.append(TeamRule(
            category=r.get("category", "custom"),
            description=r.get("description", ""),
            example=r.get("example", ""),
            weight=r.get("weight", 1.0),
            source=r.get("source", ""),
            frequency=r.get("frequency", 1),
        ))

    return TeamPattern(
        rules=rules,
        common_terms=data.get("common_terms", []),
        severity_preference=data.get("severity_preference", {}),
        focus_areas=data.get("focus_areas", []),
        repo_url=data.get("repo_url", ""),
        learned_at=data.get("learned_at", ""),
    )


def merge_team_rules(
    team_pattern: TeamPattern | None,
    manual_rules: list[str],
) -> list[TeamRule]:
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
