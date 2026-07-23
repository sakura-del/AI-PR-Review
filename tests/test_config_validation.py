"""配置校验（validate_config / load_config_strict）的单元测试。

覆盖：缺必填项、范围越界、专家名非法、合法配置通过、load_config_strict 集成。
"""

import pytest

from ai_pr_review.config import (
    AIConfig,
    AnalysisConfig,
    AppConfig,
    ExpertConfig,
    GitHubConfig,
    load_config_strict,
    validate_config,
)
from ai_pr_review.config_error import (
    ConfigError,
    InvalidValueError,
    MissingRequiredError,
)


def _make_valid_config() -> AppConfig:
    """构造一个各项均合法的配置，供各测试按需破坏单项。"""
    return AppConfig(
        github=GitHubConfig(token="fake-token"),
        ai=AIConfig(api_key="fake-key", model="deepseek-chat"),
        analysis=AnalysisConfig(),
        expert=ExpertConfig(),
    )


class TestValidateRequired:
    """必填项校验。"""

    def test_missing_api_key_raises_missing_required(self):
        # 仅清空 api_key，其余字段保持合法，确保唯一错误为 MissingRequiredError
        config = _make_valid_config()
        config.ai.api_key = ""
        with pytest.raises(MissingRequiredError) as exc_info:
            validate_config(config)
        # 错误消息应包含修复建议与字段名
        message = str(exc_info.value)
        assert "ai.api_key" in message
        assert "AI_API_KEY" in message

    def test_missing_model_raises_missing_required(self):
        config = _make_valid_config()
        config.ai.model = ""
        with pytest.raises(MissingRequiredError) as exc_info:
            validate_config(config)
        assert "ai.model" in str(exc_info.value)


class TestValidateRanges:
    """范围校验。"""

    @pytest.mark.parametrize("temperature", [-0.1, 2.5, 10])
    def test_temperature_out_of_range_raises_invalid(self, temperature):
        config = _make_valid_config()
        config.ai.temperature = temperature
        with pytest.raises(InvalidValueError) as exc_info:
            validate_config(config)
        assert "ai.temperature" in str(exc_info.value)

    @pytest.mark.parametrize("temperature", [0, 1.0, 2])
    def test_temperature_boundary_valid(self, temperature):
        # 边界值 0 与 2 应通过校验
        config = _make_valid_config()
        config.ai.temperature = temperature
        validate_config(config)  # 不抛异常即通过

    @pytest.mark.parametrize("min_confidence", [0, 6, -1])
    def test_min_confidence_out_of_range_raises_invalid(self, min_confidence):
        config = _make_valid_config()
        config.analysis.min_confidence = min_confidence
        with pytest.raises(InvalidValueError) as exc_info:
            validate_config(config)
        assert "analysis.min_confidence" in str(exc_info.value)

    @pytest.mark.parametrize("min_confidence", [1, 3, 5])
    def test_min_confidence_boundary_valid(self, min_confidence):
        config = _make_valid_config()
        config.analysis.min_confidence = min_confidence
        validate_config(config)

    @pytest.mark.parametrize("max_tokens", [0, -1, -100])
    def test_max_tokens_non_positive_raises_invalid(self, max_tokens):
        config = _make_valid_config()
        config.ai.max_tokens = max_tokens
        with pytest.raises(InvalidValueError) as exc_info:
            validate_config(config)
        assert "ai.max_tokens" in str(exc_info.value)


class TestValidateExperts:
    """专家名校验。"""

    def test_invalid_expert_name_raises_invalid(self):
        config = _make_valid_config()
        config.expert.enabled_experts = ["security", "nonexistent_expert"]
        with pytest.raises(InvalidValueError) as exc_info:
            validate_config(config)
        message = str(exc_info.value)
        assert "expert.enabled_experts" in message
        # 错误消息应列出非法专家名
        assert "nonexistent_expert" in message

    def test_empty_enabled_experts_valid(self):
        # 空专家列表不应触发非法专家错误
        config = _make_valid_config()
        config.expert.enabled_experts = []
        validate_config(config)


class TestValidConfig:
    """合法配置应通过校验。"""

    def test_valid_config_passes(self):
        config = _make_valid_config()
        # 不应抛出任何异常
        validate_config(config)


class TestLoadConfigStrict:
    """load_config_strict 集成测试。"""

    def test_strict_raises_config_error_on_invalid(self, monkeypatch):
        # 通过 mock load_config 返回一个无效配置（api_key 为空）
        invalid_config = AppConfig(
            github=GitHubConfig(),
            ai=AIConfig(api_key="", model="deepseek-chat"),
            analysis=AnalysisConfig(),
            expert=ExpertConfig(),
        )
        import ai_pr_review.config as config_module
        monkeypatch.setattr(config_module, "load_config", lambda **kwargs: invalid_config)
        with pytest.raises(ConfigError):
            load_config_strict()

    def test_strict_returns_config_on_valid(self, monkeypatch):
        valid_config = _make_valid_config()
        import ai_pr_review.config as config_module
        monkeypatch.setattr(config_module, "load_config", lambda **kwargs: valid_config)
        result = load_config_strict()
        assert result is valid_config
