import asyncio
import os
import sys
import time
import logging
from typing import Optional
from pathlib import Path
from rich.console import Console
from rich.panel import Panel
from rich.table import Table
import typer

from ai_pr_review.config import (
    load_config,
    load_config_strict,
    validate_config,
    DEFAULT_CONFIG_PATH,
    MODEL_PRESETS,
)
from ai_pr_review.config_error import ConfigError
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

# 配置管理子命令组
config_app = typer.Typer(help="配置管理")
app.add_typer(config_app, name="config")


def _mask_secret(value: str) -> str:
    """脱敏处理：长度 > 4 时显示前 4 位 + ***，否则全 ***"""
    if len(value) > 4:
        return value[:4] + "***"
    return "***"


def _generate_toml_content(
    provider: str,
    api_key: str,
    model: Optional[str] = None,
    token: str = "",
) -> str:
    """根据 provider 生成 TOML 配置文本（避免引入 tomli_w 依赖）"""
    preset = MODEL_PRESETS.get(provider, MODEL_PRESETS["deepseek"])
    effective_model = model or preset["default_model"]
    base_url = preset["default_base_url"]

    # TOML 中数组格式的专家列表
    experts_str = ", ".join(
        f'"{e}"' for e in ["security", "architecture", "performance", "readability", "testing"]
    )

    return f"""# AI PR Review 配置文件
# 注意：api_key 与 token 以明文存储，请妥善保管文件权限

[github]
# 也可通过 GITHUB_TOKEN 环境变量配置
token = "{token}"

[ai]
provider = "{provider}"
api_key = "{api_key}"
model = "{effective_model}"
base_url = "{base_url}"
max_tokens = 8000
temperature = 0.3

[analysis]
severity_threshold = "low"
max_file_size = 50000
context_budget = 6000
min_confidence = 2

[expert]
enabled_experts = [{experts_str}]
"""


@config_app.command("init")
def config_init(
    provider: str = typer.Option("deepseek", "--provider", "-p", help="AI 提供商 (deepseek/qwen/glm)"),
    api_key: str = typer.Option(..., "--api-key", "-k", help="API Key"),
    model: Optional[str] = typer.Option(None, "--model", "-m", help="模型名（留空使用 provider 默认）"),
    output: Optional[str] = typer.Option(None, "--output", "-o", help="输出文件路径（默认 ~/.ai-pr-review.toml）"),
    force: bool = typer.Option(False, "--force", help="覆盖已存在文件"),
):
    """生成 ~/.ai-pr-review.toml 配置文件"""
    output_path = Path(output) if output else DEFAULT_CONFIG_PATH

    # 已存在且未传 --force 时拒绝覆盖
    if output_path.exists() and not force:
        console.print(f"[yellow]⚠️  配置文件已存在：{output_path}[/yellow]")
        console.print("使用 --force 覆盖")
        raise typer.Exit(code=1)

    toml_content = _generate_toml_content(provider, api_key, model)

    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(toml_content, encoding="utf-8")

    console.print(f"[green]✅ 配置文件已生成：{output_path}[/green]")
    console.print("\n📋 下一步：")
    console.print(f"  1. 编辑 {output_path} 调整参数")
    console.print("  2. 运行 [bold]ai-pr-review config validate[/bold] 校验配置")
    console.print(f"  3. 运行 [bold]ai-pr-review review <pr_url>[/bold] 开始审查")


@config_app.command("validate")
def config_validate(
    config_path: Optional[str] = typer.Option(None, "--config", "-c", help="配置文件路径"),
    model: Optional[str] = typer.Option(None, "--model", "-m", help="模型名覆盖"),
):
    """校验配置并输出结果"""
    try:
        config = load_config(
            Path(config_path) if config_path else None,
            model_override=model,
        )
        validate_config(config)
    except ConfigError as e:
        console.print(f"[red]❌ 配置校验失败：[/red]")
        console.print(f"  字段：{e.field}")
        console.print(f"  错误：{e}")
        raise typer.Exit(code=1)
    except Exception as e:
        console.print(f"[red]❌ 配置加载失败：{e}[/red]")
        raise typer.Exit(code=1)

    console.print("[green]✅ 配置校验通过[/green]")
    console.print(f"  model:           {config.ai.model}")
    console.print(f"  base_url:        {config.ai.base_url}")
    console.print(f"  max_tokens:      {config.ai.max_tokens}")
    console.print(f"  temperature:     {config.ai.temperature}")
    console.print(f"  enabled_experts: {', '.join(config.expert.enabled_experts)}")


@config_app.command("show")
def config_show(
    config_path: Optional[str] = typer.Option(None, "--config", "-c", help="配置文件路径"),
    model: Optional[str] = typer.Option(None, "--model", "-m", help="模型名覆盖"),
):
    """展示生效配置（敏感字段脱敏）"""
    try:
        config = load_config(
            Path(config_path) if config_path else None,
            model_override=model,
        )
    except Exception as e:
        console.print(f"[red]❌ 配置加载失败：{e}[/red]")
        raise typer.Exit(code=1)

    table = Table(title="生效配置", show_header=True, header_style="bold cyan")
    table.add_column("Section", style="bold")
    table.add_column("字段", style="dim")
    table.add_column("值")

    # GitHub section
    table.add_row("github", "token", _mask_secret(config.github.token))

    # AI section
    table.add_row("ai", "provider", config.ai.provider)
    table.add_row("ai", "api_key", _mask_secret(config.ai.api_key))
    table.add_row("ai", "model", config.ai.model)
    table.add_row("ai", "base_url", config.ai.base_url)
    table.add_row("ai", "max_tokens", str(config.ai.max_tokens))
    table.add_row("ai", "temperature", str(config.ai.temperature))

    # Analysis section
    table.add_row("analysis", "severity_threshold", config.analysis.severity_threshold)
    table.add_row("analysis", "min_confidence", str(config.analysis.min_confidence))

    # Expert section
    table.add_row("expert", "enabled_experts", ", ".join(config.expert.enabled_experts))

    console.print(table)


@app.command()
def review(
    pr_url: str = typer.Argument(..., help="GitHub PR URL"),
    model: Optional[str] = typer.Option(None, "--model", "-m", help="AI model (deepseek/qwen/glm or full model name)"),
    no_comment: bool = typer.Option(False, "--no-comment", help="Do not post GitHub comments"),
    severity: str = typer.Option("low", "--severity", "-s", help="Minimum severity threshold (low/medium/high)"),
    focus: Optional[str] = typer.Option(None, "--focus", "-f", help="Analysis dimensions (comma-separated: risk,security,performance,quality,testing,architecture,readability)"),
    stream: bool = typer.Option(False, "--stream", help="Stream output"),
    config_path: Optional[str] = typer.Option(None, "--config", "-c", help="Config file path"),
    review_action: str = typer.Option("COMMENT", "--review-action", help="GitHub review action (COMMENT/APPROVE/REQUEST_CHANGES)"),
    incremental: bool = typer.Option(False, "--incremental", "-i", help="Incremental analysis (only new changes since last review)"),
    min_confidence: int = typer.Option(2, "--min-confidence", help="Minimum confidence threshold (1-5)"),
    no_cache: bool = typer.Option(False, "--no-cache", help="Skip cache, force fresh analysis"),
    multi_agent: bool = typer.Option(False, "--multi-agent", help="Multi-agent review: each expert independently reviews, results aggregated with consensus weighting"),
    no_adversarial: bool = typer.Option(False, "--no-adversarial", help="Disable adversarial verification of HIGH severity findings (only effective with --multi-agent)"),
    rate_limit: int = typer.Option(5, "--rate-limit", help="AI 调用每秒限流（仅多 Agent 与分片路径生效，0=禁用）"),
    log_format: str = typer.Option("text", "--log-format", help="日志格式 (text/json)"),
):
    # 初始化结构化日志（structured_logging 模块可能尚未创建，用 try/except 兜底）
    try:
        from ai_pr_review.structured_logging import setup_logging
        setup_logging(format=log_format, level="INFO")
    except ImportError:
        logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")

    # 严格加载并校验配置（失败时友好退出）
    try:
        config = load_config_strict(
            Path(config_path) if config_path else None,
            model_override=model,
        )
    except ConfigError as e:
        console.print(f"[red]❌ 配置校验失败：[/red]")
        console.print(f"  字段：{e.field}")
        console.print(f"  错误：{e}")
        raise typer.Exit(code=1)

    config.analysis.min_confidence = min_confidence

    # 限流配置：写入环境变量供 rate_limiter 读取，rate > 0 时初始化单例
    os.environ["RATE_LIMIT"] = str(rate_limit)
    if rate_limit > 0:
        from ai_pr_review.rate_limiter import get_rate_limiter
        get_rate_limiter(rate=rate_limit)

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

    # 检查结果缓存（仅非增量、非流式、非多 Agent 时）
    cache_hit = False
    if not no_cache and not incremental and not stream and not multi_agent:
        from ai_pr_review.cache import get_cached_result
        try:
            current_sha = gh_client.get_pr_head_sha(pr_url)
        except Exception:
            current_sha = ""
        if current_sha:
            cached = get_cached_result(pr_url, current_sha)
            if cached:
                console.print(f"💚 Cache hit! Returning cached result for {current_sha[:7]}")
                result = cached
                cache_hit = True

    if not cache_hit:
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

            # 多 Agent 路径：独立专家并行审查 + 聚合 + 对抗式验证
            if multi_agent:
                console.print(f"🤖 Multi-agent review enabled (adversarial: {not no_adversarial})")
                with console.status("Analyzing with multi-agent..."):
                    result = asyncio.run(
                        analyzer.analyze_multi_agent(
                            pr_metadata=pr_metadata,
                            parsed_diff=parsed_diff,
                            severity_threshold=severity,
                            focus=focus_list,
                            enable_adversarial=not no_adversarial,
                        )
                    )
            elif should_shard and not stream:
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

    # 保存分析结果到缓存（跳过缓存命中、增量分析、多 Agent 的情况）
    if not no_cache and current_sha and not cache_hit and not is_incremental_analysis and not multi_agent:
        from ai_pr_review.cache import save_cached_result
        save_cached_result(pr_url, current_sha, result)

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


@app.command()
def serve(
    port: int = typer.Option(8000, "--port", "-p", help="Port to listen on"),
    host: str = typer.Option("0.0.0.0", "--host", help="Host to bind"),
    webhook_secret: Optional[str] = typer.Option(None, "--webhook-secret", help="GitHub Webhook secret for signature verification"),
    log_format: str = typer.Option("text", "--log-format", help="日志格式 (text/json)"),
):
    """启动 REST API 服务（含 webhook 端点）"""
    # 初始化结构化日志
    try:
        from ai_pr_review.structured_logging import setup_logging
        setup_logging(format=log_format, level="INFO")
    except ImportError:
        logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")

    import asyncio as _asyncio
    from ai_pr_review.api_server import build_router, serve as _serve

    config = load_config()

    async def review_callback(pr_url: str) -> None:
        """webhook/API 触发的审查回调"""
        console.print(f"📨 Received review request: {pr_url}")
        # 复用 review 命令的核心逻辑（简化版，避免递归调用 typer）
        gh_client = GitHubClient(token=config.github.token)
        pr_metadata = gh_client.get_pr_metadata(pr_url)
        diff_content = gh_client.get_pr_diff_content(pr_url)
        parsed_diff = parse_diff(diff_content)
        analyzer = AIAnalyzer(
            config=config,
            get_file_content_fn=lambda url, path, ref: gh_client.get_file_content(
                pr_url, path, pr_metadata.head_branch
            ),
            repo_url=pr_url,
        )
        result = await analyzer.analyze(
            pr_metadata=pr_metadata,
            parsed_diff=parsed_diff,
        )
        output = format_terminal(result)
        console.print(output)
        if config.github.token:
            current_sha = gh_client.get_pr_head_sha(pr_url)
            commenter = Commenter(gh_client)
            commenter.post_review_with_inline_comments(pr_url, result, commit_id=current_sha)
            console.print("✅ Review posted to GitHub!")

    def history_callback() -> list:
        from ai_pr_review.history import load_records
        from dataclasses import asdict
        return [asdict(r) for r in load_records()]

    router = build_router(
        review_fn=review_callback,
        history_fn=history_callback,
        webhook_secret=webhook_secret or "",
    )

    console.print(Panel(f"🚀 AI PR Review API Server", subtitle=f"{host}:{port}"))
    console.print("Endpoints:")
    console.print("  POST /api/review     - 触发 PR 审查")
    console.print("  GET  /api/history    - 查询审查历史")
    console.print("  GET  /api/health     - 健康检查")
    console.print("  POST /webhook        - GitHub Webhook 入口")
    console.print("\nPress Ctrl+C to stop.\n")

    _asyncio.run(_serve(router, host=host, port=port).serve_forever())


@app.command()
def dashboard(
    output: str = typer.Option("dashboard.html", "--output", "-o", help="Output HTML file path"),
    port: int = typer.Option(8001, "--port", "-p", help="Port to serve on (0 = no server, just write file)"),
):
    """生成审查历史 Dashboard HTML 页面"""
    from ai_pr_review.dashboard import render_dashboard
    import webbrowser
    from pathlib import Path as _Path

    html_content = render_dashboard()
    output_path = _Path(output)
    output_path.write_text(html_content, encoding="utf-8")
    console.print(f"✅ Dashboard saved to {output_path}")

    if port > 0:
        # 启动简易 HTTP 服务展示页面
        import http.server
        import socketserver
        import threading

        class _Handler(http.server.SimpleHTTPRequestHandler):
            def __init__(self, *args, **kwargs):
                super().__init__(*args, directory=str(output_path.parent), **kwargs)

            def do_GET(self):
                if self.path == "/" or self.path == "/dashboard.html":
                    self.path = "/" + output_path.name
                return super().do_GET()

        console.print(f"🌐 Serving dashboard at http://localhost:{port}")
        console.print("Press Ctrl+C to stop.")
        with socketserver.TCPServer(("127.0.0.1", port), _Handler) as httpd:
            webbrowser.open(f"http://localhost:{port}/")
            try:
                httpd.serve_forever()
            except KeyboardInterrupt:
                console.print("\n👋 Dashboard server stopped.")


if __name__ == "__main__":
    app()
