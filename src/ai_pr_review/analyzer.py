import json
import re
import asyncio
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
from ai_pr_review.config import AppConfig, load_project_config
from ai_pr_review.context_builder import ContextBuilder
from ai_pr_review.expert_knowledge import select_experts, get_expert_profiles, merge_expert_config
from ai_pr_review.prompt_templates import build_analysis_prompt
from ai_pr_review.team_rules import load_team_pattern, merge_team_rules

logger = logging.getLogger(__name__)

SHARD_FILE_THRESHOLD = 20
SHARD_LINE_THRESHOLD = 5000


def _normalize_severity(value: str) -> Severity:
    p_map = {"P0": Severity.HIGH, "P1": Severity.MEDIUM, "P2": Severity.MEDIUM, "P3": Severity.LOW}
    if value in p_map:
        return p_map[value]
    try:
        return Severity(value)
    except ValueError:
        return Severity.LOW


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
                    severity=_normalize_severity(f.get("severity", "low")),
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
                    priority=_normalize_severity(s.get("priority", "low")),
                    description=s.get("description", ""),
                    example=s.get("example", ""),
                )
            )
        except (ValueError, TypeError):
            continue

    return AnalysisResult(summary=summary, findings=findings, suggestions=suggestions)


class AIAnalyzer:
    def __init__(self, config: AppConfig, get_file_content_fn=None, repo_url: str = ""):
        self._config = config
        self._client = AsyncOpenAI(
            api_key=config.ai.api_key,
            base_url=config.ai.base_url,
        )
        self._context_builder = ContextBuilder(config, get_file_content_fn)
        self._project_config = load_project_config()
        self._merged_skills = merge_expert_config(self._project_config)
        self._custom_rules = self._project_config.custom_rules
        self._custom_expert_keys = list(self._project_config.custom_experts.keys())
        self._team_rules = self._load_team_rules(repo_url)

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
        expert_names = select_experts(file_paths, hunks_content, self._custom_expert_keys)
        experts = get_expert_profiles(expert_names, self._merged_skills)

        messages = build_analysis_prompt(
            pr_context=context.get("pr_metadata", ""),
            diff_context=context.get("diff", ""),
            file_context=context.get("file_contents", ""),
            experts=experts,
            custom_rules=self._custom_rules,
            team_rules=self._team_rules if self._team_rules else None,
        )

        raw_response = await self._call_ai(messages)
        result = parse_ai_response(raw_response)

        result = self._apply_filters(result, severity_threshold, focus, self._config.analysis.min_confidence)

        return result

    async def analyze_incremental(
        self,
        pr_metadata: PRMetadata,
        incremental_parsed_diff: ParsedDiff,
        incremental_context: dict,
        severity_threshold: str = "low",
        focus: list[str] | None = None,
    ) -> AnalysisResult:
        context = self._context_builder.build_context(pr_metadata, incremental_parsed_diff)

        file_paths = [f.path for f in incremental_parsed_diff.files]
        hunks_content = "\n".join(
            h.content for f in incremental_parsed_diff.files for h in f.hunks
        )
        expert_names = select_experts(file_paths, hunks_content, self._custom_expert_keys)
        experts = get_expert_profiles(expert_names, self._merged_skills)

        messages = build_analysis_prompt(
            pr_context=context.get("pr_metadata", ""),
            diff_context=context.get("diff", ""),
            file_context=context.get("file_contents", ""),
            experts=experts,
            custom_rules=self._custom_rules,
            incremental_context=incremental_context,
            team_rules=self._team_rules if self._team_rules else None,
        )

        raw_response = await self._call_ai(messages)
        result = parse_ai_response(raw_response)
        result = self._apply_filters(result, severity_threshold, focus, self._config.analysis.min_confidence)
        return result

    def _load_team_rules(self, repo_url: str) -> list:
        from ai_pr_review.team_learner import TeamRule
        if not repo_url:
            return []
        ttl = self._project_config.team_learning.rule_ttl_days
        team_pattern = load_team_pattern(repo_url, ttl_days=ttl)
        if not team_pattern:
            return []
        min_weight = self._project_config.team_learning.min_rule_weight
        rules = merge_team_rules(team_pattern, self._custom_rules)
        return [r for r in rules if r.weight >= min_weight]

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

    async def analyze_stream(self, pr_metadata: PRMetadata, parsed_diff: ParsedDiff, severity_threshold: str = "low", focus: list[str] | None = None):
        context = self._context_builder.build_context(pr_metadata, parsed_diff)

        file_paths = [f.path for f in parsed_diff.files]
        hunks_content = "\n".join(h.content for f in parsed_diff.files for h in f.hunks)
        expert_names = select_experts(file_paths, hunks_content, self._custom_expert_keys)
        experts = get_expert_profiles(expert_names, self._merged_skills)

        messages = build_analysis_prompt(
            pr_context=context.get("pr_metadata", ""),
            diff_context=context.get("diff", ""),
            file_context=context.get("file_contents", ""),
            experts=experts,
            custom_rules=self._custom_rules,
            team_rules=self._team_rules if self._team_rules else None,
        )

        full_response = ""
        try:
            stream = await self._client.chat.completions.create(
                model=self._config.ai.model,
                messages=messages,
                max_tokens=self._config.ai.max_tokens,
                temperature=self._config.ai.temperature,
                stream=True,
            )
            async for chunk in stream:
                if chunk.choices and chunk.choices[0].delta.content:
                    content = chunk.choices[0].delta.content
                    full_response += content
                    yield content
        except Exception as e:
            logger.error(f"Streaming AI call failed: {e}")
            yield ""

        result = parse_ai_response(full_response)
        result = self._apply_filters(result, severity_threshold, focus, self._config.analysis.min_confidence)
        yield ("__RESULT__", result)

    def _apply_filters(
        self,
        result: AnalysisResult,
        severity_threshold: str,
        focus: list[str] | None,
        min_confidence: int = 2,
    ) -> AnalysisResult:
        severity_order = {"low": 0, "medium": 1, "high": 2}
        min_severity = severity_order.get(severity_threshold, 0)

        filtered_findings = [
            f
            for f in result.findings
            if severity_order.get(f.severity.value, 0) >= min_severity
            and f.confidence >= min_confidence
        ]

        if focus:
            filtered_findings = [
                f for f in filtered_findings if f.type in focus or f.expert in focus
            ]

        result.findings = filtered_findings
        return result

    @staticmethod
    def _should_shard(parsed_diff: ParsedDiff) -> bool:
        file_count = len(parsed_diff.files)
        total_lines = parsed_diff.total_additions + parsed_diff.total_deletions
        return file_count > SHARD_FILE_THRESHOLD or total_lines > SHARD_LINE_THRESHOLD

    @staticmethod
    def _shard_diff(parsed_diff: ParsedDiff) -> list[ParsedDiff]:
        files = parsed_diff.files
        shard_size = max(1, len(files) // 3)
        shards = []
        for i in range(0, len(files), shard_size):
            shard_files = files[i : i + shard_size]
            shard_additions = sum(f.additions for f in shard_files)
            shard_deletions = sum(f.deletions for f in shard_files)
            shards.append(ParsedDiff(
                files=shard_files,
                total_additions=shard_additions,
                total_deletions=shard_deletions,
            ))
        return shards

    async def _analyze_shard(self, pr_metadata: PRMetadata, shard: ParsedDiff, severity_threshold: str, focus: list[str] | None) -> AnalysisResult:
        context = self._context_builder.build_context(pr_metadata, shard)

        file_paths = [f.path for f in shard.files]
        hunks_content = "\n".join(h.content for f in shard.files for h in f.hunks)
        expert_names = select_experts(file_paths, hunks_content, self._custom_expert_keys)
        experts = get_expert_profiles(expert_names, self._merged_skills)

        messages = build_analysis_prompt(
            pr_context=context.get("pr_metadata", ""),
            diff_context=context.get("diff", ""),
            file_context=context.get("file_contents", ""),
            experts=experts,
            custom_rules=self._custom_rules,
            team_rules=self._team_rules if self._team_rules else None,
        )

        raw_response = await self._call_ai(messages)
        result = parse_ai_response(raw_response)
        result = self._apply_filters(result, severity_threshold, focus, self._config.analysis.min_confidence)
        return result

    async def analyze_with_shards(
        self,
        pr_metadata: PRMetadata,
        parsed_diff: ParsedDiff,
        severity_threshold: str = "low",
        focus: list[str] | None = None,
    ) -> AnalysisResult:
        if not self._should_shard(parsed_diff):
            return await self.analyze(pr_metadata, parsed_diff, severity_threshold, focus)

        logger.info(f"Large PR detected ({len(parsed_diff.files)} files), sharding analysis")
        shards = self._shard_diff(parsed_diff)
        logger.info(f"Split into {len(shards)} shards")

        tasks = [self._analyze_shard(pr_metadata, shard, severity_threshold, focus) for shard in shards]
        results = await asyncio.gather(*tasks)

        return self._merge_shard_results(results)

    async def analyze_with_shards_stream(
        self,
        pr_metadata: PRMetadata,
        parsed_diff: ParsedDiff,
        severity_threshold: str = "low",
        focus: list[str] | None = None,
    ):
        if not self._should_shard(parsed_diff):
            async for chunk in self.analyze_stream(pr_metadata, parsed_diff, severity_threshold, focus):
                yield chunk
            return

        logger.info(f"Large PR detected ({len(parsed_diff.files)} files), streaming with sharding")
        shards = self._shard_diff(parsed_diff)
        logger.info(f"Split into {len(shards)} shards")

        all_results = []
        for i, shard in enumerate(shards):
            yield f"\n📦 Shard {i + 1}/{len(shards)}\n"

            shard_result = None
            async for chunk in self.analyze_stream(pr_metadata, shard, severity_threshold, focus):
                if isinstance(chunk, tuple) and chunk[0] == "__RESULT__":
                    shard_result = chunk[1]
                else:
                    yield chunk

            if shard_result:
                all_results.append(shard_result)

        merged = self._merge_shard_results(all_results)
        yield ("__RESULT__", merged)

    @staticmethod
    def _merge_shard_results(results: list[AnalysisResult]) -> AnalysisResult:
        all_findings = []
        all_suggestions = []
        key_changes = []

        for result in results:
            all_findings.extend(result.findings)
            all_suggestions.extend(result.suggestions)
            key_changes.extend(result.summary.key_changes)

        all_findings.sort(key=lambda f: (f.file, f.line))
        deduplicated = []
        seen = set()
        for f in all_findings:
            key = (f.file, f.line, f.title[:50])
            if key not in seen:
                seen.add(key)
                deduplicated.append(f)

        summary = AnalysisSummary(
            intent=results[0].summary.intent if results else "",
            scope=f"Merged from {len(results)} shards",
            key_changes=key_changes[:10],
        )

        return AnalysisResult(summary=summary, findings=deduplicated, suggestions=all_suggestions)
