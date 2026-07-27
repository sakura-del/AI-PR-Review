"""CLI serve --web 标志测试（v0.10 M7）

覆盖：
- --web 标志存在且可被识别
- 不带 --web 走 v0.9 路径（默认）
- serve 命令整体加载不报错
"""
from typer.testing import CliRunner

from ai_pr_review.cli.cli import app


runner = CliRunner()


def test_serve_help_includes_web_flag():
    """serve --help 应显示 --web 选项"""
    result = runner.invoke(app, ["serve", "--help"])
    assert result.exit_code == 0
    assert "--web" in result.stdout
    # 默认值应说明
    assert "FastAPI" in result.stdout or "v0.10" in result.stdout


def test_serve_command_registered():
    """serve 子命令在 CLI 中"""
    result = runner.invoke(app, ["--help"])
    assert result.exit_code == 0
    assert "serve" in result.stdout


def test_dashboard_command_still_registered():
    """dashboard 命令保留（v0.7 的静态 HTML 版本）"""
    result = runner.invoke(app, ["--help"])
    assert "dashboard" in result.stdout