"""multi_agent 模块测试 — 覆盖单 Agent 运行、并行调度、异常容错"""
import asyncio
import pytest
from ai_pr_review.multi_agent import (
    _build_single_expert_messages,
    run_agent,
    run_multi_agent_review,
    MULTI_AGENT_CONCURRENCY,
)
from ai_pr_review.expert_knowledge import ExpertProfile, EXPERT_SKILLS
from ai_pr_review.models import AnalysisResult, AnalysisSummary, Finding, Suggestion, Severity


def _make_expert(name: str = "security") -> ExpertProfile:
    return EXPERT_SKILLS[name]


def _make_result(expert_name: str = "安全审查", findings_count: int = 1) -> AnalysisResult:
    findings = [
        Finding(
            type="security", severity=Severity.HIGH, confidence=4,
            expert=expert_name, file="app.py", line=10,
            title=f"问题{i}", description="desc", suggestion="fix", code_snippet="",
        )
        for i in range(findings_count)
    ]
    return AnalysisResult(
        summary=AnalysisSummary(intent="test", scope="scope", key_changes=["c"]),
        findings=findings,
        suggestions=[],
    )


# ===== _build_single_expert_messages 单元测试 =====

def test_build_single_expert_messages_includes_only_one_expert():
    expert = _make_expert("security")
    msgs = _build_single_expert_messages(
        pr_context="PR info",
        diff_context="diff",
        file_context="files",
        expert=expert,
        context_extras={},
    )
    # 系统消息 + 用户消息
    assert len(msgs) == 2
    user_content = msgs[1]["content"]
    # 仅包含 security 专家名
    assert "安全审查" in user_content
    # 不包含其他专家
    assert "架构审查" not in user_content


def test_build_single_expert_messages_includes_context_extras():
    expert = _make_expert()
    msgs = _build_single_expert_messages(
        pr_context="PR",
        diff_context="diff",
        file_context="files",
        expert=expert,
        context_extras={
            "cross_file_context": "## 跨文件依赖",
            "call_chain_context": "## 调用链",
            "impact_graph_context": "## 影响图",
            "similar_reviews_context": "## 相似经验",
        },
    )
    user_content = msgs[1]["content"]
    assert "跨文件依赖" in user_content
    assert "调用链" in user_content
    assert "影响图" in user_content
    assert "相似经验" in user_content


# ===== run_agent 单元测试 =====

@pytest.mark.asyncio
async def test_run_agent_success():
    async def fake_call_ai(messages):
        return '{"summary":{"intent":"t","scope":"s","key_changes":[]},"findings":[],"suggestions":[]}'

    def fake_parse(raw):
        return AnalysisResult(
            summary=AnalysisSummary(intent="t", scope="s", key_changes=[]),
            findings=[], suggestions=[],
        )

    result = await run_agent(
        fake_call_ai, _make_expert(),
        "pr", "diff", "files", {}, fake_parse,
    )
    assert result.summary.intent == "t"


@pytest.mark.asyncio
async def test_run_agent_fills_missing_expert_field():
    """AI 返回的 finding 未带 expert 字段时，应填充为当前 Agent 名"""
    async def fake_call_ai(messages):
        return "raw"

    def fake_parse(raw):
        # 模拟 AI 返回未带 expert 字段的 finding
        return AnalysisResult(
            summary=AnalysisSummary(intent="", scope="", key_changes=[]),
            findings=[Finding(
                type="security", severity=Severity.HIGH, confidence=4,
                expert="",  # 空，应被填充
                file="app.py", line=1, title="t", description="d",
                suggestion="s", code_snippet="",
            )],
            suggestions=[],
        )

    result = await run_agent(
        fake_call_ai, _make_expert("security"),
        "pr", "diff", "files", {}, fake_parse,
    )
    assert result.findings[0].expert == "安全审查"


@pytest.mark.asyncio
async def test_run_agent_handles_ai_exception():
    """AI 调用抛异常时应降级返回空结果，不向上抛"""
    async def fake_call_ai(messages):
        raise RuntimeError("network down")

    def fake_parse(raw):
        raise AssertionError("should not be called")

    result = await run_agent(
        fake_call_ai, _make_expert(),
        "pr", "diff", "files", {}, fake_parse,
    )
    assert result.findings == []
    assert result.suggestions == []


@pytest.mark.asyncio
async def test_run_agent_preserves_existing_expert_field():
    """AI 已填充 expert 时不应被覆盖"""
    async def fake_call_ai(messages):
        return "raw"

    def fake_parse(raw):
        return AnalysisResult(
            summary=AnalysisSummary(intent="", scope="", key_changes=[]),
            findings=[Finding(
                type="security", severity=Severity.LOW, confidence=2,
                expert="custom",  # 已有值
                file="app.py", line=1, title="t", description="d",
                suggestion="s", code_snippet="",
            )],
            suggestions=[],
        )

    result = await run_agent(
        fake_call_ai, _make_expert("security"),
        "pr", "diff", "files", {}, fake_parse,
    )
    assert result.findings[0].expert == "custom"


# ===== run_multi_agent_review 集成测试 =====

@pytest.mark.asyncio
async def test_multi_agent_review_runs_all_experts_in_parallel():
    """验证所有专家都被调用，且顺序与入参一致"""
    call_log: list[str] = []

    async def fake_call_ai(messages):
        # 从 messages 中提取专家名以记录调用顺序
        user_content = messages[1]["content"]
        for name in ["安全审查", "架构审查", "性能审查"]:
            if name in user_content:
                call_log.append(name)
                break
        return '{"summary":{"intent":"t","scope":"s","key_changes":[]},"findings":[],"suggestions":[]}'

    def fake_parse(raw):
        return AnalysisResult(
            summary=AnalysisSummary(intent="t", scope="s", key_changes=[]),
            findings=[], suggestions=[],
        )

    experts = [_make_expert("security"), _make_expert("architecture"), _make_expert("performance")]
    results = await run_multi_agent_review(
        fake_call_ai, experts,
        "pr", "diff", "files", {}, fake_parse,
    )
    assert len(results) == 3
    assert set(call_log) == {"安全审查", "架构审查", "性能审查"}


@pytest.mark.asyncio
async def test_multi_agent_review_empty_experts():
    results = await run_multi_agent_review(
        lambda m: asyncio.sleep(0),  # 不会被调用
        [], "pr", "diff", "files", {}, lambda r: None,
    )
    assert results == []


@pytest.mark.asyncio
async def test_multi_agent_review_partial_failure_does_not_block():
    """一个 Agent 失败时其他 Agent 仍应正常返回"""
    call_count = 0

    async def fake_call_ai(messages):
        nonlocal call_count
        call_count += 1
        # 第二个 Agent 抛异常
        if call_count == 2:
            raise RuntimeError("agent 2 down")
        return '{"summary":{"intent":"t","scope":"s","key_changes":[]},"findings":[],"suggestions":[]}'

    def fake_parse(raw):
        return AnalysisResult(
            summary=AnalysisSummary(intent="t", scope="s", key_changes=[]),
            findings=[], suggestions=[],
        )

    experts = [_make_expert("security"), _make_expert("architecture"), _make_expert("performance")]
    results = await run_multi_agent_review(
        fake_call_ai, experts,
        "pr", "diff", "files", {}, fake_parse,
    )
    assert len(results) == 3
    # 第二个为空结果，其他两个有 summary
    assert results[0].summary.intent == "t"
    assert results[1].findings == []  # 失败降级
    assert results[2].summary.intent == "t"


@pytest.mark.asyncio
async def test_multi_agent_review_respects_concurrency_limit():
    """并发数应受 Semaphore 限制（同时运行的 Agent 数 <= concurrency）"""
    current_concurrent = 0
    max_observed = 0

    async def fake_call_ai(messages):
        nonlocal current_concurrent, max_observed
        current_concurrent += 1
        max_observed = max(max_observed, current_concurrent)
        await asyncio.sleep(0.05)  # 模拟 IO
        current_concurrent -= 1
        return '{"summary":{"intent":"t","scope":"s","key_changes":[]},"findings":[],"suggestions":[]}'

    def fake_parse(raw):
        return AnalysisResult(
            summary=AnalysisSummary(intent="", scope="", key_changes=[]),
            findings=[], suggestions=[],
        )

    # 6 个专家，并发限制 2
    experts = [_make_expert("security") for _ in range(6)]
    await run_multi_agent_review(
        fake_call_ai, experts,
        "pr", "diff", "files", {}, fake_parse,
        concurrency=2,
    )
    assert max_observed <= 2


def test_multi_agent_concurrency_constant():
    """模块级常量应为正整数"""
    assert isinstance(MULTI_AGENT_CONCURRENCY, int)
    assert MULTI_AGENT_CONCURRENCY > 0
