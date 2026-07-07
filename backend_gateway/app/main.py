"""FastAPI 入口。"""
import logging
from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from app.core.config import settings
from app.core.logging import setup_logging
from app.api import auth, kb, diagnose, machines, notify, health, agents, settings as settings_api
from app.api.agents import seed_agents
from app.core.settings_store import seed_defaults
from app.db.session import init_db

# 入口模块最顶端调用:配置 JSON 结构化日志
setup_logging(level="INFO" if not settings.DEBUG else "DEBUG")
log = logging.getLogger("testmate.main")


@asynccontextmanager
async def lifespan(app: FastAPI):
    """启动 / 关闭钩子。"""
    log.info("startup.begin", app=settings.APP_NAME, version=settings.APP_VERSION)
    await init_db()
    await seed_agents()
    await seed_defaults()  # 把 .env 里的值首次落库, 后续 UI 改 DB
    log.info("startup.complete")
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


@app.get("/", include_in_schema=False)
async def root():
    return JSONResponse(
        {
            "name": settings.APP_NAME,
            "version": settings.APP_VERSION,
            "docs": "/docs",
        }
    )
