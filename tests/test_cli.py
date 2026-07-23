"""cli.py 的单元测试。

使用 pytest + typer.testing.CliRunner 测试 CLI 命令。
所有外部依赖（GitHubClient、AIAnalyzer、Commenter 等）均通过 mock 隔离。
"""

import tempfile
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch
from typer.testing import CliRunner

import pytest

from ai_pr_review.cli import app
from ai_pr_review.config import AppConfig, AIConfig, GitHubConfig, AnalysisConfig, ExpertConfig
from ai_pr_review.models import (
    AnalysisResult,
    AnalysisSummary,
    Finding,
    Suggestion,
    Severity,
    ParsedDiff,
    FileDiff,
    DiffHunk,
    ChangeType,
    PRMetadata,
)
from ai_pr_review.history import AnalysisRecord
from ai_pr_review.team_learner import TeamRule, TeamPattern

runner = CliRunner()


@pytest.fixture(autouse=True)
def _isolate_cache_dir():
    """自动隔离缓存目录，避免测试读写真实的 ~/.ai-pr-review/cache/。"""
    with tempfile.TemporaryDirectory() as tmpdir:
        with patch("ai_pr_review.cache.CACHE_DIR", Path(tmpdir) / "cache"):
            yield

PR_URL = "https://github.com/owner/repo/pull/1"


# ---------- 工具函数：构造 mock 数据 ----------

def _make_config(token: str = "fake-token") -> AppConfig:
    """构造一个带 token 的测试配置。"""
    return AppConfig(
        github=GitHubConfig(token=token),
        ai=AIConfig(model="deepseek-chat", api_key="fake-key"),
        analysis=AnalysisConfig(),
        expert=ExpertConfig(),
    )


def _make_metadata() -> PRMetadata:
    return PRMetadata(
        title="Test PR",
        description="test description",
        author="tester",
        base_branch="main",
        head_branch="feature",
        labels=[],
        url=PR_URL,
        number=1,
        repo_owner="owner",
        repo_name="repo",
    )


def _make_small_diff() -> ParsedDiff:
    """构造一个小型 diff（不触发分片）。"""
    hunk = DiffHunk(
        file_path="src/app.py",
        change_type=ChangeType.MODIFIED,
        old_start=1, old_count=3,
        new_start=1, new_count=5,
        content="@@ -1,3 +1,5 @@\n+new line\n+another\n old line",
        header="@@ -1,3 +1,5 @@",
    )
    f = FileDiff(
        path="src/app.py",
        change_type=ChangeType.MODIFIED,
        hunks=[hunk],
        additions=5,
        deletions=3,
    )
    return ParsedDiff(files=[f], total_additions=5, total_deletions=3)


def _make_large_diff() -> ParsedDiff:
    """构造一个大型 diff（触发分片，文件数 > SHARD_FILE_THRESHOLD）。"""
    files = []
    for i in range(25):
        hunk = DiffHunk(
            file_path=f"file_{i}.py",
            change_type=ChangeType.MODIFIED,
            old_start=1, old_count=3, new_start=1, new_count=5,
            content=f"@@ -1,3 +1,5 @@\n+line {i}",
            header="@@ -1,3 +1,5 @@",
        )
        files.append(FileDiff(
            path=f"file_{i}.py",
            change_type=ChangeType.MODIFIED,
            hunks=[hunk],
            additions=5, deletions=3,
        ))
    return ParsedDiff(files=files, total_additions=125, total_deletions=75)


def _make_result() -> AnalysisResult:
    """构造一个标准分析结果。"""
    return AnalysisResult(
        summary=AnalysisSummary(
            intent="修复登录 bug",
            scope="auth 模块",
            key_changes=["重置 token", "更新校验逻辑"],
        ),
        findings=[
            Finding(
                type="security",
                severity=Severity.HIGH,
                confidence=4,
                expert="security",
                file="src/app.py",
                line=10,
                title="硬编码密钥",
                description="代码中存在硬编码密钥",
                suggestion="使用环境变量",
                code_snippet="SECRET='xxx'",
            ),
            Finding(
                type="performance",
                severity=Severity.LOW,
                confidence=2,
                expert="performance",
                file="src/app.py",
                line=20,
                title="循环内查询数据库",
                description="循环中查询数据库影响性能",
                suggestion="批量查询",
                code_snippet="for x: db.query(x)",
            ),
        ],
        suggestions=[
            Suggestion(
                category="refactor",
                priority=Severity.MEDIUM,
                description="建议提取公共函数",
                example="...",
            ),
        ],
    )


def _build_review_mocks(
    *,
    config: AppConfig,
    pr_metadata: PRMetadata = None,
    parsed_diff: ParsedDiff = None,
    result: AnalysisResult = None,
    head_sha: str = "abc123",
    diff_content: str = "fake diff",
):
    """构造 review 命令所需的所有 mock 对象（不修改模块属性，仅返回 mock 实例）。

    调用方需通过 @patch 装饰器将这些 mock 的 return_value 注入到模块。
    """
    pr_metadata = pr_metadata or _make_metadata()
    parsed_diff = parsed_diff or _make_small_diff()
    result = result or _make_result()

    mock_gh = MagicMock()
    mock_gh.get_pr_metadata.return_value = pr_metadata
    mock_gh.get_pr_diff_content.return_value = diff_content
    mock_gh.get_pr_head_sha.return_value = head_sha
    mock_gh.get_file_content.return_value = ""

    mock_analyzer = MagicMock()
    mock_analyzer.analyze = AsyncMock(return_value=result)
    mock_analyzer.analyze_incremental = AsyncMock(return_value=result)
    mock_analyzer.analyze_with_shards = AsyncMock(return_value=result)
    mock_analyzer.analyze_stream = MagicMock()
    mock_analyzer.analyze_with_shards_stream = MagicMock()

    mock_commenter = MagicMock()

    mock_inc = MagicMock()
    mock_inc.should_analyze_incremental.return_value = None
    mock_inc.get_incremental_diff.return_value = ""
    mock_inc.build_incremental_context.return_value = {"is_incremental": True}

    return {
        "config": config,
        "gh": mock_gh,
        "analyzer": mock_analyzer,
        "commenter": mock_commenter,
        "incremental": mock_inc,
        "result": result,
        "parsed_diff": parsed_diff,
        "pr_metadata": pr_metadata,
    }


def _wire_review_patches(
    mocks,
    mock_load_config,
    mock_save_record,
    mock_gh_class,
    mock_analyzer_class,
    mock_commenter_class,
    mock_inc_class,
    mock_parse_diff,
    mock_format_terminal,
):
    """将 mock 对象的 return_value 绑定到 @patch 装饰器传入的 MagicMock 上。

    这样测试函数中的 mock_* 参数与 CLI 实际调用的对象保持一致，断言才有效。
    """
    mock_load_config.return_value = mocks["config"]
    mock_gh_class.return_value = mocks["gh"]
    mock_analyzer_class.return_value = mocks["analyzer"]
    mock_commenter_class.return_value = mocks["commenter"]
    mock_inc_class.return_value = mocks["incremental"]
    mock_parse_diff.return_value = mocks["parsed_diff"]
    mock_format_terminal.return_value = "REPORT"


# ============================================================
# review 命令测试
# ============================================================

class TestReviewCommand:
    """review 命令相关测试。"""

    @patch("ai_pr_review.cli.parse_diff")
    @patch("ai_pr_review.cli.format_terminal")
    @patch("ai_pr_review.cli.IncrementalAnalyzer")
    @patch("ai_pr_review.cli.Commenter")
    @patch("ai_pr_review.cli.AIAnalyzer")
    @patch("ai_pr_review.cli.GitHubClient")
    @patch("ai_pr_review.cli.save_record")
    @patch("ai_pr_review.cli.load_config")
    def test_review_normal_flow(
        self,
        mock_load_config,
        mock_save_record,
        mock_gh_class,
        mock_analyzer_class,
        mock_commenter_class,
        mock_inc_class,
        mock_format_terminal,
        mock_parse_diff,
    ):
        """正常 review 流程：验证输出包含分析结果，并发布评论与保存记录。"""
        mocks = _build_review_mocks(config=_make_config())
        _wire_review_patches(
            mocks, mock_load_config, mock_save_record, mock_gh_class,
            mock_analyzer_class, mock_commenter_class, mock_inc_class,
            mock_parse_diff, mock_format_terminal,
        )

        cmd_result = runner.invoke(app, ["review", PR_URL])

        assert cmd_result.exit_code == 0
        assert "REPORT" in cmd_result.output
        # 验证发布了评论
        mocks["commenter"].post_review_with_inline_comments.assert_called_once()
        # 验证保存了历史记录
        mock_save_record.assert_called_once()

    @patch("ai_pr_review.cli.parse_diff")
    @patch("ai_pr_review.cli.format_terminal")
    @patch("ai_pr_review.cli.IncrementalAnalyzer")
    @patch("ai_pr_review.cli.Commenter")
    @patch("ai_pr_review.cli.AIAnalyzer")
    @patch("ai_pr_review.cli.GitHubClient")
    @patch("ai_pr_review.cli.save_record")
    @patch("ai_pr_review.cli.load_config")
    def test_review_no_comment_flag(
        self,
        mock_load_config,
        mock_save_record,
        mock_gh_class,
        mock_analyzer_class,
        mock_commenter_class,
        mock_inc_class,
        mock_format_terminal,
        mock_parse_diff,
    ):
        """--no-comment 时不发布评论。"""
        mocks = _build_review_mocks(config=_make_config())
        _wire_review_patches(
            mocks, mock_load_config, mock_save_record, mock_gh_class,
            mock_analyzer_class, mock_commenter_class, mock_inc_class,
            mock_parse_diff, mock_format_terminal,
        )

        cmd_result = runner.invoke(app, ["review", PR_URL, "--no-comment"])

        assert cmd_result.exit_code == 0
        # Commenter.post_review_with_inline_comments 不应被调用
        mocks["commenter"].post_review_with_inline_comments.assert_not_called()

    @patch("ai_pr_review.cli.parse_diff")
    @patch("ai_pr_review.cli.format_terminal")
    @patch("ai_pr_review.cli.IncrementalAnalyzer")
    @patch("ai_pr_review.cli.Commenter")
    @patch("ai_pr_review.cli.AIAnalyzer")
    @patch("ai_pr_review.cli.GitHubClient")
    @patch("ai_pr_review.cli.save_record")
    @patch("ai_pr_review.cli.load_config")
    def test_review_severity_medium_filters_low(
        self,
        mock_load_config,
        mock_save_record,
        mock_gh_class,
        mock_analyzer_class,
        mock_commenter_class,
        mock_inc_class,
        mock_format_terminal,
        mock_parse_diff,
    ):
        """--severity medium 过滤低严重级别（传递给 analyze）。"""
        mocks = _build_review_mocks(config=_make_config())
        _wire_review_patches(
            mocks, mock_load_config, mock_save_record, mock_gh_class,
            mock_analyzer_class, mock_commenter_class, mock_inc_class,
            mock_parse_diff, mock_format_terminal,
        )

        cmd_result = runner.invoke(app, ["review", PR_URL, "--severity", "medium"])

        assert cmd_result.exit_code == 0
        kwargs = mocks["analyzer"].analyze.call_args.kwargs
        assert kwargs.get("severity_threshold") == "medium"

    @patch("ai_pr_review.cli.parse_diff")
    @patch("ai_pr_review.cli.format_terminal")
    @patch("ai_pr_review.cli.IncrementalAnalyzer")
    @patch("ai_pr_review.cli.Commenter")
    @patch("ai_pr_review.cli.AIAnalyzer")
    @patch("ai_pr_review.cli.GitHubClient")
    @patch("ai_pr_review.cli.save_record")
    @patch("ai_pr_review.cli.load_config")
    def test_review_focus_security(
        self,
        mock_load_config,
        mock_save_record,
        mock_gh_class,
        mock_analyzer_class,
        mock_commenter_class,
        mock_inc_class,
        mock_format_terminal,
        mock_parse_diff,
    ):
        """--focus security 过滤非安全相关发现。"""
        mocks = _build_review_mocks(config=_make_config())
        _wire_review_patches(
            mocks, mock_load_config, mock_save_record, mock_gh_class,
            mock_analyzer_class, mock_commenter_class, mock_inc_class,
            mock_parse_diff, mock_format_terminal,
        )

        cmd_result = runner.invoke(app, ["review", PR_URL, "--focus", "security"])

        assert cmd_result.exit_code == 0
        kwargs = mocks["analyzer"].analyze.call_args.kwargs
        assert kwargs.get("focus") == ["security"]

    @patch("ai_pr_review.cli.parse_diff")
    @patch("ai_pr_review.cli.format_terminal")
    @patch("ai_pr_review.cli._run_stream")
    @patch("ai_pr_review.cli.IncrementalAnalyzer")
    @patch("ai_pr_review.cli.Commenter")
    @patch("ai_pr_review.cli.AIAnalyzer")
    @patch("ai_pr_review.cli.GitHubClient")
    @patch("ai_pr_review.cli.save_record")
    @patch("ai_pr_review.cli.load_config")
    def test_review_stream_output(
        self,
        mock_load_config,
        mock_save_record,
        mock_gh_class,
        mock_analyzer_class,
        mock_commenter_class,
        mock_inc_class,
        mock_run_stream,
        mock_format_terminal,
        mock_parse_diff,
    ):
        """--stream 流式输出：调用 analyze_stream 而非 analyze。"""
        mocks = _build_review_mocks(config=_make_config())
        _wire_review_patches(
            mocks, mock_load_config, mock_save_record, mock_gh_class,
            mock_analyzer_class, mock_commenter_class, mock_inc_class,
            mock_parse_diff, mock_format_terminal,
        )
        # _run_stream 被 asyncio.run 调用，mock 其返回值为分析结果
        mock_run_stream.return_value = mocks["result"]

        cmd_result = runner.invoke(app, ["review", PR_URL, "--stream"])

        assert cmd_result.exit_code == 0
        # 流式分支应调用 analyze_stream，且不调用 analyze
        mocks["analyzer"].analyze_stream.assert_called_once()
        mocks["analyzer"].analyze.assert_not_called()

    @patch("ai_pr_review.cli.parse_diff")
    @patch("ai_pr_review.cli.format_terminal")
    @patch("ai_pr_review.cli.IncrementalAnalyzer")
    @patch("ai_pr_review.cli.Commenter")
    @patch("ai_pr_review.cli.AIAnalyzer")
    @patch("ai_pr_review.cli.GitHubClient")
    @patch("ai_pr_review.cli.save_record")
    @patch("ai_pr_review.cli.load_config")
    def test_review_incremental_path(
        self,
        mock_load_config,
        mock_save_record,
        mock_gh_class,
        mock_analyzer_class,
        mock_commenter_class,
        mock_inc_class,
        mock_format_terminal,
        mock_parse_diff,
    ):
        """--incremental 增量分析路径：head_sha 与上次记录不同，触发增量分析。"""
        config = _make_config()
        # 历史记录中上次 SHA 与当前不同
        last_record = AnalysisRecord(
            pr_url=PR_URL, pr_title="old", head_sha="old_sha",
            timestamp="2024-01-01T00:00:00",
        )
        inc_parsed = _make_small_diff()
        inc_diff_text = "fake incremental diff"

        mock_gh = MagicMock()
        mock_gh.get_pr_metadata.return_value = _make_metadata()
        mock_gh.get_pr_diff_content.return_value = "full diff"
        mock_gh.get_pr_head_sha.return_value = "new_sha"
        mock_gh.get_commit_diff.return_value = inc_diff_text

        mock_analyzer = MagicMock()
        mock_analyzer.analyze_incremental = AsyncMock(return_value=_make_result())
        mock_analyzer.analyze = AsyncMock(return_value=_make_result())
        mock_commenter = MagicMock()

        mock_inc = MagicMock()
        mock_inc.should_analyze_incremental.return_value = last_record
        mock_inc.get_incremental_diff.return_value = inc_diff_text
        mock_inc.build_incremental_context.return_value = {"is_incremental": True}

        mock_load_config.return_value = config
        mock_gh_class.return_value = mock_gh
        mock_analyzer_class.return_value = mock_analyzer
        mock_commenter_class.return_value = mock_commenter
        mock_inc_class.return_value = mock_inc
        # parse_diff 第一次返回全量，第二次返回增量
        mock_parse_diff.side_effect = [_make_small_diff(), inc_parsed]
        mock_format_terminal.return_value = "REPORT"

        cmd_result = runner.invoke(app, ["review", PR_URL, "--incremental"])

        assert cmd_result.exit_code == 0
        # 验证走了增量分析路径
        mock_analyzer.analyze_incremental.assert_called_once()
        mock_analyzer.analyze.assert_not_called()
        # 输出包含增量提示
        assert "Incremental" in cmd_result.output

    @patch("ai_pr_review.cli.parse_diff")
    @patch("ai_pr_review.cli.format_terminal")
    @patch("ai_pr_review.cli.IncrementalAnalyzer")
    @patch("ai_pr_review.cli.Commenter")
    @patch("ai_pr_review.cli.AIAnalyzer")
    @patch("ai_pr_review.cli.GitHubClient")
    @patch("ai_pr_review.cli.save_record")
    @patch("ai_pr_review.cli.load_config")
    def test_review_incremental_no_history_falls_back_to_full(
        self,
        mock_load_config,
        mock_save_record,
        mock_gh_class,
        mock_analyzer_class,
        mock_commenter_class,
        mock_inc_class,
        mock_format_terminal,
        mock_parse_diff,
    ):
        """--incremental 但无历史记录时走全量分析。"""
        mocks = _build_review_mocks(config=_make_config())
        # 无历史记录
        mocks["incremental"].should_analyze_incremental.return_value = None
        _wire_review_patches(
            mocks, mock_load_config, mock_save_record, mock_gh_class,
            mock_analyzer_class, mock_commenter_class, mock_inc_class,
            mock_parse_diff, mock_format_terminal,
        )

        cmd_result = runner.invoke(app, ["review", PR_URL, "--incremental"])

        assert cmd_result.exit_code == 0
        # 走全量分析，不调用 analyze_incremental
        mocks["analyzer"].analyze.assert_called_once()
        mocks["analyzer"].analyze_incremental.assert_not_called()

    @patch("ai_pr_review.cli.parse_diff")
    @patch("ai_pr_review.cli.format_terminal")
    @patch("ai_pr_review.cli.IncrementalAnalyzer")
    @patch("ai_pr_review.cli.Commenter")
    @patch("ai_pr_review.cli.AIAnalyzer")
    @patch("ai_pr_review.cli.GitHubClient")
    @patch("ai_pr_review.cli.save_record")
    @patch("ai_pr_review.cli.load_config")
    def test_review_incremental_same_sha_no_changes(
        self,
        mock_load_config,
        mock_save_record,
        mock_gh_class,
        mock_analyzer_class,
        mock_commenter_class,
        mock_inc_class,
        mock_format_terminal,
        mock_parse_diff,
    ):
        """--incremental 且 SHA 相同时提示无新变更并提前返回。"""
        config = _make_config()
        same_sha = "same_sha_value"
        last_record = AnalysisRecord(
            pr_url=PR_URL, pr_title="same", head_sha=same_sha,
            timestamp="2024-01-01T00:00:00",
        )

        mock_gh = MagicMock()
        mock_gh.get_pr_metadata.return_value = _make_metadata()
        mock_gh.get_pr_diff_content.return_value = "diff"
        mock_gh.get_pr_head_sha.return_value = same_sha

        mock_analyzer = MagicMock()
        mock_analyzer.analyze = AsyncMock(return_value=_make_result())
        mock_analyzer.analyze_incremental = AsyncMock(return_value=_make_result())
        mock_commenter = MagicMock()

        mock_inc = MagicMock()
        mock_inc.should_analyze_incremental.return_value = last_record

        mock_load_config.return_value = config
        mock_gh_class.return_value = mock_gh
        mock_analyzer_class.return_value = mock_analyzer
        mock_commenter_class.return_value = mock_commenter
        mock_inc_class.return_value = mock_inc
        mock_parse_diff.return_value = _make_small_diff()
        mock_format_terminal.return_value = "REPORT"

        cmd_result = runner.invoke(app, ["review", PR_URL, "--incremental"])

        assert cmd_result.exit_code == 0
        # 应输出 "No new commits" 提示
        assert "No new commits" in cmd_result.output
        # 不应调用任何分析方法
        mock_analyzer.analyze.assert_not_called()
        mock_analyzer.analyze_incremental.assert_not_called()
        # 不应保存记录
        mock_save_record.assert_not_called()

    @patch("ai_pr_review.cli.parse_diff")
    @patch("ai_pr_review.cli.format_terminal")
    @patch("ai_pr_review.cli.IncrementalAnalyzer")
    @patch("ai_pr_review.cli.Commenter")
    @patch("ai_pr_review.cli.AIAnalyzer")
    @patch("ai_pr_review.cli.GitHubClient")
    @patch("ai_pr_review.cli.save_record")
    @patch("ai_pr_review.cli.load_config")
    def test_review_large_pr_triggers_sharding(
        self,
        mock_load_config,
        mock_save_record,
        mock_gh_class,
        mock_analyzer_class,
        mock_commenter_class,
        mock_inc_class,
        mock_format_terminal,
        mock_parse_diff,
    ):
        """大 PR 触发分片分析。"""
        large_diff = _make_large_diff()
        mocks = _build_review_mocks(config=_make_config(), parsed_diff=large_diff)
        _wire_review_patches(
            mocks, mock_load_config, mock_save_record, mock_gh_class,
            mock_analyzer_class, mock_commenter_class, mock_inc_class,
            mock_parse_diff, mock_format_terminal,
        )

        cmd_result = runner.invoke(app, ["review", PR_URL])

        assert cmd_result.exit_code == 0
        # 应调用 analyze_with_shards 而非 analyze
        mocks["analyzer"].analyze_with_shards.assert_called_once()
        mocks["analyzer"].analyze.assert_not_called()
        # 输出包含分片提示
        assert "Large PR detected" in cmd_result.output or "sharding" in cmd_result.output

    @patch("ai_pr_review.cli.parse_diff")
    @patch("ai_pr_review.cli.format_terminal")
    @patch("ai_pr_review.cli.IncrementalAnalyzer")
    @patch("ai_pr_review.cli.Commenter")
    @patch("ai_pr_review.cli.AIAnalyzer")
    @patch("ai_pr_review.cli.GitHubClient")
    @patch("ai_pr_review.cli.save_record")
    @patch("ai_pr_review.cli.load_config")
    def test_review_no_token_skips_comment(
        self,
        mock_load_config,
        mock_save_record,
        mock_gh_class,
        mock_analyzer_class,
        mock_commenter_class,
        mock_inc_class,
        mock_format_terminal,
        mock_parse_diff,
    ):
        """无 GitHub token 时跳过评论发布。"""
        # 关键：token 为空
        mocks = _build_review_mocks(config=_make_config(token=""))
        _wire_review_patches(
            mocks, mock_load_config, mock_save_record, mock_gh_class,
            mock_analyzer_class, mock_commenter_class, mock_inc_class,
            mock_parse_diff, mock_format_terminal,
        )

        cmd_result = runner.invoke(app, ["review", PR_URL])

        assert cmd_result.exit_code == 0
        # 应输出跳过评论提示
        assert "No GitHub token" in cmd_result.output or "skipping" in cmd_result.output
        # Commenter.post_review_with_inline_comments 不应被调用
        mocks["commenter"].post_review_with_inline_comments.assert_not_called()

    @patch("ai_pr_review.cli.parse_diff")
    @patch("ai_pr_review.cli.format_terminal")
    @patch("ai_pr_review.cli.IncrementalAnalyzer")
    @patch("ai_pr_review.cli.Commenter")
    @patch("ai_pr_review.cli.AIAnalyzer")
    @patch("ai_pr_review.cli.GitHubClient")
    @patch("ai_pr_review.cli.save_record")
    @patch("ai_pr_review.cli.load_config")
    def test_review_diff_fetch_failure_exits_gracefully(
        self,
        mock_load_config,
        mock_save_record,
        mock_gh_class,
        mock_analyzer_class,
        mock_commenter_class,
        mock_inc_class,
        mock_format_terminal,
        mock_parse_diff,
    ):
        """PR diff 获取失败时优雅退出（exit code 1）。"""
        config = _make_config()
        mock_gh = MagicMock()
        mock_gh.get_pr_metadata.return_value = _make_metadata()
        # get_pr_diff_content 抛异常
        mock_gh.get_pr_diff_content.side_effect = Exception("network error")

        mock_load_config.return_value = config
        mock_gh_class.return_value = mock_gh
        mock_analyzer_class.return_value = MagicMock()
        mock_commenter_class.return_value = MagicMock()
        mock_inc_class.return_value = MagicMock()
        mock_parse_diff.return_value = _make_small_diff()
        mock_format_terminal.return_value = "REPORT"

        cmd_result = runner.invoke(app, ["review", PR_URL])

        # 应以 exit code 1 退出
        assert cmd_result.exit_code == 1
        # 应输出错误提示
        assert "Failed to fetch PR diff" in cmd_result.output


# ============================================================
# learn 命令测试
# ============================================================

class TestLearnCommand:
    """learn 命令相关测试。"""

    @patch("ai_pr_review.cli.save_team_pattern")
    @patch("ai_pr_review.cli.load_team_pattern")
    @patch("ai_pr_review.cli.TeamLearner")
    @patch("ai_pr_review.cli.GitHubClient")
    @patch("ai_pr_review.cli.load_config")
    def test_learn_normal_flow(
        self,
        mock_load_config,
        mock_gh_class,
        mock_learner_class,
        mock_load_team_pattern,
        mock_save_team_pattern,
    ):
        """正常学习流程。"""
        config = _make_config()
        mock_load_config.return_value = config
        # 无已有缓存
        mock_load_team_pattern.return_value = None

        mock_gh = MagicMock()
        mock_gh.get_repo_pr_comments.return_value = [
            {"body": "请加测试", "author": "reviewer1"},
            {"body": "命名不规范", "author": "reviewer2"},
        ]
        mock_gh_class.return_value = mock_gh

        pattern = TeamPattern(
            rules=[
                TeamRule(category="testing", description="必须加测试", example=""),
                TeamRule(category="style", description="命名规范", example=""),
            ],
            common_terms=["测试", "命名"],
            severity_preference={},
            focus_areas=["testing", "style"],
        )
        mock_learner = MagicMock()
        mock_learner.extract_patterns = AsyncMock(return_value=pattern)
        mock_learner_class.return_value = mock_learner

        cmd_result = runner.invoke(app, ["learn", PR_URL])

        assert cmd_result.exit_code == 0
        # 验证保存了 pattern
        mock_save_team_pattern.assert_called_once()
        # 验证输出包含学到的规则数
        assert "Learned 2 team rules" in cmd_result.output

    @patch("ai_pr_review.cli.save_team_pattern")
    @patch("ai_pr_review.cli.load_team_pattern")
    @patch("ai_pr_review.cli.TeamLearner")
    @patch("ai_pr_review.cli.GitHubClient")
    @patch("ai_pr_review.cli.load_config")
    def test_learn_force_flag_relearns(
        self,
        mock_load_config,
        mock_gh_class,
        mock_learner_class,
        mock_load_team_pattern,
        mock_save_team_pattern,
    ):
        """--force 强制重新学习（即使有缓存）。"""
        config = _make_config()
        mock_load_config.return_value = config

        # 已有缓存
        existing_pattern = TeamPattern(
            rules=[TeamRule(category="style", description="old rule", example="")],
            common_terms=[], severity_preference={}, focus_areas=[],
            learned_at="2024-01-01T00:00:00",
        )
        mock_load_team_pattern.return_value = existing_pattern

        mock_gh = MagicMock()
        mock_gh.get_repo_pr_comments.return_value = [{"body": "new comment"}]
        mock_gh_class.return_value = mock_gh

        new_pattern = TeamPattern(
            rules=[TeamRule(category="security", description="new rule", example="")],
            common_terms=[], severity_preference={}, focus_areas=[],
        )
        mock_learner = MagicMock()
        mock_learner.extract_patterns = AsyncMock(return_value=new_pattern)
        mock_learner_class.return_value = mock_learner

        cmd_result = runner.invoke(app, ["learn", PR_URL, "--force"])

        assert cmd_result.exit_code == 0
        # --force 应该绕过缓存，仍然调用 learner
        mock_learner.extract_patterns.assert_called_once()
        mock_save_team_pattern.assert_called_once()

    @patch("ai_pr_review.cli.save_team_pattern")
    @patch("ai_pr_review.cli.load_team_pattern")
    @patch("ai_pr_review.cli.TeamLearner")
    @patch("ai_pr_review.cli.GitHubClient")
    @patch("ai_pr_review.cli.load_config")
    def test_learn_no_comments_returns_early(
        self,
        mock_load_config,
        mock_gh_class,
        mock_learner_class,
        mock_load_team_pattern,
        mock_save_team_pattern,
    ):
        """无评论时提示并提前返回。"""
        config = _make_config()
        mock_load_config.return_value = config
        mock_load_team_pattern.return_value = None

        mock_gh = MagicMock()
        mock_gh.get_repo_pr_comments.return_value = []
        mock_gh_class.return_value = mock_gh

        mock_learner = MagicMock()
        mock_learner.extract_patterns = AsyncMock(return_value=MagicMock())
        mock_learner_class.return_value = mock_learner

        cmd_result = runner.invoke(app, ["learn", PR_URL])

        assert cmd_result.exit_code == 0
        # 应输出无评论提示
        assert "No comments found" in cmd_result.output
        # 不应调用 learner 和 save
        mock_learner.extract_patterns.assert_not_called()
        mock_save_team_pattern.assert_not_called()


# ============================================================
# history 命令测试
# ============================================================

class TestHistoryCommand:
    """history 命令相关测试。"""

    @patch("ai_pr_review.cli.format_history_table")
    @patch("ai_pr_review.cli.load_records")
    def test_history_normal_display(
        self,
        mock_load_records,
        mock_format_history_table,
    ):
        """正常显示历史记录。"""
        records = [
            AnalysisRecord(
                pr_url=PR_URL,
                pr_title="Test PR 1",
                findings_count=3,
                high_severity_count=1,
                medium_severity_count=1,
                low_severity_count=1,
                suggestions_count=2,
                model="deepseek-chat",
            ),
            AnalysisRecord(
                pr_url=PR_URL,
                pr_title="Test PR 2",
                findings_count=1,
                high_severity_count=0,
                medium_severity_count=1,
                low_severity_count=0,
                suggestions_count=1,
                model="qwen-plus",
            ),
        ]
        mock_load_records.return_value = records
        mock_format_history_table.return_value = ""

        cmd_result = runner.invoke(app, ["history"])

        assert cmd_result.exit_code == 0
        # 验证调用了 format_history_table，并传入默认 limit=20
        mock_format_history_table.assert_called_once()
        args, kwargs = mock_format_history_table.call_args
        # 第一个位置参数应为 records 列表
        assert args[0] is records
        # limit 应为默认值 20
        if len(args) >= 2:
            assert args[1] == 20
        if "limit" in kwargs:
            assert kwargs["limit"] == 20

    @patch("ai_pr_review.cli.format_history_table")
    @patch("ai_pr_review.cli.load_records")
    def test_history_no_records(
        self,
        mock_load_records,
        mock_format_history_table,
    ):
        """无历史记录时提示。"""
        mock_load_records.return_value = []

        cmd_result = runner.invoke(app, ["history"])

        assert cmd_result.exit_code == 0
        # 应输出无历史记录提示
        assert "No review history found" in cmd_result.output
        # 不应调用 format_history_table
        mock_format_history_table.assert_not_called()

    @patch("ai_pr_review.cli.format_history_table")
    @patch("ai_pr_review.cli.load_records")
    def test_history_respects_limit_flag(
        self,
        mock_load_records,
        mock_format_history_table,
    ):
        """--limit/-n 参数生效。"""
        records = [
            AnalysisRecord(pr_url=PR_URL, pr_title=f"PR {i}") for i in range(5)
        ]
        mock_load_records.return_value = records
        mock_format_history_table.return_value = ""

        cmd_result = runner.invoke(app, ["history", "-n", "3"])

        assert cmd_result.exit_code == 0
        # 验证 limit=3 被传递
        args, kwargs = mock_format_history_table.call_args
        if len(args) >= 2:
            assert args[1] == 3
        if "limit" in kwargs:
            assert kwargs["limit"] == 3
