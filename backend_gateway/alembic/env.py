"""Alembic 环境 — 异步 SQLAlchemy 适配 + 避开 configparser interpolation 拦截 DSN。

DSN 里的 @ 经 quote_plus 编码成 %40,configparser 默认把 %xx 当 interpolation 变量解析。
解决:用 RawConfigParser 关 interpolation,或用 alembic 1.13+ 的 no-interpolation 标志。
"""
import asyncio
import os
import sys
from logging.config import fileConfig

from sqlalchemy import pool
from sqlalchemy.engine import Connection
from sqlalchemy.ext.asyncio import async_engine_from_config

from alembic import context

# 关键: 把 app 加进 sys.path,让 Base / settings 能被 import
import os
import sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.core.config import settings  # noqa: E402
from app.db.session import Base  # noqa: E402
import app.models.user  # noqa: F401, E402
import app.models.agent  # noqa: F401, E402
import app.models.machine  # noqa: F401, E402
import app.models.system_setting  # noqa: F401, E402

# Alembic Config
config = context.config

# 关键: 关 configparser 的 interpolation
# 原因: DSN 里的 @ 经 quote_plus 编码成 %40,configparser 默认把 %xx 当 interpolation 变量解析
from configparser import RawConfigParser
config.file_config = RawConfigParser()
if config.config_file_name:
    config.file_config.read(config.config_file_name)

# 直接用 settings 的 DSN 覆盖,不走 configparser 拦截
config.set_main_option("sqlalchemy.url", settings.mysql_async_dsn)

# 配 logging — 走 alembic.ini
if config.config_file_name is not None:
    fileConfig(config.config_file_name)

# 拿 metadata 给 autogenerate 用
target_metadata = Base.metadata


def run_migrations_offline() -> None:
    """离线模式 — 只生成 SQL 不执行。

    用法:  alembic upgrade head --sql > migration.sql
    """
    url = config.get_main_option("sqlalchemy.url")
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )
    with context.begin_transaction():
        context.run_migrations()


def do_run_migrations(connection: Connection) -> None:
    context.configure(connection=connection, target_metadata=target_metadata)
    with context.begin_transaction():
        context.run_migrations()


async def run_async_migrations() -> None:
    """异步模式 — 主流。"""
    connectable = async_engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )
    async with connectable.connect() as connection:
        await connection.run_sync(do_run_migrations)
    await connectable.dispose()


def run_migrations_online() -> None:
    """入口 — 异步包一层。"""
    asyncio.run(run_async_migrations())


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
