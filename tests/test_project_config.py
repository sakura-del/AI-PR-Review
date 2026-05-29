import pytest
import tempfile
from pathlib import Path
from ai_pr_review.config import ProjectConfig, load_project_config


class TestProjectConfig:
    def test_default_values(self):
        config = ProjectConfig()
        assert len(config.ignore_paths) > 0
        assert "*.lock" in config.ignore_paths or any("lock" in p for p in config.ignore_paths)
        assert len(config.custom_rules) == 0
        assert config.max_context_files == 10

    def test_should_ignore_matches_pattern(self):
        config = ProjectConfig(ignore_paths=["*.lock", "vendor/"])
        assert config.should_ignore("test.lock")
        assert config.should_ignore("path/to/vendor/lib.py")

    def test_should_ignore_no_match(self):
        config = ProjectConfig(ignore_paths=["*.lock"])
        assert not config.should_ignore("src/main.py")

    def test_should_ignore_subdirectory_match(self):
        config = ProjectConfig(ignore_paths=["__pycache__/"])
        assert config.should_ignore("__pycache__/module.cpython-311.pyc")
        assert config.should_ignore("src/__pycache__/module.cpython-311.pyc")


class TestLoadProjectConfig:
    def test_returns_default_when_no_file(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            config = load_project_config(Path(tmpdir))
            assert isinstance(config, ProjectConfig)

    def test_loads_valid_yaml(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            config_path = Path(tmpdir) / ".ai-pr-review.yaml"
            config_path.write_text("""
ignore_paths:
  - "*.test"
  - "tmp/"
custom_rules:
  - "Rule 1"
  - "Rule 2"
max_context_files: 5
enabled_experts:
  - security
  - testing
""", encoding="utf-8")
            config = load_project_config(Path(tmpdir))
            assert "*.test" in config.ignore_paths
            assert "tmp/" in config.ignore_paths
            assert len(config.custom_rules) == 2
            assert config.custom_rules[0] == "Rule 1"
            assert config.max_context_files == 5
            assert config.enabled_experts == ["security", "testing"]

    def test_handles_invalid_yaml(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            config_path = Path(tmpdir) / ".ai-pr-review.yaml"
            config_path.write_text("{invalid: [yaml: content}", encoding="utf-8")
            config = load_project_config(Path(tmpdir))
            assert isinstance(config, ProjectConfig)
            assert len(config.ignore_paths) > 0

    def test_handles_empty_file(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            config_path = Path(tmpdir) / ".ai-pr-review.yaml"
            config_path.write_text("", encoding="utf-8")
            config = load_project_config(Path(tmpdir))
            assert isinstance(config, ProjectConfig)

    def test_partial_config_preserves_defaults(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            config_path = Path(tmpdir) / ".ai-pr-review.yaml"
            config_path.write_text("""
custom_rules:
  - "Only custom rule"
""", encoding="utf-8")
            config = load_project_config(Path(tmpdir))
            assert len(config.custom_rules) == 1
            assert config.max_context_files == 10
            assert len(config.ignore_paths) > 0


class TestIgnorePathPatterns:
    def test_wildcard_extension(self):
        config = ProjectConfig(ignore_paths=["*.min.js"])
        assert config.should_ignore("bundle.min.js")
        assert not config.should_ignore("bundle.js")

    def test_directory_pattern(self):
        config = ProjectConfig(ignore_paths=["dist/"])
        assert config.should_ignore("dist/app.js")
        assert config.should_ignore("path/to/dist/file.js")
        assert not config.should_ignore("src/app.js")

    def test_nested_directory(self):
        config = ProjectConfig(ignore_paths=["node_modules/"])
        assert config.should_ignore("packages/frontend/node_modules/lodash")

    def test_exact_filename(self):
        config = ProjectConfig(ignore_paths=["package-lock.json"])
        assert config.should_ignore("package-lock.json")
        assert not config.should_ignore("yarn.lock")

    def test_multiple_patterns(self):
        config = ProjectConfig(ignore_paths=["*.lock", "generated/*"])
        assert config.should_ignore("test.lock")
        assert config.should_ignore("generated/code.py")
        assert not config.should_ignore("src/main.py")

    def test_lock_pattern_matches_variations(self):
        config = ProjectConfig(ignore_paths=["*.lock"])
        assert config.should_ignore("yarn.lock")
        assert config.should_ignore("test.lock")
        assert not config.should_ignore("locker.py")
