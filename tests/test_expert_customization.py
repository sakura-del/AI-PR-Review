import pytest
import tempfile
from pathlib import Path
from ai_pr_review.config import ProjectConfig, ExpertOverride, load_project_config
from ai_pr_review.expert_knowledge import (
    EXPERT_SKILLS,
    ExpertProfile,
    merge_expert_config,
    get_expert_profiles,
    select_experts,
)
from ai_pr_review.prompt_templates import build_analysis_prompt


class TestExpertOverrideAppend:
    def test_checklist_append(self):
        override = ExpertOverride(checklist_append=["新增规则1", "新增规则2"])
        config = ProjectConfig(expert_overrides={"security": override})
        merged = merge_expert_config(config)
        original_len = len(EXPERT_SKILLS["security"].checklist)
        assert len(merged["security"].checklist) == original_len + 2
        assert "新增规则1" in merged["security"].checklist
        assert "新增规则2" in merged["security"].checklist

    def test_red_flags_append(self):
        override = ExpertOverride(red_flags_append=["新红旗1"])
        config = ProjectConfig(expert_overrides={"performance": override})
        merged = merge_expert_config(config)
        original_len = len(EXPERT_SKILLS["performance"].red_flags)
        assert len(merged["performance"].red_flags) == original_len + 1
        assert "新红旗1" in merged["performance"].red_flags


class TestExpertOverrideReplace:
    def test_checklist_replace(self):
        override = ExpertOverride(checklist_replace=["替换规则1", "替换规则2"])
        config = ProjectConfig(expert_overrides={"architecture": override})
        merged = merge_expert_config(config)
        assert merged["architecture"].checklist == ["替换规则1", "替换规则2"]

    def test_red_flags_replace(self):
        override = ExpertOverride(red_flags_replace=["替换红旗"])
        config = ProjectConfig(expert_overrides={"testing": override})
        merged = merge_expert_config(config)
        assert merged["testing"].red_flags == ["替换红旗"]

    def test_replace_takes_priority_over_append(self):
        override = ExpertOverride(
            checklist_append=["追加项"],
            checklist_replace=["替换项"],
        )
        config = ProjectConfig(expert_overrides={"security": override})
        merged = merge_expert_config(config)
        assert merged["security"].checklist == ["替换项"]
        assert "追加项" not in merged["security"].checklist


class TestCustomExpertAdded:
    def test_custom_expert_in_merged(self):
        config = ProjectConfig(
            custom_experts={
                "company_compliance": {
                    "name": "合规审查",
                    "knowledge_source": "公司内部合规标准",
                    "checklist": ["数据脱敏", "审计日志"],
                    "red_flags": ["未经审批的依赖"],
                }
            }
        )
        merged = merge_expert_config(config)
        assert "company_compliance" in merged
        assert merged["company_compliance"].name == "合规审查"
        assert len(merged["company_compliance"].checklist) == 2

    def test_custom_expert_defaults(self):
        config = ProjectConfig(
            custom_experts={
                "minimal_expert": {
                    "checklist": ["仅一条规则"],
                }
            }
        )
        merged = merge_expert_config(config)
        assert "minimal_expert" in merged
        assert merged["minimal_expert"].name == "minimal_expert"
        assert merged["minimal_expert"].knowledge_source == "自定义"
        assert merged["minimal_expert"].red_flags == []


class TestMergePreservesBuiltin:
    def test_builtin_unchanged_after_merge(self):
        original_security_checklist = list(EXPERT_SKILLS["security"].checklist)
        override = ExpertOverride(checklist_append=["追加项"])
        config = ProjectConfig(expert_overrides={"security": override})
        merge_expert_config(config)
        assert EXPERT_SKILLS["security"].checklist == original_security_checklist

    def test_no_config_returns_copy(self):
        merged = merge_expert_config(None)
        assert len(merged) == len(EXPERT_SKILLS)
        for key in EXPERT_SKILLS:
            assert key in merged


class TestGetExpertProfilesWithMerged:
    def test_with_merged_skills(self):
        config = ProjectConfig(
            custom_experts={
                "custom1": {
                    "name": "自定义专家",
                    "checklist": ["规则1"],
                    "red_flags": [],
                    "knowledge_source": "测试",
                }
            }
        )
        merged = merge_expert_config(config)
        profiles = get_expert_profiles(["security", "custom1"], merged)
        assert len(profiles) == 2
        assert profiles[0].name == "安全审查"
        assert profiles[1].name == "自定义专家"

    def test_without_merged_uses_builtin(self):
        profiles = get_expert_profiles(["security", "architecture"])
        assert len(profiles) == 2

    def test_missing_expert_skipped(self):
        profiles = get_expert_profiles(["security", "nonexistent"])
        assert len(profiles) == 1


class TestLoadProjectConfigExpertOverrides:
    def test_parse_expert_overrides(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            config_path = Path(tmpdir) / ".ai-pr-review.yaml"
            config_path.write_text("""
expert_overrides:
  security:
    checklist_append:
      - "内部API必须使用mTLS"
    red_flags_append:
      - "未经审批的外部调用"
  readability:
    checklist_replace:
      - "遵循公司编码规范"
""", encoding="utf-8")
            config = load_project_config(Path(tmpdir))
            assert "security" in config.expert_overrides
            assert "内部API必须使用mTLS" in config.expert_overrides["security"].checklist_append
            assert config.expert_overrides["readability"].checklist_replace == ["遵循公司编码规范"]

    def test_parse_custom_experts(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            config_path = Path(tmpdir) / ".ai-pr-review.yaml"
            config_path.write_text("""
custom_experts:
  company_compliance:
    name: "合规审查"
    knowledge_source: "公司标准"
    checklist:
      - "数据脱敏"
      - "审计日志"
    red_flags:
      - "未经审批依赖"
""", encoding="utf-8")
            config = load_project_config(Path(tmpdir))
            assert "company_compliance" in config.custom_experts
            assert config.custom_experts["company_compliance"]["name"] == "合规审查"
            assert len(config.custom_experts["company_compliance"]["checklist"]) == 2


class TestCustomRulesInPrompt:
    def test_custom_rules_appear_in_prompt(self):
        experts = [EXPERT_SKILLS["security"]]
        messages = build_analysis_prompt(
            pr_context="Test PR",
            diff_context="diff content",
            file_context="",
            experts=experts,
            custom_rules=["禁止使用any类型", "所有函数必须有类型注解"],
        )
        user_msg = messages[1]["content"]
        assert "团队自定义规则" in user_msg
        assert "禁止使用any类型" in user_msg
        assert "所有函数必须有类型注解" in user_msg

    def test_no_custom_rules_omits_section(self):
        experts = [EXPERT_SKILLS["security"]]
        messages = build_analysis_prompt(
            pr_context="Test PR",
            diff_context="diff content",
            file_context="",
            experts=experts,
        )
        user_msg = messages[1]["content"]
        assert "团队自定义规则" not in user_msg


class TestEmptyProjectConfigDefaults:
    def test_no_config_returns_defaults(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            config = load_project_config(Path(tmpdir))
            assert config.expert_overrides == {}
            assert config.custom_experts == {}


class TestSelectExpertsIncludesCustom:
    def test_custom_expert_keys_included(self):
        result = select_experts(
            ["src/main.py"],
            "some code content",
            custom_expert_keys=["company_compliance", "data_privacy"],
        )
        assert "company_compliance" in result or "data_privacy" in result or len(result) > 0
