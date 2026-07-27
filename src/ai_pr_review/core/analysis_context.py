"""分析上下文数据类 — 收敛 build_analysis_prompt 的多参数

设计目标：
- 把当前 8+ 参数的 build_analysis_prompt 签名收敛到一个对象
- 冻结 dataclass 保证不可变性，避免下游误改
- 提供 from_context_builder 工厂方法，便于从 ContextBuilder 输出构造

注：本文件定义仅对应 T6，build_analysis_prompt 签名改造属 T17 [A13]，
4 个调用点改造属 T18 [A14]。
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Optional

if TYPE_CHECKING:
    from ai_pr_review.core.expert_knowledge import ExpertProfile
    from ai_pr_review.core.team_learner import TeamRule


@dataclass(frozen=True)
class AnalysisContext:
    """单次 AI 审查所需的全部上下文

    字段顺序与原 build_analysis_prompt 参数保持一致，便于 grep 迁移。
    必填字段放前，可选字段放后带默认值。

    设计说明：
    - frozen=True：构建后不可变，下游消费者不会意外改字段
    - list 默认值用 field(default_factory=list)：避免可变默认值陷阱
    - Type-only import ExpertProfile/TeamRule：不增加运行时依赖
    """
    pr_context: str
    diff_context: str
    file_context: str
    experts: list["ExpertProfile"]

    custom_rules: list[str] = field(default_factory=list)
    incremental_context: Optional[dict] = None
    team_rules: list["TeamRule"] = field(default_factory=list)
    cross_file_context: str = ""
    call_chain_context: str = ""
    impact_graph_context: str = ""
    similar_reviews_context: str = ""

    @classmethod
    def from_context_builder(
        cls,
        context: dict,
        experts: list["ExpertProfile"],
        custom_rules: Optional[list[str]] = None,
        incremental_context: Optional[dict] = None,
        team_rules: Optional[list["TeamRule"]] = None,
    ) -> "AnalysisContext":
        """从 ContextBuilder.build_context() 的 dict 输出构造

        显式接收 experts/rules/incremental，因为它们不来自 context dict。
        未知 key 被静默忽略，便于 ContextBuilder 演进时兼容。

        Args:
            context: ContextBuilder.build_context() 的返回值（dict 形式）
            experts: 已选定的专家列表
            custom_rules: 项目级自定义规则
            incremental_context: 增量审查上下文（None 表示全量审查）
            team_rules: 团队学习规则

        Returns:
            填充好的 AnalysisContext 实例
        """
        return cls(
            pr_context=context.get("pr_metadata", ""),
            diff_context=context.get("diff", ""),
            file_context=context.get("file_contents", ""),
            cross_file_context=context.get("cross_file_context", ""),
            call_chain_context=context.get("call_chain_context", ""),
            impact_graph_context=context.get("impact_graph_context", ""),
            similar_reviews_context=context.get("similar_reviews_context", ""),
            experts=experts,
            custom_rules=custom_rules or [],
            incremental_context=incremental_context,
            team_rules=team_rules or [],
        )