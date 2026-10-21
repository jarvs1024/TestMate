"""FastAPI 入口。"""
import logging
import os
from contextlib import asynccontextmanager
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, Response

from app.core.config import settings
from app.core.logging import setup_logging
from app.api import auth, kb, diagnose, machines, notify, health, agents, settings as settings_api, pr_agent, review_agent, marketplace
from app.api.agents import seed_agents
from app.core.settings_store import seed_defaults
from app.db.session import init_db

# 入口模块最顶端调用:配置 JSON 结构化日志
setup_logging(level="INFO" if not settings.DEBUG else "DEBUG")
import structlog
log = structlog.get_logger("testmate.main")


@asynccontextmanager
async def lifespan(app: FastAPI):
    """启动 / 关闭钩子。"""
    log.info("startup.begin", app=settings.APP_NAME, version=settings.APP_VERSION)
    await init_db()
    await seed_agents()
    await seed_defaults()  # 把 .env 里的值首次落库, 后续 UI 改 DB
    # 资产市场: 启动后台同步 worker, 并把上次没推完的任务重新入队
    from app.core.asset_jobs import recover_pending_jobs, start_worker
    from app.core.sync_puller import start_puller
    start_worker()
    requeued = await recover_pending_jobs()
    # 反向同步: 定期从 GitLab 拉取远端变更, 对齐本地工作区与 DB 镜像
    interval = int(os.environ.get("MARKET_SYNC_INTERVAL_SECONDS", "30") or 30)
    await start_puller(interval)
    log.info("startup.complete", requeued_asset_jobs=requeued,
             sync_interval_seconds=interval)
    yield
    log.info("shutdown")


app = FastAPI(
    title=settings.APP_NAME,
    version=settings.APP_VERSION,
    lifespan=lifespan,
    docs_url="/docs",
    redoc_url="/redoc",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.CORS_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# 路由
app.include_router(health.router, prefix="/api/v1", tags=["health"])
app.include_router(auth.router, prefix="/api/v1/auth", tags=["auth"])
app.include_router(machines.router, prefix="/api/v1/machines", tags=["machines"])
app.include_router(kb.router, prefix="/api/v1/kb", tags=["kb"])
app.include_router(diagnose.router, prefix="/api/v1/diagnose", tags=["diagnose"])
app.include_router(notify.router, prefix="/api/v1/notify", tags=["notify"])
app.include_router(agents.router, prefix="/api/v1/agents", tags=["agents"])
app.include_router(settings_api.router, prefix="/api/v1/settings", tags=["settings"])
app.include_router(pr_agent.router, prefix="/api/v1/pr-agent", tags=["pr-agent"])
app.include_router(review_agent.router, prefix="/api/v1/review-agent", tags=["review-agent"])
app.include_router(marketplace.router, prefix="/api/v1/assets", tags=["marketplace"])


@app.get("/marketplace.json", include_in_schema=False)
async def qoder_marketplace(request: Request):
    """Qoder 原生市场清单 —— 无需登录 (Qoder 拉取时不带 token).

    Qoder 把这个 URL 加为市场源后, 自带安装器负责下载/校验/解压,
    并可用 autoUpdate 自动更新.
    """
    from app.core.qoder_marketplace import build_marketplace, render
    from app.core.settings_store import get

    configured = (await get("marketplace.public_base_url", "")) or ""
    base = configured.rstrip("/") or str(request.base_url).rstrip("/")
    name = (await get("marketplace.marketplace_name", "testmate")) or "testmate"
    manifest = await build_marketplace(base, name=name)
    return Response(content=render(manifest), media_type="application/json")


@app.get("/", include_in_schema=False)
async def root():
    return JSONResponse(
        {
            "name": settings.APP_NAME,
            "version": settings.APP_VERSION,
            "docs": "/docs",
        }
    )
