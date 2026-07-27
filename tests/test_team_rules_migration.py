"""team_rules 模块基于 Storage 的迁移与行为测试（T12 [A12]）

覆盖：
- 正常 save/load 通过 Storage 走通
- TTL 检查
- 旧 team_rules 目录一次性迁移
- merge_team_rules 仍按权重排序

注：使用 configure_storage 注入临时 LocalJSONStorage。
"""
import json
from unittest.mock import patch

import pytest

from ai_pr_review.data import team_rules as tr_mod
from ai_pr_review.data.persistence import LocalJSONStorage, configure_storage
from ai_pr_review.core.team_learner import TeamPattern, TeamRule
from ai_pr_review.data.team_rules import (
    _repo_key,
    load_team_pattern,
    merge_team_rules,
    save_team_pattern,
)


def _make_pattern(repo_url: str = "https://github.com/owner/repo/pull/1") -> TeamPattern:
    return TeamPattern(
        rules=[
            TeamRule(category="security", description="Use env for secrets", example="os.environ", weight=1.0, source="learned", frequency=3),
            TeamRule(category="testing", description="Add tests for new features", example="", weight=0.8, source="learned", frequency=2),
        ],
        common_terms=["typo", "nit"],
        severity_preference={"high": "P0", "medium": "P1"},
        focus_areas=["security", "testing"],
        repo_url=repo_url,
        learned_at="2024-06-01T00:00:00+00:00",
    )


@pytest.fixture
def storage(tmp_path):
    s = LocalJSONStorage(base_dir=tmp_path / "storage")
    configure_storage(s)
    return s


def test_repo_key_format():
    assert _repo_key("https://github.com/owner/repo/pull/1") == "owner_repo"


def test_repo_key_fallback_on_invalid_url():
    """非 GitHub URL 用占位字符替换"""
    key = _repo_key("not-a-url")
    assert "/" not in key
    assert ":" not in key


def test_save_and_load_roundtrip_via_storage(storage):
    pattern = _make_pattern()
    save_team_pattern(pattern)

    loaded = load_team_pattern("https://github.com/owner/repo/pull/5")
    assert loaded is not None
    assert len(loaded.rules) == 2
    assert loaded.rules[0].category == "security"
    assert loaded.focus_areas == ["security", "testing"]
    assert loaded.repo_url == "https://github.com/owner/repo/pull/1"
    assert loaded.learned_at == "2024-06-01T00:00:00+00:00"


def test_load_returns_none_when_not_saved(storage):
    assert load_team_pattern("https://github.com/no/such/repo") is None


def test_load_ttl_zero_returns_data_regardless_of_age(storage):
    """ttl_days=0 表示不检查 TTL"""
    pattern = _make_pattern()
    pattern.learned_at = "2020-01-01T00:00:00+00:00"  # 多年以前
    save_team_pattern(pattern)

    loaded = load_team_pattern(pattern.repo_url, ttl_days=0)
    assert loaded is not None


def test_load_ttl_expired_returns_none(storage):
    """超过 TTL 天数返回 None"""
    from datetime import datetime, timezone, timedelta
    pattern = _make_pattern()
    # 设为 60 天前，ttl=30 → 已过期
    pattern.learned_at = (datetime.now(timezone.utc) - timedelta(days=60)).isoformat()
    save_team_pattern(pattern)

    loaded = load_team_pattern(pattern.repo_url, ttl_days=30)
    assert loaded is None


def test_load_ttl_within_window_returns_data(storage):
    """TTL 内应能取到"""
    from datetime import datetime, timezone, timedelta
    pattern = _make_pattern()
    # 设为 5 天前，确保在 ttl_days=30 窗口内
    pattern.learned_at = (datetime.now(timezone.utc) - timedelta(days=5)).isoformat()
    save_team_pattern(pattern)

    loaded = load_team_pattern(pattern.repo_url, ttl_days=30)
    assert loaded is not None


def test_old_team_rules_dir_migrates_on_first_load(tmp_path):
    """旧 ~/.ai-pr-review/team_rules/*.json 首次 load 时迁移到 Storage"""
    with patch.object(tr_mod, "_OLD_TEAM_RULES_DIR", tmp_path / "old_team_rules"):
        old_dir = tmp_path / "old_team_rules"
        old_dir.mkdir()

        old_data = {
            "rules": [
                {"category": "security", "description": "old rule", "example": "", "weight": 1.0, "source": "learned", "frequency": 1},
            ],
            "common_terms": ["old"],
            "severity_preference": {},
            "focus_areas": ["old"],
            "repo_url": "https://github.com/owner/repo",
            "learned_at": "2024-06-01T00:00:00+00:00",
        }
        old_file = old_dir / "owner_repo.json"
        old_file.write_text(json.dumps(old_data), encoding="utf-8")

        configure_storage(LocalJSONStorage(base_dir=tmp_path / "storage"))

        loaded = load_team_pattern("https://github.com/owner/repo/pull/1")
        assert loaded is not None
        assert len(loaded.rules) == 1
        assert loaded.rules[0].description == "old rule"
        assert loaded.common_terms == ["old"]


def test_old_team_rules_files_not_deleted_after_migration(tmp_path):
    """迁移后旧文件应保留"""
    with patch.object(tr_mod, "_OLD_TEAM_RULES_DIR", tmp_path / "old_team_rules"):
        old_dir = tmp_path / "old_team_rules"
        old_dir.mkdir()
        old_file = old_dir / "owner_repo.json"
        old_file.write_text(json.dumps({
            "rules": [], "common_terms": [], "severity_preference": {},
            "focus_areas": [], "repo_url": "x", "learned_at": "2024-01-01T00:00:00+00:00",
        }), encoding="utf-8")

        configure_storage(LocalJSONStorage(base_dir=tmp_path / "storage"))
        load_team_pattern("https://github.com/owner/repo")

        assert old_file.exists()


def test_migration_is_idempotent(tmp_path):
    """多次 load 不重复迁移"""
    with patch.object(tr_mod, "_OLD_TEAM_RULES_DIR", tmp_path / "old_team_rules"):
        old_dir = tmp_path / "old_team_rules"
        old_dir.mkdir()
        old_dir.joinpath("owner_repo.json").write_text(json.dumps({
            "rules": [], "common_terms": [], "severity_preference": {},
            "focus_areas": [], "repo_url": "x", "learned_at": "2024-01-01T00:00:00+00:00",
        }), encoding="utf-8")

        storage = LocalJSONStorage(base_dir=tmp_path / "storage")
        configure_storage(storage)

        load_team_pattern("https://github.com/owner/repo")
        from ai_pr_review.data.storage import Namespace
        count1 = storage.count(Namespace.TEAM_RULES)

        load_team_pattern("https://github.com/owner/repo")
        count2 = storage.count(Namespace.TEAM_RULES)

        assert count1 == count2 == 1


def test_merge_team_rules_sorts_by_weight_desc():
    """merge_team_rules 应按 weight 降序排列"""
    pattern = TeamPattern(
        rules=[
            TeamRule(category="a", description="low", example="", weight=0.5, source="learned", frequency=1),
            TeamRule(category="b", description="high", example="", weight=2.0, source="learned", frequency=1),
        ],
        common_terms=[], severity_preference={}, focus_areas=[],
        repo_url="x", learned_at="",
    )
    merged = merge_team_rules(pattern, ["manual rule"])
    # 顺序：high(2.0) > manual(1.5) > low(0.5)
    assert merged[0].description == "high"
    assert merged[1].description == "manual rule"
    assert merged[2].description == "low"


def test_merge_team_rules_empty_pattern():
    """None pattern 时只返回手动规则"""
    merged = merge_team_rules(None, ["only manual"])
    assert len(merged) == 1
    assert merged[0].weight == 1.5
    assert merged[0].source == "manual"


def test_save_sets_learned_at_if_missing(storage):
    """pattern.learned_at 为空时应自动填充"""
    pattern = _make_pattern()
    pattern.learned_at = ""
    save_team_pattern(pattern)

    loaded = load_team_pattern(pattern.repo_url)
    assert loaded.learned_at != ""  # 自动填充