# AI PR Review 助手 - 设计文档

## 1. 项目概述

### 1.1 项目背景

代码评审（Code Review）是软件工程中保障代码质量的关键环节，但在实际开发中面临诸多痛点：

- **PR堆积**：团队协作中PR数量多，人工Review耗时长，导致PR等待时间过长
- **质量不均**：不同Reviewer的经验和关注点不同，Review质量参差不齐
- **遗漏风险**：人工Review容易遗漏安全漏洞、性能问题等非功能性缺陷
- **缺乏专业反馈**：个人开发者缺少"专业的人"指出代码问题

市场现有工具（如CodeRabbit、GitHub Copilot PR Review）已验证了AI辅助Review的可行性，但存在以下不足：
- 依赖海外模型，国内访问受限
- 无法自定义审查标准和专家知识
- 误报率较高，泛泛建议多

### 1.2 项目目标

开发一个基于国产AI模型的CLI代码评审工具，帮助开发者：

1. **快速理解PR**：自动总结变更内容和影响范围
2. **识别风险代码**：发现潜在Bug、安全漏洞、性能问题
3. **生成Review建议**：提供具体的代码改进方案
4. **回写GitHub评论**：将分析结果直接发布到PR上

### 1.3 设计原则

- **准确性优先**：通过专家知识库和上下文增强减少误报
- **上下文理解**：提供充足的代码上下文，避免断章取义
- **可控可配置**：用户可控制分析维度、严重级别、模型选择
- **国产模型优先**：支持DeepSeek、Qwen、GLM等国产模型
- **模块化可扩展**：各模块独立，便于后续扩展

## 2. 系统架构

### 2.1 架构选型

采用**模块化管道架构**，将系统拆分为独立模块，通过管道连接数据流。

选择理由：
- 模块解耦可独立测试
- 支持大PR智能分片
- 上下文理解更准确
- 易扩展新分析维度
- 天然支持多模型切换

### 2.2 整体架构图

```
用户输入 PR URL
       │
       ▼
┌─────────────┐
│  CLI 入口层  │  (Typer) - 解析参数、调度流程
└──────┬──────┘
       │
       ▼
┌─────────────┐
│  PR 获取层   │  (PyGithub) - 获取PR元数据、diff、文件内容
└──────┬──────┘
       │
       ▼
┌─────────────┐
│  Diff 解析层  │  - 解析unified diff，提取变更块(hunk)
└──────┬──────┘
       │
       ▼
┌─────────────┐
│  上下文构建层  │  - 获取关联文件、函数签名、依赖关系
└──────┬──────┘
       │
       ▼
┌─────────────────────┐
│  AI 分析引擎（核心）  │  - 分片策略、Prompt工程、专家知识库、多维度分析
└──────┬──────────────┘
       │
       ▼
┌─────────────┐
│  结果格式化层  │  - 终端输出(Markdown) / GitHub评论
└──────┬──────┘
       │
       ▼
┌─────────────┐
│  GitHub 回写层 │  - 发布Review评论到PR
└─────────────┘
```

### 2.3 核心数据流

1. **输入**：用户通过CLI指定PR URL
2. **获取**：通过GitHub API获取PR元数据和diff内容
3. **解析**：将unified diff解析为结构化的变更块列表
4. **上下文增强**：对每个变更文件获取相关上下文
5. **AI分析**：将变更块+上下文+专家知识分片发送给AI模型
6. **格式化输出**：将AI返回的结构化结果渲染为终端Markdown或GitHub评论
7. **回写**（可选）：通过GitHub API将分析结果作为PR评论发布

### 2.4 项目结构

```
ai-pr-review/
├── pyproject.toml
├── src/
│   └── ai_pr_review/
│       ├── __init__.py
│       ├── cli.py              # CLI入口
│       ├── config.py           # 配置管理
│       ├── github_client.py    # GitHub API封装
│       ├── diff_parser.py      # Diff解析
│       ├── context_builder.py  # 上下文构建
│       ├── analyzer.py         # AI分析引擎
│       ├── prompt_templates.py # Prompt模板
│       ├── expert_knowledge.py # 专家知识库
│       ├── formatter.py        # 结果格式化
│       ├── commenter.py        # GitHub评论回写
│       └── models.py           # 数据模型
├── tests/
│   ├── test_diff_parser.py
│   ├── test_context_builder.py
│   ├── test_analyzer.py
│   └── fixtures/
└── README.md
```

## 3. 核心模块详细设计

### 3.1 CLI入口层 (`cli.py`)

**技术选型**：Typer（基于Click的类型安全CLI框架）

**命令接口**：

```bash
# 基本用法
ai-pr-review https://github.com/owner/repo/pull/123

# 指定模型
ai-pr-review https://github.com/owner/repo/pull/123 --model deepseek-chat

# 只输出总结，不回写GitHub
ai-pr-review https://github.com/owner/repo/pull/123 --no-comment

# 指定最低严重级别
ai-pr-review https://github.com/owner/repo/pull/123 --severity medium

# 只分析特定维度
ai-pr-review https://github.com/owner/repo/pull/123 --focus risk,security

# 流式输出
ai-pr-review https://github.com/owner/repo/pull/123 --stream
```

**参数说明**：

| 参数 | 类型 | 默认值 | 说明 |
|------|------|--------|------|
| `pr_url` | str | 必填 | GitHub PR URL |
| `--model` | str | 配置文件值 | AI模型名称 |
| `--no-comment` | flag | False | 不回写GitHub评论 |
| `--severity` | str | low | 最低展示严重级别 |
| `--focus` | str | 全部 | 分析维度过滤 |
| `--stream` | flag | False | 流式输出 |
| `--config` | str | ~/.ai-pr-review.toml | 配置文件路径 |

### 3.2 配置管理 (`config.py`)

**配置文件格式** (`~/.ai-pr-review.toml`)：

```toml
[github]
token = "ghp_xxx"  # 或通过环境变量 GITHUB_TOKEN

[ai]
provider = "deepseek"  # deepseek / qwen / glm / openai
api_key = "sk-xxx"     # 或通过环境变量 AI_API_KEY
model = "deepseek-chat"
base_url = "https://api.deepseek.com/v1"
max_tokens = 8000
temperature = 0.3

[analysis]
severity_threshold = "low"
skip_patterns = ["*.lock", "*.generated.*", "package-lock.json"]
max_file_size = 50000
context_budget = 6000

[expert]
enabled_experts = ["security", "architecture", "performance", "readability", "testing"]
```

**配置优先级**：CLI参数 > 环境变量 > 配置文件 > 默认值

### 3.3 GitHub客户端 (`github_client.py`)

**职责**：封装所有GitHub API交互

**核心功能**：
- `get_pr_metadata(url)` → PR元数据（标题、描述、作者、分支、标签）
- `get_pr_diff(url)` → PR的完整unified diff
- `get_file_content(url, path, ref)` → 指定文件的完整内容
- `create_review_comment(url, path, line, body)` → 创建行级Review评论
- `create_pr_comment(url, body)` → 创建PR级别评论

**关键设计**：
- 使用PyGithub库，支持GitHub Token认证
- 实现速率限制感知，自动处理API rate limit
- 支持公开仓库和私有仓库（需Token权限）
- URL解析：从PR URL中提取owner/repo/number

### 3.4 Diff解析器 (`diff_parser.py`)

**职责**：将原始unified diff转换为结构化数据

**输出数据模型**：

```python
@dataclass
class DiffHunk:
    file_path: str
    change_type: str  # added / modified / deleted / renamed
    old_start: int
    old_count: int
    new_start: int
    new_count: int
    content: str      # 变更的具体内容
    header: str       # @@ ... @@ 行

@dataclass
class FileDiff:
    path: str
    change_type: str
    hunks: list[DiffHunk]
    additions: int
    deletions: int
    is_binary: bool
    is_generated: bool  # 自动生成文件标记

@dataclass
class ParsedDiff:
    files: list[FileDiff]
    total_additions: int
    total_deletions: int
    stats: dict
```

**关键设计**：
- 支持二进制文件检测和跳过
- 支持大文件分块（超过阈值的文件只分析变更部分+上下文）
- 识别自动生成文件（package-lock.json、*.generated.*等）并标记为低优先级
- 识别文件变更类型（新增/修改/删除/重命名）

### 3.5 上下文构建器 (`context_builder.py`)

**职责**：为AI分析提供足够的代码上下文，减少误报

**三层上下文获取**：

1. **PR元数据层**（必选）
   - PR标题、描述、标签 → 理解变更意图
   - base/head分支名 → 理解分支策略
   - 关联issue内容 → 理解需求背景

2. **代码变更层**（必选）
   - Unified diff → 精确的变更内容
   - 变更文件列表 → 变更影响范围
   - 增删行统计 → 变更规模感知

3. **深度上下文层**（按需获取）
   - 变更文件完整内容 → 理解代码结构
   - 被修改函数的完整定义 → 理解函数逻辑
   - import语句和类型定义 → 理解依赖关系
   - 调用方/被调用方 → 理解影响传播

**上下文预算管理**：

```
总Token预算 = 模型上下文窗口 - 输出预留(2048) - Prompt模板(1024)
可用Token = 总预算 - PR元数据 - 代码变更
剩余Token → 按优先级分配给深度上下文
```

**智能截断优先级**：
- P0：变更代码本身（不可截断）
- P1：被修改函数的完整定义
- P2：文件头import和类定义
- P3：关联文件和依赖

### 3.6 AI分析引擎 (`analyzer.py`)

**职责**：核心分析逻辑，调用AI模型进行多维度代码审查

**分片策略**：
- 小PR（< 2000 tokens diff）：整体分析
- 中PR（2000-8000 tokens）：按文件分组分析
- 大PR（> 8000 tokens）：按文件分组 + 每组内按hunk分片，最后做汇总分析

**多维度分析**：

| 维度 | 分析内容 | 输出格式 |
|------|---------|---------|
| 变更总结 | 变更意图、影响范围、关键修改点 | 结构化摘要 |
| 风险识别 | 潜在Bug、安全漏洞、性能问题、并发风险 | 风险列表(含严重级别) |
| 代码质量 | 可读性、命名规范、设计模式、最佳实践 | 改进建议列表 |
| 测试覆盖 | 是否需要新增测试、测试用例建议 | 测试建议列表 |

**模型调用**：
- 使用OpenAI兼容API格式，通过配置切换DeepSeek/Qwen/GLM
- 支持流式输出（SSE），实时显示分析进度
- 实现重试机制（指数退避）和错误处理

**统一AI Provider接口**：

```python
class AIProvider(ABC):
    @abstractmethod
    async def analyze(self, prompt: str, stream: bool = False) -> str:
        ...

class OpenAICompatibleProvider(AIProvider):
    def __init__(self, base_url: str, api_key: str, model: str):
        ...
```

### 3.7 专家知识库 (`expert_knowledge.py`)

**核心理念**：将Google、GitHub、OWASP等业界成熟的代码审查最佳实践结构化为知识库，在分析时动态注入到Prompt中。

**专家类型**：

#### 安全审查专家 (security)
- **知识来源**：OWASP Code Review Guide、CWE Top 25
- **Checklist**：SQL注入、XSS、认证/授权、敏感数据、加密算法等
- **Red Flags**：eval()/exec()调用、直接拼接SQL、未验证的用户输入、硬编码密钥

#### 架构审查专家 (architecture)
- **知识来源**：Google Code Review Guidelines、Clean Architecture
- **Checklist**：单一职责、耦合度、抽象层次、接口设计
- **Red Flags**：God Class/Function、循环依赖、跨层直接调用

#### 性能审查专家 (performance)
- **知识来源**：性能优化最佳实践
- **Checklist**：N+1查询、内存泄漏、算法复杂度、并发安全
- **Red Flags**：循环内数据库/网络调用、未关闭资源、全局可变状态、无锁并发修改

#### 可读性审查专家 (readability)
- **知识来源**：代码大全、Google Style Guides
- **Checklist**：命名表达意图、函数长度、嵌套深度、风格一致性
- **Red Flags**：超长函数、深层嵌套、魔法数字、过度缩写

#### 测试审查专家 (testing)
- **知识来源**：测试最佳实践
- **Checklist**：覆盖率、边界条件、测试隔离、Mock合理性
- **Red Flags**：无测试的业务逻辑、仅测试正常路径、硬编码外部依赖

**动态专家选择策略**：
- 检测到SQL/数据库相关变更 → 注入 security + performance 专家
- 检测到新API端点 → 注入 security + architecture 专家
- 检测到认证/授权相关 → 强制注入 security 专家
- 默认 → 注入 readability + architecture 专家

### 3.8 Prompt模板 (`prompt_templates.py`)

**Prompt结构**：

```
系统角色定义 → 你是一位代码审查专家团队的组织者
├── 专家知识注入 → 根据变更类型，注入1-3个专家的checklist和red_flags
├── 上下文注入 → PR信息、变更代码、关联上下文
├── 分析指令 → 按维度+专家checklist逐项分析
├── 输出格式约束 → 严格JSON Schema（含置信度和专家标签）
└── 质量控制 → 每个发现必须关联具体代码行，给出修复示例
```

**关键Prompt策略**：
1. **角色锚定**：明确模型角色为"代码审查专家"，而非通用助手
2. **上下文窗口**：在prompt中提供变更前后的代码对比，而非仅提供diff
3. **示例引导**：在prompt中包含1-2个高质量review示例（few-shot）
4. **否定约束**：明确告知"不要报告风格偏好问题"、"不要报告缺少注释等低价值建议"
5. **专家清单绑定**：AI的每个发现必须能映射到专家checklist中的某一项

**输出JSON Schema**：

```json
{
  "summary": {
    "intent": "string",
    "scope": "string",
    "key_changes": ["string"]
  },
  "findings": [
    {
      "type": "risk|quality|testing",
      "severity": "high|medium|low",
      "confidence": 1-5,
      "expert": "security|architecture|performance|readability|testing",
      "file": "string",
      "line": 0,
      "title": "string",
      "description": "string",
      "suggestion": "string",
      "code_snippet": "string"
    }
  ],
  "suggestions": [
    {
      "category": "string",
      "priority": "high|medium|low",
      "description": "string",
      "example": "string"
    }
  ]
}
```

### 3.9 结果格式化 (`formatter.py`)

**终端输出格式**：

```
📋 PR 变更总结
━━━━━━━━━━━━━━━━━━━━━━━━━━
本次PR修改了5个文件，主要变更：
- 新增用户认证模块 (auth.py)
- 修复了SQL注入漏洞 (db.py:L45)
- ...

⚠️  风险识别 (3项)
━━━━━━━━━━━━━━━━━━━━━━━━━━
🔴 [高] db.py:L45 - 潜在SQL注入 [security]
   参数未经过滤直接拼接SQL语句
   建议：使用参数化查询

🟡 [中] auth.py:L78 - Token过期处理缺失 [security]
   ...

💡 Review 建议 (2项)
━━━━━━━━━━━━━━━━━━━━━━━━━━
...
```

**GitHub评论格式**：使用Markdown，支持行级定位（通过GitHub Review Comments API）

### 3.10 GitHub评论回写 (`commenter.py`)

**职责**：将分析结果发布到GitHub PR

**回写策略**：
- PR级别评论：发布变更总结和总体建议
- 行级Review Comment：对每个具体发现，在对应代码行发布评论
- 使用GitHub Pull Request Review API创建正式Review（approve/request changes/comment）

**安全控制**：
- 默认以"comment"类型发布（不直接approve或request changes）
- 用户可通过 `--review-action` 参数指定（comment/approve/request-changes）

## 4. 误报与漏报控制

### 4.1 误报控制（减少假阳性）

1. **置信度过滤**：要求AI对每个发现给出1-5置信度评分，默认只展示3分以上
2. **专家清单校验**：AI的每个发现必须能映射到专家checklist中的某一项，避免泛泛而谈
3. **代码行锚定**：要求每个发现必须关联到具体的代码行号，无法定位的发现降级处理
4. **上下文增强**：通过提供更完整的上下文，减少因信息不足导致的误判
5. **可配置阈值**：用户可通过 `--severity` 参数控制展示的最低严重级别

### 4.2 漏报控制（减少假阴性）

1. **分专家维度**：不同专家关注不同维度，覆盖面更广
2. **Red Flags扫描**：强制检查red_flags清单中的高风险模式
3. **强制安全审查**：对安全相关变更（认证、加密、SQL、文件操作）强制启用security专家
4. **清单式校验**：分析完成后，用专家checklist做反向校验，确认是否遗漏

## 5. 模型选择设计

### 5.1 支持的国产模型

| 模型 | API端点 | 优势 | 适用场景 |
|------|---------|------|---------|
| DeepSeek-V3 | api.deepseek.com | 代码理解能力强，性价比高 | 默认推荐 |
| Qwen2.5-Coder | dashscope.aliyuncs.com | 阿里云生态，中文理解好 | 中文项目 |
| GLM-4 | open.bigmodel.cn | 智谱生态，综合能力强 | 通用场景 |

### 5.2 统一接口设计

- 所有模型使用OpenAI兼容API格式（`/v1/chat/completions`）
- 通过配置文件的 `base_url` + `api_key` + `model` 三要素切换
- 实现统一的 `AIProvider` 抽象类，各模型只需配置参数

### 5.3 模型选择考量

- **准确性**：DeepSeek-V3在代码任务上表现接近GPT-4，性价比最优
- **上下文窗口**：DeepSeek-V3支持64K上下文，可处理较大PR
- **响应速度**：国产模型API延迟通常低于海外模型
- **成本控制**：DeepSeek-V3价格约为GPT-4的1/10，适合频繁使用

## 6. 上下文获取方式

### 6.1 获取策略

1. **PR元数据层**（必选）：PR标题、描述、标签、分支、关联issue
2. **代码变更层**（必选）：Unified diff、变更文件列表、增删行统计
3. **深度上下文层**（按需）：文件完整内容、函数定义、import语句、调用关系

### 6.2 Token预算管理

```
总Token预算 = 模型上下文窗口 - 输出预留(2048) - Prompt模板(1024)
可用Token = 总预算 - PR元数据 - 代码变更
剩余Token → 按优先级分配给深度上下文
```

## 7. 未来扩展方向

1. **GitHub App集成**：从CLI演进为GitHub App，PR创建时自动触发Review
2. **增量分析**：对同一PR的多次commit，只分析增量变更
3. **团队规范学习**：从团队历史Review评论中学习团队特定的代码规范
4. **多语言深度支持**：针对不同编程语言的AST级深度分析
5. **Review报告持久化**：将分析结果存储，支持历史趋势分析
6. **IDE插件**：VS Code / JetBrains插件，在IDE内直接查看Review结果
7. **自定义专家**：用户可定义自己的专家checklist和red_flags
8. **Agent架构演进**：从管道架构演进为Agent架构，让AI自主决定分析策略

## 8. 技术栈

| 组件 | 技术选型 | 说明 |
|------|---------|------|
| 语言 | Python 3.11+ | 生态成熟，AI SDK支持广泛 |
| CLI框架 | Typer | 类型安全，自动生成帮助文档 |
| GitHub API | PyGithub | 成熟的GitHub API封装 |
| AI调用 | OpenAI Python SDK | 兼容国产模型API格式 |
| 配置管理 | tomllib + dynaconf | TOML配置文件 + 环境变量 |
| 异步 | asyncio + httpx | 异步HTTP调用，提升并发性能 |
| 测试 | pytest + pytest-asyncio | 异步测试支持 |
| 包管理 | uv / pip | 现代Python包管理 |
