import json
import re
import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone
from openai import AsyncOpenAI
from ai_pr_review.config import AppConfig

logger = logging.getLogger(__name__)


@dataclass
class TeamRule:
    category: str
    description: str
    example: str
    weight: float = 1.0
    source: str = ""
    frequency: int = 1


@dataclass
class TeamPattern:
    rules: list[TeamRule]
    common_terms: list[str]
    severity_preference: dict
    focus_areas: list[str]
    repo_url: str = ""
    learned_at: str = ""

    def __post_init__(self):
        if not self.learned_at:
            self.learned_at = datetime.now(timezone.utc).isoformat()


EXTRACTION_SYSTEM_PROMPT = """你是一位代码审查模式分析专家。分析团队在PR审查中留下的评论，提取审查模式。

规则：
- 提取团队反复关注的审查规则
- 识别团队常用的审查术语和表达
- 推断团队对不同严重级别问题的关注偏好
- 识别团队重点关注的领域
- 每条规则标注类别(security/performance/style/testing/architecture/custom)
- 每条规则标注出现频率(1-5)
- 忽略无意义的评论（如"LGTM"、"+1"、纯表情）
"""

EXTRACTION_OUTPUT_SCHEMA = """\
输出严格JSON格式（无其他内容）：

```json
{
  "rules": [
    {
      "category": "security|performance|style|testing|architecture|custom",
      "description": "规则描述",
      "example": "示例代码或模式",
      "frequency": 1-5
    }
  ],
  "common_terms": ["团队常用术语1", "术语2"],
  "severity_preference": {
    "P0": 0.0-1.0,
    "P1": 0.0-1.0,
    "P2": 0.0-1.0,
    "P3": 0.0-1.0
  },
  "focus_areas": ["关注领域1", "领域2"]
}
```\
"""


class TeamLearner:
    def __init__(self, config: AppConfig):
        self._client = AsyncOpenAI(
            api_key=config.ai.api_key,
            base_url=config.ai.base_url,
        )
        self._model = config.ai.model
        self._max_tokens = config.ai.max_tokens
        self._temperature = config.ai.temperature

    async def extract_patterns(self, comments: list[dict]) -> TeamPattern:
        filtered = self._filter_comments(comments)
        if not filtered:
            return TeamPattern(
                rules=[],
                common_terms=[],
                severity_preference={},
                focus_areas=[],
            )

        messages = self._build_extraction_prompt(filtered)
        raw = await self._call_ai(messages)
        return self._parse_pattern(raw)

    def _filter_comments(self, comments: list[dict]) -> list[dict]:
        filtered = []
        for c in comments:
            author = c.get("author", "").lower()
            if "bot" in author or "ai-review" in author:
                continue
            body = c.get("body", "").strip()
            if len(body) < 10:
                continue
            filtered.append(c)
        return filtered[:100]

    def _build_extraction_prompt(self, comments: list[dict]) -> list[dict]:
        comments_text_parts = []
        for c in comments:
            pr_info = f"PR#{c.get('pr_number', '?')} {c.get('pr_title', '')}"
            file_info = f" ({c.get('file', '')}:{c.get('line', '')})" if c.get("file") else ""
            comments_text_parts.append(
                f"[{pr_info}{file_info}] @{c.get('author', '')}: {c.get('body', '')}"
            )
        comments_text = "\n".join(comments_text_parts)

        if len(comments_text) > 8000:
            comments_text = comments_text[:8000] + "\n...(truncated)"

        user_content = (
            f"以下是团队在 {len(comments)} 条PR审查评论中的内容：\n\n"
            f"{comments_text}\n\n"
            f"{EXTRACTION_OUTPUT_SCHEMA}"
        )

        return [
            {"role": "system", "content": EXTRACTION_SYSTEM_PROMPT},
            {"role": "user", "content": user_content},
        ]

    def _parse_pattern(self, raw: str) -> TeamPattern:
        json_match = re.search(r"```(?:json)?\s*\n?(.*?)\n?```", raw, re.DOTALL)
        if json_match:
            raw = json_match.group(1).strip()

        try:
            data = json.loads(raw)
        except json.JSONDecodeError:
            logger.warning("Failed to parse team pattern as JSON")
            return TeamPattern(
                rules=[],
                common_terms=[],
                severity_preference={},
                focus_areas=[],
            )

        rules = []
        for r in data.get("rules", []):
            freq = int(r.get("frequency", 1))
            weight = min(2.0, 0.3 + freq * 0.3)
            rules.append(TeamRule(
                category=r.get("category", "custom"),
                description=r.get("description", ""),
                example=r.get("example", ""),
                weight=weight,
                source="learned",
                frequency=freq,
            ))

        return TeamPattern(
            rules=rules,
            common_terms=data.get("common_terms", []),
            severity_preference=data.get("severity_preference", {}),
            focus_areas=data.get("focus_areas", []),
        )

    async def _call_ai(self, messages: list[dict[str, str]]) -> str:
        try:
            response = await self._client.chat.completions.create(
                model=self._model,
                messages=messages,
                max_tokens=min(self._max_tokens, 4000),
                temperature=self._temperature,
            )
            return response.choices[0].message.content or ""
        except Exception as e:
            logger.error(f"Team learning AI call failed: {e}")
            return ""
