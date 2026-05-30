import json
from ai_pr_review.expert_knowledge import ExpertProfile


SYSTEM_PROMPT = """你是一位代码审查专家。根据PR变更进行专业审查。

规则：
- 每个发现必须关联具体的文件路径和行号
- 使用P0-P3严重级别：P0=安全/致命问题(阻止合并), P1=重要问题(合并前修复), P2=代码味道(建议修复), P3=可选优化
- 每个发现必须包含置信度(1-5)和修复代码示例
- 忽略：风格偏好、注释缺失、无实际价值的泛泛建议
- 优先报告：安全问题、逻辑错误、性能问题、测试缺失
"""


OUTPUT_SCHEMA = """\
输出严格JSON格式（无其他内容）：

```json
{
  "summary": {
    "intent": "变更意图",
    "scope": "影响范围",
    "changes": ["关键修改点"]
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
      "fix": "修复代码"
    }
  ],
  "suggestions": [
    {
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
    "changes": ["新增auth.py", "修改db.py使用参数化查询"]
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
      "fix": "SECRET = os.environ.get('JWT_SECRET')"
    }
  ],
  "suggestions": [
    {
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


def build_analysis_prompt(
    pr_context: str,
    diff_context: str,
    file_context: str,
    experts: list[ExpertProfile],
    custom_rules: list[str] | None = None,
) -> list[dict[str, str]]:
    expert_context = build_expert_context(experts)

    user_content_parts = [
        "## PR信息\n" + pr_context,
        "\n## 代码变更\n" + diff_context,
    ]

    if file_context:
        user_content_parts.append("\n## 相关文件\n" + file_context)

    user_content_parts.append("\n## 审查规则\n" + expert_context)

    if custom_rules:
        rules_text = "\n".join(f"- {r}" for r in custom_rules)
        user_content_parts.append("\n## 团队自定义规则\n" + rules_text)

    user_content_parts.append("\n" + OUTPUT_SCHEMA)
    user_content_parts.append("\n" + FEW_SHOT_EXAMPLE)

    messages = [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": "\n".join(user_content_parts)},
    ]

    return messages
