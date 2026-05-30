# 增量分析功能实施计划

## 目标

实现 PR 增量分析：当同一 PR 被多次审查时，仅分析自上次审查以来的新增变更，大幅降低 token 消耗并提升分析速度。

## 当前架构分析

### 已有基础设施
- `history.py`：`AnalysisRecord` 记录 PR 审查历史，但**未记录 commit SHA**
- `github_client.py`：`get_pr_diff_content()` 获取完整 PR diff，**无 commit 对比能力**
- `diff_parser.py`：`parse_diff()` 解析 unified diff，可直接复用
- `analyzer.py`：`AIAnalyzer` 分析管道，需支持增量模式
- `cli.py`：`review` 命令，需新增 `--incremental` 参数

### 关键缺失
1. `AnalysisRecord` 无 `head_sha` 字段 → 无法追踪上次分析的 commit
2. `GitHubClient` 无获取两个 commit 之间 diff 的方法
3. 无增量 diff 与完整 diff 的合并逻辑
4. prompt 中无增量上下文信息

## 实施步骤

### Step 1: 扩展 AnalysisRecord 记录 commit SHA

**文件**: `src/ai_pr_review/history.py`

在 `AnalysisRecord` 中新增字段：

```python
@dataclass
class AnalysisRecord:
    pr_url: str
    pr_title: str
    timestamp: str = ""
    findings_count: int = 0
    high_severity_count: int = 0
    medium_severity_count: int = 0
    low_severity_count: int = 0
    suggestions_count: int = 0
    model: str = ""
    duration_seconds: float = 0.0
    head_sha: str = ""        # 新增：PR head commit SHA
    base_sha: str = ""        # 新增：PR base commit SHA
    is_incremental: bool = False  # 新增：是否增量分析
```

新增查找函数：

```python
def find_last_record(pr_url: str) -> AnalysisRecord | None:
    """查找指定 PR 的最近一次分析记录"""
    records = load_records()
    for r in records:
        if r.pr_url == pr_url and r.head_sha:
            return r
    return None
```

### Step 2: 扩展 GitHubClient 支持 commit diff

**文件**: `src/ai_pr_review/github_client.py`

新增方法：

```python
def get_commit_diff(self, url: str, base_sha: str, head_sha: str) -> str:
    """获取两个 commit 之间的 diff"""
    owner, repo_name, _ = parse_pr_url(url)
    headers = {
        "Accept": "application/vnd.github.v3.diff",
    }
    if self._token:
        headers["Authorization"] = f"Bearer {self._token}"
    compare_url = f"https://api.github.com/repos/{owner}/{repo_name}/compare/{base_sha}...{head_sha}"
    response = requests.get(compare_url, headers=headers, timeout=60)
    response.raise_for_status()
    data = response.json()
    return data.get("diff", "")

def get_pr_head_sha(self, url: str) -> str:
    """获取 PR 的最新 head commit SHA"""
    owner, repo_name, number = parse_pr_url(url)
    repo = self._client.get_repo(f"{owner}/{repo_name}")
    pr = repo.get_pull(number)
    return pr.head.sha
```

### Step 3: 新增增量分析模块

**文件**: `src/ai_pr_review/incremental.py`（新建）

```python
"""增量分析模块：仅分析自上次审查以来的变更"""

from ai_pr_review.models import ParsedDiff
from ai_pr_review.history import find_last_record, AnalysisRecord
from ai_pr_review.github_client import GitHubClient


class IncrementalAnalyzer:
    def __init__(self, gh_client: GitHubClient):
        self._gh_client = gh_client

    def should_analyze_incremental(self, pr_url: str) -> AnalysisRecord | None:
        """判断是否应进行增量分析，返回上次记录或 None"""
        last = find_last_record(pr_url)
        if not last or not last.head_sha:
            return None
        return last

    def get_incremental_diff(
        self,
        pr_url: str,
        last_sha: str,
        current_sha: str,
    ) -> str:
        """获取增量 diff（上次 SHA → 当前 SHA）"""
        if last_sha == current_sha:
            return ""
        return self._gh_client.get_commit_diff(pr_url, last_sha, current_sha)

    def build_incremental_context(
        self,
        pr_url: str,
        full_diff: ParsedDiff,
        incremental_diff: ParsedDiff,
        last_record: AnalysisRecord,
    ) -> dict:
        """构建增量分析上下文"""
        changed_files = [f.path for f in incremental_diff.files]
        unchanged_files = [
            f.path for f in full_diff.files if f.path not in changed_files
        ]
        return {
            "incremental_diff": incremental_diff,
            "changed_files": changed_files,
            "unchanged_files": unchanged_files,
            "last_sha": last_record.head_sha,
            "last_timestamp": last_record.timestamp,
            "is_incremental": True,
        }
```

### Step 4: 扩展 prompt_templates.py 支持增量上下文

**文件**: `src/ai_pr_review/prompt_templates.py`

新增增量分析系统提示：

```python
INCREMENTAL_SYSTEM_PROMPT = """你是一位代码审查专家。本次为增量审查——仅分析自上次审查以来的新增变更。

规则：
- 仅关注增量变更部分，已审查过的代码不再重复报告
- 如果增量变更影响了已有代码的逻辑，仍需报告
- 每个发现标注 [增量] 前缀
- 使用P0-P3严重级别
- 优先报告：新增安全问题、逻辑错误、性能问题
"""
```

修改 `build_analysis_prompt()` 新增 `incremental_context` 参数：

```python
def build_analysis_prompt(
    pr_context, diff_context, file_context, experts,
    custom_rules=None,
    incremental_context=None,  # 新增
) -> list[dict[str, str]]:
    ...
    if incremental_context:
        system_prompt = INCREMENTAL_SYSTEM_PROMPT
        inc_info = (
            f"\n## 增量分析信息\n"
            f"- 上次审查 commit: {incremental_context['last_sha']}\n"
            f"- 上次审查时间: {incremental_context['last_timestamp']}\n"
            f"- 本次变更文件: {', '.join(incremental_context['changed_files'])}\n"
            f"- 未变更文件: {', '.join(incremental_context['unchanged_files'][:10])}\n"
        )
        user_content_parts.append(inc_info)
    ...
```

### Step 5: 修改 analyzer.py 支持增量分析

**文件**: `src/ai_pr_review/analyzer.py`

在 `AIAnalyzer` 中新增 `analyze_incremental()` 方法：

```python
async def analyze_incremental(
    self,
    pr_metadata: PRMetadata,
    full_parsed_diff: ParsedDiff,
    incremental_parsed_diff: ParsedDiff,
    incremental_context: dict,
    severity_threshold: str = "low",
    focus: list[str] | None = None,
) -> AnalysisResult:
    """增量分析：仅分析增量变更"""
    context = self._context_builder.build_context(pr_metadata, incremental_parsed_diff)
    file_paths = [f.path for f in incremental_parsed_diff.files]
    hunks_content = "\n".join(h.content for f in incremental_parsed_diff.files for h in f.hunks)
    expert_names = select_experts(file_paths, hunks_content, self._custom_expert_keys)
    experts = get_expert_profiles(expert_names, self._merged_skills)

    messages = build_analysis_prompt(
        pr_context=context.get("pr_metadata", ""),
        diff_context=context.get("diff", ""),
        file_context=context.get("file_contents", ""),
        experts=experts,
        custom_rules=self._custom_rules,
        incremental_context=incremental_context,
    )

    raw_response = await self._call_ai(messages)
    result = parse_ai_response(raw_response)
    result = self._apply_filters(result, severity_threshold, focus)
    return result
```

### Step 6: 修改 cli.py 集成增量分析

**文件**: `src/ai_pr_review/cli.py`

新增 `--incremental` 参数：

```python
@app.command()
def review(
    pr_url: str = typer.Argument(...),
    ...
    incremental: bool = typer.Option(False, "--incremental", "-i", help="Incremental analysis (only new changes since last review)"),
):
```

在 review 逻辑中集成增量判断：

```python
from ai_pr_review.incremental import IncrementalAnalyzer
from ai_pr_review.diff_parser import parse_diff

# 获取当前 head SHA
current_sha = gh_client.get_pr_head_sha(pr_url)

# 判断是否增量分析
inc_analyzer = IncrementalAnalyzer(gh_client)
last_record = None
if incremental:
    last_record = inc_analyzer.should_analyze_incremental(pr_url)

if last_record and last_record.head_sha != current_sha:
    # 增量分析
    inc_diff_text = inc_analyzer.get_incremental_diff(pr_url, last_record.head_sha, current_sha)
    incremental_parsed = parse_diff(inc_diff_text)
    inc_context = inc_analyzer.build_incremental_context(pr_url, parsed_diff, incremental_parsed, last_record)
    
    result = asyncio.run(analyzer.analyze_incremental(
        pr_metadata, parsed_diff, incremental_parsed, inc_context, severity, focus_list
    ))
    console.print(f"🔄 Incremental analysis: {len(incremental_parsed.files)} changed files since {last_record.head_sha[:7]}")
elif last_record and last_record.head_sha == current_sha:
    console.print("✅ No new changes since last review.")
    return
else:
    # 完整分析（原有逻辑）
    result = asyncio.run(analyzer.analyze(...))

# 保存记录时包含 SHA
record = AnalysisRecord(
    pr_url=pr_url,
    pr_title=pr_metadata.title,
    ...
    head_sha=current_sha,
    is_incremental=last_record is not None,
)
save_record(record)
```

### Step 7: 编写测试

**文件**: `tests/test_incremental.py`（新建）

测试用例：

1. `test_analysis_record_sha_fields` - AnalysisRecord 新字段默认值
2. `test_find_last_record_found` - 查找 PR 的最近记录
3. `test_find_last_record_not_found` - 无记录时返回 None
4. `test_should_analyze_incremental_with_record` - 有上次记录时返回记录
5. `test_should_analyze_incremental_no_record` - 无记录时返回 None
6. `test_get_incremental_diff_same_sha` - SHA 相同时返回空
7. `test_build_incremental_context` - 构建增量上下文
8. `test_incremental_prompt_contains_context` - 增量 prompt 包含增量信息
9. `test_incremental_prompt_uses_special_system` - 增量分析使用专用系统提示
10. `test_full_analysis_no_incremental_context` - 完整分析无增量上下文

### Step 8: 更新 README.md

在功能特性和使用示例中补充增量分析说明。

## 修改文件清单

| 文件 | 变更类型 | 说明 |
|------|----------|------|
| `src/ai_pr_review/history.py` | 修改 | AnalysisRecord 新增 head_sha/base_sha/is_incremental，新增 find_last_record() |
| `src/ai_pr_review/github_client.py` | 修改 | 新增 get_commit_diff() 和 get_pr_head_sha() |
| `src/ai_pr_review/incremental.py` | 新建 | IncrementalAnalyzer 类 |
| `src/ai_pr_review/prompt_templates.py` | 修改 | 新增 INCREMENTAL_SYSTEM_PROMPT，build_analysis_prompt 新增 incremental_context |
| `src/ai_pr_review/analyzer.py` | 修改 | 新增 analyze_incremental() 方法 |
| `src/ai_pr_review/cli.py` | 修改 | 新增 --incremental 参数，集成增量分析流程 |
| `tests/test_incremental.py` | 新建 | 10 个测试用例 |
| `README.md` | 修改 | 补充增量分析说明 |

## Token 消耗优化效果预估

| 场景 | 完整分析 | 增量分析 | 节省 |
|------|----------|----------|------|
| PR 新增 3 个 commit（5 文件变更） | ~3000 tokens | ~800 tokens | ~73% |
| PR 迭代 10 次（每次 2-3 文件） | ~3000 × 10 | ~800 × 9 + 3000 | ~70% |
| 大 PR（50 文件）后续小修改 | ~15000 tokens | ~2000 tokens | ~87% |

## 向后兼容性

- `--incremental` 默认为 False，不启用时行为完全不变
- `AnalysisRecord` 新字段有默认值，旧记录兼容
- `build_analysis_prompt()` 新参数默认为 None
- 现有 110 个测试不受影响
