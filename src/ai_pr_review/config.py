import os
import fnmatch
try:
    import tomllib
except ModuleNotFoundError:
    import tomli as tomllib
from dataclasses import dataclass, field
from pathlib import Path

from dotenv import load_dotenv

from ai_pr_review.config_error import ConfigError, InvalidValueError, MissingRequiredError


MODEL_PRESETS: dict[str, dict[str, str]] = {
    "deepseek": {
        "api_key_env": "DEEPSEEK_API_KEY",
        "base_url_env": "DEEPSEEK_BASE_URL",
        "model_env": "DEEPSEEK_MODEL",
        "default_base_url": "https://api.deepseek.com/v1",
        "default_model": "deepseek-chat",
    },
    "qwen": {
        "api_key_env": "QWEN_API_KEY",
        "base_url_env": "QWEN_BASE_URL",
        "model_env": "QWEN_MODEL",
        "default_base_url": "https://dashscope.aliyuncs.com/compatible-mode/v1",
        "default_model": "qwen-plus",
    },
    "glm": {
        "api_key_env": "GLM_API_KEY",
        "base_url_env": "GLM_BASE_URL",
        "model_env": "GLM_MODEL",
        "default_base_url": "https://open.bigmodel.cn/api/paas/v4",
        "default_model": "glm-4",
    },
}


def _resolve_provider(model_name: str) -> str | None:
    if not model_name:
        return None
    low = model_name.lower()
    for provider in MODEL_PRESETS:
        if low.startswith(provider):
            return provider
    return None


@dataclass
class GitHubConfig:
    token: str = ""


@dataclass
class AIConfig:
    provider: str = "deepseek"
    api_key: str = ""
    model: str = "deepseek-chat"
    base_url: str = "https://api.deepseek.com/v1"
    max_tokens: int = 8000
    temperature: float = 0.3


@dataclass
class AnalysisConfig:
    severity_threshold: str = "low"
    max_file_size: int = 50000
    context_budget: int = 6000
    min_confidence: int = 2


@dataclass
class ExpertConfig:
    enabled_experts: list[str] = field(
        default_factory=lambda: [
            "security",
            "architecture",
            "performance",
            "readability",
            "testing",
        ]
    )


@dataclass
class AppConfig:
    github: GitHubConfig = field(default_factory=GitHubConfig)
    ai: AIConfig = field(default_factory=AIConfig)
    analysis: AnalysisConfig = field(default_factory=AnalysisConfig)
    expert: ExpertConfig = field(default_factory=ExpertConfig)


DEFAULT_CONFIG_PATH = Path.home() / ".ai-pr-review.toml"

_ENV_SEARCH_PATHS = [
    Path.cwd() / ".env",
    Path.home() / ".ai-pr-review.env",
]


def _load_env_file() -> None:
    for env_path in _ENV_SEARCH_PATHS:
        if env_path.exists():
            load_dotenv(env_path, override=False)
            return
    load_dotenv(override=False)


def _load_provider_config(provider: str) -> dict[str, str]:
    preset = MODEL_PRESETS.get(provider)
    if not preset:
        return {}
    return {
        "api_key": os.environ.get(preset["api_key_env"], ""),
        "base_url": os.environ.get(preset["base_url_env"], preset["default_base_url"]),
        "model": os.environ.get(preset["model_env"], preset["default_model"]),
    }


def load_config(config_path: Path | None = None, model_override: str | None = None) -> AppConfig:
    _load_env_file()

    path = config_path or DEFAULT_CONFIG_PATH
    config = AppConfig()

    if path.exists():
        with open(path, "rb") as f:
            data = tomllib.load(f)

        if "github" in data:
            for k, v in data["github"].items():
                if hasattr(config.github, k):
                    setattr(config.github, k, v)

        if "ai" in data:
            for k, v in data["ai"].items():
                if hasattr(config.ai, k):
                    setattr(config.ai, k, v)

        if "analysis" in data:
            for k, v in data["analysis"].items():
                if hasattr(config.analysis, k):
                    setattr(config.analysis, k, v)

        if "expert" in data:
            for k, v in data["expert"].items():
                if hasattr(config.expert, k):
                    setattr(config.expert, k, v)

    config.github.token = os.environ.get("GITHUB_TOKEN", config.github.token)

    effective_model = model_override or os.environ.get("AI_MODEL", "") or config.ai.model
    provider = _resolve_provider(effective_model)

    if provider:
        provider_cfg = _load_provider_config(provider)
        if provider_cfg.get("api_key"):
            config.ai.api_key = provider_cfg["api_key"]
        if provider_cfg.get("base_url"):
            config.ai.base_url = provider_cfg["base_url"]
        config.ai.model = effective_model
        config.ai.provider = provider
    else:
        config.ai.api_key = os.environ.get("AI_API_KEY", config.ai.api_key)
        config.ai.base_url = os.environ.get("AI_BASE_URL", config.ai.base_url)
        config.ai.model = effective_model

    return config


def validate_config(config: AppConfig) -> None:
    """校验配置，失败时抛出对应的 ConfigError 子类。

    校验规则：
    - ai.api_key、ai.model 必填（空值抛 MissingRequiredError）
    - ai.temperature ∈ [0, 2]
    - analysis.min_confidence ∈ [1, 5]
    - ai.max_tokens > 0
    - expert.enabled_experts 中每个专家名必须存在于 EXPERT_SKILLS

    聚合所有错误一次性抛出：单个错误抛出具体子类，多个错误用 ConfigError 汇总。
    """
    # 延迟导入避免与 expert_knowledge 产生循环依赖
    from ai_pr_review.expert_knowledge import EXPERT_SKILLS

    errors: list[ConfigError] = []

    # ---- 必填项校验 ----
    if not config.ai.api_key:
        errors.append(MissingRequiredError(
            field="ai.api_key",
            suggestion="请配置 AI_API_KEY 环境变量，或在 ~/.ai-pr-review.toml 中设置 [ai] api_key",
        ))
    if not config.ai.model:
        errors.append(MissingRequiredError(
            field="ai.model",
            suggestion="请配置 AI_MODEL 环境变量，或在 ~/.ai-pr-review.toml 中设置 [ai] model",
        ))

    # ---- 范围校验 ----
    if not 0 <= config.ai.temperature <= 2:
        errors.append(InvalidValueError(
            field="ai.temperature",
            current_value=config.ai.temperature,
            expected="取值范围 [0, 2]",
            suggestion="请将 temperature 设置为 0 到 2 之间的浮点数",
        ))

    if not 1 <= config.analysis.min_confidence <= 5:
        errors.append(InvalidValueError(
            field="analysis.min_confidence",
            current_value=config.analysis.min_confidence,
            expected="取值范围 [1, 5]",
            suggestion="请将 min_confidence 设置为 1 到 5 之间的整数",
        ))

    if config.ai.max_tokens <= 0:
        errors.append(InvalidValueError(
            field="ai.max_tokens",
            current_value=config.ai.max_tokens,
            expected="正整数 (> 0)",
            suggestion="请将 max_tokens 设置为大于 0 的整数",
        ))

    # ---- 专家名校验 ----
    invalid_experts = [
        expert for expert in config.expert.enabled_experts
        if expert not in EXPERT_SKILLS
    ]
    if invalid_experts:
        valid_experts = ", ".join(sorted(EXPERT_SKILLS.keys()))
        errors.append(InvalidValueError(
            field="expert.enabled_experts",
            current_value=invalid_experts,
            expected=f"已注册专家之一：{valid_experts}",
            suggestion=f"请从已注册专家中选择：{valid_experts}",
        ))

    # ---- 聚合抛出 ----
    if not errors:
        return
    # 单个错误直接抛出具体子类，便于调用方按类型捕获
    if len(errors) == 1:
        raise errors[0]
    # 多个错误用基类 ConfigError 汇总全部信息
    summary = "\n".join(f"- {err}" for err in errors)
    raise ConfigError(
        field="(multiple)",
        current_value=None,
        expected="见下方逐项说明",
        suggestion=f"共发现 {len(errors)} 个配置错误：\n{summary}",
    )


def load_config_strict(
    config_path: Path | None = None,
    model_override: str | None = None,
) -> AppConfig:
    """加载并严格校验配置，校验失败时抛出 ConfigError。

    在 load_config 基础上追加启动校验，供 CLI 入口使用以确保配置合法；
    load_config 本身保持不变，避免破坏既有调用方与测试。
    """
    config = load_config(config_path=config_path, model_override=model_override)
    validate_config(config)
    return config


@dataclass
class ExpertOverride:
    checklist_append: list[str] = field(default_factory=list)
    checklist_replace: list[str] | None = None
    red_flags_append: list[str] = field(default_factory=list)
    red_flags_replace: list[str] | None = None


@dataclass
class TeamLearningConfig:
    enabled: bool = False
    max_prs: int = 20
    max_comments: int = 100
    min_rule_weight: float = 0.3
    rule_ttl_days: int = 30


@dataclass
class ProjectConfig:
    ignore_paths: list[str] = field(default_factory=lambda: [
        "*.lock",
        "*.generated.*",
        "package-lock.json",
        "vendor/",
        "node_modules/",
        "__pycache__/",
    ])
    custom_rules: list[str] = field(default_factory=list)
    max_context_files: int = 10
    enabled_experts: list[str] | None = None
    expert_overrides: dict[str, ExpertOverride] = field(default_factory=dict)
    custom_experts: dict[str, dict] = field(default_factory=dict)
    team_learning: TeamLearningConfig = field(default_factory=TeamLearningConfig)

    def should_ignore(self, file_path: str) -> bool:
        for pattern in self.ignore_paths:
            if fnmatch.fnmatch(file_path, pattern):
                return True
            if pattern.endswith("/") and (file_path.startswith(pattern) or f"{pattern}" in file_path):
                return True
            if "*" in pattern:
                base_name = file_path.split("/")[-1]
                if fnmatch.fnmatch(base_name, pattern):
                    return True
        return False


PROJECT_CONFIG_FILENAME = ".ai-pr-review.yaml"


def load_project_config(project_dir: Path | None = None) -> ProjectConfig:
    base_dir = project_dir or Path.cwd()
    config_path = base_dir / PROJECT_CONFIG_FILENAME

    if not config_path.exists():
        return ProjectConfig()

    import yaml
    with open(config_path, "r", encoding="utf-8") as f:
        try:
            data = yaml.safe_load(f) or {}
        except yaml.YAMLError:
            return ProjectConfig()

    config = ProjectConfig()
    if "ignore_paths" in data and isinstance(data["ignore_paths"], list):
        config.ignore_paths = data["ignore_paths"]
    if "custom_rules" in data and isinstance(data["custom_rules"], list):
        config.custom_rules = data["custom_rules"]
    if "max_context_files" in data:
        config.max_context_files = int(data["max_context_files"])
    if "enabled_experts" in data and isinstance(data["enabled_experts"], list):
        config.enabled_experts = data["enabled_experts"]

    if "expert_overrides" in data and isinstance(data["expert_overrides"], dict):
        for expert_key, override_data in data["expert_overrides"].items():
            if isinstance(override_data, dict):
                config.expert_overrides[expert_key] = ExpertOverride(
                    checklist_append=override_data.get("checklist_append", []),
                    checklist_replace=override_data.get("checklist_replace"),
                    red_flags_append=override_data.get("red_flags_append", []),
                    red_flags_replace=override_data.get("red_flags_replace"),
                )

    if "custom_experts" in data and isinstance(data["custom_experts"], dict):
        for expert_key, expert_data in data["custom_experts"].items():
            if isinstance(expert_data, dict):
                config.custom_experts[expert_key] = expert_data

    if "team_learning" in data and isinstance(data["team_learning"], dict):
        tl = data["team_learning"]
        config.team_learning = TeamLearningConfig(
            enabled=tl.get("enabled", False),
            max_prs=int(tl.get("max_prs", 20)),
            max_comments=int(tl.get("max_comments", 100)),
            min_rule_weight=float(tl.get("min_rule_weight", 0.3)),
            rule_ttl_days=int(tl.get("rule_ttl_days", 30)),
        )

    return config
