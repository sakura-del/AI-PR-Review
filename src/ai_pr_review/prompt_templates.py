import json
from ai_pr_review.expert_knowledge import ExpertProfile


SYSTEM_PROMPT = """你是一位代码审查专家团队的组织者。你将根据提供的专家知识清单，对Pull Request的代码变更进行专业、深入的审查。

核心原则：
1. 每个发现必须关联到具体的代码行号和文件
2. 每个发现必须给出置信度评分(1-5)和严重级别(high/medium/low)
3. 每个发现必须映射到某个专家的checklist项
4. 避免泛泛建议，只报告有实际价值的问题
5. 不要报告风格偏好问题（如单引号vs双引号）
6. 不要报告缺少注释等低价值建议
7. 每个建议必须附带具体的修复代码示例
"""

OUTPUT_SCHEMA = """\
请严格按照以下JSON格式输出，不要包含任何其他文字：

```json
{
  "summary": {
    "intent": "本次PR的变更意图（一句话）",
    "scope": "变更影响范围",
    "key_changes": ["关键修改点1", "关键修改点2"]
  },
  "findings": [
    {
      "type": "risk|quality|testing",
      "severity": "high|medium|low",
      "confidence": 1-5,
      "expert": "security|architecture|performance|readability|testing",
      "file": "文件路径",
      "line": 行号,
      "title": "发现标题",
      "description": "详细描述",
      "suggestion": "修复建议",
      "code_snippet": "相关代码片段"
    }
  ],
  "suggestions": [
    {
      "category": "分类",
      "priority": "high|medium|low",
      "description": "改进建议描述",
      "example": "代码示例"
    }
  ]
}
```\
"""

FEW_SHOT_EXAMPLE = """
示例输出（仅供参考格式）：

```json
{
  "summary": {
    "intent": "添加JWT认证功能",
    "scope": "认证模块",
    "key_changes": ["新增auth.py实现JWT生成和验证", "修改db.py使用参数化查询"]
  },
  "findings": [
    {
      "type": "risk",
      "severity": "high",
      "confidence": 5,
      "expert": "security",
      "file": "auth.py",
      "line": 4,
      "title": "硬编码JWT密钥",
      "description": "JWT密钥直接硬编码在源代码中，存在泄露风险",
      "suggestion": "使用环境变量存储密钥",
      "code_snippet": "SECRET = 'hardcoded-secret'"
    }
  ],
  "suggestions": [
    {
      "category": "security",
      "priority": "high",
      "description": "将所有敏感配置移至环境变量",
      "example": "SECRET = os.environ.get('JWT_SECRET')"
    }
  ]
}
```\
"""


def build_expert_context(experts: list[ExpertProfile]) -> str:
    parts = ["当前启用的审查专家及其检查清单：\n"]
    for expert in experts:
        parts.append(f"## {expert.name}")
        parts.append(f"知识来源：{expert.knowledge_source}")
        parts.append("\n检查清单：")
        for item in expert.checklist:
            parts.append(f"  - {item}")
        parts.append("\n高风险信号（Red Flags）：")
        for flag in expert.red_flags:
            parts.append(f"  - {flag}")
        parts.append("")
    return "\n".join(parts)


def build_analysis_prompt(
    pr_context: str,
    diff_context: str,
    file_context: str,
    experts: list[ExpertProfile],
) -> list[dict[str, str]]:
    expert_context = build_expert_context(experts)

    user_content_parts = [
        "## PR信息\n" + pr_context,
        "\n## 代码变更\n" + diff_context,
    ]

    if file_context:
        user_content_parts.append("\n## 相关文件内容\n" + file_context)

    user_content_parts.append("\n## 审查专家\n" + expert_context)
    user_content_parts.append("\n" + OUTPUT_SCHEMA)
    user_content_parts.append("\n" + FEW_SHOT_EXAMPLE)

    messages = [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": "\n".join(user_content_parts)},
    ]

    return messages
