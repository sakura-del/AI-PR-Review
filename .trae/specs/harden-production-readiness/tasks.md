# Tasks

## 阶段六：生产化加固 + 集成体验优化

### Task 1: 配置错误类型与校验
- [x] Task 1: 实现 `config_error.py` 与 `validate_config()`，统一配置错误处理
  - [x] SubTask 1.1: 新增 `src/ai_pr_review/config_error.py`，定义 `ConfigError`、`MissingRequiredError`、`InvalidValueError` 异常类
  - [x] SubTask 1.2: 在 `config.py` 中新增 `validate_config(config: AppConfig) -> None`，校验必填项、类型、范围、专家名合法性
  - [x] SubTask 1.3: 新增 `load_config_strict()`（在 `load_config` 基础上追加 `validate_config`），供 CLI 入口使用；保持 `load_config()` 签名不变以兼容既有调用
  - [x] SubTask 1.4: 新增 `tests/test_config_validation.py`，覆盖：缺 API key、temperature 越界、min_confidence 越界、专家名非法、合法配置通过、load_config_strict

### Task 2: 结构化日志
- [x] Task 2: 实现 `structured_logging.py`，支持 text/json 双格式
  - [x] SubTask 2.1: 新增 `src/ai_pr_review/structured_logging.py`，提供 `setup_logging(format: str, level: str)` 函数
  - [x] SubTask 2.2: JSON 格式输出单行 JSON，含 timestamp(ISO8601)、level、logger、message 字段
  - [x] SubTask 2.3: 修改 `cli.py` 启动时调用 `setup_logging()`，支持 `--log-format` 参数与 `LOG_FORMAT` 环境变量
  - [x] SubTask 2.4: 新增 `tests/test_structured_logging.py`，覆盖：text 格式可读、json 格式可被 json.loads 解析、环境变量切换

### Task 3: Metrics 收集
- [x] Task 3: 实现 `metrics.py`，提供计数器/直方图/仪表三类指标
  - [x] SubTask 3.1: 新增 `src/ai_pr_review/metrics.py`，实现 `Counter`、`Histogram`、`Gauge` 类与 `MetricsRegistry` 单例
  - [x] SubTask 3.2: 在 `analyzer._call_ai` 埋点：ai_calls_total{status}、ai_call_duration_seconds、ai_concurrent_current
  - [x] SubTask 3.3: 在 `api_server.handle_connection` 埋点：http_requests_total{method,path,status}、http_request_duration_seconds
  - [x] SubTask 3.4: 在 `webhook.WebhookHandler.handle` 埋点：webhook_events_total{event,action,status}
  - [x] SubTask 3.5: 新增 `tests/test_metrics.py`，覆盖：计数器自增、直方图分桶、仪表增减、registry 快照 JSON 输出

### Task 4: 限流器
- [x] Task 4: 实现 `rate_limiter.py`，基于 token bucket 的全局限流
  - [x] SubTask 4.1: 新增 `src/ai_pr_review/rate_limiter.py`，实现 `RateLimiter` 类（asyncio.Semaphore + 令牌补充协程）
  - [x] SubTask 4.2: 提供 `acquire()` 异步方法，超出限流时排队等待
  - [x] SubTask 4.3: 在 `analyzer._call_ai` 中调用 `RateLimiter.acquire()`（仅多 Agent 与分片路径生效）
  - [x] SubTask 4.4: CLI 新增 `--rate-limit` 参数与 `RATE_LIMIT` 环境变量（默认 5）
  - [x] SubTask 4.5: 新增 `tests/test_rate_limiter.py`，覆盖：限流生效、排队等待、并发上限、默认值

### Task 5: 降级策略
- [x] Task 5: 实现 `degradation.py`，AI 不可用时分级降级
  - [x] SubTask 5.1: 新增 `src/ai_pr_review/degradation.py`，实现 `DegradationManager` 单例（连续失败计数 + 自动触发）
  - [x] SubTask 5.2: Level 1 — 连续失败 5 次后，尝试返回过期缓存（调用 `cache.get_cached_result` 忽略 TTL）
  - [x] SubTask 5.3: Level 2 — 缓存也无时返回空 AnalysisResult，描述含 `[降级模式]` 标记
  - [x] SubTask 5.4: Level 3 — Webhook/API 触发时返回 503 状态码与重试提示
  - [x] SubTask 5.5: 新增 `tests/test_degradation.py`，覆盖：连续失败触发、缓存降级、空结果降级、503 响应

### Task 6: CLI config 子命令
- [x] Task 6: 实现 `config init/validate/show` 三个子命令
  - [x] SubTask 6.1: 在 `cli.py` 新增 `config` 子命令组，含 `init`、`validate`、`show` 三个子命令
  - [x] SubTask 6.2: `config init` 交互式询问 provider（deepseek/qwen/glm）与 API key，生成 `~/.ai-pr-review.toml`
  - [x] SubTask 6.3: `config validate` 调用 `validate_config()` 输出校验结果（含具体错误）
  - [x] SubTask 6.4: `config show` 展示生效配置，api_key 与 token 字段脱敏为 `***`
  - [x] SubTask 6.5: 新增 `tests/test_cli_config.py`，覆盖：init 生成文件内容、validate 校验失败提示、show 脱敏

### Task 7: 集成体验优化
- [x] Task 7: 配置示例模板与文档更新
  - [x] SubTask 7.1: 新增 `.ai-pr-review.example.yaml`，包含所有项目级配置项与注释
  - [x] SubTask 7.2: 更新 `.env.example`，补充 `LOG_FORMAT`、`RATE_LIMIT`、`METRICS_ENABLED` 环境变量
  - [x] SubTask 7.3: 更新 `README.md`，新增"生产部署"章节（配置校验、限流、降级、可观测性）

### Task 8: 端到端验证
- [x] Task 8: 全量测试与回归验证
  - [x] SubTask 8.1: 运行全量测试确保无回归（目标 445+ 用例通过）— 实际 513 passed
  - [x] SubTask 8.2: 手动验证 `config validate` 能识别错误配置（缺 API key / temperature 越界均正确识别并给修复建议）
  - [x] SubTask 8.3: 手动验证 `--log-format json` 输出可被 `json.loads` 解析（含 timestamp/level/logger/message 四字段）

# Task Dependencies
- [Task 2] depends on [Task 1]（日志格式化依赖配置错误类型）
- [Task 3] depends on [Task 2]（metrics 埋点依赖结构化日志）
- [Task 4] 独立（限流器不依赖其他）
- [Task 5] depends on [Task 3, Task 4]（降级依赖 metrics 与限流的失败信号）
- [Task 6] depends on [Task 1]（config 子命令依赖配置校验）
- [Task 7] depends on [Task 1-6]（文档汇总所有新能力）
- [Task 8] depends on [Task 1-7]
