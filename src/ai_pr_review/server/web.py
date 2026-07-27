"""FastAPI Web 应用工厂（v0.10）

设计目标：
- 替代 v0.9 的手写 asyncio http server（v0.9 的 api_server.py 保留作为 fallback）
- 提供 OAuth 登录 + Dashboard + JobQueue 状态查询的统一入口
- 路由分组：auth / dashboard / api / jobs / settings
- lifespan 管理：JobQueue / Storage / metrics 单例

启动方式：
    uvicorn ai_pr_review.server.web:app --reload

CLI 集成（v0.10 M7）：
    ai-pr-review serve --web
"""
import logging
from contextlib import asynccontextmanager
from typing import AsyncIterator

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from ai_pr_review.core.degradation import get_degradation_manager
from ai_pr_review.core.metrics import get_registry
from ai_pr_review.data.persistence import get_storage
from ai_pr_review.server.job_queue_runtime import (
    configure_job_queue,
    get_job_queue,
    reset_job_queue,
)

logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    """FastAPI lifespan：启动时初始化单例，关闭时清理

    关键设计：
    - JobQueue 是单进程异步任务队列；FastAPI 进程退出时优雅关闭
    - Storage 单例在启动时确认（CLI 可能已配置过；这里复用）
    - Metrics / DegradationManager 都是模块单例，不需显式管理
    """
    logger.info("Web app starting up")
    # 确保 JobQueue 已配置；handler 由 build_app 注入或使用默认
    try:
        queue = get_job_queue()
        logger.info(f"JobQueue ready, pending={queue.pending_count}")
    except RuntimeError:
        logger.warning("JobQueue not initialized yet; routes that submit jobs will fail")

    yield

    # 关闭时清理
    logger.info("Web app shutting down")
    try:
        await get_job_queue().shutdown()
    except Exception as e:
        logger.warning(f"JobQueue shutdown error: {e}")
    finally:
        reset_job_queue()


def create_app(
    review_handler=None,
    cors_origins: list[str] | None = None,
) -> FastAPI:
    """FastAPI 应用工厂

    Args:
        review_handler: 异步回调 review_fn(pr_url) -> AnalysisResult
                       提供时自动配置 JobQueue 单例
        cors_origins: CORS 白名单（如 ['http://localhost:5173'] 用于 Vite dev server）

    Returns:
        配置完成的 FastAPI 实例
    """
    app = FastAPI(
        title="AI PR Review Web",
        version="0.10.0",
        lifespan=lifespan,
        docs_url="/api/docs",      # Swagger UI（开发用）
        redoc_url="/api/redoc",
    )

    # CORS（前端 Vite dev 默认 :5173）
    app.add_middleware(
        CORSMiddleware,
        allow_origins=cors_origins or ["http://localhost:5173", "http://127.0.0.1:5173"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    # 配置 JobQueue（如果提供了 handler）
    if review_handler is not None:
        from ai_pr_review.server.job_queue_runtime import InMemoryJobQueue
        configure_job_queue(InMemoryJobQueue(review_handler))

    # 静态文件（前端构建产物或开发占位）
    import os
    static_dir = os.path.join(os.path.dirname(__file__), "static")
    if os.path.isdir(static_dir):
        app.mount("/static", StaticFiles(directory=static_dir), name="static")

        # SPA fallback：把 GET / 重定向到 index.html（前端 SPA 入口）
        # 注意：必须放在 router 注册之后，否则会被 router 的 / 覆盖
        @app.get("/", include_in_schema=False)
        async def spa_root():
            """SPA 入口：返回 index.html"""
            from fastapi.responses import FileResponse
            index_path = os.path.join(static_dir, "index.html")
            if os.path.isfile(index_path):
                return FileResponse(index_path, media_type="text/html")
            return {"error": "index.html not found"}

    # 注册路由
    from ai_pr_review.server.routes import auth, dashboard, jobs, settings

    app.include_router(auth.router, prefix="/auth", tags=["auth"])
    app.include_router(dashboard.router, tags=["dashboard"])
    app.include_router(jobs.router, tags=["jobs"])  # router 自带 prefix="/api/jobs"
    app.include_router(settings.router, prefix="/settings", tags=["settings"])

    # 健康检查（无需认证）
    @app.get("/api/health")
    async def health():
        try:
            queue = get_job_queue()
            jobs_info = {"pending": queue.pending_count, "running": queue.running_count}
        except RuntimeError:
            jobs_info = {"pending": 0, "running": 0, "status": "uninitialized"}
        return {
            "status": "ok",
            "version": app.version,
            "jobs": jobs_info,
            "degradation_level": get_degradation_manager().current_level(),
        }

    logger.info(f"Web app created (cors_origins={cors_origins or 'default'})")
    return app


# 模块级 app 实例（uvicorn 直接引用：uvicorn ai_pr_review.server.web:app）
# 注意：未提供 review_handler，应用启动后 /api/jobs 等路由可能不可用
app = create_app()