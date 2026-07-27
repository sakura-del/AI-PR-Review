# Changelog

## v0.10.0 (Web 化 MVP)

### Features

#### FastAPI Web 框架
- **server/web.py** — `create_app()` 工厂，lifespan 管理 JobQueue / Storage 单例
- **CORS** 默认白名单含 Vite dev server (`localhost:5173`)
- **lifespan 优雅关闭** — 启动确认 JobQueue，关闭时 graceful shutdown
- **OpenAPI / Swagger** 自动暴露（`/api/docs`）

#### GitHub OAuth
- **server/routes/auth.py** — `httpx-oauth` 简化 authorization code flow
- **scopes** — `read:user` / `user:email` / `repo`
- **Session cookie** — `itsdangerous` 签名，7 天有效期，httponly + samesite=lax
- **路由**：
  - `GET /auth/login` → 重定向到 GitHub 授权
  - `GET /auth/callback?code=...` → 换 token + 拉 user info + 设 cookie
  - `POST /auth/logout` → 清 cookie
  - `GET /auth/me` → 当前用户信息
- **Dependencies** — `get_current_session`（Optional）/ `require_session`（401 否则）
- **环境变量** — `GITHUB_OAUTH_CLIENT_ID` / `GITHUB_OAUTH_CLIENT_SECRET` / `SESSION_SECRET_KEY`

#### SPA Dashboard
- **server/static/index.html / dashboard.css / dashboard.js** — vanilla JS + hash 路由
- **统计卡片** — total / HIGH / MEDIUM / avg_duration
- **PR 提交表单** — POST /api/jobs 即时返回 job_id
- **最近审查表 + 任务列表** — 客户端 fetch /api/* JSON 端点
- **SPA fallback** — FastAPI `/` 返回 `index.html`，未知路由客户端 hash 路由处理

#### Web API 端点
- `GET /api/stats` — Dashboard 统计（用户隔离）
- `GET /api/history?limit=N` — 最近审查记录（按用户过滤）
- `GET /api/history/me` — 仅当前用户（需登录）
- `GET /api/jobs?limit=N` — 任务列表
- `GET /api/jobs/{job_id}` — 任务状态
- `POST /api/jobs` — 提交 PR 审查（返回 202 + job_id，async）
- `GET /api/metrics` — 指标快照

#### 多用户隔离
- **AnalysisRecord.user_id** 字段（CLI 单用户默认 `""`）
- **`_record_key`** 改为 `{timestamp}__{user_id}__{url_hash}` 格式
- **`load_records_for_user(user_id)`** — 按用户过滤
- **`_enforce_max_records_for_user`** — MAX_RECORDS 按用户独立

#### CLI 集成
- **`ai-pr-review serve --web`** — 启动 FastAPI + uvicorn
- 默认（无 `--web`）仍走 v0.9 asyncio server（向后兼容）
- Web 模式端点列表 UI 提示包含 OAuth 环境变量

#### Docker
- **Dockerfile** 默认 `CMD ["serve", "--web", "--host", "0.0.0.0", "--port", "8000"]`
- **`EXPOSE 8000`**
- 部署需设置 OAuth 三个环境变量

### Bug Fixes
- 修：FastAPI lifespan 中 JobQueue 启动检查逻辑（避免 RuntimeError 被吞）
- 修：JobQueue 未配置时 `GET /api/jobs/{id}` 返回 503 而非 500

### Tests
- `test_web_app.py` — 12 个 FastAPI 骨架测试
- `test_web_auth.py` — 13 个 GitHub OAuth + session 测试
- `test_web_static.py` — 7 个静态资源 + SPA fallback 测试
- `test_web_api_dashboard.py` — 11 个 Web API 端点测试
- `test_user_history.py` — 9 个多用户隔离测试
- `test_cli_serve_web.py` — 3 个 CLI --web 标志测试
- **新增 55 个测试**（v0.9 759 → v0.10 814）

### Configuration Changes
- **新环境变量**：
  - `GITHUB_OAUTH_CLIENT_ID` — GitHub OAuth App Client ID
  - `GITHUB_OAUTH_CLIENT_SECRET` — Client Secret
  - `SESSION_SECRET_KEY` — session cookie 签名密钥（生产必设，dev 有占位）
- **新依赖**：
  - `fastapi>=0.110.0`
  - `uvicorn[standard]>=0.27.0`
  - `jinja2>=3.1.0`（预留，当前版本用 SPA）
  - `python-multipart>=0.0.9`
  - `itsdangerous>=2.1.0`
  - `httpx-oauth>=0.15.0`

### Migration Notes
- **CLI 用户**：无需操作，行为完全等同 v0.9
- **Web 部署**：
  1. 创建 GitHub OAuth App（https://github.com/settings/developers）
  2. 设置 callback URL 为 `https://your-domain/auth/callback`
  3. 配置三个环境变量
  4. 启动 `ai-pr-review serve --web`
  5. 浏览器访问 `https://your-domain/`

### 后续（v1.0）
- VS Code 插件
- Autofix（AI 生成 patch + commit）
- Learning 系统（用户反馈闭环）

---

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