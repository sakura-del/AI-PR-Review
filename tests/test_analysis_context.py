"""AnalysisContext 数据类测试

T6 [A2] 范围：仅 dataclass 本身 + 工厂方法。
build_analysis_prompt 签名改造与 4 个调用点改造属 T17/T18，本文件不涉及。
"""
from dataclasses import dataclass, FrozenInstanceError

import pytest

from ai_pr_review.core.analysis_context import AnalysisContext


@dataclass
class _FakeExpert:
    """最小专家对象，避开 expert_knowledge 重依赖"""
    name: str
    checklist: list = None

    def __post_init__(self):
        if self.checklist is None:
            self.checklist = []


def _fake_experts():
    return [_FakeExpert("security", ["check 1"]), _FakeExpert("architecture", [])]


def test_required_fields_are_stored():
    experts = _fake_experts()
    ctx = AnalysisContext(
        pr_context="PR info",
        diff_context="diff body",
        file_context="file body",
        experts=experts,
    )
    assert ctx.pr_context == "PR info"
    assert ctx.diff_context == "diff body"
    assert ctx.file_context == "file body"
    assert ctx.experts is experts


def test_optional_fields_default_to_empty():
    ctx = AnalysisContext(
        pr_context="x", diff_context="y", file_context="z", experts=_fake_experts(),
    )
    assert ctx.custom_rules == []
    assert ctx.team_rules == []
    assert ctx.cross_file_context == ""
    assert ctx.call_chain_context == ""
    assert ctx.impact_graph_context == ""
    assert ctx.similar_reviews_context == ""
    assert ctx.incremental_context is None


def test_incremental_context_can_be_set():
    ctx = AnalysisContext(
        pr_context="x", diff_context="y", file_context="z",
        experts=_fake_experts(),
        incremental_context={"last_sha": "abc123"},
    )
    assert ctx.incremental_context == {"last_sha": "abc123"}


def test_is_frozen_after_init():
    """冻结 dataclass 不允许字段重新赋值"""
    ctx = AnalysisContext(
        pr_context="x", diff_context="y", file_context="z", experts=_fake_experts(),
    )
    with pytest.raises(FrozenInstanceError):
        ctx.pr_context = "mutated"


def test_default_list_fields_are_independent_per_instance():
    """避免可变默认值陷阱：每个实例的 list 字段是独立对象"""
    ctx1 = AnalysisContext(pr_context="1", diff_context="1", file_context="1", experts=_fake_experts())
    ctx2 = AnalysisContext(pr_context="2", diff_context="2", file_context="2", experts=_fake_experts())
    ctx1.custom_rules.append("rule-A")
    assert ctx2.custom_rules == []


def test_from_context_builder_extracts_known_keys():
    context_dict = {
        "pr_metadata": "PR info",
        "diff": "diff body",
        "file_contents": "file body",
        "cross_file_context": "cross",
        "call_chain_context": "call chain",
        "impact_graph_context": "impact",
        "similar_reviews_context": "similar",
        # 未知字段应被静默忽略
        "unknown_extra": "should be dropped",
    }
    ctx = AnalysisContext.from_context_builder(
        context=context_dict,
        experts=_fake_experts(),
        custom_rules=["rule1"],
    )
    assert ctx.pr_context == "PR info"
    assert ctx.diff_context == "diff body"
    assert ctx.file_context == "file body"
    assert ctx.cross_file_context == "cross"
    assert ctx.call_chain_context == "call chain"
    assert ctx.impact_graph_context == "impact"
    assert ctx.similar_reviews_context == "similar"
    assert ctx.custom_rules == ["rule1"]


def test_from_context_builder_handles_missing_keys():
    """context dict 缺字段时用空字符串兜底而非抛 KeyError"""
    ctx = AnalysisContext.from_context_builder(
        context={}, experts=_fake_experts(),
    )
    assert ctx.pr_context == ""
    assert ctx.diff_context == ""
    assert ctx.file_context == ""
    assert ctx.cross_file_context == ""


def test_from_context_builder_passes_incremental_and_team_rules():
    """工厂方法的 optional 参数正确传递给字段"""
    ctx = AnalysisContext.from_context_builder(
        context={"pr_metadata": "x", "diff": "y", "file_contents": "z"},
        experts=_fake_experts(),
        incremental_context={"last_sha": "abc"},
        team_rules=["ignored-because-not-list-of-teamrule"],
    )
    assert ctx.incremental_context == {"last_sha": "abc"}
    # team_rules 字段类型声明为 list[TeamRule]，但这里传 list[str] 仅做结构验证
    assert ctx.team_rules == ["ignored-because-not-list-of-teamrule"]