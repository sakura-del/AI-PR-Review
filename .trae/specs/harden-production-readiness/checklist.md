# Checklist

## 配置错误类型与校验
- [x] `config_error.py` 定义 `ConfigError`、`MissingRequiredError`、`InvalidValueError` 三类异常
- [x] `validate_config()` 校验必填项（api_key/model）、类型、范围（temperature ∈ [0,2]、min_confidence ∈ [1,5]、max_tokens > 0）
- [x] `validate_config()` 校验 `enabled_experts` 中的专家名必须存在于 `EXPERT_SKILLS`
- [x] 新增 `load_config_strict()`（追加 `validate_config`）供 CLI 入口使用；`load_config()` 保持不变以兼容既有调用
- [x] 缺少 API key 时错误消息包含明确修复建议（环境变量名或配置文件路径）
- [x] `test_config_validation.py` 覆盖缺 API key、temperature 越界、min_confidence 越界、专家名非法、合法配置通过

## 结构化日志
- [x] `structured_logging.py` 提供 `setup_logging(format, level)` 函数
- [x] text 格式输出人类可读的 `[LEVEL] message`
- [x] json 格式输出单行 JSON，含 timestamp(ISO8601)、level、logger、message 必填字段
- [x] CLI 支持 `--log-format` 参数与 `LOG_FORMAT` 环境变量
- [x] json 格式输出可被 `json.loads` 正确解析
- [x] `test_structured_logging.py` 覆盖两种格式与环境变量切换

## Metrics 收集
- [x] `metrics.py` 实现 `Counter`、`Histogram`、`Gauge` 三类指标
- [x] `MetricsRegistry` 单例聚合所有指标，提供 `snapshot()` 返回 JSON
- [x] `analyzer._call_ai` 埋点：ai_calls_total{status}、ai_call_duration_seconds、ai_concurrent_current
- [x] `api_server.handle_connection` 埋点：http_requests_total{method,path,status}、http_request_duration_seconds
- [x] `webhook.WebhookHandler.handle` 埋点：webhook_events_total{event,action,status}
- [x] 并发仪表正确反映实时状态（Agent 启动 +1，完成 -1）
- [x] `test_metrics.py` 覆盖计数器自增、直方图分桶、仪表增减、registry 快照

## 限流器
- [x] `rate_limiter.py` 基于 token bucket + asyncio.Semaphore 实现全局限流
- [x] `acquire()` 异步方法，超出限流时排队等待（不立即拒绝）
- [x] 默认值 5（每秒 5 次 AI 调用），可通过 `--rate-limit` 与 `RATE_LIMIT` 配置
- [x] 限流器仅作用于多 Agent 与分片路径，单次审查不受限
- [x] `test_rate_limiter.py` 覆盖限流生效、排队等待、并发上限、默认值

## 降级策略
- [x] `degradation.py` 实现 `DegradationManager` 单例（连续失败计数 + 自动触发）
- [x] Level 1：连续失败 5 次后尝试返回过期缓存（忽略 TTL）
- [x] Level 2：缓存无时返回空 AnalysisResult，描述含 `[降级模式]` 标记
- [x] Level 3：Webhook/API 触发时返回 503 状态码与重试提示
- [x] 降级事件被结构化日志记录（含 pr_url、降级级别、原因）
- [x] `test_degradation.py` 覆盖连续失败触发、缓存降级、空结果降级、503 响应

## CLI config 子命令
- [x] `config init` 交互式询问 provider 与 API key，生成 `~/.ai-pr-review.toml`
- [x] `config validate` 调用 `validate_config()` 输出校验结果（含具体错误）
- [x] `config show` 展示生效配置，api_key 与 token 脱敏为 `***`
- [x] `config show` 非敏感字段（model、base_url、max_tokens）正常显示
- [x] `test_cli_config.py` 覆盖 init 生成文件内容、validate 校验失败提示、show 脱敏

## 集成体验优化
- [x] 新增 `.ai-pr-review.example.yaml`，包含所有项目级配置项与注释
- [x] `.env.example` 补充 `LOG_FORMAT`、`RATE_LIMIT`、`METRICS_ENABLED` 环境变量
- [x] `README.md` 新增"生产部署"章节，涵盖配置校验、限流、降级、可观测性

## 端到端验证
- [x] 全量测试通过（实际 513 用例，无回归）
- [x] 手动验证 `config validate` 能识别错误配置并给出修复建议（缺 API key / temperature 越界）
- [x] 手动验证 `--log-format json` 输出可被 `json.loads` 解析（含 timestamp/level/logger/message 四字段）
- [x] 限流排队行为由 `test_rate_limiter.py` 9 个用例覆盖（限流生效/排队等待/并发上限）
