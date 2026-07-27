# 生产化加固 + 集成体验优化 Spec

## Why

项目已完成五阶段功能演进（445 测试通过，覆盖 CLI/Webhook/API/多平台/Dashboard/多 Agent/RAG/影响图），但在生产环境部署与多入口集成时存在三类痛点：

1. **缺乏可观测性** — 无 metrics 收集、无结构化日志、无 tracing，线上问题难以定位
2. **缺乏限流降级** — AI 调用仅靠单点重试（3 次指数退避），无全局限流、无降级策略，突发流量会击穿 AI 配额
3. **配置分散且无校验** — 全局 `~/.ai-pr-review.toml` 与项目级 `.ai-pr-review.yaml` 双轨制但缺乏统一入口，无效配置只在运行时报错；CLI/API/Webhook 三种入口的配置管理割裂

本变更聚焦"生产化加固 + 集成体验优化"，让项目达到生产级稳定性，并提供统一的配置管理入口。

## What Changes

### 可观测性
- 新增 `metrics.py`：计数器（请求数/失败数）、直方图（耗时分布）、仪表（当前并发数）
- 新增 `structured_logging.py`：JSON 格式结构化日志，支持 `--log-format json` 切换
- 在 `analyzer.py` / `api_server.py` / `webhook.py` 关键路径埋点

### 限流降级
- 新增 `rate_limiter.py`：基于 `asyncio.Semaphore` + token bucket 的全局限流器
- 新增 `degradation.py`：降级策略（AI 不可用时返回缓存/简化分析/空结果）
- `analyzer.py._call_ai` 接入限流器与降级策略
- CLI 新增 `--rate-limit` 参数（每秒最大 AI 调用数）

### 配置中心化与校验
- 重构 `config.py`：新增 `validate_config()` 函数，启动时校验必填项与类型
- 新增 `config_error.py`：统一配置错误类型（`ConfigError`、`MissingRequiredError`、`InvalidValueError`）
- `cli.py` 启动时调用 `validate_config()`，失败时给出明确修复建议

### 集成体验
- CLI 新增 `config` 子命令：`init`（交互式生成配置）、`validate`（校验当前配置）、`show`（展示生效配置，敏感字段脱敏）
- 新增 `.ai-pr-review.example.yaml`：项目级配置示例模板
- 更新 `.env.example`：补充新增环境变量（`LOG_FORMAT`、`RATE_LIMIT`、`METRICS_ENABLED`）

### **BREAKING**
- `load_config()` 在配置无效时由"静默使用默认值"改为"抛出 `ConfigError`"，调用方需捕获处理

## Impact

- **Affected specs**: 无既有 spec 受影响（`fix-large-pr-analysis` 已完成）
- **Affected code**:
  - 新增：`src/ai_pr_review/metrics.py`、`structured_logging.py`、`rate_limiter.py`、`degradation.py`、`config_error.py`
  - 修改：`src/ai_pr_review/config.py`（新增 `validate_config`）、`analyzer.py`（接入限流降级 metrics）、`api_server.py`（接入 metrics 日志）、`webhook.py`（接入 metrics）、`cli.py`（新增 `config` 子命令 + 启动校验）
  - 新增配置：`.ai-pr-review.example.yaml`
  - 修改：`.env.example`、`README.md`

## ADDED Requirements

### Requirement: Metrics 收集

系统 SHALL 在关键路径（AI 调用、PR 审查、Webhook 处理、API 请求）收集以下指标：
- 请求计数器：总数、成功数、失败数
- 耗时直方图：AI 调用耗时、端到端审查耗时
- 并发仪表：当前并发 AI 调用数、当前排队请求数

指标 SHALL 通过 `MetricsRegistry` 单例聚合，CLI `metrics` 子命令可输出 JSON 格式快照。

#### Scenario: AI 调用失败被计数
- **WHEN** AI 调用因网络异常重试 3 次后失败
- **THEN** `ai_calls_total{status="failure"}` 计数器 +1
- **AND** `ai_call_duration_seconds` 直方图记录本次耗时
- **AND** 错误被结构化日志记录（含 pr_url、model、error_type 字段）

#### Scenario: 并发仪表正确反映实时状态
- **WHEN** 多 Agent 并行审查启动 3 个 Agent
- **THEN** `ai_concurrent_current` 仪表值变为 3
- **AND** 任一 Agent 完成后仪表值减为 2

### Requirement: 结构化日志

系统 SHALL 支持两种日志格式：
- `text`（默认）：人类可读的 `[LEVEL] message` 格式
- `json`：单行 JSON，含 `timestamp`、`level`、`logger`、`message`、`pr_url`、`model`、`duration` 等字段

日志格式 SHALL 通过 `--log-format` CLI 参数或 `LOG_FORMAT` 环境变量配置。

#### Scenario: JSON 日志可被日志系统解析
- **WHEN** 设置 `LOG_FORMAT=json` 并执行审查
- **THEN** 每条日志为单行 JSON
- **AND** 包含 `timestamp`（ISO8601）、`level`、`message` 必填字段
- **AND** 可被 `jq .level` 正确解析

### Requirement: 全局限流器

系统 SHALL 提供基于 token bucket 的全局限流器，限制每秒最大 AI 调用数：
- 默认值：5（每秒 5 次 AI 调用）
- 可通过 `--rate-limit` CLI 参数或 `RATE_LIMIT` 环境变量配置
- 超出限流时请求排队等待，不立即拒绝

#### Scenario: 限流器排队等待
- **WHEN** `--rate-limit 2` 且并发 5 个 AI 调用
- **THEN** 最多 2 个调用同时执行
- **AND** 其余 3 个排队等待
- **AND** 所有调用最终完成（无拒绝）

### Requirement: 降级策略

系统 SHALL 在 AI 调用持续失败时启用降级：
- **Level 1**（AI 不可用）：尝试返回缓存结果（即使 TTL 已过）
- **Level 2**（缓存也无）：返回空 AnalysisResult 并在描述中标注 `[降级模式]`
- **Level 3**（Webhook/API 触发）：返回 503 并提示稍后重试

降级 SHALL 通过 `DegradationManager` 单例管理，自动检测连续失败次数触发。

#### Scenario: AI 不可用时降级返回缓存
- **WHEN** AI 调用连续失败 5 次
- **AND** 缓存中存在该 PR 的历史结果（即使 TTL 已过）
- **THEN** 返回缓存结果
- **AND** 结果描述中包含 `[降级模式: 返回缓存]` 标记
- **AND** 结构化日志记录降级事件

### Requirement: 配置校验

系统 SHALL 在启动时校验配置：
- 必填项：`ai.api_key`（或预设 provider 的对应环境变量）、`ai.model`
- 类型校验：数值字段（`max_tokens`、`temperature`、`min_confidence`）必须为合法值
- 范围校验：`temperature` ∈ [0, 2]，`min_confidence` ∈ [1, 5]，`max_tokens` > 0
- 冲突检测：`enabled_experts` 中的专家名必须存在于 `EXPERT_SKILLS`

校验失败 SHALL 抛出 `ConfigError`，错误消息包含字段名、当前值、期望值与修复建议。

#### Scenario: 缺少 API Key 时给出明确提示
- **WHEN** 配置中 `ai.api_key` 为空
- **AND** 未设置任何 provider 环境变量
- **THEN** 启动时抛出 `MissingRequiredError`
- **AND** 错误消息包含："请配置 AI_API_KEY 环境变量，或在 ~/.ai-pr-review.toml 中设置 [ai] api_key"
- **AND** 退出码为 2

### Requirement: CLI config 子命令

系统 SHALL 提供 `config` 子命令：
- `config init`：交互式生成 `~/.ai-pr-review.toml`（询问 provider、API key、模型）
- `config validate`：校验当前配置并输出结果
- `config show`：展示生效配置，敏感字段（api_key、token）脱敏显示为 `***`

#### Scenario: config show 脱敏敏感字段
- **WHEN** 执行 `ai-pr-review config show`
- **THEN** 输出包含 `api_key = "***"` 而非真实值
- **AND** 输出包含 `token = "***"` 而非真实值
- **AND** 非敏感字段（model、base_url、max_tokens）正常显示

#### Scenario: config init 交互式生成
- **WHEN** 执行 `ai-pr-review config init`
- **AND** 用户选择 provider "deepseek" 并输入 API key
- **THEN** 在 `~/.ai-pr-review.toml` 生成配置文件
- **AND** 文件包含 `[ai]` 段，provider、api_key、model、base_url 字段
- **AND** 控制台提示"配置已生成，可执行 `ai-pr-review config validate` 校验"

## MODIFIED Requirements

### Requirement: load_config 启动校验

`load_config()` SHALL 在返回前调用 `validate_config()`：
- 校验通过：正常返回 `AppConfig`
- 校验失败：抛出 `ConfigError`（含具体错误信息）

CLI 与 API server SHALL 捕获 `ConfigError` 并以友好格式输出错误后退出（退出码 2）。

### Requirement: _call_ai 接入限流与 metrics

`AIAnalyzer._call_ai()` SHALL：
1. 通过 `RateLimiter.acquire()` 获取令牌（排队等待）
2. 通过 `MetricsRegistry` 记录并发数 +1
3. 执行 AI 调用
4. 无论成功失败，记录耗时直方图与状态计数器
5. 并发数 -1
6. 连续失败时触发 `DegradationManager` 评估

## REMOVED Requirements

### Requirement: 静默使用默认配置
**Reason**: 生产环境要求配置错误显式失败，避免"用错配置静默运行"导致审查结果异常
**Migration**: 调用方需捕获 `ConfigError`；CLI 已内置友好错误输出，无需额外处理
