# AI PR Review 助手 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 构建一个基于国产AI模型的CLI代码评审工具，支持PR变更总结、风险代码识别、Review建议生成和GitHub评论回写。

**Architecture:** 模块化管道架构，数据从CLI输入流经GitHub获取→Diff解析→上下文构建→AI分析→格式化输出→GitHub回写。各模块通过数据模型解耦，支持独立测试和替换。

**Tech Stack:** Python 3.11+, Typer, PyGithub, OpenAI Python SDK (兼容国产模型), asyncio/httpx, pytest

---

## File Structure

| 文件 | 职责 |
|------|------|
| `pyproject.toml` | 项目元数据、依赖、CLI入口点 |
| `src/ai_pr_review/__init__.py` | 包初始化 |
| `src/ai_pr_review/models.py` | 所有数据模型定义 |
| `src/ai_pr_review/config.py` | 配置管理（文件+环境变量+CLI参数） |
| `src/ai_pr_review/github_client.py` | GitHub API封装 |
| `src/ai_pr_review/diff_parser.py` | Unified diff解析 |
| `src/ai_pr_review/context_builder.py` | 上下文构建与Token预算管理 |
| `src/ai_pr_review/expert_knowledge.py` | 专家知识库定义 |
| `src/ai_pr_review/prompt_templates.py` | Prompt模板构建 |
| `src/ai_pr_review/analyzer.py` | AI分析引擎（分片+多维度分析） |
| `src/ai_pr_review/formatter.py` | 终端输出格式化 |
| `src/ai_pr_review/commenter.py` | GitHub评论回写 |
| `src/ai_pr_review/cli.py` | CLI入口（Typer） |
| `tests/test_models.py` | 数据模型测试 |
| `tests/test_diff_parser.py` | Diff解析测试 |
| `tests/test_context_builder.py` | 上下文构建测试 |
| `tests/test_analyzer.py` | 分析引擎测试 |
| `tests/test_formatter.py` | 格式化测试 |
| `tests/fixtures/sample.diff` | 测试用diff文件 |

---

### Task 1: 项目初始化与依赖配置

**Files:**
- Create: `pyproject.toml`
- Create: `src/ai_pr_review/__init__.py`

- [ ] **Step 1: 创建 pyproject.toml**

```toml
[build-system]
requires = ["hatchling"]
build-backend = "hatchling.build"

[project]
name = "ai-pr-review"
version = "0.1.0"
description = "AI-powered Pull Request review assistant using domestic LLMs"
requires-python = ">=3.11"
dependencies = [
    "typer>=0.12.0",
    "pygithub>=2.3.0",
    "openai>=1.30.0",
    "httpx>=0.27.0",
    "rich>=13.7.0",
    "tiktoken>=0.7.0",
]

[project.optional-dependencies]
dev = [
    "pytest>=8.0.0",
    "pytest-asyncio>=0.23.0",
    "pytest-cov>=5.0.0",
]

[project.scripts]
ai-pr-review = "ai_pr_review.cli:app"

[tool.hatch.build.targets.wheel]
packages = ["src/ai_pr_review"]

[tool.pytest.ini_options]
testpaths = ["tests"]
asyncio_mode = "auto"
```

- [ ] **Step 2: 创建包初始化文件**

```python
__version__ = "0.1.0"
```

- [ ] **Step 3: 安装依赖**

Run: `cd "e:\AI PR Review" && pip install -e ".[dev]"`
Expected: 成功安装所有依赖

- [ ] **Step 4: 验证CLI入口点可用**

Run: `ai-pr-review --help`
Expected: 显示帮助信息（此时会报错因为cli.py还未创建，这是预期行为）

- [ ] **Step 5: Commit**

```bash
git add pyproject.toml src/ai_pr_review/__init__.py
git commit -m "feat: initialize project with dependencies"
```

---

### Task 2: 数据模型定义

**Files:**
- Create: `src/ai_pr_review/models.py`
- Create: `tests/test_models.py`

- [ ] **Step 1: 编写数据模型测试**

```python
from ai_pr_review.models import DiffHunk, FileDiff, ParsedDiff, PRMetadata, Finding, AnalysisResult, Severity, ChangeType


def test_diff_hunk_creation():
    hunk = DiffHunk(
        file_path="src/main.py",
        change_type=ChangeType.MODIFIED,
        old_start=10,
        old_count=5,
        new_start=10,
        new_count=8,
        content="@@ -10,5 +10,8 @@\n-old line\n+new line\n+added line",
        header="@@ -10,5 +10,8 @@ def process():",
    )
    assert hunk.file_path == "src/main.py"
    assert hunk.change_type == ChangeType.MODIFIED
    assert hunk.old_start == 10
    assert hunk.new_count == 8


def test_file_diff_creation():
    hunk = DiffHunk(
        file_path="app.py",
        change_type=ChangeType.ADDED,
        old_start=0,
        old_count=0,
        new_start=1,
        new_count=10,
        content="new file content",
        header="@@ -0,0 +1,10 @@",
    )
    file_diff = FileDiff(
        path="app.py",
        change_type=ChangeType.ADDED,
        hunks=[hunk],
        additions=10,
        deletions=0,
        is_binary=False,
        is_generated=False,
    )
    assert file_diff.path == "app.py"
    assert len(file_diff.hunks) == 1
    assert file_diff.is_binary is False


def test_parsed_diff_stats():
    file1 = FileDiff(
        path="a.py",
        change_type=ChangeType.MODIFIED,
        hunks=[],
        additions=5,
        deletions=3,
        is_binary=False,
        is_generated=False,
    )
    file2 = FileDiff(
        path="b.py",
        change_type=ChangeType.ADDED,
        hunks=[],
        additions=20,
        deletions=0,
        is_binary=False,
        is_generated=False,
    )
    parsed = ParsedDiff(files=[file1, file2], total_additions=25, total_deletions=3)
    assert parsed.total_additions == 25
    assert parsed.total_deletions == 3
    assert len(parsed.files) == 2


def test_pr_metadata_creation():
    meta = PRMetadata(
        title="Add auth module",
        description="Implements JWT authentication",
        author="developer",
        base_branch="main",
        head_branch="feature/auth",
        labels=["enhancement"],
        url="https://github.com/owner/repo/pull/1",
        number=1,
        repo_owner="owner",
        repo_name="repo",
    )
    assert meta.title == "Add auth module"
    assert meta.number == 1


def test_finding_creation():
    finding = Finding(
        type="risk",
        severity=Severity.HIGH,
        confidence=4,
        expert="security",
        file="db.py",
        line=45,
        title="SQL Injection",
        description="User input directly concatenated into SQL query",
        suggestion="Use parameterized queries",
        code_snippet="query = f\"SELECT * FROM users WHERE id = {user_id}\"",
    )
    assert finding.severity == Severity.HIGH
    assert finding.confidence == 4
    assert finding.expert == "security"


def test_analysis_result_creation():
    result = AnalysisResult(
        summary=AnalysisSummary(
            intent="Add JWT authentication",
            scope="Authentication module",
            key_changes=["New auth.py module", "Updated middleware"],
        ),
        findings=[
            Finding(
                type="risk",
                severity=Severity.HIGH,
                confidence=4,
                expert="security",
                file="auth.py",
                line=10,
                title="Hardcoded secret",
                description="JWT secret is hardcoded",
                suggestion="Use environment variable",
                code_snippet="secret = 'my-secret'",
            )
        ],
        suggestions=[
            Suggestion(
                category="security",
                priority=Severity.HIGH,
                description="Move secrets to environment variables",
                example="secret = os.environ['JWT_SECRET']",
            )
        ],
    )
    assert len(result.findings) == 1
    assert result.summary.intent == "Add JWT authentication"
```

- [ ] **Step 2: 运行测试确认失败**

Run: `cd "e:\AI PR Review" && python -m pytest tests/test_models.py -v`
Expected: FAIL - ModuleNotFoundError

- [ ] **Step 3: 实现数据模型**

```python
from dataclasses import dataclass, field
from enum import Enum


class ChangeType(str, Enum):
    ADDED = "added"
    MODIFIED = "modified"
    DELETED = "deleted"
    RENAMED = "renamed"


class Severity(str, Enum):
    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"


@dataclass
class DiffHunk:
    file_path: str
    change_type: ChangeType
    old_start: int
    old_count: int
    new_start: int
    new_count: int
    content: str
    header: str


@dataclass
class FileDiff:
    path: str
    change_type: ChangeType
    hunks: list[DiffHunk]
    additions: int
    deletions: int
    is_binary: bool = False
    is_generated: bool = False


@dataclass
class ParsedDiff:
    files: list[FileDiff]
    total_additions: int
    total_deletions: int


@dataclass
class PRMetadata:
    title: str
    description: str
    author: str
    base_branch: str
    head_branch: str
    labels: list[str]
    url: str
    number: int
    repo_owner: str
    repo_name: str


@dataclass
class AnalysisSummary:
    intent: str
    scope: str
    key_changes: list[str]


@dataclass
class Finding:
    type: str
    severity: Severity
    confidence: int
    expert: str
    file: str
    line: int
    title: str
    description: str
    suggestion: str
    code_snippet: str


@dataclass
class Suggestion:
    category: str
    priority: Severity
    description: str
    example: str


@dataclass
class AnalysisResult:
    summary: AnalysisSummary
    findings: list[Finding]
    suggestions: list[Suggestion]
```

- [ ] **Step 4: 运行测试确认通过**

Run: `cd "e:\AI PR Review" && python -m pytest tests/test_models.py -v`
Expected: 全部PASS

- [ ] **Step 5: Commit**

```bash
git add src/ai_pr_review/models.py tests/test_models.py
git commit -m "feat: add data models for diff, PR metadata, and analysis results"
```

---

### Task 3: 配置管理

**Files:**
- Create: `src/ai_pr_review/config.py`

- [ ] **Step 1: 实现配置管理模块**

```python
import os
import tomllib
from dataclasses import dataclass, field
from pathlib import Path


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


def load_config(config_path: Path | None = None) -> AppConfig:
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

    return config
```

- [ ] **Step 2: 验证配置加载**

Run: `cd "e:\AI PR Review" && python -c "from ai_pr_review.config import load_config; c = load_config(); print(c.ai.model, c.ai.base_url)"`
Expected: `deepseek-chat https://api.deepseek.com/v1`

- [ ] **Step 3: Commit**

```bash
git add src/ai_pr_review/config.py
git commit -m "feat: add configuration management with TOML and env vars"
```

---

### Task 4: GitHub客户端

**Files:**
- Create: `src/ai_pr_review/github_client.py`

- [ ] **Step 1: 实现GitHub客户端**

```python
import re
from github import Github, GithubException
from github.PullRequest import PullRequest
from ai_pr_review.models import PRMetadata


PR_URL_PATTERN = re.compile(
    r"https?://github\.com/(?P<owner>[^/]+)/(?P<repo>[^/]+)/pull/(?P<number>\d+)"
)


def parse_pr_url(url: str) -> tuple[str, str, int]:
    match = PR_URL_PATTERN.match(url)
    if not match:
        raise ValueError(f"Invalid GitHub PR URL: {url}")
    return match.group("owner"), match.group("repo"), int(match.group("number"))


class GitHubClient:
    def __init__(self, token: str = ""):
        self._client = Github(token) if token else Github()

    def get_pr_metadata(self, url: str) -> PRMetadata:
        owner, repo_name, number = parse_pr_url(url)
        repo = self._client.get_repo(f"{owner}/{repo_name}")
        pr = repo.get_pull(number)

        return PRMetadata(
            title=pr.title,
            description=pr.body or "",
            author=pr.user.login,
            base_branch=pr.base.ref,
            head_branch=pr.head.ref,
            labels=[label.name for label in pr.labels],
            url=url,
            number=number,
            repo_owner=owner,
            repo_name=repo_name,
        )

    def get_pr_diff(self, url: str) -> str:
        owner, repo_name, number = parse_pr_url(url)
        repo = self._client.get_repo(f"{owner}/{repo_name}")
        pr = repo.get_pull(number)
        return pr.diff_url

    def get_pr_diff_content(self, url: str) -> str:
        owner, repo_name, number = parse_pr_url(url)
        repo = self._client.get_repo(f"{owner}/{repo_name}")
        pr = repo.get_pull(number)
        headers = {"Accept": "application/vnd.github.v3.diff"}
        import httpx

        response = httpx.get(pr.diff_url, headers=headers)
        response.raise_for_status()
        return response.text

    def get_file_content(self, url: str, file_path: str, ref: str) -> str:
        owner, repo_name, _ = parse_pr_url(url)
        repo = self._client.get_repo(f"{owner}/{repo_name}")
        try:
            content = repo.get_contents(file_path, ref=ref)
            if isinstance(content, list):
                return ""
            return content.decoded_content.decode("utf-8")
        except GithubException:
            return ""

    def create_review_comment(
        self, url: str, commit_id: str, path: str, line: int, body: str
    ):
        owner, repo_name, number = parse_pr_url(url)
        repo = self._client.get_repo(f"{owner}/{repo_name}")
        pr = repo.get_pull(number)
        commit = repo.get_commit(commit_id)
        pr.create_review_comment(body=body, commit=commit, path=path, line=line)

    def create_pr_comment(self, url: str, body: str):
        owner, repo_name, number = parse_pr_url(url)
        repo = self._client.get_repo(f"{owner}/{repo_name}")
        pr = repo.get_pull(number)
        pr.create_issue_comment(body)

    def create_review(self, url: str, body: str, event: str = "COMMENT"):
        owner, repo_name, number = parse_pr_url(url)
        repo = self._client.get_repo(f"{owner}/{repo_name}")
        pr = repo.get_pull(number)
        pr.create_review(body=body, event=event)
```

- [ ] **Step 2: 验证URL解析**

Run: `cd "e:\AI PR Review" && python -c "from ai_pr_review.github_client import parse_pr_url; print(parse_pr_url('https://github.com/owner/repo/pull/123'))"`
Expected: `('owner', 'repo', 123)`

- [ ] **Step 3: Commit**

```bash
git add src/ai_pr_review/github_client.py
git commit -m "feat: add GitHub client with PR metadata, diff, and comment APIs"
```

---

### Task 5: Diff解析器

**Files:**
- Create: `src/ai_pr_review/diff_parser.py`
- Create: `tests/test_diff_parser.py`
- Create: `tests/fixtures/sample.diff`

- [ ] **Step 1: 创建测试用diff文件**

```
diff --git a/src/auth.py b/src/auth.py
new file mode 100644
index 0000000..abc1234
--- /dev/null
+++ b/src/auth.py
@@ -0,0 +1,15 @@
+import jwt
+import os
+
+SECRET = "hardcoded-secret"
+
+def generate_token(user_id):
+    payload = {"user_id": user_id}
+    token = jwt.encode(payload, SECRET, algorithm="HS256")
+    return token
+
+def verify_token(token):
+    try:
+        payload = jwt.decode(token, SECRET, algorithms=["HS256"])
+        return payload
+    except jwt.ExpiredSignatureError:
+        return None
+    except jwt.InvalidTokenError:
+        return None
diff --git a/src/db.py b/src/db.py
index 1111111..2222222 100644
--- a/src/db.py
+++ b/src/db.py
@@ -10,5 +10,8 @@ def get_user(user_id):
-    query = f"SELECT * FROM users WHERE id = {user_id}"
-    result = db.execute(query)
+    query = "SELECT * FROM users WHERE id = %s"
+    result = db.execute(query, (user_id,))
     return result.fetchone()
+
+def delete_user(user_id):
+    query = f"DELETE FROM users WHERE id = {user_id}"
+    db.execute(query)
diff --git a/package-lock.json b/package-lock.json
deleted file mode 100644
index 3333333..0000000
--- a/package-lock.json
+++ /dev/null
@@ -1,1000 +0,0 @@
-...lock content...
```

- [ ] **Step 2: 编写diff解析器测试**

```python
from pathlib import Path
from ai_pr_review.diff_parser import parse_diff
from ai_pr_review.models import ChangeType


FIXTURES_DIR = Path(__file__).parent / "fixtures"


def test_parse_diff_returns_parsed_diff():
    diff_text = (FIXTURES_DIR / "sample.diff").read_text()
    result = parse_diff(diff_text)
    assert result is not None
    assert len(result.files) == 3


def test_parse_diff_detects_added_file():
    diff_text = (FIXTURES_DIR / "sample.diff").read_text()
    result = parse_diff(diff_text)
    auth_file = next(f for f in result.files if f.path == "src/auth.py")
    assert auth_file.change_type == ChangeType.ADDED
    assert auth_file.additions > 0
    assert auth_file.deletions == 0


def test_parse_diff_detects_modified_file():
    diff_text = (FIXTURES_DIR / "sample.diff").read_text()
    result = parse_diff(diff_text)
    db_file = next(f for f in result.files if f.path == "src/db.py")
    assert db_file.change_type == ChangeType.MODIFIED
    assert db_file.additions > 0
    assert db_file.deletions > 0


def test_parse_diff_detects_deleted_file():
    diff_text = (FIXTURES_DIR / "sample.diff").read_text()
    result = parse_diff(diff_text)
    lock_file = next(f for f in result.files if f.path == "package-lock.json")
    assert lock_file.change_type == ChangeType.DELETED


def test_parse_diff_counts_totals():
    diff_text = (FIXTURES_DIR / "sample.diff").read_text()
    result = parse_diff(diff_text)
    assert result.total_additions > 0
    assert result.total_deletions > 0


def test_parse_diff_extracts_hunks():
    diff_text = (FIXTURES_DIR / "sample.diff").read_text()
    result = parse_diff(diff_text)
    db_file = next(f for f in result.files if f.path == "src/db.py")
    assert len(db_file.hunks) >= 1
    hunk = db_file.hunks[0]
    assert hunk.old_start >= 0
    assert hunk.new_start >= 0
    assert len(hunk.content) > 0


def test_parse_diff_marks_generated_files():
    diff_text = (FIXTURES_DIR / "sample.diff").read_text()
    result = parse_diff(diff_text)
    lock_file = next(f for f in result.files if f.path == "package-lock.json")
    assert lock_file.is_generated is True


def test_parse_empty_diff():
    result = parse_diff("")
    assert len(result.files) == 0
    assert result.total_additions == 0
    assert result.total_deletions == 0
```

- [ ] **Step 3: 运行测试确认失败**

Run: `cd "e:\AI PR Review" && python -m pytest tests/test_diff_parser.py -v`
Expected: FAIL - ModuleNotFoundError

- [ ] **Step 4: 实现diff解析器**

```python
import re
from ai_pr_review.models import DiffHunk, FileDiff, ParsedDiff, ChangeType

GENERATED_PATTERNS = re.compile(
    r"(package-lock\.json|yarn\.lock|pnpm-lock\.yaml|\.generated\.|go\.sum|poetry\.lock|Gemfile\.lock|cargo\.lock)",
    re.IGNORECASE,
)

FILE_HEADER_PATTERN = re.compile(r"^diff --git a/(.*?) b/(.*?)$", re.MULTILINE)
NEW_FILE_PATTERN = re.compile(r"^new file mode", re.MULTILINE)
DELETED_FILE_PATTERN = re.compile(r"^deleted file mode", re.MULTILINE)
HUNK_HEADER_PATTERN = re.compile(
    r"^@@ -(\d+)(?:,(\d+))? \+(\d+)(?:,(\d+))? @@(.*)$", re.MULTILINE
)
BINARY_PATTERN = re.compile(r"^Binary files", re.MULTILINE)
RENAMED_PATTERN = re.compile(r"^rename from ", re.MULTILINE)


def _determine_change_type(diff_section: str) -> ChangeType:
    if NEW_FILE_PATTERN.search(diff_section):
        return ChangeType.ADDED
    if DELETED_FILE_PATTERN.search(diff_section):
        return ChangeType.DELETED
    if RENAMED_PATTERN.search(diff_section):
        return ChangeType.RENAMED
    return ChangeType.MODIFIED


def _is_binary(diff_section: str) -> bool:
    return bool(BINARY_PATTERN.search(diff_section))


def _is_generated(path: str) -> bool:
    return bool(GENERATED_PATTERNS.search(path))


def _parse_hunks(diff_section: str, file_path: str, change_type: ChangeType) -> list[DiffHunk]:
    hunks = []
    hunk_matches = list(HUNK_HEADER_PATTERN.finditer(diff_section))

    for i, match in enumerate(hunk_matches):
        old_start = int(match.group(1))
        old_count = int(match.group(2)) if match.group(2) else 1
        new_start = int(match.group(3))
        new_count = int(match.group(4)) if match.group(4) else 1
        header = match.group(0)

        end_pos = (
            hunk_matches[i + 1].start() if i + 1 < len(hunk_matches) else len(diff_section)
        )
        content = diff_section[match.start() : end_pos]

        hunks.append(
            DiffHunk(
                file_path=file_path,
                change_type=change_type,
                old_start=old_start,
                old_count=old_count,
                new_start=new_start,
                new_count=new_count,
                content=content,
                header=header,
            )
        )

    return hunks


def _count_additions_deletions(hunks: list[DiffHunk]) -> tuple[int, int]:
    additions = 0
    deletions = 0
    for hunk in hunks:
        for line in hunk.content.split("\n"):
            if line.startswith("+") and not line.startswith("+++"):
                additions += 1
            elif line.startswith("-") and not line.startswith("---"):
                deletions += 1
    return additions, deletions


def parse_diff(diff_text: str) -> ParsedDiff:
    if not diff_text.strip():
        return ParsedDiff(files=[], total_additions=0, total_deletions=0)

    file_sections = FILE_HEADER_PATTERN.split(diff_text)
    files = []
    total_additions = 0
    total_deletions = 0

    for i in range(1, len(file_sections), 3):
        a_path = file_sections[i]
        b_path = file_sections[i + 1]
        section_content = file_sections[i + 2] if i + 2 < len(file_sections) else ""

        file_path = b_path if b_path else a_path
        diff_section = f"diff --git a/{a_path} b/{b_path}{section_content}"

        change_type = _determine_change_type(diff_section)
        is_binary = _is_binary(diff_section)
        is_generated = _is_generated(file_path)

        hunks = _parse_hunks(diff_section, file_path, change_type) if not is_binary else []
        additions, deletions = _count_additions_deletions(hunks)

        files.append(
            FileDiff(
                path=file_path,
                change_type=change_type,
                hunks=hunks,
                additions=additions,
                deletions=deletions,
                is_binary=is_binary,
                is_generated=is_generated,
            )
        )
        total_additions += additions
        total_deletions += deletions

    return ParsedDiff(
        files=files,
        total_additions=total_additions,
        total_deletions=total_deletions,
    )
```

- [ ] **Step 5: 运行测试确认通过**

Run: `cd "e:\AI PR Review" && python -m pytest tests/test_diff_parser.py -v`
Expected: 全部PASS

- [ ] **Step 6: Commit**

```bash
git add src/ai_pr_review/diff_parser.py tests/test_diff_parser.py tests/fixtures/sample.diff
git commit -m "feat: add diff parser with hunk extraction and file type detection"
```

---

### Task 6: 专家知识库

**Files:**
- Create: `src/ai_pr_review/expert_knowledge.py`

- [ ] **Step 1: 实现专家知识库**

```python
from dataclasses import dataclass, field


@dataclass
class ExpertProfile:
    name: str
    checklist: list[str]
    red_flags: list[str]
    knowledge_source: str


EXPERT_SKILLS: dict[str, ExpertProfile] = {
    "security": ExpertProfile(
        name="安全审查专家",
        knowledge_source="OWASP Code Review Guide, CWE Top 25",
        checklist=[
            "SQL注入：检查是否使用参数化查询，是否存在字符串拼接SQL",
            "XSS：检查用户输入是否经过转义/编码后输出",
            "认证/授权：检查权限校验是否完整，是否存在越权访问",
            "敏感数据：检查是否有硬编码密钥/密码/Token",
            "加密：检查是否使用不安全的加密算法(MD5/SHA1/DES)",
            "路径遍历：检查文件路径是否经过验证",
            "命令注入：检查是否安全处理外部输入传入系统命令",
            "CSRF：检查状态变更操作是否有CSRF防护",
            "不安全反序列化：检查是否安全处理反序列化输入",
            "信息泄露：检查错误信息是否暴露敏感内部信息",
        ],
        red_flags=[
            "eval() / exec() 调用",
            "直接拼接SQL语句",
            "未验证的用户输入直接使用",
            "硬编码的API Key / Secret / Password",
            "使用MD5/SHA1进行密码哈希",
            "subprocess.call with shell=True",
            "pickle.loads on untrusted data",
        ],
    ),
    "architecture": ExpertProfile(
        name="架构审查专家",
        knowledge_source="Google Code Review Guidelines, Clean Architecture",
        checklist=[
            "单一职责：函数/类是否职责清晰，是否承担过多功能",
            "耦合度：变更是否引入不必要的依赖，模块间是否松耦合",
            "抽象层次：是否存在层次穿越，抽象是否合理",
            "接口设计：API契约是否合理，参数是否过多",
            "依赖注入：是否通过依赖注入而非硬编码依赖",
            "错误处理：错误处理策略是否一致，是否吞没异常",
            "可扩展性：设计是否便于未来扩展",
        ],
        red_flags=[
            "God Class / God Function（超过100行的函数）",
            "循环依赖",
            "跨层直接调用（如Controller直接操作数据库）",
            "过多参数（超过5个）",
            "深层继承（超过3层）",
            "全局可变状态",
        ],
    ),
    "performance": ExpertProfile(
        name="性能审查专家",
        knowledge_source="性能优化最佳实践",
        checklist=[
            "N+1查询：循环中是否有数据库/网络调用",
            "内存泄漏：资源（文件/连接/句柄）是否正确释放",
            "算法复杂度：是否存在可优化的O(n²)或更高复杂度操作",
            "并发安全：共享状态是否有竞态条件",
            "缓存策略：频繁访问的数据是否有缓存",
            "懒加载：大对象是否延迟初始化",
            "批量操作：是否可以合并多次IO为批量操作",
        ],
        red_flags=[
            "循环内的数据库/网络调用",
            "未关闭的文件/连接",
            "全局可变状态",
            "无锁的并发修改",
            "大列表/字典的频繁拷贝",
            "正则表达式未预编译",
            "同步阻塞调用在异步上下文中",
        ],
    ),
    "readability": ExpertProfile(
        name="可读性审查专家",
        knowledge_source="代码大全, Google Style Guides",
        checklist=[
            "命名：变量/函数名是否表达意图，是否一致",
            "函数长度：是否超过合理范围（建议50行以内）",
            "复杂度：嵌套是否过深（建议3层以内）",
            "一致性：是否与项目现有风格一致",
            "注释：复杂逻辑是否有必要的注释，注释是否准确",
            "代码重复：是否存在可提取的重复代码",
            "魔法值：是否存在未命名的常量",
        ],
        red_flags=[
            "超过50行的函数",
            "超过3层的嵌套",
            "魔法数字/字符串",
            "过度缩写（如 a, b, tmp1）",
            "注释掉的代码块",
            "过长的条件表达式",
            "不一致的命名风格",
        ],
    ),
    "testing": ExpertProfile(
        name="测试审查专家",
        knowledge_source="测试最佳实践",
        checklist=[
            "覆盖率：新增业务逻辑是否有对应测试",
            "边界条件：是否考虑了空值/异常/极端场景",
            "测试隔离：测试是否相互独立，是否有执行顺序依赖",
            "Mock合理性：Mock是否过度/不足，是否Mock了外部依赖而非内部逻辑",
            "测试命名：测试名是否清晰表达测试意图",
            "断言质量：断言是否充分，是否只验证了关键行为",
        ],
        red_flags=[
            "无测试的新增业务逻辑",
            "仅测试正常路径（happy path）",
            "测试中硬编码外部依赖地址",
            "测试之间有执行顺序依赖",
            "过度Mock导致测试失去意义",
            "断言过于宽泛（如只检查不为None）",
        ],
    ),
}


KEYWORD_EXPERT_MAP: dict[str, list[str]] = {
    "sql": ["security", "performance"],
    "database": ["security", "performance"],
    "db": ["security", "performance"],
    "query": ["security", "performance"],
    "auth": ["security"],
    "login": ["security"],
    "password": ["security"],
    "token": ["security"],
    "jwt": ["security"],
    "session": ["security"],
    "api": ["security", "architecture"],
    "route": ["security", "architecture"],
    "endpoint": ["security", "architecture"],
    "controller": ["architecture"],
    "service": ["architecture"],
    "model": ["architecture"],
    "middleware": ["security", "architecture"],
    "encrypt": ["security"],
    "decrypt": ["security"],
    "crypto": ["security"],
    "hash": ["security"],
    "test": ["testing"],
    "spec": ["testing"],
    "cache": ["performance"],
    "async": ["performance"],
    "thread": ["performance"],
    "concurrent": ["performance"],
    "pool": ["performance"],
}


def select_experts(file_paths: list[str], hunks_content: str) -> list[str]:
    expert_scores: dict[str, int] = {}
    combined = " ".join(file_paths).lower() + " " + hunks_content.lower()

    for keyword, experts in KEYWORD_EXPERT_MAP.items():
        if keyword in combined:
            for expert in experts:
                expert_scores[expert] = expert_scores.get(expert, 0) + 1

    if not expert_scores:
        return ["readability", "architecture"]

    sorted_experts = sorted(expert_scores.items(), key=lambda x: x[1], reverse=True)
    return [expert for expert, _ in sorted_experts[:3]]


def get_expert_profiles(expert_names: list[str]) -> list[ExpertProfile]:
    return [EXPERT_SKILLS[name] for name in expert_names if name in EXPERT_SKILLS]
```

- [ ] **Step 2: 验证专家选择逻辑**

Run: `cd "e:\AI PR Review" && python -c "from ai_pr_review.expert_knowledge import select_experts; print(select_experts(['auth.py', 'db.py'], 'jwt token sql query'))"`
Expected: `['security', 'performance']` (security得分最高)

- [ ] **Step 3: Commit**

```bash
git add src/ai_pr_review/expert_knowledge.py
git commit -m "feat: add expert knowledge base with 5 specialist profiles"
```

---

### Task 7: 上下文构建器

**Files:**
- Create: `src/ai_pr_review/context_builder.py`

- [ ] **Step 1: 实现上下文构建器**

```python
import tiktoken
from ai_pr_review.models import ParsedDiff, FileDiff, PRMetadata
from ai_pr_review.config import AppConfig


def _count_tokens(text: str, model: str = "gpt-4") -> int:
    try:
        encoding = tiktoken.encoding_for_model(model)
    except KeyError:
        encoding = tiktoken.get_encoding("cl100k_base")
    return len(encoding.encode(text))


def _estimate_tokens(text: str) -> int:
    return len(text) // 4


class ContextBuilder:
    def __init__(self, config: AppConfig, get_file_content_fn=None):
        self._config = config
        self._get_file_content = get_file_content_fn
        self._budget = config.analysis.context_budget

    def build_context(
        self,
        pr_metadata: PRMetadata,
        parsed_diff: ParsedDiff,
    ) -> dict[str, str]:
        context_parts: dict[str, str] = {}

        pr_context = self._build_pr_context(pr_metadata)
        context_parts["pr_metadata"] = pr_context

        diff_context = self._build_diff_context(parsed_diff)
        context_parts["diff"] = diff_context

        remaining_budget = self._budget - _estimate_tokens(pr_context) - _estimate_tokens(diff_context)

        if remaining_budget > 500 and self._get_file_content:
            file_contexts = self._build_file_contexts(parsed_diff, remaining_budget)
            if file_contexts:
                context_parts["file_contents"] = file_contexts

        return context_parts

    def _build_pr_context(self, metadata: PRMetadata) -> str:
        parts = [
            f"PR Title: {metadata.title}",
            f"Author: {metadata.author}",
            f"Branch: {metadata.head_branch} → {metadata.base_branch}",
        ]
        if metadata.description:
            parts.append(f"Description:\n{metadata.description}")
        if metadata.labels:
            parts.append(f"Labels: {', '.join(metadata.labels)}")
        return "\n".join(parts)

    def _build_diff_context(self, parsed_diff: ParsedDiff) -> str:
        parts = [
            f"Total changes: +{parsed_diff.total_additions} -{parsed_diff.total_deletions} across {len(parsed_diff.files)} files",
            "",
        ]
        for file_diff in parsed_diff.files:
            if file_diff.is_binary:
                continue
            if file_diff.is_generated:
                parts.append(f"[SKIPPED: generated] {file_diff.path}")
                continue
            parts.append(f"--- {file_diff.path} ({file_diff.change_type.value}) ---")
            for hunk in file_diff.hunks:
                parts.append(hunk.content)
            parts.append("")
        return "\n".join(parts)

    def _build_file_contexts(
        self, parsed_diff: ParsedDiff, budget: int
    ) -> str:
        parts = []
        used = 0

        priority_files = sorted(
            [f for f in parsed_diff.files if not f.is_binary and not f.is_generated],
            key=lambda f: f.change_type.value,
        )

        for file_diff in priority_files:
            if used >= budget:
                break

            content = self._get_file_content(
                "", file_diff.path, ""
            )
            if not content:
                continue

            estimated = _estimate_tokens(content)
            if used + estimated > budget:
                truncated = content[: (budget - used) * 4]
                parts.append(f"=== {file_diff.path} (truncated) ===\n{truncated}")
                used = budget
                break

            parts.append(f"=== {file_diff.path} ===\n{content}")
            used += estimated

        return "\n\n".join(parts)
```

- [ ] **Step 2: 验证上下文构建**

Run: `cd "e:\AI PR Review" && python -c "from ai_pr_review.context_builder import ContextBuilder; from ai_pr_review.config import AppConfig; cb = ContextBuilder(AppConfig()); print(type(cb))"`
Expected: `<class 'ai_pr_review.context_builder.ContextBuilder'>`

- [ ] **Step 3: Commit**

```bash
git add src/ai_pr_review/context_builder.py
git commit -m "feat: add context builder with token budget management"
```

---

### Task 8: Prompt模板

**Files:**
- Create: `src/ai_pr_review/prompt_templates.py`

- [ ] **Step 1: 实现Prompt模板**

```python
import json
from ai_pr_review.expert_knowledge import ExpertProfile


SYSTEM_PROMPT = """你是一位代码审查专家团队的组织者。你将根据提供的专家知识清单，对Pull Request的代码变更进行专业、深入的审查。

核心原则：
1. 每个发现必须关联到具体的代码行号和文件
2. 每个发现必须给出置信度评分(1-5)和严重级别(high/medium/low)
3. 每个发现必须映射到某个专家的checklist项
4. 避免泛泛建议，只报告有实际价值的问题
5. 不要报告风格偏好问题（如单引号vs双引号）
6. 不要报告缺少注释等低价值建议
7. 每个建议必须附带具体的修复代码示例
"""

OUTPUT_SCHEMA = """\
请严格按照以下JSON格式输出，不要包含任何其他文字：

```json
{
  "summary": {
    "intent": "本次PR的变更意图（一句话）",
    "scope": "变更影响范围",
    "key_changes": ["关键修改点1", "关键修改点2"]
  },
  "findings": [
    {
      "type": "risk|quality|testing",
      "severity": "high|medium|low",
      "confidence": 1-5,
      "expert": "security|architecture|performance|readability|testing",
      "file": "文件路径",
      "line": 行号,
      "title": "发现标题",
      "description": "详细描述",
      "suggestion": "修复建议",
      "code_snippet": "相关代码片段"
    }
  ],
  "suggestions": [
    {
      "category": "分类",
      "priority": "high|medium|low",
      "description": "改进建议描述",
      "example": "代码示例"
    }
  ]
}
```\
"""

FEW_SHOT_EXAMPLE = """
示例输出（仅供参考格式）：

```json
{
  "summary": {
    "intent": "添加JWT认证功能",
    "scope": "认证模块",
    "key_changes": ["新增auth.py实现JWT生成和验证", "修改db.py使用参数化查询"]
  },
  "findings": [
    {
      "type": "risk",
      "severity": "high",
      "confidence": 5,
      "expert": "security",
      "file": "auth.py",
      "line": 4,
      "title": "硬编码JWT密钥",
      "description": "JWT密钥直接硬编码在源代码中，存在泄露风险",
      "suggestion": "使用环境变量存储密钥",
      "code_snippet": "SECRET = 'hardcoded-secret'"
    }
  ],
  "suggestions": [
    {
      "category": "security",
      "priority": "high",
      "description": "将所有敏感配置移至环境变量",
      "example": "SECRET = os.environ.get('JWT_SECRET')"
    }
  ]
}
```\
"""


def build_expert_context(experts: list[ExpertProfile]) -> str:
    parts = ["当前启用的审查专家及其检查清单：\n"]
    for expert in experts:
        parts.append(f"## {expert.name}")
        parts.append(f"知识来源：{expert.knowledge_source}")
        parts.append("\n检查清单：")
        for item in expert.checklist:
            parts.append(f"  - {item}")
        parts.append("\n高风险信号（Red Flags）：")
        for flag in expert.red_flags:
            parts.append(f"  - {flag}")
        parts.append("")
    return "\n".join(parts)


def build_analysis_prompt(
    pr_context: str,
    diff_context: str,
    file_context: str,
    experts: list[ExpertProfile],
) -> list[dict[str, str]]:
    expert_context = build_expert_context(experts)

    user_content_parts = [
        "## PR信息\n" + pr_context,
        "\n## 代码变更\n" + diff_context,
    ]

    if file_context:
        user_content_parts.append("\n## 相关文件内容\n" + file_context)

    user_content_parts.append("\n## 审查专家\n" + expert_context)
    user_content_parts.append("\n" + OUTPUT_SCHEMA)
    user_content_parts.append("\n" + FEW_SHOT_EXAMPLE)

    messages = [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": "\n".join(user_content_parts)},
    ]

    return messages
```

- [ ] **Step 2: 验证Prompt构建**

Run: `cd "e:\AI PR Review" && python -c "from ai_pr_review.prompt_templates import build_analysis_prompt; from ai_pr_review.expert_knowledge import get_expert_profiles; experts = get_expert_profiles(['security']); msgs = build_analysis_prompt('PR Title: Test', 'diff content', '', experts); print(len(msgs), msgs[0]['role'][:6])"`
Expected: `2 system`

- [ ] **Step 3: Commit**

```bash
git add src/ai_pr_review/prompt_templates.py
git commit -m "feat: add prompt templates with expert context and structured output"
```

---

### Task 9: AI分析引擎

**Files:**
- Create: `src/ai_pr_review/analyzer.py`
- Create: `tests/test_analyzer.py`

- [ ] **Step 1: 编写分析引擎测试**

```python
import json
import pytest
from ai_pr_review.analyzer import parse_ai_response, AIAnalyzer
from ai_pr_review.models import Severity


def test_parse_ai_response_valid_json():
    raw = json.dumps({
        "summary": {
            "intent": "Add auth",
            "scope": "Auth module",
            "key_changes": ["New auth.py"],
        },
        "findings": [
            {
                "type": "risk",
                "severity": "high",
                "confidence": 4,
                "expert": "security",
                "file": "auth.py",
                "line": 10,
                "title": "Hardcoded secret",
                "description": "Secret is hardcoded",
                "suggestion": "Use env var",
                "code_snippet": "secret = 'xxx'",
            }
        ],
        "suggestions": [],
    })
    result = parse_ai_response(raw)
    assert result.summary.intent == "Add auth"
    assert len(result.findings) == 1
    assert result.findings[0].severity == Severity.HIGH


def test_parse_ai_response_with_markdown_wrapper():
    raw = '```json\n{"summary": {"intent": "Fix bug", "scope": "Core", "key_changes": []}, "findings": [], "suggestions": []}\n```'
    result = parse_ai_response(raw)
    assert result.summary.intent == "Fix bug"


def test_parse_ai_response_invalid_json_returns_empty():
    result = parse_ai_response("not valid json at all")
    assert result.summary.intent == ""
    assert len(result.findings) == 0
```

- [ ] **Step 2: 运行测试确认失败**

Run: `cd "e:\AI PR Review" && python -m pytest tests/test_analyzer.py -v`
Expected: FAIL - ModuleNotFoundError

- [ ] **Step 3: 实现AI分析引擎**

```python
import json
import re
import logging
from abc import ABC, abstractmethod
from openai import AsyncOpenAI
from ai_pr_review.models import (
    ParsedDiff,
    PRMetadata,
    AnalysisResult,
    AnalysisSummary,
    Finding,
    Suggestion,
    Severity,
)
from ai_pr_review.config import AppConfig
from ai_pr_review.context_builder import ContextBuilder
from ai_pr_review.expert_knowledge import select_experts, get_expert_profiles
from ai_pr_review.prompt_templates import build_analysis_prompt

logger = logging.getLogger(__name__)


def parse_ai_response(raw: str) -> AnalysisResult:
    json_match = re.search(r"```(?:json)?\s*\n?(.*?)\n?```", raw, re.DOTALL)
    if json_match:
        raw = json_match.group(1).strip()

    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        logger.warning("Failed to parse AI response as JSON")
        return AnalysisResult(
            summary=AnalysisSummary(intent="", scope="", key_changes=[]),
            findings=[],
            suggestions=[],
        )

    summary = AnalysisSummary(
        intent=data.get("summary", {}).get("intent", ""),
        scope=data.get("summary", {}).get("scope", ""),
        key_changes=data.get("summary", {}).get("key_changes", []),
    )

    findings = []
    for f in data.get("findings", []):
        try:
            findings.append(
                Finding(
                    type=f.get("type", "quality"),
                    severity=Severity(f.get("severity", "low")),
                    confidence=int(f.get("confidence", 3)),
                    expert=f.get("expert", ""),
                    file=f.get("file", ""),
                    line=int(f.get("line", 0)),
                    title=f.get("title", ""),
                    description=f.get("description", ""),
                    suggestion=f.get("suggestion", ""),
                    code_snippet=f.get("code_snippet", ""),
                )
            )
        except (ValueError, TypeError):
            continue

    suggestions = []
    for s in data.get("suggestions", []):
        try:
            suggestions.append(
                Suggestion(
                    category=s.get("category", ""),
                    priority=Severity(s.get("priority", "low")),
                    description=s.get("description", ""),
                    example=s.get("example", ""),
                )
            )
        except (ValueError, TypeError):
            continue

    return AnalysisResult(summary=summary, findings=findings, suggestions=suggestions)


class AIAnalyzer:
    def __init__(self, config: AppConfig, get_file_content_fn=None):
        self._config = config
        self._client = AsyncOpenAI(
            api_key=config.ai.api_key,
            base_url=config.ai.base_url,
        )
        self._context_builder = ContextBuilder(config, get_file_content_fn)

    async def analyze(
        self,
        pr_metadata: PRMetadata,
        parsed_diff: ParsedDiff,
        severity_threshold: str = "low",
        focus: list[str] | None = None,
    ) -> AnalysisResult:
        context = self._context_builder.build_context(pr_metadata, parsed_diff)

        file_paths = [f.path for f in parsed_diff.files]
        hunks_content = "\n".join(
            h.content for f in parsed_diff.files for h in f.hunks
        )
        expert_names = select_experts(file_paths, hunks_content)
        experts = get_expert_profiles(expert_names)

        messages = build_analysis_prompt(
            pr_context=context.get("pr_metadata", ""),
            diff_context=context.get("diff", ""),
            file_context=context.get("file_contents", ""),
            experts=experts,
        )

        raw_response = await self._call_ai(messages)
        result = parse_ai_response(raw_response)

        result = self._apply_filters(result, severity_threshold, focus)

        return result

    async def _call_ai(self, messages: list[dict[str, str]]) -> str:
        try:
            response = await self._client.chat.completions.create(
                model=self._config.ai.model,
                messages=messages,
                max_tokens=self._config.ai.max_tokens,
                temperature=self._config.ai.temperature,
            )
            return response.choices[0].message.content or ""
        except Exception as e:
            logger.error(f"AI API call failed: {e}")
            return ""

    def _apply_filters(
        self,
        result: AnalysisResult,
        severity_threshold: str,
        focus: list[str] | None,
    ) -> AnalysisResult:
        severity_order = {"low": 0, "medium": 1, "high": 2}
        min_severity = severity_order.get(severity_threshold, 0)

        filtered_findings = [
            f
            for f in result.findings
            if severity_order.get(f.severity.value, 0) >= min_severity
            and f.confidence >= 3
        ]

        if focus:
            filtered_findings = [
                f for f in filtered_findings if f.type in focus or f.expert in focus
            ]

        result.findings = filtered_findings
        return result
```

- [ ] **Step 4: 运行测试确认通过**

Run: `cd "e:\AI PR Review" && python -m pytest tests/test_analyzer.py -v`
Expected: 全部PASS

- [ ] **Step 5: Commit**

```bash
git add src/ai_pr_review/analyzer.py tests/test_analyzer.py
git commit -m "feat: add AI analyzer with response parsing and filtering"
```

---

### Task 10: 结果格式化

**Files:**
- Create: `src/ai_pr_review/formatter.py`
- Create: `tests/test_formatter.py`

- [ ] **Step 1: 编写格式化测试**

```python
from ai_pr_review.formatter import format_terminal, format_github_comment
from ai_pr_review.models import (
    AnalysisResult,
    AnalysisSummary,
    Finding,
    Suggestion,
    Severity,
)


def _make_result() -> AnalysisResult:
    return AnalysisResult(
        summary=AnalysisSummary(
            intent="Add JWT authentication",
            scope="Authentication module",
            key_changes=["New auth.py module", "Updated db.py queries"],
        ),
        findings=[
            Finding(
                type="risk",
                severity=Severity.HIGH,
                confidence=5,
                expert="security",
                file="auth.py",
                line=4,
                title="Hardcoded JWT secret",
                description="JWT secret is hardcoded in source code",
                suggestion="Use environment variable",
                code_snippet="SECRET = 'hardcoded-secret'",
            ),
            Finding(
                type="risk",
                severity=Severity.MEDIUM,
                confidence=3,
                expert="security",
                file="db.py",
                line=15,
                title="SQL Injection risk",
                description="User input concatenated into SQL",
                suggestion="Use parameterized queries",
                code_snippet='query = f"DELETE FROM users WHERE id = {user_id}"',
            ),
        ],
        suggestions=[
            Suggestion(
                category="security",
                priority=Severity.HIGH,
                description="Move all secrets to environment variables",
                example="SECRET = os.environ['JWT_SECRET']",
            )
        ],
    )


def test_format_terminal_contains_summary():
    result = _make_result()
    output = format_terminal(result)
    assert "Add JWT authentication" in output
    assert "auth.py" in output


def test_format_terminal_contains_severity_emoji():
    result = _make_result()
    output = format_terminal(result)
    assert "🔴" in output or "HIGH" in output.upper() or "高" in output


def test_format_github_comment_is_markdown():
    result = _make_result()
    output = format_github_comment(result)
    assert "##" in output
    assert "auth.py" in output
```

- [ ] **Step 2: 运行测试确认失败**

Run: `cd "e:\AI PR Review" && python -m pytest tests/test_formatter.py -v`
Expected: FAIL - ModuleNotFoundError

- [ ] **Step 3: 实现结果格式化**

```python
from ai_pr_review.models import AnalysisResult, Finding, Severity

SEVERITY_EMOJI = {
    Severity.HIGH: "🔴",
    Severity.MEDIUM: "🟡",
    Severity.LOW: "🟢",
}

SEVERITY_LABEL = {
    Severity.HIGH: "高",
    Severity.MEDIUM: "中",
    Severity.LOW: "低",
}


def format_terminal(result: AnalysisResult) -> str:
    parts = []

    parts.append("📋 PR 变更总结")
    parts.append("━" * 40)
    parts.append(f"变更意图：{result.summary.intent}")
    parts.append(f"影响范围：{result.summary.scope}")
    parts.append("关键修改：")
    for change in result.summary.key_changes:
        parts.append(f"  - {change}")
    parts.append("")

    if result.findings:
        parts.append(f"⚠️  风险识别 ({len(result.findings)}项)")
        parts.append("━" * 40)
        for finding in result.findings:
            emoji = SEVERITY_EMOJI.get(finding.severity, "⚪")
            label = SEVERITY_LABEL.get(finding.severity, finding.severity.value)
            parts.append(
                f"{emoji} [{label}] {finding.file}:L{finding.line} - {finding.title} [{finding.expert}]"
            )
            parts.append(f"   {finding.description}")
            parts.append(f"   建议：{finding.suggestion}")
            if finding.code_snippet:
                parts.append(f"   代码：{finding.code_snippet}")
            parts.append("")

    if result.suggestions:
        parts.append(f"💡 Review 建议 ({len(result.suggestions)}项)")
        parts.append("━" * 40)
        for suggestion in result.suggestions:
            label = SEVERITY_LABEL.get(suggestion.priority, suggestion.priority.value)
            parts.append(f"  [{label}] [{suggestion.category}] {suggestion.description}")
            if suggestion.example:
                parts.append(f"   示例：{suggestion.example}")
            parts.append("")

    return "\n".join(parts)


def format_github_comment(result: AnalysisResult) -> str:
    parts = []

    parts.append("## 🤖 AI PR Review")
    parts.append("")
    parts.append("### 📋 变更总结")
    parts.append(f"**意图**：{result.summary.intent}")
    parts.append(f"**范围**：{result.summary.scope}")
    parts.append("**关键修改**：")
    for change in result.summary.key_changes:
        parts.append(f"- {change}")
    parts.append("")

    if result.findings:
        parts.append(f"### ⚠️ 风险识别 ({len(result.findings)}项)")
        parts.append("")
        for finding in result.findings:
            label = finding.severity.value.upper()
            parts.append(
                f"- **[{label}]** `{finding.file}:L{finding.line}` - {finding.title} _({finding.expert})_"
            )
            parts.append(f"  - {finding.description}")
            parts.append(f"  - 💡 建议：{finding.suggestion}")
            if finding.code_snippet:
                parts.append(f"  - 代码：`{finding.code_snippet}`")
        parts.append("")

    if result.suggestions:
        parts.append(f"### 💡 改进建议 ({len(result.suggestions)}项)")
        parts.append("")
        for suggestion in result.suggestions:
            parts.append(
                f"- **[{suggestion.priority.value.upper()}]** [{suggestion.category}] {suggestion.description}"
            )
            if suggestion.example:
                parts.append(f"  - 示例：`{suggestion.example}`")
        parts.append("")

    parts.append("---")
    parts.append("*Generated by [AI PR Review](https://github.com/ai-pr-review)*")

    return "\n".join(parts)
```

- [ ] **Step 4: 运行测试确认通过**

Run: `cd "e:\AI PR Review" && python -m pytest tests/test_formatter.py -v`
Expected: 全部PASS

- [ ] **Step 5: Commit**

```bash
git add src/ai_pr_review/formatter.py tests/test_formatter.py
git commit -m "feat: add terminal and GitHub Markdown result formatters"
```

---

### Task 11: GitHub评论回写

**Files:**
- Create: `src/ai_pr_review/commenter.py`

- [ ] **Step 1: 实现GitHub评论回写**

```python
import logging
from ai_pr_review.github_client import GitHubClient
from ai_pr_review.models import AnalysisResult
from ai_pr_review.formatter import format_github_comment

logger = logging.getLogger(__name__)


class Commenter:
    def __init__(self, client: GitHubClient):
        self._client = client

    def post_review(self, url: str, result: AnalysisResult, event: str = "COMMENT"):
        body = format_github_comment(result)
        try:
            self._client.create_review(url, body=body, event=event)
            logger.info(f"Successfully posted review to {url}")
        except Exception as e:
            logger.error(f"Failed to post review: {e}")
            raise

    def post_summary_comment(self, url: str, result: AnalysisResult):
        body = format_github_comment(result)
        try:
            self._client.create_pr_comment(url, body=body)
            logger.info(f"Successfully posted summary comment to {url}")
        except Exception as e:
            logger.error(f"Failed to post summary comment: {e}")
            raise

    def post_inline_comments(self, url: str, result: AnalysisResult, commit_id: str):
        for finding in result.findings:
            if finding.line > 0 and finding.file:
                body = (
                    f"**[{finding.severity.value.upper()}] {finding.title}** _({finding.expert})_\n\n"
                    f"{finding.description}\n\n"
                    f"💡 **建议**：{finding.suggestion}"
                )
                if finding.code_snippet:
                    body += f"\n\n相关代码：`{finding.code_snippet}`"
                try:
                    self._client.create_review_comment(
                        url,
                        commit_id=commit_id,
                        path=finding.file,
                        line=finding.line,
                        body=body,
                    )
                except Exception as e:
                    logger.warning(
                        f"Failed to post inline comment for {finding.file}:L{finding.line}: {e}"
                    )
```

- [ ] **Step 2: Commit**

```bash
git add src/ai_pr_review/commenter.py
git commit -m "feat: add GitHub commenter for review and inline comments"
```

---

### Task 12: CLI入口

**Files:**
- Create: `src/ai_pr_review/cli.py`

- [ ] **Step 1: 实现CLI入口**

```python
import asyncio
import logging
from typing import Optional
from rich.console import Console
from rich.panel import Panel
import typer

from ai_pr_review.config import load_config, AppConfig
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
    config = load_config(config_path and __import__("pathlib").Path(config_path))

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
```

- [ ] **Step 2: 验证CLI帮助信息**

Run: `cd "e:\AI PR Review" && python -m ai_pr_review.cli --help`
Expected: 显示完整的CLI帮助信息

- [ ] **Step 3: Commit**

```bash
git add src/ai_pr_review/cli.py
git commit -m "feat: add CLI entry point with Typer"
```

---

### Task 13: 集成测试与最终验证

**Files:**
- Modify: `pyproject.toml` (如有需要)

- [ ] **Step 1: 运行全部测试**

Run: `cd "e:\AI PR Review" && python -m pytest tests/ -v`
Expected: 全部PASS

- [ ] **Step 2: 验证CLI入口点**

Run: `cd "e:\AI PR Review" && pip install -e . && ai-pr-review --help`
Expected: 显示帮助信息，包含所有参数说明

- [ ] **Step 3: 运行代码质量检查**

Run: `cd "e:\AI PR Review" && python -m pytest tests/ -v --cov=ai_pr_review --cov-report=term-missing`
Expected: 测试通过，覆盖率报告显示

- [ ] **Step 4: Final Commit**

```bash
git add -A
git commit -m "feat: complete AI PR Review assistant v0.1.0"
```

---

## Self-Review Checklist

- [x] **Spec coverage**: 每个设计文档中的模块都有对应的Task实现
- [x] **Placeholder scan**: 无TBD/TODO/未完成步骤
- [x] **Type consistency**: 所有数据模型在Task间保持一致（models.py定义一次，各模块引用）
- [x] **CLI参数**: 与设计文档中的CLI接口完全匹配
- [x] **专家知识库**: 5个专家完整实现，动态选择逻辑已包含
- [x] **误报控制**: 置信度过滤和严重级别过滤已实现
- [x] **GitHub回写**: Review评论和行级评论都已实现
