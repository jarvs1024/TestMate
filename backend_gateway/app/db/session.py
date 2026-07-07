"""SQLAlchemy 异步 session。"""
import asyncio
import os
from pathlib import Path
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import DeclarativeBase

from app.core.config import settings


class Base(DeclarativeBase):
    pass


engine = create_async_engine(
    settings.mysql_async_dsn,
    echo=settings.DEBUG,
    pool_pre_ping=True,
    pool_recycle=3600,
)

AsyncSessionLocal = async_sessionmaker(
    engine,
    class_=AsyncSession,
    expire_on_commit=False,
)


async def init_db() -> None:
    """跑 alembic upgrade head — 数据库 schema 版本化管理。

    由 deploy.sh / docker entrypoint / lifespan 钩子触发。
    不要再用 Base.metadata.create_all(只新建不改列,生产危险)。
    """
    # 引入 models 让 Base.metadata 知道表 — alembic env.py 也 import 了,这里再 import 一次保险
    from app.models import user, machine, agent, system_setting  # noqa: F401

    # 跑 alembic upgrade head 子进程
    # session.py 在 backend_gateway/app/db/session.py,需要 .parent.parent.parent 才是仓库根 (backend_gateway/)
    backend_dir = Path(__file__).resolve().parent.parent.parent
    proc = await asyncio.create_subprocess_exec(
        "alembic", "upgrade", "head",
        cwd=str(backend_dir),
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
        env={**os.environ, "PYTHONPATH": str(backend_dir)},
    )
    stdout, stderr = await proc.communicate()
    if proc.returncode != 0:
        raise RuntimeError(
            f"alembic upgrade head failed (exit {proc.returncode}):\n"
            f"stdout: {stdout.decode()}\nstderr: {stderr.decode()}"
        )


async def get_session() -> AsyncSession:
    async with AsyncSessionLocal() as session:
        yield session
