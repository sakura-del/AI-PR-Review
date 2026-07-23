"""多 Agent 并行审查协调器

设计目标：
- 为每个被选中的专家独立调用 AI（每个 Agent 仅看自己领域的 checklist）
- 使用 asyncio.gather + Semaphore 并行调度，复用 analyzer 的 _call_ai 重试机制
- 单个 Agent 失败不影响其他 Agent，降级返回空结果
- 仅当多 Agent 模式启用时调用，默认仍走单 Agent 路径
"""
import asyncio
import logging
from ai_pr_review.models import (
    ParsedDiff, PRMetadata, AnalysisResult, AnalysisSummary,
    Finding, Suggestion, Severity,
)
from ai_pr_review.expert_knowledge import ExpertProfile
from ai_pr_review.prompt_templates import build_analysis_prompt

logger = logging.getLogger(__name__)

# 多 Agent 并行最大并发数（与分片并发一致，避免叠加触发限流）
MULTI_AGENT_CONCURRENCY = 3


def _build_single_expert_messages(
    pr_context: str,
    diff_context: str,
    file_context: str,
    expert: ExpertProfile,
    context_extras: dict[str, str],
) -> list[dict[str, str]]:
    """为单个专家构建专属 prompt（仅包含该专家的 checklist）

    与默认 build_analysis_prompt 区别：experts 参数只传当前 Agent，
    使 AI 聚焦于单一领域的审查标准，提升深度。
    """
    return build_analysis_prompt(
        pr_context=pr_context,
        diff_context=diff_context,
        file_context=file_context,
        experts=[expert],
        custom_rules=None,
        team_rules=None,
        cross_file_context=context_extras.get("cross_file_context", ""),
        call_chain_context=context_extras.get("call_chain_context", ""),
        impact_graph_context=context_extras.get("impact_graph_context", ""),
        similar_reviews_context=context_extras.get("similar_reviews_context", ""),
    )


async def run_agent(
    call_ai_fn,
    expert: ExpertProfile,
    pr_context: str,
    diff_context: str,
    file_context: str,
    context_extras: dict[str, str],
    parse_response_fn,
) -> AnalysisResult:
    """运行单个专家 Agent，返回该 Agent 的审查结果

    - call_ai_fn: 异步函数，接收 messages 返回 raw_response 字符串
    - parse_response_fn: 解析函数（analyzer.parse_ai_response）
    - 任意异常都被捕获并返回空结果，避免单点失败拖垮整体
    """
    try:
        messages = _build_single_expert_messages(
            pr_context, diff_context, file_context, expert, context_extras
        )
        raw = await call_ai_fn(messages)
        result = parse_response_fn(raw)
        # 标记每条 finding 的 expert 字段，便于后续聚合做共识统计
        for f in result.findings:
            if not f.expert:
                f.expert = expert.name
        return result
    except Exception as e:
        logger.warning(f"Agent {expert.name} failed: {e}")
        return AnalysisResult(
            summary=AnalysisSummary(intent="", scope="", key_changes=[]),
            findings=[],
            suggestions=[],
        )


async def run_multi_agent_review(
    call_ai_fn,
    experts: list[ExpertProfile],
    pr_context: str,
    diff_context: str,
    file_context: str,
    context_extras: dict[str, str],
    parse_response_fn,
    concurrency: int = MULTI_AGENT_CONCURRENCY,
) -> list[AnalysisResult]:
    """并行调度多个专家 Agent

    返回每个 Agent 的独立结果列表（顺序与 experts 入参一致）。
    聚合由 aggregator 模块统一处理，此处仅负责调度。
    """
    if not experts:
        return []

    semaphore = asyncio.Semaphore(concurrency)

    async def _limited_run(expert: ExpertProfile) -> AnalysisResult:
        async with semaphore:
            return await run_agent(
                call_ai_fn, expert,
                pr_context, diff_context, file_context,
                context_extras, parse_response_fn,
            )

    tasks = [_limited_run(e) for e in experts]
    # return_exceptions=True 已经在 run_agent 内部处理，此处再保一层防御
    return await asyncio.gather(*tasks)
