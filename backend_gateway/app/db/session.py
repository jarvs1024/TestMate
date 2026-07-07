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

    # session.py 在 backend_gateway/app/db/session.py,需要 .parent.parent.parent 才是仓库根 (backend_gateway/)
    backend_dir = Path(__file__).resolve().parent.parent.parent

    async def _alembic(*args: str) -> tuple[int, str, str]:
        proc = await asyncio.create_subprocess_exec(
            "alembic", *args,
            cwd=str(backend_dir),
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            env={**os.environ, "PYTHONPATH": str(backend_dir)},
        )
        so, se = await proc.communicate()
        return proc.returncode, so.decode(errors="replace"), se.decode(errors="replace")

    # 智能判定:
    # 1) alembic_version 表缺失(老环境 create_all 没建)/ 版本落后 -> stamp head 兜底 + upgrade
    # 2) 已经在 head -> 跳过 upgrade, 避免无意义的报错
    rc2, _so2, se2 = await _alembic("check")
    if rc2 != 0:
        print(f"[init_db] alembic check exit {rc2}, stamping head: {se2.strip()[:200]}")
        rc3, so3, se3 = await _alembic("stamp", "head")
        if rc3 != 0:
            raise RuntimeError(
                f"alembic stamp head failed (exit {rc3}):\n"
                f"stdout: {so3}\nstderr: {se3}"
            )

    rc4, so4, se4 = await _alembic("upgrade", "head")
    if rc4 != 0:
        raise RuntimeError(
            f"alembic upgrade head failed (exit {rc4}):\n"
            f"stdout: {so4}\nstderr: {se4}"
        )


async def get_session() -> AsyncSession:
    async with AsyncSessionLocal() as session:
        yield session
