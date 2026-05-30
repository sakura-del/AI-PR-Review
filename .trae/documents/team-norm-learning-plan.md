# 团队规范学习功能 - 实现计划

## 1. 功能概述

从 GitHub 仓库的历史 PR 评论中提取团队审查模式，自动生成个性化审查规则，注入到分析 prompt 中，让 AI 学习团队特定的审查风格和关注点。

**核心价值**：
- 减少误报：AI 了解团队真正在意什么
- 提升准确性：审查风格与团队习惯一致
- 知识沉淀：团队审查经验自动积累

## 2. 架构设计

### 数据流

```
GitHub PR 评论 → 评论采集器 → 模式提取器(AI) → 规则存储 → prompt 注入
                                                          ↑
                                          .ai-pr-review.yaml (手动规则)
```

### 新增模块

| 模块 | 文件 | 职责 |
|------|------|------|
| 评论采集器 | `github_client.py` 扩展 | 从 GitHub API 获取仓库历史 PR 评论 |
| 模式提取器 | `team_learner.py` (新建) | 用 AI 从评论中提取审查规则和模式 |
| 规则存储 | `team_rules.py` (新建) | 持久化团队规则，支持权重和版本管理 |
| prompt 注入 | `prompt_templates.py` 扩展 | 将团队规则注入分析 prompt |

## 3. 详细实现步骤

### Step 1: 扩展 GitHubClient - 获取历史 PR 评论

在 `github_client.py` 中新增方法：

```python
def get_repo_pr_comments(self, url: str, max_prs: int = 20) -> list[dict]:
    """获取仓库最近 N 个 PR 的评论"""
    owner, repo_name, _ = parse_pr_url(url)
    repo = self._client.get_repo(f"{owner}/{repo_name}")
    pulls = repo.get_pulls(state="closed", sort="updated", direction="desc")

    comments = []
    for pr in pulls[:max_prs]:
        pr_comments = pr.get_review_comments()  # 行级评论（更有价值）
        issue_comments = pr.get_issue_comments()  # PR 级评论
        for c in pr_comments:
            comments.append({
                "pr_number": pr.number,
                "pr_title": pr.title,
                "file": c.path,
                "line": c.line,
                "body": c.body,
                "author": c.user.login,
                "created_at": str(c.created_at),
                "comment_type": "review",
            })
        for c in issue_comments:
            comments.append({
                "pr_number": pr.number,
                "pr_title": pr.title,
                "file": "",
                "line": 0,
                "body": c.body,
                "author": c.user.login,
                "created_at": str(c.created_at),
                "comment_type": "issue",
            })
    return comments
```

**关键决策**：
- 优先采集行级 review comments（比 issue comments 更精确）
- 限制 `max_prs=20` 避免过多 API 调用
- 过滤掉机器人评论（`author` 包含 `bot` 或 `ai-review`）

### Step 2: 新建 `team_learner.py` - 模式提取器

```python
@dataclass
class TeamRule:
    category: str           # security/performance/style/testing/custom
    description: str        # 规则描述
    example: str            # 示例代码或模式
    weight: float = 1.0     # 权重 (0.0-2.0)
    source: str = ""        # 来源 (learned/manual)
    frequency: int = 1      # 出现频率

@dataclass
class TeamPattern:
    rules: list[TeamRule]
    common_terms: list[str]     # 团队常用术语
    severity_preference: dict   # 严重级别偏好 {"P0": 0.1, "P1": 0.3, ...}
    focus_areas: list[str]      # 团队重点关注领域
    repo_url: str = ""
    learned_at: str = ""
```

核心方法：

```python
class TeamLearner:
    def __init__(self, config: AppConfig):
        self._client = AsyncOpenAI(
            api_key=config.ai.api_key,
            base_url=config.ai.base_url,
        )
        self._model = config.ai.model

    async def extract_patterns(self, comments: list[dict]) -> TeamPattern:
        """从评论中提取团队审查模式"""
        # 1. 过滤和预处理评论
        filtered = self._filter_comments(comments)
        if not filtered:
            return TeamPattern(rules=[], common_terms=[], severity_preference={}, focus_areas=[])

        # 2. 构建 AI 提取 prompt
        messages = self._build_extraction_prompt(filtered)

        # 3. 调用 AI 提取模式
        raw = await self._call_ai(messages)

        # 4. 解析 AI 响应为 TeamPattern
        return self._parse_pattern(raw)

    def _filter_comments(self, comments: list[dict]) -> list[dict]:
        """过滤机器人评论和低质量评论"""
        filtered = []
        for c in comments:
            author = c.get("author", "").lower()
            if "bot" in author or "ai-review" in author:
                continue
            body = c.get("body", "").strip()
            if len(body) < 10:
                continue
            filtered.append(c)
        return filtered[:100]  # 最多取 100 条

    def _build_extraction_prompt(self, comments: list[dict]) -> list[dict]:
        """构建模式提取 prompt"""
        ...

    def _parse_pattern(self, raw: str) -> TeamPattern:
        """解析 AI 响应为 TeamPattern"""
        ...
```

**AI 提取 prompt 设计**：

```
你是一位代码审查模式分析专家。以下是一个团队在 PR 审查中留下的评论。

请分析这些评论，提取：
1. 团队反复关注的审查规则（category + description + example）
2. 团队常用的审查术语和表达
3. 团队对不同严重级别问题的关注偏好
4. 团队重点关注的领域

输出严格 JSON 格式...
```

### Step 3: 新建 `team_rules.py` - 规则存储

```python
TEAM_RULES_DIR = Path.home() / ".ai-pr-review" / "team_rules"

def save_team_pattern(pattern: TeamPattern) -> None:
    """保存团队模式到本地"""
    ...

def load_team_pattern(repo_url: str) -> TeamPattern | None:
    """加载指定仓库的团队模式"""
    # 文件名: {owner}_{repo}.json
    ...

def merge_team_rules(
    team_pattern: TeamPattern | None,
    manual_rules: list[str],
    expert_overrides: dict,
) -> list[TeamRule]:
    """合并学习规则与手动规则"""
    merged = []

    # 1. 加入学习到的规则
    if team_pattern:
        for rule in team_pattern.rules:
            merged.append(rule)

    # 2. 加入手动规则（权重更高）
    for rule_text in manual_rules:
        merged.append(TeamRule(
            category="custom",
            description=rule_text,
            example="",
            weight=1.5,
            source="manual",
        ))

    # 3. 按权重排序
    merged.sort(key=lambda r: r.weight, reverse=True)
    return merged
```

### Step 4: 扩展 `prompt_templates.py` - 注入团队规则

在 `build_analysis_prompt()` 中新增 `team_rules` 参数：

```python
def build_analysis_prompt(
    pr_context: str,
    diff_context: str,
    file_context: str,
    experts: list[ExpertProfile],
    custom_rules: list[str] | None = None,
    incremental_context: dict | None = None,
    team_rules: list[TeamRule] | None = None,       # 新增
) -> list[dict[str, str]]:
    ...
    if team_rules:
        team_text = "## 团队审查模式（从历史评论中学习）\n"
        for rule in team_rules:
            source_tag = "[学习]" if rule.source == "learned" else "[手动]"
            weight_tag = f"(权重:{rule.weight:.1f})" if rule.weight != 1.0 else ""
            team_text += f"- {source_tag} {rule.description} {weight_tag}\n"
            if rule.example:
                team_text += f"  示例：{rule.example}\n"
        user_content_parts.append(team_text)
    ...
```

### Step 5: 扩展 `config.py` - 团队学习配置

在 `ProjectConfig` 中新增：

```python
@dataclass
class TeamLearningConfig:
    enabled: bool = False
    max_prs: int = 20            # 最多分析多少个历史 PR
    max_comments: int = 100      # 最多提取多少条评论
    min_rule_weight: float = 0.3 # 最低规则权重阈值
    auto_learn: bool = False     # 是否在每次审查后自动学习
    rule_ttl_days: int = 30      # 学习规则的过期天数

@dataclass
class ProjectConfig:
    ...
    team_learning: TeamLearningConfig = field(default_factory=TeamLearningConfig)
```

`.ai-pr-review.yaml` 新增配置：

```yaml
team_learning:
  enabled: true
  max_prs: 20
  max_comments: 100
  min_rule_weight: 0.3
  auto_learn: false
  rule_ttl_days: 30
```

### Step 6: 扩展 `cli.py` - 新增 `learn` 子命令

```python
@app.command()
def learn(
    pr_url: str = typer.Argument(..., help="GitHub PR URL (用于定位仓库)"),
    model: Optional[str] = typer.Option(None, "--model", "-m", help="AI model"),
    max_prs: int = typer.Option(20, "--max-prs", help="Maximum PRs to analyze"),
    force: bool = typer.Option(False, "--force", "-f", help="Force re-learn even if cached"),
):
    """从历史 PR 评论中学习团队审查模式"""
    config = load_config(model_override=model)
    gh_client = GitHubClient(token=config.github.token)

    # 1. 检查缓存
    if not force:
        existing = load_team_pattern(pr_url)
        if existing:
            console.print(f"✅ 已有团队模式缓存 (学习于 {existing.learned_at})")
            console.print(f"   使用 --force 重新学习")
            return

    # 2. 采集评论
    with console.status("Fetching PR comments..."):
        comments = gh_client.get_repo_pr_comments(pr_url, max_prs=max_prs)
    console.print(f"📝 Fetched {len(comments)} comments from {max_prs} PRs")

    # 3. 提取模式
    with console.status("Learning team patterns..."):
        learner = TeamLearner(config)
        pattern = asyncio.run(learner.extract_patterns(comments))

    # 4. 保存
    save_team_pattern(pattern)
    console.print(f"✅ Learned {len(pattern.rules)} team rules")
    for rule in pattern.rules:
        console.print(f"  • [{rule.category}] {rule.description}")
```

同时在 `review` 命令中自动加载团队规则：

```python
# 在 review 命令中，构建 analyzer 后加载团队规则
team_pattern = load_team_pattern(pr_url)
team_rules = merge_team_rules(team_pattern, config.custom_rules, config.expert_overrides)

# 传递给 analyzer
messages = build_analysis_prompt(
    ...,
    team_rules=team_rules,  # 新增
)
```

### Step 7: 扩展 `analyzer.py` - 支持团队规则

在 `AIAnalyzer.__init__` 中加载团队规则：

```python
class AIAnalyzer:
    def __init__(self, config: AppConfig, get_file_content_fn=None, repo_url: str = ""):
        ...
        self._team_rules: list[TeamRule] = []
        if repo_url:
            team_pattern = load_team_pattern(repo_url)
            if team_pattern:
                self._team_rules = merge_team_rules(
                    team_pattern,
                    self._custom_rules,
                    self._project_config.expert_overrides,
                )
```

在 `analyze()` 和 `analyze_incremental()` 中传递 `team_rules`：

```python
messages = build_analysis_prompt(
    ...,
    team_rules=self._team_rules if self._team_rules else None,
)
```

### Step 8: 编写测试 `tests/test_team_learner.py`

测试用例规划：

1. **TeamRule 数据模型**
   - test_team_rule_creation - 创建规则
   - test_team_rule_default_weight - 默认权重
   - test_team_rule_weight_range - 权重范围

2. **TeamPattern 数据模型**
   - test_team_pattern_creation - 创建模式
   - test_team_pattern_empty - 空模式

3. **评论过滤**
   - test_filter_bot_comments - 过滤机器人评论
   - test_filter_short_comments - 过滤短评论
   - test_filter_limit_count - 限制评论数量

4. **模式提取**
   - test_extract_patterns_from_comments - 从评论提取模式
   - test_extract_patterns_empty_comments - 空评论返回空模式
   - test_parse_pattern_valid_json - 解析有效 JSON
   - test_parse_pattern_invalid_json - 解析无效 JSON 返回空模式

5. **规则存储**
   - test_save_and_load_team_pattern - 保存和加载
   - test_load_nonexistent_pattern - 加载不存在的模式
   - test_team_pattern_file_naming - 文件命名规则

6. **规则合并**
   - test_merge_team_and_manual_rules - 合并学习和手动规则
   - test_merge_manual_rules_higher_weight - 手动规则权重更高
   - test_merge_sorted_by_weight - 按权重排序
   - test_merge_empty_team_rules - 空学习规则时仅手动规则

7. **Prompt 注入**
   - test_team_rules_in_prompt - 团队规则出现在 prompt 中
   - test_learned_tag_in_prompt - 学习规则有 [学习] 标签
   - test_manual_tag_in_prompt - 手动规则有 [手动] 标签
   - test_weight_in_prompt - 权重显示在 prompt 中
   - test_no_team_rules_omits_section - 无规则时不显示该部分

8. **CLI learn 子命令**
   - test_learn_command_saves_pattern - learn 命令保存模式
   - test_learn_command_force_relearn - --force 重新学习
   - test_learn_command_cached - 有缓存时跳过

9. **项目配置**
   - test_team_learning_config_defaults - 默认配置
   - test_parse_team_learning_from_yaml - 从 YAML 解析

### Step 9: 更新 README.md

- 功能特性新增"团队规范学习"
- 新增 `learn` 子命令使用说明
- 新增 `.ai-pr-review.yaml` 中 `team_learning` 配置说明
- 更新项目结构（新增 `team_learner.py` 和 `team_rules.py`）
- 更新"未来扩展方向"（移除已实现的"团队规范学习"）

## 4. 文件变更清单

| 文件 | 操作 | 说明 |
|------|------|------|
| `src/ai_pr_review/team_learner.py` | 新建 | 模式提取器（TeamLearner + TeamRule + TeamPattern） |
| `src/ai_pr_review/team_rules.py` | 新建 | 规则存储和合并 |
| `src/ai_pr_review/github_client.py` | 修改 | 新增 `get_repo_pr_comments()` |
| `src/ai_pr_review/prompt_templates.py` | 修改 | `build_analysis_prompt()` 新增 `team_rules` 参数 |
| `src/ai_pr_review/analyzer.py` | 修改 | 加载和传递团队规则 |
| `src/ai_pr_review/config.py` | 修改 | 新增 `TeamLearningConfig`，`ProjectConfig` 扩展 |
| `src/ai_pr_review/cli.py` | 修改 | 新增 `learn` 子命令，review 命令集成团队规则 |
| `tests/test_team_learner.py` | 新建 | 团队学习功能测试 |
| `.ai-pr-review.yaml` | 修改 | 新增 `team_learning` 配置 |
| `README.md` | 修改 | 更新功能说明 |

## 5. 关键设计决策

### 5.1 为什么用 AI 提取而非规则匹配？

- PR 评论格式多样，规则匹配难以覆盖
- AI 可以理解语义，提取出隐含的审查偏好
- 一次提取，多次使用，AI 调用成本可控

### 5.2 为什么规则有权重？

- 团队对不同规则的关注度不同
- 高频出现的规则权重更高
- 手动规则权重 > 学习规则（1.5 vs 0.3-1.0）
- 低权重规则在 prompt 中靠后，减少 token 消耗

### 5.3 为什么规则有 TTL？

- 团队规范会演变
- 过期规则需要重新学习
- 避免过时规则影响审查质量

### 5.4 Token 消耗控制

- 评论采集限制 100 条
- AI 提取使用精简 prompt（~500 token）
- 提取结果为结构化 JSON，存储后无需重复提取
- 注入 prompt 时按权重排序，低权重规则可裁剪

## 6. 实施顺序

1. Step 1: 扩展 GitHubClient（`get_repo_pr_comments`）
2. Step 2: 新建 `team_learner.py`（TeamRule + TeamPattern + TeamLearner）
3. Step 3: 新建 `team_rules.py`（存储 + 合并）
4. Step 4: 扩展 `prompt_templates.py`（注入团队规则）
5. Step 5: 扩展 `config.py`（TeamLearningConfig）
6. Step 6: 扩展 `analyzer.py`（加载团队规则）
7. Step 7: 扩展 `cli.py`（learn 子命令 + review 集成）
8. Step 8: 编写测试
9. Step 9: 更新 README.md
10. 运行全部测试验证
11. Commit 并推送到 GitHub
