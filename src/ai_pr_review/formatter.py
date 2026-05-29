from ai_pr_review.models import AnalysisResult, Finding, Severity
from rich.console import Console
from rich.panel import Panel
from rich.table import Table
from rich.tree import Tree
from rich.text import Text
from rich import box

SEVERITY_EMOJI = {
    Severity.HIGH: "🔴",
    Severity.MEDIUM: "🟡",
    Severity.LOW: "🟢",
}

SEVERITY_LABEL = {
    Severity.HIGH: "高",
    Severity.MEDIUM: "中",
    Severity.LOW: "低",
}

SEVERITY_COLOR = {
    Severity.HIGH: "red",
    Severity.MEDIUM: "yellow",
    Severity.LOW: "green",
}


def format_terminal(result: AnalysisResult) -> str:
    parts = []

    parts.append("📋 PR 变更总结")
    parts.append("━" * 40)
    parts.append(f"变更意图：{result.summary.intent}")
    parts.append(f"影响范围：{result.summary.scope}")
    parts.append("关键修改：")
    for change in result.summary.key_changes:
        parts.append(f"  - {change}")
    parts.append("")

    if result.findings:
        parts.append(f"⚠️  风险识别 ({len(result.findings)}项)")
        parts.append("━" * 40)
        for finding in result.findings:
            emoji = SEVERITY_EMOJI.get(finding.severity, "⚪")
            label = SEVERITY_LABEL.get(finding.severity, finding.severity.value)
            parts.append(
                f"{emoji} [{label}] {finding.file}:L{finding.line} - {finding.title} [{finding.expert}]"
            )
            parts.append(f"   {finding.description}")
            parts.append(f"   建议：{finding.suggestion}")
            if finding.code_snippet:
                parts.append(f"   代码：{finding.code_snippet}")
            parts.append("")

    if result.suggestions:
        parts.append(f"💡 Review 建议 ({len(result.suggestions)}项)")
        parts.append("━" * 40)
        for suggestion in result.suggestions:
            label = SEVERITY_LABEL.get(suggestion.priority, suggestion.priority.value)
            parts.append(f"  [{label}] [{suggestion.category}] {suggestion.description}")
            if suggestion.example:
                parts.append(f"   示例：{suggestion.example}")
            parts.append("")

    return "\n".join(parts)


def format_rich(result: AnalysisResult, console: Console | None = None) -> None:
    _console = console or Console()

    summary_panel = Panel(
        f"[bold]变更意图：[/bold]{result.summary.intent}\n"
        f"[bold]影响范围：[/bold]{result.summary.scope}\n"
        f"[bold]关键修改：[/bold]\n" +
        "\n".join(f"  • {change}" for change in result.summary.key_changes),
        title="📋 PR 变更总结",
        border_style="blue",
    )
    _console.print(summary_panel)

    if result.findings:
        table = Table(
            title=f"⚠️  风险识别 ({len(result.findings)}项)",
            box=box.ROUNDED,
            show_lines=True,
        )
        table.add_column("严重", style="bold", width=6)
        table.add_column("文件:行", style="cyan")
        table.add_column("问题", style="bold")
        table.add_column("专家", style="dim")

        for finding in result.findings:
            emoji = SEVERITY_EMOJI.get(finding.severity, "⚪")
            color = SEVERITY_COLOR.get(finding.severity, "white")
            table.add_row(
                f"{emoji} [{color}]{SEVERITY_LABEL.get(finding.severity, finding.severity.value)}[/{color}]",
                f"{finding.file}:L{finding.line}",
                finding.title,
                finding.expert,
            )
        _console.print(table)

        tree = Tree("📝 详情")
        for finding in result.findings[:10]:
            color = SEVERITY_COLOR.get(finding.severity, "white")
            branch = tree.add(
                f"[{color}]{finding.title}[/{color}] - {finding.file}:L{finding.line}"
            )
            branch.add(f"描述：{finding.description}")
            if finding.suggestion:
                branch.add(f"建议：{finding.suggestion}")
            if finding.code_snippet:
                branch.add(Text.from_markup(f"`{finding.code_snippet}`", style="dim"))
        _console.print(tree)

    if result.suggestions:
        sug_table = Table(
            title=f"💡 改进建议 ({len(result.suggestions)}项)",
            box=box.SIMPLE,
        )
        sug_table.add_column("优先级", width=8)
        sug_table.add_column("类别", width=12)
        sug_table.add_column("描述")

        for s in result.suggestions:
            label = SEVERITY_LABEL.get(s.priority, s.priority.value)
            color = SEVERITY_COLOR.get(s.priority, "white")
            sug_table.add_row(
                f"[{color}]{label}[/{color}]",
                s.category,
                s.description,
            )
        _console.print(sug_table)


def format_github_comment(result: AnalysisResult) -> str:
    parts = []

    parts.append("## 🤖 AI PR Review")
    parts.append("")
    parts.append("### 📋 变更总结")
    parts.append(f"**意图**：{result.summary.intent}")
    parts.append(f"**范围**：{result.summary.scope}")
    parts.append("**关键修改**：")
    for change in result.summary.key_changes:
        parts.append(f"- {change}")
    parts.append("")

    if result.findings:
        parts.append(f"### ⚠️ 风险识别 ({len(result.findings)}项)")
        parts.append("")
        for finding in result.findings:
            label = finding.severity.value.upper()
            parts.append(
                f"- **[{label}]** `{finding.file}:L{finding.line}` - {finding.title} _({finding.expert})_"
            )
            parts.append(f"  - {finding.description}")
            parts.append(f"  - 💡 建议：{finding.suggestion}")
            if finding.code_snippet:
                parts.append(f"  - 代码：`{finding.code_snippet}`")
        parts.append("")

    if result.suggestions:
        parts.append(f"### 💡 改进建议 ({len(result.suggestions)}项)")
        parts.append("")
        for suggestion in result.suggestions:
            parts.append(
                f"- **[{suggestion.priority.value.upper()}]** [{suggestion.category}] {suggestion.description}"
            )
            if suggestion.example:
                parts.append(f"  - 示例：`{suggestion.example}`")
        parts.append("")

    parts.append("---")
    parts.append("*Generated by [AI PR Review](https://github.com/ai-pr-review)*")

    return "\n".join(parts)
