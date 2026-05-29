import asyncio
import logging
from typing import Optional
from pathlib import Path
from rich.console import Console
from rich.panel import Panel
import typer

from ai_pr_review.config import load_config
from ai_pr_review.github_client import GitHubClient
from ai_pr_review.diff_parser import parse_diff
from ai_pr_review.analyzer import AIAnalyzer
from ai_pr_review.formatter import format_terminal
from ai_pr_review.commenter import Commenter

app = typer.Typer(
    name="ai-pr-review",
    help="AI-powered Pull Request review assistant using domestic LLMs",
)
console = Console()


@app.command()
def review(
    pr_url: str = typer.Argument(..., help="GitHub PR URL"),
    model: Optional[str] = typer.Option(None, "--model", "-m", help="AI model name"),
    no_comment: bool = typer.Option(False, "--no-comment", help="Do not post GitHub comments"),
    severity: str = typer.Option("low", "--severity", "-s", help="Minimum severity threshold (low/medium/high)"),
    focus: Optional[str] = typer.Option(None, "--focus", "-f", help="Analysis dimensions (comma-separated: risk,quality,testing,security)"),
    stream: bool = typer.Option(False, "--stream", help="Stream output"),
    config_path: Optional[str] = typer.Option(None, "--config", "-c", help="Config file path"),
    review_action: str = typer.Option("COMMENT", "--review-action", help="GitHub review action (COMMENT/APPROVE/REQUEST_CHANGES)"),
):
    config = load_config(Path(config_path) if config_path else None)

    if model:
        config.ai.model = model

    logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")

    console.print(Panel(f"🔍 AI PR Review", subtitle=pr_url))

    with console.status("Fetching PR metadata..."):
        gh_client = GitHubClient(token=config.github.token)
        pr_metadata = gh_client.get_pr_metadata(pr_url)

    console.print(f"📋 PR: [bold]{pr_metadata.title}[/bold] by {pr_metadata.author}")

    with console.status("Fetching PR diff..."):
        diff_content = gh_client.get_pr_diff_content(pr_url)

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
    )

    with console.status("Analyzing with AI..."):
        result = asyncio.run(
            analyzer.analyze(
                pr_metadata=pr_metadata,
                parsed_diff=parsed_diff,
                severity_threshold=severity,
                focus=focus_list,
            )
        )

    output = format_terminal(result)
    console.print(output)

    if not no_comment and config.github.token:
        with console.status("Posting review to GitHub..."):
            commenter = Commenter(gh_client)
            commenter.post_review(pr_url, result, event=review_action)
        console.print("✅ Review posted to GitHub!")
    elif not no_comment and not config.github.token:
        console.print("⚠️  No GitHub token configured, skipping comment post")


if __name__ == "__main__":
    app()
