# Changelog

## v0.9.0 (阶段七：架构加固 + Web 化前置)

### Features

#### 存储层抽象（v0.9 核心）
- **Storage ABC**（`storage.py`）—— 抽象 Key-Value 存储接口，支持命名空间隔离与 Schema 版本
- **LocalJSONStorage**（`persistence/local_json.py`）—— 默认 JSON 文件实现，原子写入（临时文件 + rename）
- **SQLiteStorage**（`persistence/sqlite.sqlite`）—— Web 化用 sqlite3 实现，索引 + LIKE 前缀搜索
- **Storage 工厂**（`persistence/factory.py`）—— `get_storage()` 单例 + `AI_PR_REVIEW_STORAGE` 环境变量切换

#### 数据迁移到 Storage
- **history** —— 从 `~/.ai-pr-review/history/history.json` 迁移到 Storage，旧文件保留
- **cache** —— 从 `~/.ai-pr-review/cache/*.json` 迁移到 Storage
- **team_rules** —— 从 `~/.ai-pr-review/team_rules/*.json` 迁移到 Storage

#### JobQueue 异步任务队列
- **Job / JobQueue ABC**（`job_queue.py`）—— 任务状态机 + 异步接口
- **InMemoryJobQueue**（`job_queue_runtime.py`）—— asyncio.Queue + 后台 worker，懒启动、优雅关闭
- **api_server 接入 JobQueue** —— `POST /api/review` 改为返回 `job_id`，新增 `GET /api/jobs/{job_id}` 状态查询
- **路径参数路由** —— APIRouter 支持 `/api/jobs/{job_id}` 模式

#### Prompt 重构
- **AnalysisContext** dataclass —— 收敛 build_analysis_prompt 的 8+ 参数
- **`build_analysis_prompt(ctx)`** 新签名 + `_legacy` 向后兼容 shim
- **AIAnalyzer._build_ctx** helper —— 4 个调用点（analyze / analyze_incremental / analyze_stream / _analyze_shard）统一收敛

#### 可靠性
- **retry.py** —— `retry_async` + `retry_sync` 通用重试：指数退避、jitter、Retry-After、on_retry 回调
- **GitHubClient / GitLabPlatform** 接入 retry —— 429/5xx 退避，4xx 业务错误不重试
- **llm_token_usage_total{model, type}** Counter —— 从 OpenAI 响应提取 prompt/completion tokens

### Bug Fixes
- 修：retry_async 在 pytest-asyncio event loop 内被 `asyncio.run()` 拒绝 —— 改用 `new_event_loop()` 隔离
- 修：`analyzer_stream` 等方法意外移出 class —— Prompt 重构时小心 class 边界

### Tests

#### 新增
- `tests/test_storage.py` —— 50 个参数化契约测试（memory / local_json / sqlite）
- `tests/test_local_json_storage.py` —— 10 个 impl-specific 测试
- `tests/test_sqlite_storage.py` —— 10 个 impl-specific 测试
- `tests/test_factory.py` —— 13 个 Storage 工厂测试
- `tests/test_history_migration.py` / `test_cache_migration.py` / `test_team_rules_migration.py` —— 迁移测试
- `tests/test_inmemory_job_queue.py` —— 15 个 JobQueue 测试
- `tests/test_api_job_endpoints.py` —— 15 个 API Job 端点测试
- `tests/test_retry.py` —— 22 个重试单元测试
- `tests/test_token_usage.py` —— 10 个 token 用量测试
- `tests/test_failure_injection.py` —— 19 个故障注入（GitHub 429/5xx/401、AI 降级、RateLimiter、JobQueue cancel）

#### 适配
- `test_github_client.py` / `test_platform.py` —— 改用 AsyncMock + AsyncClient
- `test_history.py` / `test_cache.py` —— 用 `configure_storage` 替代旧文件 patch
- `test_expert_customization.py` / `test_team_learner.py` / `test_incremental.py` —— 改用 `build_analysis_prompt_legacy`

### Configuration Changes
- 新环境变量：`AI_PR_REVIEW_STORAGE`（`local` 默认 / `sqlite` 备选）

### Migration Notes
- **CLI 用户**：无需任何操作，首次运行自动从旧 JSON 文件迁移到新 Storage
- **Web 部署**：设置 `AI_PR_REVIEW_STORAGE=sqlite` 切换到数据库后端
- **数据完整性**：迁移过程不删除旧文件，作为回滚备份保留

---

## v0.8.0 (阶段六：生产化加固 + 集成体验优化)
（参见 git history）

## v0.7.0 (阶段五：生态集成 + 平台化)
（参见 git history）

## v0.6.0 (阶段四：多 Agent 协作 + 评审质量)
（参见 git history）

## v0.5.0 (阶段三 P2：增量影响图 + RAG 知识库)
（参见 git history）

## v0.4.0 (阶段三：上下文工程 + 智能化)
（参见 git history）

## v0.3.0 (阶段二：质量加固 + 体验优化)
（参见 git history）

## v0.2.0 (阶段一：缺陷修复 + 基础补强)
（参见 git history）

## v0.1.0
- 初版发布：PR 分析、风险识别、智能建议、行级评论、流式输出、团队规范学习、增量分析、专家知识库等核心能力