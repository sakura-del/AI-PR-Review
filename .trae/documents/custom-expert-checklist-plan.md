# 自定义专家 Checklist 扩展计划

## 目标

扩展 `.ai-pr-review.yaml` 配置文件，支持用户自定义专家 checklist 和 red_flags，使用户可根据团队规范、领域特定规则定制审查标准。

## 当前架构分析

### 已有基础设施
- `ExpertProfile` 数据结构：`name`, `checklist`, `red_flags`, `knowledge_source`
- `EXPERT_SKILLS`：5 个内置专家的硬编码字典
- `ProjectConfig`：已有 `custom_rules`（纯文本规则列表）和 `enabled_experts` 字段
- `load_project_config()`：已能解析 `.ai-pr-review.yaml`
- `build_expert_context()`：将专家 checklist 渲染到 prompt
- `get_expert_profiles()`：根据 expert_names 返回 ExpertProfile 列表

### 问题
- `custom_rules` 只是纯文本追加到 prompt，无法结构化关联到具体专家
- 无法覆盖/扩展内置专家的 checklist 和 red_flags
- 无法添加全新的自定义专家

## 实施步骤

### Step 1: 扩展 ProjectConfig 数据结构

**文件**: `src/ai_pr_review/config.py`

在 `ProjectConfig` 中新增 `expert_overrides` 和 `custom_experts` 字段：

```python
@dataclass
class ExpertOverride:
    checklist_append: list[str] = field(default_factory=list)
    checklist_replace: list[str] | None = None
    red_flags_append: list[str] = field(default_factory=list)
    red_flags_replace: list[str] | None = None

@dataclass
class ProjectConfig:
    ignore_paths: list[str] = field(...)
    custom_rules: list[str] = field(...)
    max_context_files: int = 10
    enabled_experts: list[str] | None = None
    expert_overrides: dict[str, ExpertOverride] = field(default_factory=dict)  # 新增
    custom_experts: dict[str, ExpertProfile] = field(default_factory=dict)     # 新增
```

### Step 2: 扩展 load_project_config 解析逻辑

**文件**: `src/ai_pr_review/config.py`

在 `load_project_config()` 中新增对 `expert_overrides` 和 `custom_experts` 的 YAML 解析。

YAML 配置格式设计：

```yaml
# 覆盖/扩展内置专家
expert_overrides:
  security:
    checklist_append:
      - "内部API必须使用mTLS认证"
      - "禁止在日志中记录PII数据"
    red_flags_append:
      - "未经审批的外部服务调用"
  readability:
    checklist_replace:           # 完全替换 checklist
      - "遵循公司Java编码规范v3.2"
      - "所有public方法必须有Javadoc"

# 添加全新自定义专家
custom_experts:
  company_compliance:
    name: "合规审查"
    knowledge_source: "公司内部合规标准"
    checklist:
      - "数据导出必须经过脱敏处理"
      - "用户数据访问必须有审计日志"
      - "第三方SDK需通过安全评审"
    red_flags:
      - "未经审批的第三方依赖"
      - "缺少数据分类标注"
```

### Step 3: 修改 expert_knowledge.py 支持合并

**文件**: `src/ai_pr_review/expert_knowledge.py`

新增 `merge_expert_config()` 函数，将 ProjectConfig 中的覆盖/自定义合并到 EXPERT_SKILLS：

```python
def merge_expert_config(
    project_config: ProjectConfig | None = None,
) -> dict[str, ExpertProfile]:
    """合并内置专家与项目级自定义配置"""
    merged = dict(EXPERT_SKILLS)  # 浅拷贝

    if not project_config:
        return merged

    # 1. 应用 expert_overrides（覆盖/追加到内置专家）
    for key, override in project_config.expert_overrides.items():
        if key in merged:
            original = merged[key]
            checklist = list(original.checklist)
            red_flags = list(original.red_flags)

            if override.checklist_replace is not None:
                checklist = override.checklist_replace
            else:
                checklist.extend(override.checklist_append)

            if override.red_flags_replace is not None:
                red_flags = override.red_flags_replace
            else:
                red_flags.extend(override.red_flags_append)

            merged[key] = ExpertProfile(
                name=original.name,
                checklist=checklist,
                red_flags=red_flags,
                knowledge_source=original.knowledge_source,
            )

    # 2. 添加 custom_experts（全新专家）
    for key, profile in project_config.custom_experts.items():
        merged[key] = profile

    return merged
```

修改 `get_expert_profiles()` 接受可选的 `merged_skills` 参数：

```python
def get_expert_profiles(
    expert_names: list[str],
    skills: dict[str, ExpertProfile] | None = None,
) -> list[ExpertProfile]:
    source = skills or EXPERT_SKILLS
    return [source[name] for name in expert_names if name in source]
```

### Step 4: 修改 analyzer.py 传递项目配置

**文件**: `src/ai_pr_review/analyzer.py`

在 `AIAnalyzer.__init__` 中加载项目配置，在 `analyze()` / `analyze_stream()` / `_analyze_shard()` 中使用合并后的专家技能：

```python
from ai_pr_review.config import load_project_config
from ai_pr_review.expert_knowledge import merge_expert_config, get_expert_profiles

class AIAnalyzer:
    def __init__(self, config, get_file_content_fn=None):
        ...
        self._project_config = load_project_config()
        self._merged_skills = merge_expert_config(self._project_config)

    async def analyze(self, ...):
        ...
        experts = get_expert_profiles(expert_names, self._merged_skills)
        ...
```

### Step 5: 修改 prompt_templates.py 支持自定义规则注入

**文件**: `src/ai_pr_review/prompt_templates.py`

在 `build_analysis_prompt()` 中追加 `custom_rules`：

```python
def build_analysis_prompt(
    pr_context, diff_context, file_context, experts,
    custom_rules: list[str] | None = None,  # 新增
) -> list[dict[str, str]]:
    ...
    if custom_rules:
        user_content_parts.append("\n## 团队自定义规则\n" + "\n".join(f"- {r}" for r in custom_rules))
    ...
```

### Step 6: 更新 .ai-pr-review.yaml 示例

**文件**: `.ai-pr-review.yaml`

添加 `expert_overrides` 和 `custom_experts` 配置示例和注释说明。

### Step 7: 编写测试

**文件**: `tests/test_expert_customization.py`（新建）

测试用例：
1. `test_expert_override_append` - 追加 checklist/red_flags 到内置专家
2. `test_expert_override_replace` - 完全替换 checklist/red_flags
3. `test_custom_expert_added` - 添加全新自定义专家
4. `test_merge_preserves_builtin` - 合并不影响内置专家原始数据
5. `test_get_expert_profiles_with_merged` - get_expert_profiles 使用合并后的技能
6. `test_load_project_config_expert_overrides` - YAML 解析 expert_overrides
7. `test_load_project_config_custom_experts` - YAML 解析 custom_experts
8. `test_custom_rules_in_prompt` - custom_rules 注入到 prompt
9. `test_empty_project_config_defaults` - 无配置时回退到默认
10. `test_select_experts_includes_custom` - 自定义专家参与关键词匹配

### Step 8: 更新 README.md

在「项目级自定义配置」章节补充 `expert_overrides` 和 `custom_experts` 的说明和示例。

## 修改文件清单

| 文件 | 变更类型 | 说明 |
|------|----------|------|
| `src/ai_pr_review/config.py` | 修改 | 新增 ExpertOverride 数据类，扩展 ProjectConfig，扩展 load_project_config |
| `src/ai_pr_review/expert_knowledge.py` | 修改 | 新增 merge_expert_config()，修改 get_expert_profiles() 签名 |
| `src/ai_pr_review/analyzer.py` | 修改 | 加载项目配置，使用合并后的专家技能，传递 custom_rules |
| `src/ai_pr_review/prompt_templates.py` | 修改 | build_analysis_prompt 新增 custom_rules 参数 |
| `.ai-pr-review.yaml` | 修改 | 添加 expert_overrides 和 custom_experts 示例 |
| `tests/test_expert_customization.py` | 新建 | 10 个测试用例 |
| `README.md` | 修改 | 补充自定义专家配置说明 |

## 向后兼容性

- 所有新增字段都有默认值，不配置时行为与现有完全一致
- `custom_rules` 保持原有功能不变
- `get_expert_profiles()` 新参数 `skills` 默认为 None，回退到 EXPERT_SKILLS
- 现有 92 个测试不受影响
