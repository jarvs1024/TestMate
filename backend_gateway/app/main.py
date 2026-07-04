"""FastAPI 入口。"""
from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from app.core.config import settings
from app.api import auth, kb, diagnose, machines, notify, health
from app.db.session import init_db


@asynccontextmanager
async def lifespan(app: FastAPI):
    """启动 / 关闭钩子。"""
    # 启动:建表(P0 简化,生产用 Alembic)
    await init_db()
    yield
    # 关闭:清理资源


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


@app.get("/", include_in_schema=False)
async def root():
    return JSONResponse(
        {
            "name": settings.APP_NAME,
            "version": settings.APP_VERSION,
            "docs": "/docs",
        }
    )
