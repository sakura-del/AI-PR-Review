# AI PR Review 助手

一个基于国产大模型的 Pull Request 智能代码审查工具，帮助开发者提升代码质量。

## ✨ 功能特性

- 📋 **PR 变更总结** - 自动生成简洁易懂的 PR 变更摘要
- ⚠️  **风险识别** - 精准定位代码中的潜在 bug、安全漏洞和性能问题
- 💡 **智能建议** - 提供具体的代码改进方案和最佳实践
- 📝 **GitHub 回写** - 自动将分析结果作为评论发布到 PR
- 🔬 **专家知识库** - 内置安全、架构、性能、可读性等专家评审标准
- 🔧 **灵活配置** - 支持多种国产大模型（DeepSeek、Qwen、GLM等）

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

创建 `.env` 文件（参考 `.env.example`）：

```bash
# GitHub 配置
GITHUB_TOKEN=ghp_your_github_token

# 模型配置（默认使用 DeepSeek）
AI_API_KEY=sk_your_deepseek_api_key
AI_BASE_URL=https://api.deepseek.com/v1
AI_MODEL=deepseek-chat
```

### 使用

```bash
# 模式1: 仅终端输出，不回写 GitHub
ai-pr-review https://github.com/owner/repo/pull/123 --no-comment

# 模式2: 分析并回写 GitHub 评论
ai-pr-review https://github.com/owner/repo/pull/123

# 模式3: 只展示中高风险问题
ai-pr-review https://github.com/owner/repo/pull/123 --severity medium --no-comment

# 模式4: 只关注安全问题
ai-pr-review https://github.com/owner/repo/pull/123 --focus risk,security --no-comment
```

## 📁 项目结构

```
AI-PR-Review/
├── src/
│   └── ai_pr_review/
│       ├── __init__.py          # 包初始化
│       ├── cli.py               # CLI 入口
│       ├── config.py            # 配置管理
│       ├── github_client.py     # GitHub API 封装
│       ├── diff_parser.py       # Diff 解析器
│       ├── context_builder.py   # 上下文构建
│       ├── expert_knowledge.py  # 专家知识库
│       ├── prompt_templates.py  # Prompt 模板
│       ├── analyzer.py          # AI 分析引擎
│       ├── formatter.py         # 结果格式化
│       └── models.py            # 数据模型
├── tests/                       # 单元测试
├── docs/                        # 文档
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
| HTTP 请求 | Requests |
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
5. **专家知识** - 根据变更类型选择对应专家
6. **AI 分析** - 调用大模型进行多维度分析
7. **格式化** - 终端输出或 GitHub Markdown
8. **GitHub 回写** - 发布评论到 PR

### 模型选择策略

支持多种国产大模型，通过统一的 OpenAI 兼容接口：

| 模型 | API 端点 | 说明 |
|------|-----------|------|
| DeepSeek | https://api.deepseek.com/v1 | 默认推荐，代码能力强 |
| Qwen (阿里云) | https://dashscope.aliyuncs.com/compatible-mode/v1 | 适合中文项目 |
| GLM (智谱) | https://open.bigmodel.cn/api/paas/v4 | 综合能力均衡 |

### 专家知识库

内置5个专家知识领域，基于行业最佳实践：

| 专家 | 检查点 |
|------|--------|
| **安全审查专家** | SQL注入、XSS、认证授权、敏感数据、加密、命令注入、CSRF、不安全反序列化、信息泄露 |
| **架构审查专家** | 单一职责、耦合度、抽象层次、接口设计、依赖注入、错误处理、可扩展性 |
| **性能审查专家** | N+1查询、内存泄漏、算法复杂度、并发安全、缓存策略、批量操作 |
| **可读性审查专家** | 命名清晰、函数长度、复杂度、一致性、注释、重复代码、魔法值 |
| **测试审查专家** | 覆盖率、边界条件、测试隔离、Mock合理性、命名、断言质量 |

## 🎯 核心功能实现

### 误报与漏报控制

- **置信度过滤** - 要求 AI 给出 1-5 置信度评分，默认只展示 3 分以上
- **专家清单校验** - AI 发现需匹配专家 checklist 条目
- **代码行锚定** - 每个发现必须关联到具体代码行
- **上下文增强** - 提供充分的代码上下文减少误判

### Token 预算管理

- 按优先级分配上下文资源
- 变更代码 > 函数定义 > 文件头 > 关联代码
- 防止 token 超限导致请求失败

## 🔄 未来扩展方向

1. **GitHub App 集成** - PR 创建时自动触发审查
2. **增量分析** - 多次提交时仅分析增量变更
3. **团队规范学习** - 从历史 PR 评论中学习团队特定标准
4. **IDE 插件** - VS Code / JetBrains 插件，在 IDE 内直接查看
5. **自定义专家** - 用户自定义审查标准和 checklist

## 📚 相关文档

- 设计文档：[docs/superpowers/specs/2026-05-29-ai-pr-review-design.md](docs/superpowers/specs/2026-05-29-ai-pr-review-design.md)
- 实现计划：[docs/superpowers/plans/2026-05-29-ai-pr-review-plan.md](docs/superpowers/plans/2026-05-29-ai-pr-review-plan.md)

## 🎬 Demo 视频

- 视频链接：（待上传到 bilibili/云盘）
- 演示内容：
  - 工具安装和配置
  - 4种使用模式的演示
  - 真实 PR 的分析结果
  - GitHub 评论回写效果

## 📝 许可证

- 版权所有 © 2026
- 本作品仅用于比赛目的，开源协议待定

## 👥 作者

- sakura-del - 全栈开发

---

**注意**：本项目为比赛作品，仅供学习和评审使用。
