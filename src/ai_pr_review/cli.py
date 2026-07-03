import asyncio
import sys
import time
import logging
from typing import Optional
from pathlib import Path
from rich.console import Console
from rich.panel import Panel
import typer

from ai_pr_review.config import load_config
from ai_pr_review.github_client import GitHubClient
from ai_pr_review.diff_parser import parse_diff
from ai_pr_review.analyzer import AIAnalyzer, SHARD_FILE_THRESHOLD, SHARD_LINE_THRESHOLD
from ai_pr_review.formatter import format_terminal
from ai_pr_review.commenter import Commenter
from ai_pr_review.history import save_record, load_records, format_history_table, AnalysisRecord
from ai_pr_review.incremental import IncrementalAnalyzer
from ai_pr_review.team_learner import TeamLearner
from ai_pr_review.team_rules import save_team_pattern, load_team_pattern

async def _run_stream(stream_gen):
    result = None
    async for chunk in stream_gen:
        if isinstance(chunk, tuple) and chunk[0] == "__RESULT__":
            result = chunk[1]
        elif isinstance(chunk, str):
            if len(chunk) <= 15:
                sys.stdout.write(chunk)
                sys.stdout.flush()
            else:
                for char in chunk:
                    sys.stdout.write(char)
                    sys.stdout.flush()
                    time.sleep(0.003)
    sys.stdout.write("\n\n")
    sys.stdout.flush()
    return result

app = typer.Typer(
    name="ai-pr-review",
    help="AI-powered Pull Request review assistant using domestic LLMs",
)
console = Console()


@app.command()
def review(
    pr_url: str = typer.Argument(..., help="GitHub PR URL"),
    model: Optional[str] = typer.Option(None, "--model", "-m", help="AI model (deepseek/qwen/glm or full model name)"),
    no_comment: bool = typer.Option(False, "--no-comment", help="Do not post GitHub comments"),
    severity: str = typer.Option("low", "--severity", "-s", help="Minimum severity threshold (low/medium/high)"),
    focus: Optional[str] = typer.Option(None, "--focus", "-f", help="Analysis dimensions (comma-separated: risk,quality,testing,security)"),
    stream: bool = typer.Option(False, "--stream", help="Stream output"),
    config_path: Optional[str] = typer.Option(None, "--config", "-c", help="Config file path"),
    review_action: str = typer.Option("COMMENT", "--review-action", help="GitHub review action (COMMENT/APPROVE/REQUEST_CHANGES)"),
    incremental: bool = typer.Option(False, "--incremental", "-i", help="Incremental analysis (only new changes since last review)"),
    min_confidence: int = typer.Option(2, "--min-confidence", help="Minimum confidence threshold (1-5)"),
):
    config = load_config(Path(config_path) if config_path else None, model_override=model)
    config.analysis.min_confidence = min_confidence

    logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")

    console.print(Panel(f"🔍 AI PR Review", subtitle=f"{pr_url} | model: {config.ai.model}"))

    with console.status("Fetching PR metadata..."):
        gh_client = GitHubClient(token=config.github.token)
        pr_metadata = gh_client.get_pr_metadata(pr_url)

    console.print(f"📋 PR: [bold]{pr_metadata.title}[/bold] by {pr_metadata.author}")

    try:
        with console.status("Fetching PR diff..."):
            diff_content = gh_client.get_pr_diff_content(pr_url)
    except Exception as e:
        console.print(f"[red]❌ Failed to fetch PR diff: {e}[/red]")
        console.print("[yellow]💡 This is likely a network issue. Please check your connection and try again.[/yellow]")
        raise typer.Exit(code=1)

    with console.status("Parsing diff..."):
        parsed_diff = parse_diff(diff_content)

    console.print(
        f"📊 Changes: +{parsed_diff.total_additions} -{parsed_diff.total_deletions} "
        f"across {len(parsed_diff.files)} files"
    )

    focus_list = focus.split(",") if focus else None

    analyzer = AIAnalyzer(
        config=config,
        get_file_content_fn=lambda url, path, ref: gh_client.get_file_content(
            pr_url, path, pr_metadata.head_branch
        ),
        repo_url=pr_url,
    )

    current_sha = ""
    last_record = None
    is_incremental_analysis = False
    analysis_start = time.perf_counter()
    analysis_duration = 0.0

    if incremental:
        try:
            current_sha = gh_client.get_pr_head_sha(pr_url)
            inc_analyzer = IncrementalAnalyzer(gh_client)
            last_record = inc_analyzer.should_analyze_incremental(pr_url)
        except Exception:
            last_record = None

    if last_record and current_sha and last_record.head_sha != current_sha:
        inc_analyzer = IncrementalAnalyzer(gh_client)
        inc_diff_text = inc_analyzer.get_incremental_diff(pr_url, last_record.head_sha, current_sha)

        if inc_diff_text.strip():
            incremental_parsed = parse_diff(inc_diff_text)
            inc_context = inc_analyzer.build_incremental_context(
                pr_url, parsed_diff, incremental_parsed, last_record
            )
            console.print(
                f"🔄 Incremental: {len(incremental_parsed.files)} changed files "
                f"since {last_record.head_sha[:7]}"
            )
            with console.status("Analyzing incremental changes..."):
                result = asyncio.run(
                    analyzer.analyze_incremental(
                        pr_metadata=pr_metadata,
                        incremental_parsed_diff=incremental_parsed,
                        incremental_context=inc_context,
                        severity_threshold=severity,
                        focus=focus_list,
                    )
                )
            is_incremental_analysis = True
        else:
            console.print("✅ No new changes since last review.")
            return
    elif last_record and current_sha and last_record.head_sha == current_sha:
        console.print("✅ No new commits since last review.")
        return
    else:
        file_count = len(parsed_diff.files)
        total_lines = parsed_diff.total_additions + parsed_diff.total_deletions
        should_shard = file_count > SHARD_FILE_THRESHOLD or total_lines > SHARD_LINE_THRESHOLD

        if should_shard and not stream:
            console.print(
                f"📦 Large PR detected ({file_count} files, {total_lines} lines), "
                f"sharding analysis..."
            )
            with console.status("Analyzing with AI (sharded)..."):
                result = asyncio.run(
                    analyzer.analyze_with_shards(
                        pr_metadata=pr_metadata,
                        parsed_diff=parsed_diff,
                        severity_threshold=severity,
                        focus=focus_list,
                    )
                )
        elif stream:
            if should_shard:
                console.print(
                    f"📦 Large PR detected ({file_count} files, {total_lines} lines), "
                    f"streaming with sharding..."
                )
                gen = analyzer.analyze_with_shards_stream(
                    pr_metadata=pr_metadata,
                    parsed_diff=parsed_diff,
                    severity_threshold=severity,
                    focus=focus_list,
                )
            else:
                console.print("\n🔍 [dim]Streaming analysis...[/dim]\n")
                gen = analyzer.analyze_stream(
                    pr_metadata=pr_metadata,
                    parsed_diff=parsed_diff,
                    severity_threshold=severity,
                    focus=focus_list,
                )
            result = asyncio.run(_run_stream(gen))
        else:
            with console.status("Analyzing with AI..."):
                result = asyncio.run(
                    analyzer.analyze(
                        pr_metadata=pr_metadata,
                        parsed_diff=parsed_diff,
                        severity_threshold=severity,
                        focus=focus_list,
                    )
                )

    analysis_duration = time.perf_counter() - analysis_start

    if stream:
        console.print("\n" + "─" * 60)
        console.print("[bold]📊 格式化分析报告[/bold]\n")
    output = format_terminal(result)
    console.print(output)

    if not current_sha:
        try:
            current_sha = gh_client.get_pr_head_sha(pr_url)
        except Exception:
            current_sha = ""

    if not no_comment and config.github.token:
        with console.status("Posting review to GitHub..."):
            commenter = Commenter(gh_client)
            commenter.post_review_with_inline_comments(
                pr_url, result, commit_id=current_sha, event=review_action,
            )
        console.print("✅ Review posted to GitHub!")
    elif not no_comment and not config.github.token:
        console.print("⚠️  No GitHub token configured, skipping comment post")

    record = AnalysisRecord(
        pr_url=pr_url,
        pr_title=pr_metadata.title,
        findings_count=len(result.findings),
        high_severity_count=sum(1 for f in result.findings if f.severity.value == "high"),
        medium_severity_count=sum(1 for f in result.findings if f.severity.value == "medium"),
        low_severity_count=sum(1 for f in result.findings if f.severity.value == "low"),
        suggestions_count=len(result.suggestions),
        model=config.ai.model,
        head_sha=current_sha,
        is_incremental=is_incremental_analysis,
        duration_seconds=round(analysis_duration, 2),
    )
    save_record(record)


@app.command()
def learn(
    pr_url: str = typer.Argument(..., help="GitHub PR URL (用于定位仓库)"),
    model: Optional[str] = typer.Option(None, "--model", "-m", help="AI model"),
    max_prs: int = typer.Option(20, "--max-prs", help="Maximum PRs to analyze"),
    force: bool = typer.Option(False, "--force", "-f", help="Force re-learn even if cached"),
):
    config = load_config(model_override=model)

    logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")

    if not force:
        existing = load_team_pattern(pr_url)
        if existing and existing.rules:
            console.print(f"✅ 已有团队模式缓存 (学习于 {existing.learned_at[:19]})")
            console.print(f"   使用 --force 重新学习")
            return

    gh_client = GitHubClient(token=config.github.token)

    with console.status("Fetching PR comments..."):
        comments = gh_client.get_repo_pr_comments(pr_url, max_prs=max_prs)
    console.print(f"📝 Fetched {len(comments)} comments from {max_prs} PRs")

    if not comments:
        console.print("[yellow]No comments found in this repository.[/yellow]")
        return

    with console.status("Learning team patterns..."):
        learner = TeamLearner(config)
        pattern = asyncio.run(learner.extract_patterns(comments))

    pattern.repo_url = pr_url
    save_team_pattern(pattern)

    console.print(f"✅ Learned {len(pattern.rules)} team rules")
    for rule in pattern.rules:
        console.print(f"  • [{rule.category}] {rule.description}")

    if pattern.focus_areas:
        console.print(f"\n🎯 Focus areas: {', '.join(pattern.focus_areas)}")
    if pattern.common_terms:
        console.print(f"💬 Common terms: {', '.join(pattern.common_terms[:10])}")


@app.command()
def history(
    limit: int = typer.Option(20, "--limit", "-n", help="Number of records to show"),
):
    records = load_records()
    if not records:
        console.print("[yellow]No review history found.[/yellow]")
        return
    format_history_table(records, limit=limit)


if __name__ == "__main__":
    app()
