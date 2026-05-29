import json
import re
import logging
from openai import AsyncOpenAI
from ai_pr_review.models import (
    ParsedDiff,
    PRMetadata,
    AnalysisResult,
    AnalysisSummary,
    Finding,
    Suggestion,
    Severity,
)
from ai_pr_review.config import AppConfig
from ai_pr_review.context_builder import ContextBuilder
from ai_pr_review.expert_knowledge import select_experts, get_expert_profiles
from ai_pr_review.prompt_templates import build_analysis_prompt

logger = logging.getLogger(__name__)


def parse_ai_response(raw: str) -> AnalysisResult:
    json_match = re.search(r"```(?:json)?\s*\n?(.*?)\n?```", raw, re.DOTALL)
    if json_match:
        raw = json_match.group(1).strip()

    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        logger.warning("Failed to parse AI response as JSON")
        return AnalysisResult(
            summary=AnalysisSummary(intent="", scope="", key_changes=[]),
            findings=[],
            suggestions=[],
        )

    summary = AnalysisSummary(
        intent=data.get("summary", {}).get("intent", ""),
        scope=data.get("summary", {}).get("scope", ""),
        key_changes=data.get("summary", {}).get("key_changes", []),
    )

    findings = []
    for f in data.get("findings", []):
        try:
            findings.append(
                Finding(
                    type=f.get("type", "quality"),
                    severity=Severity(f.get("severity", "low")),
                    confidence=int(f.get("confidence", 3)),
                    expert=f.get("expert", ""),
                    file=f.get("file", ""),
                    line=int(f.get("line", 0)),
                    title=f.get("title", ""),
                    description=f.get("description", ""),
                    suggestion=f.get("suggestion", ""),
                    code_snippet=f.get("code_snippet", ""),
                )
            )
        except (ValueError, TypeError):
            continue

    suggestions = []
    for s in data.get("suggestions", []):
        try:
            suggestions.append(
                Suggestion(
                    category=s.get("category", ""),
                    priority=Severity(s.get("priority", "low")),
                    description=s.get("description", ""),
                    example=s.get("example", ""),
                )
            )
        except (ValueError, TypeError):
            continue

    return AnalysisResult(summary=summary, findings=findings, suggestions=suggestions)


class AIAnalyzer:
    def __init__(self, config: AppConfig, get_file_content_fn=None):
        self._config = config
        self._client = AsyncOpenAI(
            api_key=config.ai.api_key,
            base_url=config.ai.base_url,
        )
        self._context_builder = ContextBuilder(config, get_file_content_fn)

    async def analyze(
        self,
        pr_metadata: PRMetadata,
        parsed_diff: ParsedDiff,
        severity_threshold: str = "low",
        focus: list[str] | None = None,
    ) -> AnalysisResult:
        context = self._context_builder.build_context(pr_metadata, parsed_diff)

        file_paths = [f.path for f in parsed_diff.files]
        hunks_content = "\n".join(
            h.content for f in parsed_diff.files for h in f.hunks
        )
        expert_names = select_experts(file_paths, hunks_content)
        experts = get_expert_profiles(expert_names)

        messages = build_analysis_prompt(
            pr_context=context.get("pr_metadata", ""),
            diff_context=context.get("diff", ""),
            file_context=context.get("file_contents", ""),
            experts=experts,
        )

        raw_response = await self._call_ai(messages)
        result = parse_ai_response(raw_response)

        result = self._apply_filters(result, severity_threshold, focus)

        return result

    async def _call_ai(self, messages: list[dict[str, str]]) -> str:
        try:
            response = await self._client.chat.completions.create(
                model=self._config.ai.model,
                messages=messages,
                max_tokens=self._config.ai.max_tokens,
                temperature=self._config.ai.temperature,
            )
            return response.choices[0].message.content or ""
        except Exception as e:
            logger.error(f"AI API call failed: {e}")
            return ""

    def _apply_filters(
        self,
        result: AnalysisResult,
        severity_threshold: str,
        focus: list[str] | None,
    ) -> AnalysisResult:
        severity_order = {"low": 0, "medium": 1, "high": 2}
        min_severity = severity_order.get(severity_threshold, 0)

        filtered_findings = [
            f
            for f in result.findings
            if severity_order.get(f.severity.value, 0) >= min_severity
            and f.confidence >= 3
        ]

        if focus:
            filtered_findings = [
                f for f in filtered_findings if f.type in focus or f.expert in focus
            ]

        result.findings = filtered_findings
        return result
