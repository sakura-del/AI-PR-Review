import pytest
import json
from unittest.mock import MagicMock, patch
from pathlib import Path

from ai_pr_review.team_learner import TeamRule, TeamPattern, TeamLearner
from ai_pr_review.team_rules import (
    save_team_pattern,
    load_team_pattern,
    merge_team_rules,
    _repo_key,
    TEAM_RULES_DIR,
)
from ai_pr_review.prompt_templates import build_analysis_prompt
from ai_pr_review.expert_knowledge import EXPERT_SKILLS
from ai_pr_review.config import TeamLearningConfig, ProjectConfig, load_project_config


class TestTeamRule:
    def test_team_rule_creation(self):
        rule = TeamRule(
            category="security",
            description="No hardcoded secrets",
            example="SECRET = os.environ.get('KEY')",
            weight=1.2,
            source="learned",
            frequency=3,
        )
        assert rule.category == "security"
        assert rule.description == "No hardcoded secrets"
        assert rule.weight == 1.2
        assert rule.source == "learned"
        assert rule.frequency == 3

    def test_team_rule_default_weight(self):
        rule = TeamRule(category="style", description="Use camelCase", example="")
        assert rule.weight == 1.0
        assert rule.source == ""
        assert rule.frequency == 1


class TestTeamPattern:
    def test_team_pattern_creation(self):
        rules = [TeamRule(category="security", description="test", example="")]
        pattern = TeamPattern(
            rules=rules,
            common_terms=["LGTM", "nit"],
            severity_preference={"P0": 0.2, "P1": 0.5},
            focus_areas=["security", "testing"],
            repo_url="https://github.com/o/r/pull/1",
        )
        assert len(pattern.rules) == 1
        assert pattern.common_terms == ["LGTM", "nit"]
        assert pattern.severity_preference["P0"] == 0.2
        assert pattern.learned_at != ""

    def test_team_pattern_empty(self):
        pattern = TeamPattern(
            rules=[], common_terms=[], severity_preference={}, focus_areas=[]
        )
        assert len(pattern.rules) == 0
        assert pattern.learned_at != ""


class TestFilterComments:
    def test_filter_bot_comments(self):
        learner = TeamLearner.__new__(TeamLearner)
        comments = [
            {"author": "dependabot", "body": "This is a bot comment with enough text", "pr_number": 1, "pr_title": "t"},
            {"author": "renovate-bot", "body": "Another bot comment with enough text", "pr_number": 2, "pr_title": "t"},
            {"author": "ai-review", "body": "AI review comment with enough text here", "pr_number": 3, "pr_title": "t"},
            {"author": "john", "body": "This is a real human comment with enough text", "pr_number": 4, "pr_title": "t"},
        ]
        filtered = learner._filter_comments(comments)
        assert len(filtered) == 1
        assert filtered[0]["author"] == "john"

    def test_filter_short_comments(self):
        learner = TeamLearner.__new__(TeamLearner)
        comments = [
            {"author": "alice", "body": "LGTM", "pr_number": 1, "pr_title": "t"},
            {"author": "bob", "body": "+1", "pr_number": 2, "pr_title": "t"},
            {"author": "carol", "body": "This is a detailed review comment about the code", "pr_number": 3, "pr_title": "t"},
        ]
        filtered = learner._filter_comments(comments)
        assert len(filtered) == 1
        assert filtered[0]["author"] == "carol"

    def test_filter_limit_count(self):
        learner = TeamLearner.__new__(TeamLearner)
        comments = [
            {"author": f"user{i}", "body": f"Comment number {i} with enough text to pass", "pr_number": i, "pr_title": "t"}
            for i in range(150)
        ]
        filtered = learner._filter_comments(comments)
        assert len(filtered) == 100


class TestParsePattern:
    def test_parse_pattern_valid_json(self):
        learner = TeamLearner.__new__(TeamLearner)
        raw = json.dumps({
            "rules": [
                {"category": "security", "description": "No SQL injection", "example": "Use params", "frequency": 4},
                {"category": "style", "description": "Use type hints", "example": "def foo(x: int)", "frequency": 2},
            ],
            "common_terms": ["LGTM", "nit"],
            "severity_preference": {"P0": 0.1, "P1": 0.4, "P2": 0.3, "P3": 0.2},
            "focus_areas": ["security", "testing"],
        })
        pattern = learner._parse_pattern(raw)
        assert len(pattern.rules) == 2
        assert pattern.rules[0].category == "security"
        assert pattern.rules[0].source == "learned"
        assert pattern.rules[0].frequency == 4
        assert pattern.rules[0].weight > 1.0
        assert pattern.common_terms == ["LGTM", "nit"]
        assert pattern.focus_areas == ["security", "testing"]

    def test_parse_pattern_invalid_json(self):
        learner = TeamLearner.__new__(TeamLearner)
        pattern = learner._parse_pattern("not json at all")
        assert len(pattern.rules) == 0
        assert pattern.common_terms == []

    def test_parse_pattern_with_markdown_wrapper(self):
        learner = TeamLearner.__new__(TeamLearner)
        raw = "```json\n" + json.dumps({
            "rules": [{"category": "custom", "description": "test rule", "example": "", "frequency": 1}],
            "common_terms": [],
            "severity_preference": {},
            "focus_areas": [],
        }) + "\n```"
        pattern = learner._parse_pattern(raw)
        assert len(pattern.rules) == 1

    def test_parse_pattern_weight_from_frequency(self):
        learner = TeamLearner.__new__(TeamLearner)
        raw = json.dumps({
            "rules": [
                {"category": "security", "description": "high freq", "example": "", "frequency": 5},
                {"category": "style", "description": "low freq", "example": "", "frequency": 1},
            ],
            "common_terms": [],
            "severity_preference": {},
            "focus_areas": [],
        })
        pattern = learner._parse_pattern(raw)
        assert pattern.rules[0].weight > pattern.rules[1].weight
        assert pattern.rules[0].weight <= 2.0


class TestTeamRulesStorage:
    def test_save_and_load_team_pattern(self, tmp_path, monkeypatch):
        monkeypatch.setattr("ai_pr_review.team_rules.TEAM_RULES_DIR", tmp_path)
        rules = [TeamRule(category="security", description="test", example="", weight=1.5, source="learned", frequency=3)]
        pattern = TeamPattern(
            rules=rules,
            common_terms=["LGTM"],
            severity_preference={"P0": 0.1},
            focus_areas=["security"],
            repo_url="https://github.com/owner/repo/pull/1",
        )
        save_team_pattern(pattern)
        loaded = load_team_pattern("https://github.com/owner/repo/pull/1")
        assert loaded is not None
        assert len(loaded.rules) == 1
        assert loaded.rules[0].description == "test"
        assert loaded.common_terms == ["LGTM"]

    def test_load_nonexistent_pattern(self, tmp_path, monkeypatch):
        monkeypatch.setattr("ai_pr_review.team_rules.TEAM_RULES_DIR", tmp_path)
        result = load_team_pattern("https://github.com/nonexistent/repo/pull/1")
        assert result is None

    def test_repo_key_naming(self):
        key = _repo_key("https://github.com/my-org/my-repo/pull/42")
        assert key == "my-org_my-repo"


class TestMergeTeamRules:
    def test_merge_team_and_manual_rules(self):
        team_pattern = TeamPattern(
            rules=[TeamRule(category="security", description="learned rule", example="", weight=0.9, source="learned")],
            common_terms=[],
            severity_preference={},
            focus_areas=[],
        )
        manual_rules = ["All APIs must have auth"]
        merged = merge_team_rules(team_pattern, manual_rules)
        assert len(merged) == 2
        descriptions = [r.description for r in merged]
        assert "learned rule" in descriptions
        assert "All APIs must have auth" in descriptions

    def test_merge_manual_rules_higher_weight(self):
        team_pattern = TeamPattern(
            rules=[TeamRule(category="style", description="learned", example="", weight=0.5, source="learned")],
            common_terms=[],
            severity_preference={},
            focus_areas=[],
        )
        manual_rules = ["manual rule"]
        merged = merge_team_rules(team_pattern, manual_rules)
        manual = [r for r in merged if r.source == "manual"][0]
        learned = [r for r in merged if r.source == "learned"][0]
        assert manual.weight > learned.weight

    def test_merge_sorted_by_weight(self):
        team_pattern = TeamPattern(
            rules=[
                TeamRule(category="a", description="low", example="", weight=0.3, source="learned"),
                TeamRule(category="b", description="high", example="", weight=1.8, source="learned"),
            ],
            common_terms=[],
            severity_preference={},
            focus_areas=[],
        )
        merged = merge_team_rules(team_pattern, [])
        assert merged[0].weight >= merged[1].weight

    def test_merge_empty_team_rules(self):
        merged = merge_team_rules(None, ["manual rule 1", "manual rule 2"])
        assert len(merged) == 2
        assert all(r.source == "manual" for r in merged)


class TestTeamRulesInPrompt:
    def test_team_rules_in_prompt(self):
        experts = [EXPERT_SKILLS["security"]]
        team_rules = [
            TeamRule(category="security", description="No hardcoded secrets", example="os.environ.get()", weight=1.5, source="learned"),
            TeamRule(category="custom", description="All APIs need auth", example="", weight=1.5, source="manual"),
        ]
        messages = build_analysis_prompt(
            pr_context="Test PR",
            diff_context="diff content",
            file_context="",
            experts=experts,
            team_rules=team_rules,
        )
        user_msg = messages[1]["content"]
        assert "团队审查模式" in user_msg
        assert "No hardcoded secrets" in user_msg
        assert "All APIs need auth" in user_msg

    def test_learned_tag_in_prompt(self):
        experts = [EXPERT_SKILLS["security"]]
        team_rules = [
            TeamRule(category="security", description="test rule", example="", source="learned"),
        ]
        messages = build_analysis_prompt(
            pr_context="Test",
            diff_context="diff",
            file_context="",
            experts=experts,
            team_rules=team_rules,
        )
        user_msg = messages[1]["content"]
        assert "[学习]" in user_msg

    def test_manual_tag_in_prompt(self):
        experts = [EXPERT_SKILLS["security"]]
        team_rules = [
            TeamRule(category="custom", description="manual rule", example="", source="manual"),
        ]
        messages = build_analysis_prompt(
            pr_context="Test",
            diff_context="diff",
            file_context="",
            experts=experts,
            team_rules=team_rules,
        )
        user_msg = messages[1]["content"]
        assert "[手动]" in user_msg

    def test_weight_in_prompt(self):
        experts = [EXPERT_SKILLS["security"]]
        team_rules = [
            TeamRule(category="security", description="weighted rule", example="", weight=1.8),
        ]
        messages = build_analysis_prompt(
            pr_context="Test",
            diff_context="diff",
            file_context="",
            experts=experts,
            team_rules=team_rules,
        )
        user_msg = messages[1]["content"]
        assert "权重:1.8" in user_msg

    def test_no_team_rules_omits_section(self):
        experts = [EXPERT_SKILLS["security"]]
        messages = build_analysis_prompt(
            pr_context="Test",
            diff_context="diff",
            file_context="",
            experts=experts,
        )
        user_msg = messages[1]["content"]
        assert "团队审查模式" not in user_msg

    def test_team_rules_with_example(self):
        experts = [EXPERT_SKILLS["security"]]
        team_rules = [
            TeamRule(category="security", description="Use env vars", example="SECRET = os.environ.get('KEY')", source="learned"),
        ]
        messages = build_analysis_prompt(
            pr_context="Test",
            diff_context="diff",
            file_context="",
            experts=experts,
            team_rules=team_rules,
        )
        user_msg = messages[1]["content"]
        assert "os.environ.get" in user_msg


class TestTeamLearningConfig:
    def test_team_learning_config_defaults(self):
        config = TeamLearningConfig()
        assert config.enabled is False
        assert config.max_prs == 20
        assert config.max_comments == 100
        assert config.min_rule_weight == 0.3
        assert config.rule_ttl_days == 30

    def test_parse_team_learning_from_yaml(self, tmp_path):
        yaml_content = """
team_learning:
  enabled: true
  max_prs: 30
  max_comments: 50
  min_rule_weight: 0.5
  rule_ttl_days: 60
"""
        yaml_file = tmp_path / ".ai-pr-review.yaml"
        yaml_file.write_text(yaml_content, encoding="utf-8")

        with patch("ai_pr_review.config.Path.cwd", return_value=tmp_path):
            config = load_project_config(tmp_path)

        assert config.team_learning.enabled is True
        assert config.team_learning.max_prs == 30
        assert config.team_learning.max_comments == 50
        assert config.team_learning.min_rule_weight == 0.5
        assert config.team_learning.rule_ttl_days == 60

    def test_project_config_includes_team_learning(self):
        config = ProjectConfig()
        assert isinstance(config.team_learning, TeamLearningConfig)
        assert config.team_learning.enabled is False


class TestTeamPatternTTL:
    def test_expired_pattern_returns_none(self, tmp_path, monkeypatch):
        monkeypatch.setattr("ai_pr_review.team_rules.TEAM_RULES_DIR", tmp_path)
        pattern = TeamPattern(
            rules=[TeamRule(category="security", description="old rule", example="")],
            common_terms=[],
            severity_preference={},
            focus_areas=[],
            repo_url="https://github.com/o/r/pull/1",
            learned_at="2020-01-01T00:00:00+00:00",
        )
        save_team_pattern(pattern)
        result = load_team_pattern("https://github.com/o/r/pull/1", ttl_days=1)
        assert result is None

    def test_fresh_pattern_returns_data(self, tmp_path, monkeypatch):
        monkeypatch.setattr("ai_pr_review.team_rules.TEAM_RULES_DIR", tmp_path)
        pattern = TeamPattern(
            rules=[TeamRule(category="security", description="fresh rule", example="")],
            common_terms=[],
            severity_preference={},
            focus_areas=[],
            repo_url="https://github.com/o/r/pull/1",
        )
        save_team_pattern(pattern)
        result = load_team_pattern("https://github.com/o/r/pull/1", ttl_days=30)
        assert result is not None
        assert len(result.rules) == 1
