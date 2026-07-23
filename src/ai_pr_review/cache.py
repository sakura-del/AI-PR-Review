"""分析结果缓存模块 — 基于 PR URL + head_sha 的结果缓存"""
import json
import time
import hashlib
import logging
from pathlib import Path
from ai_pr_review.models import AnalysisResult, AnalysisSummary, Finding, Suggestion, Severity

logger = logging.getLogger(__name__)

CACHE_DIR = Path.home() / ".ai-pr-review" / "cache"
DEFAULT_TTL_SECONDS = 86400  # 24小时


def _cache_key(pr_url: str, head_sha: str) -> str:
    """生成缓存键的哈希值（pr_url + head_sha 的 sha256 截断）"""
    raw = f"{pr_url}@{head_sha}"
    return hashlib.sha256(raw.encode()).hexdigest()[:16]


def _cache_path(key: str) -> Path:
    """根据缓存键返回对应的缓存文件路径"""
    return CACHE_DIR / f"{key}.json"


def _serialize_result(pr_url: str, head_sha: str, result: AnalysisResult) -> dict:
    """将 AnalysisResult 序列化为 JSON 可存储的字典

    同时保存 pr_url 与 head_sha，便于按 PR 清理缓存。
    """
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


def get_cached_result(
    pr_url: str, head_sha: str, ttl_seconds: int = DEFAULT_TTL_SECONDS
) -> AnalysisResult | None:
    """获取缓存的分析结果，不存在或已过期返回 None"""
    if not head_sha:
        return None
    key = _cache_key(pr_url, head_sha)
    path = _cache_path(key)
    if not path.exists():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        cached_at = data.get("cached_at", 0)
        # TTL 过期判断
        if time.time() - cached_at > ttl_seconds:
            logger.info(f"Cache expired for {pr_url}@{head_sha[:7]}")
            return None
        return _deserialize_result(data)
    except (json.JSONDecodeError, KeyError, ValueError) as e:
        logger.warning(f"Failed to read cache: {e}")
        return None


def save_cached_result(pr_url: str, head_sha: str, result: AnalysisResult) -> None:
    """保存分析结果到缓存"""
    if not head_sha:
        return
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    key = _cache_key(pr_url, head_sha)
    path = _cache_path(key)
    data = _serialize_result(pr_url, head_sha, result)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    logger.info(f"Cached result for {pr_url}@{head_sha[:7]}")


def clear_cache(pr_url: str | None = None) -> int:
    """清除缓存，返回清除的条目数

    - pr_url 为 None：清除全部缓存
    - pr_url 指定：仅清除该 PR 关联的缓存条目
    """
    if not CACHE_DIR.exists():
        return 0

    count = 0
    for f in CACHE_DIR.glob("*.json"):
        try:
            data = json.loads(f.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            # 文件损坏时：若指定了 PR 则跳过，否则直接删除
            if pr_url:
                continue
            f.unlink()
            count += 1
            continue

        # 指定 PR 时按 URL 过滤；未指定时清除全部
        if pr_url and data.get("pr_url") != pr_url:
            continue
        f.unlink()
        count += 1
    return count
