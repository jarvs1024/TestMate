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

    # 判定当前迁移版本 — 直查 alembic_version 表, 不用 `alembic check`.
    #
    # 历史 bug (2026-10-15 踩过): 原实现是 `alembic check` 失败 ⇒ `stamp head`.
    # 但 `alembic check` 检测的是「模型 vs 数据库」的差异, 不是「alembic_version 表是否存在」.
    # 一旦模型改了 (比如新增枚举值), check 就会失败并把版本直接盖到 head ——
    # 新迁移被整段跳过, schema 与模型静默不一致, 表现为写入时报 Data truncated。
    # 只有「版本表不存在 / 无记录」(老环境用 create_all 建的) 才允许 stamp 兜底。
    from sqlalchemy import text  # noqa: PLC0415

    current_rev: str | None = None
    try:
        async with engine.connect() as conn:
            row = (
                await conn.execute(text("SELECT version_num FROM alembic_version LIMIT 1"))
            ).first()
            current_rev = str(row[0]) if row and row[0] else None
    except Exception:  # noqa: BLE001 — 表不存在即视为老环境
        current_rev = None

    if not current_rev:
        # 老环境: 表由 create_all 建出, 没有版本历史, 直接 stamp 后跳过 upgrade
        print("[init_db] alembic_version 无记录 (老环境), stamp head 兜底")
        rc3, so3, se3 = await _alembic("stamp", "head")
        if rc3 != 0:
            raise RuntimeError(
                f"alembic stamp head failed (exit {rc3}):\n"
                f"stdout: {so3}\nstderr: {se3}"
            )
        return

    print(f"[init_db] 当前迁移版本 {current_rev}, 执行 upgrade head")
    rc4, so4, se4 = await _alembic("upgrade", "head")
    if rc4 != 0:
        raise RuntimeError(
            f"alembic upgrade head failed (exit {rc4}):\n"
            f"stdout: {so4}\nstderr: {se4}"
        )


async def get_session() -> AsyncSession:
    async with AsyncSessionLocal() as session:
        yield session
