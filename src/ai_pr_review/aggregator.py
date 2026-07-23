"""多 Agent 结果聚合器

设计目标：
- 按 (file, line, type) 元组去重，保留信息最完整的版本
- 共识加权：多个 Agent 报告同一问题 → severity 与 confidence 提升
- 同一问题不同建议时合并 suggestion，保留所有方案
- 排序：severity 降序 → confidence 降序 → 共识数降序
"""
import logging
from ai_pr_review.models import (
    AnalysisResult, AnalysisSummary, Finding, Suggestion, Severity,
)

logger = logging.getLogger(__name__)

# 共识加权：N 个 Agent 报告同一问题时的提升规则
CONSENSUS_BOOST_THRESHOLD = 2  # 至少 2 个 Agent 报告才触发提升
# severity 提升映射：low→medium, medium→high（high 不再升）
_SEVERITY_BOOST_MAP = {
    Severity.LOW: Severity.MEDIUM,
    Severity.MEDIUM: Severity.HIGH,
    Severity.HIGH: Severity.HIGH,
}
# confidence 提升幅度（每多一个 Agent 报告，confidence +1，封顶 5）
CONFIDENCE_BOOST_STEP = 1
MAX_CONFIDENCE = 5


def _finding_key(f: Finding) -> tuple:
    """生成去重键：(file, line, type)

    故意不含 title/description，让不同 Agent 对同一位置同类问题的报告能合并。
    """
    return (f.file, f.line, f.type)


def _merge_findings(findings: list[Finding]) -> Finding:
    """合并多个 Agent 对同一问题的发现，保留最完整的信息

    - severity 取最高
    - confidence 取最高 + 共识加成
    - title/description 取最长（信息量最大）
    - suggestion 合并去重，code_snippet 同理
    - expert 字段汇总为 "agent1/agent2/..."
    """
    if not findings:
        raise ValueError("cannot merge empty findings list")
    if len(findings) == 1:
        return findings[0]

    # severity：取最严重的
    severity_order = {Severity.LOW: 0, Severity.MEDIUM: 1, Severity.HIGH: 2}
    max_severity = max(findings, key=lambda f: severity_order.get(f.severity, 0)).severity

    # 共识提升：达到阈值时升级一档
    if len(findings) >= CONSENSUS_BOOST_THRESHOLD:
        max_severity = _SEVERITY_BOOST_MAP[max_severity]

    # confidence：取最大 + 共识加成
    base_confidence = max(f.confidence for f in findings)
    boost = (len(findings) - 1) * CONFIDENCE_BOOST_STEP
    final_confidence = min(base_confidence + boost, MAX_CONFIDENCE)

    # title/description：取最长的（信息量最大）
    best_title = max(findings, key=lambda f: len(f.title)).title
    best_desc = max(findings, key=lambda f: len(f.description)).description

    # suggestion/code_snippet：去重合并
    suggestions = []
    seen_sug = set()
    for f in findings:
        if f.suggestion and f.suggestion not in seen_sug:
            seen_sug.add(f.suggestion)
            suggestions.append(f.suggestion)
    snippets = []
    seen_snip = set()
    for f in findings:
        if f.code_snippet and f.code_snippet not in seen_snip:
            seen_snip.add(f.code_snippet)
            snippets.append(f.code_snippet)

    # expert：汇总所有 Agent 名（去重保序）
    experts = []
    seen_exp = set()
    for f in findings:
        if f.expert and f.expert not in seen_exp:
            seen_exp.add(f.expert)
            experts.append(f.expert)

    return Finding(
        type=findings[0].type,
        severity=max_severity,
        confidence=final_confidence,
        expert="/".join(experts) if experts else "",
        file=findings[0].file,
        line=findings[0].line,
        title=best_title,
        description=best_desc,
        suggestion=" | ".join(suggestions) if suggestions else "",
        code_snippet="\n---\n".join(snippets) if snippets else "",
    )


def aggregate_findings(all_findings: list[Finding]) -> list[Finding]:
    """聚合多个 Agent 的 findings 列表

    步骤：按 _finding_key 分组 → 每组合并 → 按 severity/confidence 排序
    """
    if not all_findings:
        return []

    # 分组：用 dict 而非 defaultdict 以避免空组残留（内存优化）
    groups: dict[tuple, list[Finding]] = {}
    for f in all_findings:
        key = _finding_key(f)
        groups.setdefault(key, []).append(f)

    merged = [_merge_findings(group) for group in groups.values()]

    # 排序：severity 降序 → confidence 降序 → 共识数（expert 字段中 / 分隔的个数）降序
    severity_order = {Severity.HIGH: 2, Severity.MEDIUM: 1, Severity.LOW: 0}

    def _consensus_count(f: Finding) -> int:
        # 通过 expert 字段的 / 数量推断共识数（合并后格式为 "a/b/c"）
        return len(f.expert.split("/")) if f.expert else 1

    merged.sort(
        key=lambda f: (
            severity_order.get(f.severity, 0),
            f.confidence,
            _consensus_count(f),
        ),
        reverse=True,
    )
    return merged


def aggregate_suggestions(all_suggestions: list[Suggestion]) -> list[Suggestion]:
    """聚合多个 Agent 的 suggestions，按 (category, description) 去重"""
    seen: set[tuple[str, str]] = set()
    aggregated: list[Suggestion] = []
    for s in all_suggestions:
        key = (s.category, s.description[:80])  # description 截断后去重，避免长文差异
        if key in seen:
            continue
        seen.add(key)
        aggregated.append(s)
    return aggregated


def aggregate_results(
    agent_results: list[AnalysisResult],
    intent: str = "",
    scope: str = "",
) -> AnalysisResult:
    """聚合多个 Agent 的完整结果为单一 AnalysisResult

    - findings: 去重 + 共识加权 + 排序
    - suggestions: 按 category+description 去重
    - summary: 合并 key_changes（去重保序，限 10 条）
    """
    all_findings: list[Finding] = []
    all_suggestions: list[Suggestion] = []
    key_changes: list[str] = []
    seen_changes: set[str] = set()

    for r in agent_results:
        all_findings.extend(r.findings)
        all_suggestions.extend(r.suggestions)
        for kc in r.summary.key_changes:
            if kc and kc not in seen_changes:
                seen_changes.add(kc)
                key_changes.append(kc)

    merged_findings = aggregate_findings(all_findings)
    merged_suggestions = aggregate_suggestions(all_suggestions)

    # 若入参未指定 intent/scope，从子结果中取最长的
    if not intent:
        intent = max((r.summary.intent for r in agent_results), key=len, default="")
    if not scope:
        scope = max((r.summary.scope for r in agent_results), key=len, default="")

    summary = AnalysisSummary(
        intent=intent,
        scope=scope or f"Multi-agent review ({len(agent_results)} experts)",
        key_changes=key_changes[:10],
    )
    return AnalysisResult(
        summary=summary,
        findings=merged_findings,
        suggestions=merged_suggestions,
    )
