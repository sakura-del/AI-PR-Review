"""adversarial 模块测试 — 覆盖 prompt 构建、verdict 解析、验证流程、结果调整"""
import asyncio
import json
import pytest
from ai_pr_review.adversarial import (
    _build_verification_prompt,
    parse_verdict,
    verify_finding,
    verify_findings,
    apply_verdicts,
    adversarial_filter,
    ADVERSARIAL_CONCURRENCY,
    VERIFIABLE_SEVERITY,
)
from ai_pr_review.models import AnalysisResult, AnalysisSummary, Finding, Suggestion, Severity


def _make_finding(
    severity: Severity = Severity.HIGH, file: str = "app.py", line: int = 10,
    title: str = "硬编码密钥", description: str = "存在风险",
    suggestion: str = "用环境变量", confidence: int = 4,
) -> Finding:
    return Finding(
        type="security", severity=severity, confidence=confidence,
        expert="安全审查", file=file, line=line, title=title,
        description=description, suggestion=suggestion, code_snippet="SECRET='x'",
    )


def _make_result(findings: list[Finding]) -> AnalysisResult:
    return AnalysisResult(
        summary=AnalysisSummary(intent="t", scope="s", key_changes=[]),
        findings=findings,
        suggestions=[],
    )


# ===== _build_verification_prompt 单元测试 =====

def test_build_prompt_includes_finding_info():
    f = _make_finding(title="SQL注入", description="用户输入未过滤")
    msgs = _build_verification_prompt(f, code_context="def query(): ...")
    assert len(msgs) == 2
    assert msgs[0]["role"] == "system"
    user_content = msgs[1]["content"]
    assert "SQL注入" in user_content
    assert "用户输入未过滤" in user_content
    assert "def query" in user_content


def test_build_prompt_without_code_context():
    f = _make_finding()
    msgs = _build_verification_prompt(f, code_context="")
    user_content = msgs[1]["content"]
    # 即使无上下文，finding 信息仍应存在
    assert "硬编码密钥" in user_content


# ===== parse_verdict 单元测试 =====

def test_parse_verdict_confirmed():
    raw = '{"verdict": "confirmed", "reason": ""}'
    verdict, reason = parse_verdict(raw)
    assert verdict == "confirmed"
    assert reason == ""


def test_parse_verdict_false_positive():
    raw = '{"verdict": "false_positive", "reason": "已使用参数化查询"}'
    verdict, reason = parse_verdict(raw)
    assert verdict == "false_positive"
    assert reason == "已使用参数化查询"


def test_parse_verdict_uncertain():
    raw = '{"verdict": "uncertain", "reason": "信息不足"}'
    verdict, reason = parse_verdict(raw)
    assert verdict == "uncertain"


def test_parse_verdict_with_codeblock_wrapper():
    raw = '```json\n{"verdict": "confirmed", "reason": "ok"}\n```'
    verdict, reason = parse_verdict(raw)
    assert verdict == "confirmed"


def test_parse_verdict_invalid_json():
    verdict, reason = parse_verdict("not json at all")
    assert verdict == "uncertain"
    assert reason == ""


def test_parse_verdict_empty():
    assert parse_verdict("") == ("uncertain", "")


def test_parse_verdict_unknown_value_falls_back():
    raw = '{"verdict": "maybe", "reason": "x"}'
    verdict, _ = parse_verdict(raw)
    assert verdict == "uncertain"


# ===== verify_finding 单元测试 =====

@pytest.mark.asyncio
async def test_verify_finding_success():
    async def fake_call(messages):
        return '{"verdict": "confirmed", "reason": "ok"}'

    f = _make_finding()
    finding, verdict, reason = await verify_finding(fake_call, f, "ctx")
    assert finding is f
    assert verdict == "confirmed"


@pytest.mark.asyncio
async def test_verify_finding_handles_exception():
    async def fake_call(messages):
        raise RuntimeError("network down")

    f = _make_finding()
    finding, verdict, reason = await verify_finding(fake_call, f)
    assert verdict == "uncertain"
    assert "network down" in reason


# ===== verify_findings 并发测试 =====

@pytest.mark.asyncio
async def test_verify_findings_runs_concurrently():
    call_order: list[int] = []

    async def fake_call(messages):
        # 模拟从 prompt 中识别 finding（简化：所有都返回 confirmed）
        call_order.append(len(call_order))
        await asyncio.sleep(0.01)
        return '{"verdict": "confirmed"}'

    findings = [_make_finding(line=i) for i in range(5)]
    results = await verify_findings(fake_call, findings)
    assert len(results) == 5
    # 顺序与入参一致
    for original, (returned_f, verdict, _) in zip(findings, results):
        assert returned_f is original
        assert verdict == "confirmed"


@pytest.mark.asyncio
async def test_verify_findings_empty():
    results = await verify_findings(lambda m: asyncio.sleep(0), [])
    assert results == []


@pytest.mark.asyncio
async def test_verify_findings_with_code_context_fn():
    async def fake_call(messages):
        return '{"verdict": "confirmed"}'

    context_calls: list[Finding] = []

    def fake_ctx_fn(finding):
        context_calls.append(finding)
        return f"context for {finding.line}"

    findings = [_make_finding(line=1), _make_finding(line=2)]
    await verify_findings(fake_call, findings, code_context_fn=fake_ctx_fn)
    assert len(context_calls) == 2


@pytest.mark.asyncio
async def test_verify_findings_respects_concurrency():
    current = 0
    max_observed = 0

    async def fake_call(messages):
        nonlocal current, max_observed
        current += 1
        max_observed = max(max_observed, current)
        await asyncio.sleep(0.05)
        current -= 1
        return '{"verdict": "confirmed"}'

    findings = [_make_finding(line=i) for i in range(6)]
    await verify_findings(fake_call, findings, concurrency=2)
    assert max_observed <= 2


# ===== apply_verdicts 单元测试 =====

def test_apply_verdicts_keeps_confirmed():
    f = _make_finding(severity=Severity.HIGH, title="原标题", description="原描述")
    verdicts = [(f, "confirmed", "ok")]
    result = apply_verdicts([f], verdicts)
    assert len(result) == 1
    assert result[0].severity == Severity.HIGH
    assert "已确认" in result[0].description


def test_apply_verdicts_demotes_false_positive():
    f = _make_finding(severity=Severity.HIGH, confidence=4, description="原描述")
    verdicts = [(f, "false_positive", "误报原因")]
    result = apply_verdicts([f], verdicts)
    assert len(result) == 1
    assert result[0].severity == Severity.LOW
    assert result[0].confidence == 3  # 4 - 1
    assert "误报嫌疑" in result[0].description


def test_apply_verdicts_drops_false_positive_when_flag_set():
    f = _make_finding(severity=Severity.HIGH)
    verdicts = [(f, "false_positive", "误报")]
    result = apply_verdicts([f], verdicts, drop_false_positive=True)
    assert result == []


def test_apply_verdicts_keeps_uncertain_unchanged():
    f = _make_finding(severity=Severity.HIGH, description="原描述")
    verdicts = [(f, "uncertain", "")]
    result = apply_verdicts([f], verdicts)
    assert len(result) == 1
    assert result[0].severity == Severity.HIGH
    assert result[0].description == "原描述"  # 不加任何标记


def test_apply_verdicts_handles_missing_verdict():
    """finding 未在 verdicts 中时应保留原样"""
    f = _make_finding(severity=Severity.HIGH)
    result = apply_verdicts([f], [])
    assert len(result) == 1
    assert result[0].severity == Severity.HIGH


# ===== adversarial_filter 集成测试 =====

@pytest.mark.asyncio
async def test_adversarial_filter_only_verifies_high_severity():
    """仅 HIGH severity 触发验证，LOW/MEDIUM 不变"""
    high_f = _make_finding(severity=Severity.HIGH, line=1)
    med_f = _make_finding(severity=Severity.MEDIUM, line=2)
    low_f = _make_finding(severity=Severity.LOW, line=3)
    result = _make_result([high_f, med_f, low_f])

    call_count = 0

    async def fake_call(messages):
        nonlocal call_count
        call_count += 1
        return '{"verdict": "false_positive", "reason": "误报"}'

    filtered = await adversarial_filter(fake_call, result)
    # 仅 HIGH 触发了一次调用
    assert call_count == 1
    # HIGH 被降级为 LOW
    severities = [f.severity for f in filtered.findings]
    assert Severity.LOW in severities
    # MEDIUM 和原始 LOW 保持不变
    assert severities.count(Severity.MEDIUM) == 1
    # 一条原始 LOW + 一条降级的 LOW
    assert severities.count(Severity.LOW) == 2


@pytest.mark.asyncio
async def test_adversarial_filter_no_high_returns_unchanged():
    """无 HIGH severity 时不触发 AI 调用"""
    result = _make_result([_make_finding(severity=Severity.LOW)])
    call_count = 0

    async def fake_call(messages):
        nonlocal call_count
        call_count += 1
        return '{"verdict": "confirmed"}'

    filtered = await adversarial_filter(fake_call, result)
    assert call_count == 0
    assert filtered is result


@pytest.mark.asyncio
async def test_adversarial_filter_with_drop_flag():
    high_f = _make_finding(severity=Severity.HIGH)
    result = _make_result([high_f])

    async def fake_call(messages):
        return '{"verdict": "false_positive", "reason": "x"}'

    filtered = await adversarial_filter(fake_call, result, drop_false_positive=True)
    assert filtered.findings == []


def test_constants():
    assert ADVERSARIAL_CONCURRENCY > 0
    assert VERIFIABLE_SEVERITY == Severity.HIGH
