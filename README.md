# AI PR Review 助手

一个基于国产大模型的 Pull Request 智能代码审查工具，帮助开发者提升代码质量。

## ✨ 功能特性

- 📋 **PR 变更总结** - 自动生成简洁易懂的 PR 变更摘要
- ⚠️  **风险识别** - 精准定位代码中的潜在 bug、安全漏洞和性能问题（P0-P3 严重级别）
- 💡 **智能建议** - 提供具体的代码改进方案和最佳实践
- 📝 **GitHub 回写** - 自动将分析结果作为行级评论发布到 PR
- 🔬 **专家知识库** - 内置安全、架构、性能、可读性等专家评审标准
- 🔧 **灵活配置** - 支持多种国产大模型（DeepSeek、Qwen、GLM等）
- 🏷️ **自动标签** - 根据分析结果自动标注 `ai-review:high-risk` 等标签
- 📊 **流式输出** - 打字机效果实时展示分析过程
- 📈 **历史记录** - 本地保存分析历史，支持按仓库/PR 查询
- 🧩 **大 PR 分片** - 超 20 文件或 5000 行自动分片并发分析
- 📐 **Token 预算** - 智能上下文裁剪，优化 token 消耗
- 🔄 **增量分析** - 仅分析自上次审查以来的新增变更，大幅节省 token
- ⚙️ **项目配置** - `.ai-pr-review.yaml` 支持忽略路径和自定义规则
- 🧠 **团队规范学习** - 从历史 PR 评论中学习团队审查模式，减少误报

## 🚀 快速开始

### 前置要求

- Python 3.11+
- GitHub Token（用于访问 PR 信息）
- DeepSeek/Qwen/GLM 等国产大模型的 API Key

### 安装

```bash
# 克隆仓库
git clone https://github.com/sakura-del/AI-PR-Review.git
cd AI-PR-Review

# 安装依赖
pip install -e ".[dev]"
```

### 配置

创建 `.env` 文件（参考 `.env.example`），支持三套模型独立配置：

```bash
# GitHub 配置
GITHUB_TOKEN=ghp_your_github_token

# ===== DeepSeek 模型配置 =====
DEEPSEEK_API_KEY=sk-your_deepseek_api_key
DEEPSEEK_BASE_URL=https://api.deepseek.com/v1
DEEPSEEK_MODEL=deepseek-chat

# ===== Qwen (阿里云) 模型配置 =====
QWEN_API_KEY=sk-your_dashscope_api_key
QWEN_BASE_URL=https://dashscope.aliyuncs.com/compatible-mode/v1
QWEN_MODEL=qwen-plus

# ===== GLM (智谱) 模型配置 =====
GLM_API_KEY=your_zhipu_api_key
GLM_BASE_URL=https://open.bigmodel.cn/api/paas/v4
GLM_MODEL=glm-4
```

> 兼容旧版：如果未配置上述预设，仍可使用 `AI_API_KEY` / `AI_BASE_URL` / `AI_MODEL` 通用键名。

### 使用

```bash
# 基础分析 + 终端输出 (Rich UI)
ai-pr-review review https://github.com/owner/repo/pull/123 --no-comment

# 流式输出（打字机效果）
ai-pr-review review https://github.com/owner/repo/pull/123 --stream --no-comment

# 分析并回写 GitHub 评论（含行级评论）
ai-pr-review review https://github.com/owner/repo/pull/123

# 只展示中高风险问题
ai-pr-review review https://github.com/owner/repo/pull/123 --severity medium --no-comment

# 只关注安全问题
ai-pr-review review https://github.com/owner/repo/pull/123 --focus risk,security --no-comment

# 指定模型
# 切换到 DeepSeek
ai-pr-review review https://github.com/owner/repo/pull/123 --model deepseek-chat --no-comment

# 切换到 Qwen
ai-pr-review review https://github.com/owner/repo/pull/123 --model qwen-plus --no-comment

# 切换到 GLM
ai-pr-review review https://github.com/owner/repo/pull/123 --model glm-4 --no-comment

# 设置 GitHub Review 动作（COMMENT/APPROVE/REQUEST_CHANGES）
ai-pr-review review https://github.com/owner/repo/pull/123 --review-action REQUEST_CHANGES

# 增量分析（仅分析自上次审查以来的新增变更，大幅节省 token）
ai-pr-review review https://github.com/owner/repo/pull/123 --incremental --no-comment

# 学习团队审查模式（从历史 PR 评论中提取规则）
ai-pr-review learn https://github.com/owner/repo/pull/123

# 强制重新学习（忽略缓存）
ai-pr-review learn https://github.com/owner/repo/pull/123 --force

# 查看历史分析记录
ai-pr-review history
ai-pr-review history --limit 10
```

### 命令行参数

| 参数 | 缩写 | 说明 | 默认值 |
|------|------|------|--------|
| `--model` | `-m` | AI 模型（deepseek/qwen/glm 或完整模型名） | deepseek-chat |
| `--no-comment` | | 不回写 GitHub 评论 | false |
| `--severity` | `-s` | 最低严重级别过滤 (low/medium/high) | low |
| `--focus` | `-f` | 分析维度 (risk,quality,testing,security) | 全部 |
| `--stream` | | 流式输出（打字机效果） | false |
| `--config` | `-c` | 配置文件路径 | 自动检测 |
| `--review-action` | | GitHub Review 动作 | COMMENT |
| `--incremental` | `-i` | 增量分析（仅分析自上次审查以来的新增变更） | false |
| `--limit` | `-n` | 历史记录显示数量 (history 子命令) | 20 |
| `--max-prs` | | 学习时分析的最大 PR 数量 (learn 子命令) | 20 |
| `--force` | `-f` | 强制重新学习，忽略缓存 (learn 子命令) | false |

## 📁 项目结构

```
AI-PR-Review/
├── src/
│   └── ai_pr_review/
│       ├── __init__.py          # 包初始化
│       ├── cli.py               # CLI 入口（Typer）
│       ├── config.py            # 配置管理 + 项目级配置
│       ├── github_client.py     # GitHub API 封装
│       ├── diff_parser.py       # Unified diff 解析器
│       ├── context_builder.py   # Token 预算管理 + 上下文构建
│       ├── expert_knowledge.py  # 5 专家 Profile + 动态选择
│       ├── prompt_templates.py  # 系统提示 + JSON Schema + Few-shot
│       ├── analyzer.py          # 异步 AI 调用 + 分片分析 + 流式输出
│       ├── formatter.py         # 终端输出 + Rich UI + GitHub Markdown
│       ├── commenter.py         # 行级评论 + 标签自动标注
│       ├── history.py           # 分析历史记录管理
│       ├── incremental.py       # 增量分析模块
│       ├── team_learner.py      # 团队规范学习（AI 模式提取）
│       ├── team_rules.py        # 团队规则存储与合并
│       └── models.py            # 数据模型
├── tests/                       # 单元测试（123 个测试用例）
├── docs/                        # 文档
├── .ai-pr-review.yaml           # 项目级自定义配置
├── .env.example                 # 环境变量示例
├── .gitignore
└── pyproject.toml               # 项目配置
```

## 🛠️ 技术栈

| 组件 | 技术 |
|------|------|
| 语言 | Python 3.11+ |
| CLI | Typer (基于 Click) |
| GitHub API | PyGithub |
| AI API | OpenAI Python SDK (兼容国产模型) |
| 终端输出 | Rich |
| HTTP 请求 | Requests + httpx |
| Token 计算 | Tiktoken |
| 环境管理 | python-dotenv |

## 📦 依赖列表

- `typer>=0.12.0` - 现代 CLI 框架
- `pygithub>=2.3.0` - GitHub API 客户端
- `openai>=1.30.0` - OpenAI SDK（兼容国产模型）
- `httpx>=0.27.0` - 异步 HTTP 客户端
- `rich>=13.7.0` - 终端美化库
- `tiktoken>=0.7.0` - Token 计数工具
- `python-dotenv>=1.0.0` - 环境变量管理
- `requests>=2.31.0` - HTTP 客户端

## 🧪 运行测试

```bash
# 运行所有单元测试
pytest tests/ -v

# 运行测试并显示覆盖率
pytest tests/ -v --cov=ai_pr_review
```

## 📄 设计思路

### 核心架构

采用**模块化管道架构**，数据从输入到输出经过多个独立模块：

1. **CLI 入口** - 解析命令行参数
2. **GitHub 客户端** - 获取 PR 元数据和 Diff
3. **Diff 解析器** - 解析 unified diff 为结构化数据
4. **上下文构建** - 补充代码上下文和 Token 预算管理
5. **专家知识** - 根据变更类型动态选择对应专家（最多 3 个）
6. **AI 分析** - 调用大模型进行多维度分析
7. **格式化** - 终端 Rich UI 或 GitHub Markdown
8. **GitHub 回写** - 行级评论 + 标签自动标注

### P0-P3 严重级别

借鉴业界代码评审最佳实践，采用 4 级严重级别：

| 级别 | 名称 | 说明 | 操作 |
|------|------|------|------|
| **P0** | Critical | 安全漏洞、数据丢失风险、正确性 bug | 必须阻止合并 |
| **P1** | High | 逻辑错误、SOLID 违规、性能退化 | 合并前修复 |
| **P2** | Medium | 代码味道、可维护性问题 | 建议修复 |
| **P3** | Low | 风格、命名、可选优化 | 可选改进 |

### 模型选择策略

支持多种国产大模型，通过统一的 OpenAI 兼容接口。`--model` 参数自动识别 provider 并切换整套配置（API Key + Base URL + 模型名）：

| 模型 | --model 参数 | API 端点 | .env 键名前缀 |
|------|-------------|----------|--------------|
| DeepSeek | `deepseek-chat` | https://api.deepseek.com/v1 | `DEEPSEEK_` |
| Qwen (阿里云) | `qwen-plus` | https://dashscope.aliyuncs.com/compatible-mode/v1 | `QWEN_` |
| GLM (智谱) | `glm-4` | https://open.bigmodel.cn/api/paas/v4 | `GLM_` |

切换示例：

```bash
# 使用 DeepSeek（默认）
ai-pr-review review https://github.com/owner/repo/pull/123 --model deepseek-chat --no-comment

# 切换到 Qwen
ai-pr-review review https://github.com/owner/repo/pull/123 --model qwen-plus --no-comment

# 切换到 GLM
ai-pr-review review https://github.com/owner/repo/pull/123 --model glm-4 --no-comment
```

> 识别规则：根据模型名前缀自动匹配 provider（如 `deepseek-chat` → `deepseek`，`qwen-plus` → `qwen`），然后从 `.env` 读取对应的 `DEEPSEEK_API_KEY` / `QWEN_API_KEY` / `GLM_API_KEY` 及其 Base URL。

### 专家知识库

内置 5 个专家知识领域，根据 PR 变更内容**动态选择**最相关的 3 个专家：

| 专家 | 检查点 |
|------|--------|
| **安全审查** | SQL注入、XSS、认证授权、敏感数据、加密、命令注入、CSRF、反序列化、信息泄露 |
| **架构审查** | 单一职责、耦合度、抽象层次、接口设计、依赖注入、错误处理、可扩展性 |
| **性能审查** | N+1查询、内存泄漏、算法复杂度、并发安全、缓存策略、批量操作 |
| **可读性审查** | 命名清晰、函数长度、复杂度、一致性、注释、重复代码、魔法值 |
| **测试审查** | 覆盖率、边界条件、测试隔离、Mock合理性、命名、断言质量 |

### 大 PR 分片分析

当 PR 超过阈值（>20 文件或 >5000 行变更）时自动触发分片：

- 将文件均匀拆分为 3 个分片
- 每个分片独立分析（并发执行）
- 合并结果时自动去重和排序

### Token 预算管理

智能上下文裁剪策略，优化 token 消耗：

- 按优先级分配上下文资源：变更代码 > 函数定义 > 文件头 > 关联代码
- diff 内容按文件优先级裁剪，超出预算时自动截断并提示剩余文件数
- 专家 checklist 精简为关键词格式，减少约 40% token 消耗
- 防止 token 超限导致请求失败

### 项目级自定义配置

在项目根目录创建 `.ai-pr-review.yaml`：

```yaml
ignore_paths:
  - "*.lock"
  - "vendor/"
  - "node_modules/"
  - "__pycache__/"
custom_rules:
  - "禁止使用 any 类型"
  - "所有公共函数必须有类型注解"
max_context_files: 10
enabled_experts:
  - security
  - architecture

# 覆盖/扩展内置专家的 checklist 和 red_flags
expert_overrides:
  security:
    checklist_append:              # 追加到原有 checklist
      - "内部API必须使用mTLS认证"
      - "禁止在日志中记录PII数据"
    red_flags_append:
      - "未经审批的外部服务调用"
  readability:
    checklist_replace:             # 完全替换原有 checklist
      - "遵循公司编码规范v3.2"
      - "所有public方法必须有文档注释"

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

# 团队规范学习配置
team_learning:
  enabled: true           # 启用团队规范学习
  max_prs: 20             # 最多分析多少个历史 PR
  max_comments: 100       # 最多提取多少条评论
  min_rule_weight: 0.3    # 最低规则权重阈值
  auto_learn: false       # 是否在每次审查后自动学习
  rule_ttl_days: 30       # 学习规则的过期天数
```

**配置说明**：

| 字段 | 说明 |
|------|------|
| `expert_overrides.<key>.checklist_append` | 追加到内置专家的 checklist |
| `expert_overrides.<key>.checklist_replace` | 完全替换内置专家的 checklist |
| `expert_overrides.<key>.red_flags_append` | 追加到内置专家的 red_flags |
| `expert_overrides.<key>.red_flags_replace` | 完全替换内置专家的 red_flags |
| `custom_experts.<key>` | 添加全新自定义专家（key 为标识符） |
| `team_learning.enabled` | 启用团队规范学习 |
| `team_learning.max_prs` | 学习时分析的最大 PR 数量 |
| `team_learning.min_rule_weight` | 最低规则权重阈值（低于此值的规则被过滤） |
| `team_learning.rule_ttl_days` | 学习规则过期天数（过期后需重新学习） |

## 🎯 核心功能实现

### 误报与漏报控制

- **置信度过滤** - 要求 AI 给出 1-5 置信度评分，默认只展示 3 分以上
- **专家清单校验** - AI 发现需匹配专家 checklist 条目
- **代码行锚定** - 每个发现必须关联到具体代码行
- **上下文增强** - 提供充分的代码上下文减少误判

### 行级评论精确回写

使用 PyGithub `create_review(comments=...)` API 一次性提交所有行级评论：

- 每个发现精确定位到文件和行号
- 评论包含严重级别、问题描述和修复建议
- 支持 COMMENT / APPROVE / REQUEST_CHANGES 三种 Review 动作

### 自动标签标注

根据分析结果自动添加标签：

| 标签 | 触发条件 |
|------|----------|
| `ai-review:high-risk` | 存在高严重级别发现 |
| `ai-review:security` | 存在安全相关发现 |
| `ai-review:performance` | 存在性能相关发现 |
| `ai-review:needs-review` | 存在任何发现 |

### 团队规范学习

从仓库历史 PR 评论中提取团队审查模式，自动生成个性化审查规则：

**工作流程**：
1. `ai-pr-review learn <url>` 采集仓库最近 N 个 PR 的评论
2. AI 分析评论内容，提取团队反复关注的审查规则
3. 规则持久化存储到本地（`~/.ai-pr-review/team_rules/`）
4. 后续 `review` 命令自动加载团队规则，注入分析 prompt

**规则权重系统**：
- 学习规则权重由出现频率决定（0.3-2.0）
- 手动规则权重固定为 1.5（高于学习规则）
- 低于 `min_rule_weight` 的规则自动过滤
- 规则按权重排序，高权重规则优先注入

**规则过期机制**：
- 学习规则有 TTL（默认 30 天）
- 过期后需重新 `learn` 以更新
- 团队规范演变后不会用过时规则影响审查

## 🔄 未来扩展方向

1. **GitHub App 集成** - PR 创建时自动触发审查
2. **IDE 插件** - VS Code / JetBrains 插件，在 IDE 内直接查看

## 📚 相关文档

- 设计文档：[docs/superpowers/specs/2026-05-29-ai-pr-review-design.md](docs/superpowers/specs/2026-05-29-ai-pr-review-design.md)
- 实现计划：[docs/superpowers/plans/2026-05-29-ai-pr-review-plan.md](docs/superpowers/plans/2026-05-29-ai-pr-review-plan.md)

## 🎬 Demo 视频

- 视频链接：（待上传到 bilibili/云盘）
- 演示内容：
  - 工具安装和配置
  - 多种使用模式的演示
  - 真实 PR 的分析结果
  - GitHub 评论回写效果

## 📝 许可证

- 版权所有 © 2026
- 本作品仅用于比赛目的，开源协议待定

## 👥 作者

- sakura-del - 全栈开发

---

**注意**：本项目为比赛作品，仅供学习和评审使用。
