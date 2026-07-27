import json
from ai_pr_review.core.expert_knowledge import ExpertProfile
from ai_pr_review.core.analysis_context import AnalysisContext
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from ai_pr_review.core.team_learner import TeamRule


SYSTEM_PROMPT = """你是一位代码审查专家。根据PR变更进行专业审查。

规则：
- 每个发现必须关联具体的文件路径和行号
- 使用P0-P3严重级别：P0=安全/致命问题(阻止合并), P1=重要问题(合并前修复), P2=代码味道(建议修复), P3=可选优化
- 每个发现必须包含置信度(1-5)和修复代码示例
- 忽略：风格偏好、注释缺失、无实际价值的泛泛建议
- 优先报告：安全问题、逻辑错误、性能问题、测试缺失
"""


INCREMENTAL_SYSTEM_PROMPT = """你是一位代码审查专家。本次为增量审查——仅分析自上次审查以来的新增变更。

规则：
- 仅关注增量变更部分，已审查过的代码不再重复报告
- 如果增量变更影响了已有代码的逻辑，仍需报告
- 每个发现标注[增量]前缀
- 使用P0-P3严重级别
- 优先报告：新增安全问题、逻辑错误、性能问题
"""


OUTPUT_SCHEMA = """\
输出严格JSON格式（无其他内容）：

```json
{
  "summary": {
    "intent": "变更意图",
    "scope": "影响范围",
    "key_changes": ["关键修改点"]
  },
  "findings": [
    {
      "severity": "P0|P1|P2|P3",
      "confidence": 1-5,
      "type": "security|logic|performance|quality|testing",
      "file": "文件路径",
      "line": 行号,
      "title": "问题标题",
      "description": "问题描述",
      "suggestion": "修复建议文字描述",
      "code_snippet": "修复代码示例"
    }
  ],
  "suggestions": [
    {
      "category": "类别",
      "priority": "P1|P2|P3",
      "description": "改进建议",
      "example": "示例代码"
    }
  ]
}
```\
"""


FEW_SHOT_EXAMPLE = """\
示例：

```json
{
  "summary": {
    "intent": "添加JWT认证",
    "scope": "认证模块",
    "key_changes": ["新增auth.py", "修改db.py使用参数化查询"]
  },
  "findings": [
    {
      "severity": "P0",
      "confidence": 5,
      "type": "security",
      "file": "auth.py",
      "line": 4,
      "title": "硬编码JWT密钥",
      "description": "密钥硬编码存在泄露风险",
      "suggestion": "从环境变量读取密钥",
      "code_snippet": "SECRET = os.environ.get('JWT_SECRET')"
    }
  ],
  "suggestions": [
    {
      "category": "security",
      "priority": "P2",
      "description": "考虑使用密钥轮换",
      "example": "from keyring import get_password"
    }
  ]
}
```\
"""


def build_expert_context(experts: list[ExpertProfile]) -> str:
    parts = ["审查专家清单：\n"]
    for expert in experts:
        parts.append(f"[{expert.name}]")
        for item in expert.checklist:
            parts.append(f"  • {item}")
    return "\n".join(parts)


def build_analysis_prompt(ctx: AnalysisContext) -> list[dict[str, str]]:
    """构造 LLM 分析提示（v0.9 接收 AnalysisContext 参数对象）

    Args:
        ctx: 单次审查所需的全部上下文（context_builder 输出 + experts + rules）

    Returns:
        OpenAI chat messages 列表（system + user）
    """
    expert_context = build_expert_context(ctx.experts)

    system_prompt = INCREMENTAL_SYSTEM_PROMPT if ctx.incremental_context else SYSTEM_PROMPT

    user_content_parts = [
        "## PR信息\n" + ctx.pr_context,
        "\n## 代码变更\n" + ctx.diff_context,
    ]

    if ctx.file_context:
        user_content_parts.append("\n## 相关文件\n" + ctx.file_context)

    if ctx.cross_file_context:
        user_content_parts.append("\n" + ctx.cross_file_context)

    if ctx.call_chain_context:
        user_content_parts.append("\n" + ctx.call_chain_context)

    if ctx.impact_graph_context:
        user_content_parts.append("\n" + ctx.impact_graph_context)

    if ctx.similar_reviews_context:
        user_content_parts.append("\n" + ctx.similar_reviews_context)

    user_content_parts.append("\n## 审查规则\n" + expert_context)

    if ctx.custom_rules:
        rules_text = "\n".join(f"- {r}" for r in ctx.custom_rules)
        user_content_parts.append("\n## 团队自定义规则\n" + rules_text)

    if ctx.incremental_context:
        ic = ctx.incremental_context
        changed = ", ".join(ic["changed_files"]) if ic.get("changed_files") else "无"
        unchanged = ", ".join(ic["unchanged_files"][:10]) if ic.get("unchanged_files") else "无"
        inc_info = (
            f"\n## 增量分析信息\n"
            f"- 上次审查commit: {ic['last_sha']}\n"
            f"- 上次审查时间: {ic['last_timestamp']}\n"
            f"- 本次变更文件: {changed}\n"
            f"- 未变更文件: {unchanged}\n"
        )
        user_content_parts.append(inc_info)

    if ctx.team_rules:
        team_text = "\n## 团队审查模式（从历史评论中学习）\n"
        for rule in ctx.team_rules:
            source_tag = "[学习]" if rule.source == "learned" else "[手动]"
            weight_tag = f"(权重:{rule.weight:.1f})" if rule.weight != 1.0 else ""
            team_text += f"- {source_tag} [{rule.category}] {rule.description} {weight_tag}\n"
            if rule.example:
                team_text += f"  示例：{rule.example}\n"
        user_content_parts.append(team_text)

    user_content_parts.append("\n" + OUTPUT_SCHEMA)
    user_content_parts.append("\n" + FEW_SHOT_EXAMPLE)

    messages = [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": "\n".join(user_content_parts)},
    ]

    return messages


def build_analysis_prompt_legacy(
    pr_context: str,
    diff_context: str,
    file_context: str,
    experts: list[ExpertProfile],
    custom_rules: list[str] | None = None,
    incremental_context: dict | None = None,
    team_rules: list["TeamRule"] | None = None,
    cross_file_context: str = "",
    call_chain_context: str = "",
    impact_graph_context: str = "",
    similar_reviews_context: str = "",
) -> list[dict[str, str]]:
    """旧签名（v0.8.x 向后兼容）— 已废弃，新代码请用 AnalysisContext

    行为与 build_analysis_prompt(ctx) 完全一致，仅参数列表不同。
    """
    import warnings
    warnings.warn(
        "build_analysis_prompt_legacy is deprecated, use build_analysis_prompt(ctx: AnalysisContext) instead",
        DeprecationWarning,
        stacklevel=2,
    )
    ctx = AnalysisContext(
        pr_context=pr_context,
        diff_context=diff_context,
        file_context=file_context,
        experts=experts,
        custom_rules=custom_rules,
        incremental_context=incremental_context,
        team_rules=team_rules or [],
        cross_file_context=cross_file_context,
        call_chain_context=call_chain_context,
        impact_graph_context=impact_graph_context,
        similar_reviews_context=similar_reviews_context,
    )
    return build_analysis_prompt(ctx)
