"""外部系统集成共用的 Redis 连接."""
from __future__ import annotations

from contextlib import asynccontextmanager

import redis.asyncio as aioredis

from app.core.config import settings


@asynccontextmanager
async def redis_client():
    client = aioredis.Redis(
        host=settings.REDIS_HOST,
        port=settings.REDIS_PORT,
        db=settings.REDIS_DB,
        decode_responses=True,
    )
    try:
        yield client
    finally:
        await client.aclose()
