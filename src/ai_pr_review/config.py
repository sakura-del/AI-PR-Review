import os
import tomllib
from dataclasses import dataclass, field
from pathlib import Path

from dotenv import load_dotenv


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
    skip_patterns: list[str] = field(
        default_factory=lambda: ["*.lock", "*.generated.*", "package-lock.json"]
    )
    max_file_size: int = 50000
    context_budget: int = 6000


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


def load_config(config_path: Path | None = None) -> AppConfig:
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
    config.ai.api_key = os.environ.get("AI_API_KEY", config.ai.api_key)
    config.ai.base_url = os.environ.get("AI_BASE_URL", config.ai.base_url)
    config.ai.model = os.environ.get("AI_MODEL", config.ai.model)

    return config
