"""对抗式验证 — 对 high severity 发现做二次 AI 验证，过滤误报

设计目标：
- 仅对 severity=HIGH 的发现做二次验证（成本控制）
- 提供 finding + 周边代码上下文，让 AI 判断 true positive / false positive
- false positive 降级为 LOW 或直接过滤
- 并发执行验证，复用 _call_ai 重试机制
"""
import asyncio
import json
import re
import logging
from ai_pr_review.models import AnalysisResult, Finding, Severity

logger = logging.getLogger(__name__)

# 验证并发上限
ADVERSARIAL_CONCURRENCY = 3
# 仅验证 HIGH severity，控制成本
VERIFIABLE_SEVERITY = Severity.HIGH


ADVERSARIAL_SYSTEM_PROMPT = """你是一位严格的代码审查仲裁者。
你的任务是判断另一个 AI 提出的代码审查发现是否为真正的误报（false positive）。

判断标准：
- 如果该发现确实成立（即使严重程度被高估），返回 {"verdict": "confirmed"}
- 如果该发现是误报（无实际风险/不影响生产/基于错误假设），返回 {"verdict": "false_positive", "reason": "误报原因"}
- 如果无法确定（信息不足），返回 {"verdict": "uncertain"}

输出严格 JSON，无其他内容。"""


def _build_verification_prompt(finding: Finding, code_context: str = "") -> list[dict[str, str]]:
    """构建对抗式验证 prompt"""
    user_parts = [
        "## 待验证的审查发现",
        f"- 文件: {finding.file}",
        f"- 行号: {finding.line}",
        f"- 类型: {finding.type}",
        f"- 标题: {finding.title}",
        f"- 描述: {finding.description}",
        f"- 建议修复: {finding.suggestion}",
    ]
    if code_context:
        user_parts.append("\n## 周边代码上下文")
        user_parts.append(code_context)
    user_parts.append('\n请判断该发现是否为误报，输出 JSON：{"verdict": "confirmed|false_positive|uncertain", "reason": "..."}')

    return [
        {"role": "system", "content": ADVERSARIAL_SYSTEM_PROMPT},
        {"role": "user", "content": "\n".join(user_parts)},
    ]


def parse_verdict(raw: str) -> tuple[str, str]:
    """解析对抗式验证返回

    返回 (verdict, reason)，verdict ∈ {"confirmed", "false_positive", "uncertain"}
    解析失败默认 "uncertain"
    """
    if not raw:
        return "uncertain", ""
    # 兼容 ```json``` 包裹与纯 JSON 两种格式
    json_match = re.search(r"```(?:json)?\s*\n?(.*?)\n?```", raw, re.DOTALL)
    if json_match:
        raw = json_match.group(1).strip()
    try:
        data = json.loads(raw)
        verdict = data.get("verdict", "uncertain")
        reason = data.get("reason", "")
        if verdict not in ("confirmed", "false_positive", "uncertain"):
            verdict = "uncertain"
        return verdict, reason
    except (json.JSONDecodeError, TypeError):
        return "uncertain", ""


async def verify_finding(
    call_ai_fn,
    finding: Finding,
    code_context: str = "",
) -> tuple[Finding, str, str]:
    """对单条 finding 执行对抗式验证

    返回 (原 finding, verdict, reason)
    """
    messages = _build_verification_prompt(finding, code_context)
    try:
        raw = await call_ai_fn(messages)
        verdict, reason = parse_verdict(raw)
        return finding, verdict, reason
    except Exception as e:
        logger.warning(f"Adversarial verification failed for {finding.file}:{finding.line}: {e}")
        return finding, "uncertain", str(e)


async def verify_findings(
    call_ai_fn,
    findings: list[Finding],
    code_context_fn=None,
    concurrency: int = ADVERSARIAL_CONCURRENCY,
) -> list[tuple[Finding, str, str]]:
    """并发验证多条 findings

    - code_context_fn: 可选函数，接收 finding 返回周边代码上下文字符串
    - 返回 [(finding, verdict, reason), ...] 顺序与入参一致
    """
    if not findings:
        return []

    semaphore = asyncio.Semaphore(concurrency)

    async def _limited_verify(finding: Finding):
        async with semaphore:
            ctx = ""
            if code_context_fn:
                try:
                    ctx = code_context_fn(finding) or ""
                except Exception:
                    ctx = ""
            return await verify_finding(call_ai_fn, finding, ctx)

    tasks = [_limited_verify(f) for f in findings]
    return await asyncio.gather(*tasks)


def apply_verdicts(
    findings: list[Finding],
    verdicts: list[tuple[Finding, str, str]],
    drop_false_positive: bool = False,
) -> list[Finding]:
    """根据对抗式验证结果调整 findings

    - confirmed: 保留原 severity
    - false_positive: 降级为 LOW，drop_false_positive=True 时直接剔除
    - uncertain: 保留原样（避免过度过滤）
    """
    verdict_map: dict[int, tuple[str, str]] = {}
    for f, verdict, reason in verdicts:
        # 用 id(finding) 作为键（finding 不可哈希）
        verdict_map[id(f)] = (verdict, reason)

    result: list[Finding] = []
    for f in findings:
        verdict, reason = verdict_map.get(id(f), ("uncertain", ""))
        if verdict == "false_positive":
            if drop_false_positive:
                logger.info(f"Dropped false positive: {f.file}:{f.line} - {reason}")
                continue
            # 降级而非剔除，保留信息给用户参考
            f = Finding(
                type=f.type, severity=Severity.LOW, confidence=max(1, f.confidence - 1),
                expert=f.expert, file=f.file, line=f.line, title=f.title,
                description=f"{f.description}\n[对抗验证: 误报嫌疑 - {reason}]",
                suggestion=f.suggestion, code_snippet=f.code_snippet,
            )
        elif verdict == "confirmed":
            # 已确认的发现，可在 description 中加标记便于用户识别
            f = Finding(
                type=f.type, severity=f.severity, confidence=f.confidence,
                expert=f.expert, file=f.file, line=f.line, title=f.title,
                description=f"{f.description}\n[对抗验证: 已确认]",
                suggestion=f.suggestion, code_snippet=f.code_snippet,
            )
        result.append(f)
    return result


async def adversarial_filter(
    call_ai_fn,
    result: AnalysisResult,
    code_context_fn=None,
    drop_false_positive: bool = False,
) -> AnalysisResult:
    """对 AnalysisResult 中的 HIGH severity 发现做对抗式验证

    其他 severity 不变，仅 HIGH 会触发二次 AI 调用。
    """
    high_findings = [f for f in result.findings if f.severity == VERIFIABLE_SEVERITY]
    if not high_findings:
        return result

    verdicts = await verify_findings(call_ai_fn, high_findings, code_context_fn)
    adjusted = apply_verdicts(result.findings, verdicts, drop_false_positive)

    return AnalysisResult(
        summary=result.summary,
        findings=adjusted,
        suggestions=result.suggestions,
    )
