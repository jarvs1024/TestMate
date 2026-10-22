"""健康检查 + 后端服务状态聚合。

分层:
  /health         liveness — 进程活着
  /health/ready   readiness — 依赖(MySQL / Redis)全就绪, 任一不通返 503
  /health/services 聚合外部服务(RAGFlow / Dify)可达性,前端顶栏 30s 轮询
"""
import asyncio
import time
from typing import Tuple

import httpx
from fastapi import APIRouter, Response, status

from app.core.config import settings

router = APIRouter()


# ---------------- liveness ----------------

@router.get("/health")
async def health() -> dict:
    """Liveness probe — 进程活着就返 ok,不依赖任何外部。

    容器编排 (k8s / docker compose) 用这个判断 "要不要重启容器"。
    """
    return {"status": "ok"}


# ---------------- readiness ----------------

async def _check_mysql() -> Tuple[bool, str]:
    """SELECT 1 探 MySQL,2s 超时。返回 (ok, err_msg)"""
    try:
        from sqlalchemy import text
        from app.db.session import engine
        async with engine.connect() as conn:
            await asyncio.wait_for(conn.execute(text("SELECT 1")), timeout=2.0)
        return True, ""
    except Exception as e:
        return False, f"{type(e).__name__}: {e}"


async def _check_redis() -> Tuple[bool, str]:
    """PING 探 Redis,2s 超时。返回 (ok, err_msg)"""
    try:
        import redis.asyncio as aioredis
        from app.core.config import settings
        client = aioredis.Redis(
            host=settings.REDIS_HOST,
            port=settings.REDIS_PORT,
            db=settings.REDIS_DB,
            socket_timeout=2.0,
            socket_connect_timeout=2.0,
        )
        try:
            await asyncio.wait_for(client.ping(), timeout=2.0)
            return True, ""
        finally:
            await client.aclose()
    except Exception as e:
        return False, f"{type(e).__name__}: {e}"


@router.get("/health/ready")
async def health_ready(response: Response) -> dict:
    """Readiness probe — MySQL + Redis 全通才返 200,任一不通返 503。

    docker compose healthcheck / k8s readinessProbe 用这个:
    "要不要把流量路由到这台",不通就先剔出去等修。

    市场链路 (GitLab / 同步积压) 只**观测**不参与 503 判定 ——
    GitLab 挂了不该让整个 TestMate (知识库 / 代码检视) 一起下线.
    """
    mysql_ok, mysql_err = await _check_mysql()
    redis_ok, redis_err = await _check_redis()
    overall_ok = mysql_ok and redis_ok
    if not overall_ok:
        response.status_code = status.HTTP_503_SERVICE_UNAVAILABLE
    market = await _check_marketplace()
    return {
        "status": "ok" if overall_ok else "degraded",
        "checks": {
            "mysql": {"ok": mysql_ok, "error": mysql_err or None},
            "redis": {"ok": redis_ok, "error": redis_err or None},
            "marketplace": market,
        },
    }


# ---------------- 市场链路 ----------------

# GitLab 探针走 SSH 握手, 不能每次健康检查都打 —— 缓存 30s
_market_probe_cache: dict = {}
_market_probe_ttl = 30.0


async def _probe_gitlab() -> Tuple[bool, str]:
    """探 GitLab 远端可达性 (ls-remote). 带 30s 缓存."""
    now = time.monotonic()
    cached = _market_probe_cache.get("gitlab")
    if cached and now - cached["ts"] < _market_probe_ttl:
        return cached["ok"], cached["err"]

    ok, err = True, ""
    try:
        from app.core import git_sync

        rc, so, se = git_sync._run_git(
            ["ls-remote", "--heads", git_sync.GIT_REMOTE],
            cwd=git_sync.WORKSPACE, timeout=8,
        )
        if rc != 0:
            ok, err = False, (se or so).strip()[:200]
    except Exception as e:  # noqa: BLE001
        ok, err = False, f"{type(e).__name__}: {e}"

    _market_probe_cache["gitlab"] = {"ok": ok, "err": err, "ts": now}
    return ok, err


async def _check_marketplace() -> dict:
    """市场链路状态: GitLab 可达性 + 同步任务积压."""
    out: dict = {
        "ok": True,
        "gitlab": {"ok": True, "error": None},
        "failed_jobs": 0,
        "pending_jobs": 0,
        "unpublished": 0,
        "error": None,
    }
    try:
        git_ok, git_err = await _probe_gitlab()
        out["gitlab"] = {"ok": git_ok, "error": git_err or None}
    except Exception as e:  # noqa: BLE001
        out["gitlab"] = {"ok": False, "error": f"{type(e).__name__}: {e}"}

    try:
        from sqlalchemy import func, select

        from app.db.session import AsyncSessionLocal
        from app.models.asset import Asset, AssetJob

        async with AsyncSessionLocal() as session:
            failed = (
                await session.execute(
                    select(func.count()).select_from(AssetJob)
                    .where(AssetJob.status == "failed")
                )
            ).scalar() or 0
            pending = (
                await session.execute(
                    select(func.count()).select_from(AssetJob)
                    .where(AssetJob.status.in_(("pending", "staged", "syncing")))
                )
            ).scalar() or 0
            unpublished = (
                await session.execute(
                    select(func.count()).select_from(Asset)
                    .where(Asset.publish_status == "unpublished")
                )
            ).scalar() or 0
        out["failed_jobs"] = int(failed)
        out["pending_jobs"] = int(pending)
        out["unpublished"] = int(unpublished)
    except Exception as e:  # noqa: BLE001
        out["error"] = f"{type(e).__name__}: {e}"

    out["ok"] = bool(out["gitlab"]["ok"]) and out["failed_jobs"] == 0
    return out



# ---------------- external services ----------------

# 30s TTL 缓存 — 避免前端 30s 轮询 + 多副本时疯狂打 Dify / RAGFlow
_probe_cache: dict = {}
_probe_cache_ttl = 30.0
_probe_cache_lock = asyncio.Lock()


async def _probe(name: str, base_url: str, api_key: str, timeout: float = 1.5) -> str:
    """P0 简化:发一个最小请求,2s 内通就 ok,否则 off. 带 30s 缓存。

    返回 'ok' | 'warn' | 'off'
    """
    if not base_url or "xxxxx" in api_key or "mock" in api_key:
        return "off"

    # 缓存命中直接返
    cache_key = f"{name}:{base_url}"
    now = time.monotonic()
    cached = _probe_cache.get(cache_key)
    if cached and now - cached["ts"] < _probe_cache_ttl:
        return cached["status"]

    async with _probe_cache_lock:
        # 双检:锁内再确认一次
        cached = _probe_cache.get(cache_key)
        if cached and now - cached["ts"] < _probe_cache_ttl:
            return cached["status"]

        try:
            async with httpx.AsyncClient(timeout=timeout) as client:
                r = await client.get(
                    base_url.rstrip("/").replace("/v1", "/").replace("/api/v1", "/")
                )
                if r.status_code < 500:
                    result = "ok"
                else:
                    result = "warn"
        except Exception:
            result = "off"

        _probe_cache[cache_key] = {"status": result, "ts": now}
        return result


@router.get("/health/services")
async def health_services() -> dict:
    """聚合 RAGFlow / Dify 的可达性,前端顶栏 30s 轮询一次。

    RAGFlow / Dify 探针都走 30s 缓存(见 _probe),不会真打外网 30 次/秒。
    """
    from app.core.ragflow_client import probe as rf_probe
    from app.core.settings_store import get
    rf_status, _ = await rf_probe()

    dify_mock = bool(await get("dify.mock_mode", False))
    if dify_mock:
        dify = "ok"
    else:
        dify_base = (await get("dify.base_url", "")) or ""
        dify_key = (await get("dify.api_key", "")) or ""
        dify = await _probe("dify", dify_base, dify_key)

    # 代码检视侧栏心跳: pr-agent 版已下线, 改探 ReviewAgent (代码检视唯一后端).
    # 只在配过 base_url 时探, 没配就 off.
    from app.core import review_agent_client
    if await review_agent_client.is_configured():
        ra_status, _ = await review_agent_client.probe()
    else:
        ra_status = "off"

    return {"ragflow": rf_status, "dify": dify, "review_agent": ra_status}
