"""config 子命令组（init/validate/show）的单元测试。

使用 pytest + typer.testing.CliRunner 测试 CLI 命令。
所有配置文件均通过 tmp_path 生成临时文件，避免污染 HOME 环境。
环境变量通过 monkeypatch 清除，确保测试结果不受外部环境影响。
"""

import pytest
from pathlib import Path
from typer.testing import CliRunner

from ai_pr_review.cli import app

runner = CliRunner()

# 可能影响 load_config 的环境变量列表
_ENV_VARS_TO_CLEAR = [
    "GITHUB_TOKEN",
    "DEEPSEEK_API_KEY", "DEEPSEEK_BASE_URL", "DEEPSEEK_MODEL",
    "QWEN_API_KEY", "QWEN_BASE_URL", "QWEN_MODEL",
    "GLM_API_KEY", "GLM_BASE_URL", "GLM_MODEL",
    "AI_API_KEY", "AI_BASE_URL", "AI_MODEL",
    "RATE_LIMIT",
]


@pytest.fixture(autouse=True)
def _isolate_env(monkeypatch):
    """自动隔离环境变量与 .env 文件，确保配置仅来自 TOML 文件。"""
    for var in _ENV_VARS_TO_CLEAR:
        monkeypatch.delenv(var, raising=False)
    # 禁止 load_config 加载 .env 文件
    monkeypatch.setattr("ai_pr_review.config._load_env_file", lambda: None)


# ---------- 辅助函数 ----------

def _write_toml(path: Path, content: str) -> Path:
    """将 TOML 内容写入指定路径并返回该路径。"""
    path.write_text(content, encoding="utf-8")
    return path


VALID_TOML = """\
[github]
token = "ghp_abcdefghijklmnopqrstuvwxyz"

[ai]
provider = "deepseek"
api_key = "sk-test1234567890abcdef"
model = "deepseek-chat"
base_url = "https://api.deepseek.com/v1"
max_tokens = 8000
temperature = 0.3

[analysis]
severity_threshold = "low"
min_confidence = 2

[expert]
enabled_experts = ["security", "architecture", "performance", "readability", "testing"]
"""

MISSING_API_KEY_TOML = """\
[github]
token = "ghp_test"

[ai]
provider = "deepseek"
api_key = ""
model = "deepseek-chat"
base_url = "https://api.deepseek.com/v1"
max_tokens = 8000
temperature = 0.3

[analysis]
min_confidence = 2

[expert]
enabled_experts = ["security", "architecture", "performance", "readability", "testing"]
"""

INVALID_TEMP_TOML = """\
[github]
token = "ghp_test"

[ai]
provider = "deepseek"
api_key = "sk-test"
model = "deepseek-chat"
base_url = "https://api.deepseek.com/v1"
max_tokens = 8000
temperature = 5.0

[analysis]
min_confidence = 2

[expert]
enabled_experts = ["security", "architecture", "performance", "readability", "testing"]
"""


# ============================================================
# config init 命令测试
# ============================================================

class TestConfigInit:
    """config init 子命令测试。"""

    def test_config_init_generates_file(self, tmp_path):
        """init 生成配置文件，内容包含 [ai]、api_key、model。"""
        output_file = tmp_path / "test_config.toml"
        cmd_result = runner.invoke(app, [
            "config", "init",
            "--provider", "deepseek",
            "--api-key", "sk-test",
            "--output", str(output_file),
            "--force",
        ])

        assert cmd_result.exit_code == 0
        assert output_file.exists()
        content = output_file.read_text(encoding="utf-8")
        assert "[ai]" in content
        assert 'api_key = "sk-test"' in content
        assert 'model = "deepseek-chat"' in content

    def test_config_init_refuses_overwrite_without_force(self, tmp_path):
        """文件已存在且未传 --force 时拒绝覆盖，退出码非 0。"""
        output_file = tmp_path / "existing.toml"
        _write_toml(output_file, "old content")

        cmd_result = runner.invoke(app, [
            "config", "init",
            "--provider", "deepseek",
            "--api-key", "sk-test",
            "--output", str(output_file),
        ])

        assert cmd_result.exit_code != 0
        # 原文件内容未被覆盖
        assert output_file.read_text(encoding="utf-8") == "old content"

    def test_config_init_force_overwrites(self, tmp_path):
        """--force 覆盖已存在文件。"""
        output_file = tmp_path / "existing.toml"
        _write_toml(output_file, "old content")

        cmd_result = runner.invoke(app, [
            "config", "init",
            "--provider", "deepseek",
            "--api-key", "sk-new",
            "--output", str(output_file),
            "--force",
        ])

        assert cmd_result.exit_code == 0
        content = output_file.read_text(encoding="utf-8")
        assert 'api_key = "sk-new"' in content
        assert "old content" not in content


# ============================================================
# config validate 命令测试
# ============================================================

class TestConfigValidate:
    """config validate 子命令测试。"""

    def test_config_validate_success(self, tmp_path):
        """合法配置校验通过，退出码 0 且输出含"校验通过"。"""
        config_file = _write_toml(tmp_path / "valid.toml", VALID_TOML)

        cmd_result = runner.invoke(app, [
            "config", "validate",
            "--config", str(config_file),
        ])

        assert cmd_result.exit_code == 0
        assert "校验通过" in cmd_result.output

    def test_config_validate_failure_missing_api_key(self, tmp_path):
        """api_key 为空时校验失败，退出码 1 且输出含"api_key"。"""
        config_file = _write_toml(tmp_path / "no_key.toml", MISSING_API_KEY_TOML)

        cmd_result = runner.invoke(app, [
            "config", "validate",
            "--config", str(config_file),
        ])

        assert cmd_result.exit_code == 1
        assert "api_key" in cmd_result.output

    def test_config_validate_failure_invalid_temperature(self, tmp_path):
        """temperature=5.0 越界时校验失败，退出码 1 且输出含"temperature"。"""
        config_file = _write_toml(tmp_path / "bad_temp.toml", INVALID_TEMP_TOML)

        cmd_result = runner.invoke(app, [
            "config", "validate",
            "--config", str(config_file),
        ])

        assert cmd_result.exit_code == 1
        assert "temperature" in cmd_result.output


# ============================================================
# config show 命令测试
# ============================================================

class TestConfigShow:
    """config show 子命令测试。"""

    def test_config_show_masks_api_key(self, tmp_path):
        """api_key 较长时输出含前 4 位 + ***，不包含完整 key。"""
        config_file = _write_toml(tmp_path / "show.toml", VALID_TOML)

        cmd_result = runner.invoke(app, [
            "config", "show",
            "--config", str(config_file),
        ])

        assert cmd_result.exit_code == 0
        # 前 4 位 + ***
        assert "sk-t***" in cmd_result.output
        # 完整 key 不应出现
        assert "sk-test1234567890abcdef" not in cmd_result.output

    def test_config_show_masks_token(self, tmp_path):
        """github.token 较长时同样脱敏。"""
        config_file = _write_toml(tmp_path / "show.toml", VALID_TOML)

        cmd_result = runner.invoke(app, [
            "config", "show",
            "--config", str(config_file),
        ])

        assert cmd_result.exit_code == 0
        # 前 4 位 + ***
        assert "ghp_***" in cmd_result.output
        # 完整 token 不应出现
        assert "ghp_abcdefghijklmnopqrstuvwxyz" not in cmd_result.output

    def test_config_show_displays_non_sensitive_fields(self, tmp_path):
        """输出包含 model、base_url、max_tokens 等非敏感字段。"""
        config_file = _write_toml(tmp_path / "show.toml", VALID_TOML)

        cmd_result = runner.invoke(app, [
            "config", "show",
            "--config", str(config_file),
        ])

        assert cmd_result.exit_code == 0
        assert "deepseek-chat" in cmd_result.output
        assert "https://api.deepseek.com/v1" in cmd_result.output
        assert "8000" in cmd_result.output
