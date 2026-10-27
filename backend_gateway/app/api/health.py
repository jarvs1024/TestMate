"""健康检查 + 后端服务状态聚合。

分层:
  /health         liveness — 进程活着
  /health/ready   readiness — 依赖(MySQL / Redis)全就绪, 任一不通返 503
  /health/services 聚合外部服务(RAGFlow / ReviewAgent)可达性,前端顶栏 30s 轮询
"""
import asyncio
import logging
import time
from typing import Tuple

from fastapi import APIRouter, Response, status

from app.core.config import settings

logger = logging.getLogger(__name__)
router = APIRouter()


# ---------------- liveness ----------------

@router.get("/health")
async def health() -> dict:
    """Liveness probe — 进程活着就返 ok,不依赖任何外部。

    容器编排 (k8s / docker compose) 用这个判断 "要不要重启容器"。

    ⚠️ 这里**带 version**: 前端页头要显示版本号, 而根路径 `/` 在浏览器里
       返回的是前端 SPA 的 HTML (不是这个后端) —— 版本号只能从这儿取.
    """
    return {"status": "ok", "version": settings.APP_VERSION}


# ---------------- readiness ----------------

# ⚠️ **错误原文不能回给调用方** —— /health/ready 是**无鉴权**的
#    (docker compose healthcheck / k8s readinessProbe 拿不到 token).
#    MySQL 的报错里带着账号和 host:port, Redis 的报错带 host:port,
#    git 的报错直接带 SSH 仓库地址 —— 全是内网拓扑.
#    探针函数返回**原文**, 由出口统一压成"哪个不可用", 原文只进日志.
def _public_error(kind: str, raw: str) -> str:
    return f"{kind} 不可用" if raw else ""


async def _check_mysql() -> Tuple[bool, str]:
    """SELECT 1 探 MySQL,2s 超时。返回 (ok, 原始 err_msg)"""
    try:
        from sqlalchemy import text
        from app.db.session import engine
        async with engine.connect() as conn:
            await asyncio.wait_for(conn.execute(text("SELECT 1")), timeout=2.0)
        return True, ""
    except Exception as e:
        logger.warning("readiness: mysql 探针失败: %s: %s", type(e).__name__, e)
        return False, f"{type(e).__name__}: {e}"


async def _check_redis() -> Tuple[bool, str]:
    """PING 探 Redis,2s 超时。返回 (ok, 原始 err_msg)"""
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
        logger.warning("readiness: redis 探针失败: %s: %s", type(e).__name__, e)
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
    # ⚠️ 出口统一脱敏 —— 探针返回的是**原文**(内部日志要看), 这里对外只说"哪个不可用".
    if mysql_err:
        mysql_err = _public_error("MySQL", mysql_err)
    if redis_err:
        redis_err = _public_error("Redis", redis_err)
    market = _sanitize_market(market)
    return {
        "status": "ok" if overall_ok else "degraded",
        "checks": {
            "mysql": {"ok": mysql_ok, "error": mysql_err or None},
            "redis": {"ok": redis_ok, "error": redis_err or None},
            "marketplace": market,
        },
    }


def _sanitize_market(market: dict) -> dict:
    """市场链路状态脱敏 (git 报错里有 SSH 仓库地址)."""
    out = dict(market)
    git = out.get("gitlab") or {}
    if git.get("error"):
        out["gitlab"] = {**git, "error": _public_error("GitLab", str(git["error"]))}
    if out.get("error"):
        out["error"] = _public_error("市场状态", str(out["error"]))
    return out


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
            ["ls-remote", "--heads", git_sync.git_remote()],
            cwd=git_sync.WORKSPACE, timeout=8,
        )
        if rc != 0:
            ok, err = False, (se or so).strip()[:200]
    except Exception as e:  # noqa: BLE001
        ok, err = False, f"{type(e).__name__}: {e}"
    if err:
        # ⚠️ git 的报错里带 SSH 仓库地址 (内网 host + 仓库路径) —— 原文进日志, 不外发
        logger.warning("readiness: gitlab 探针失败: %s", err)

    _market_probe_cache["gitlab"] = {"ok": ok, "err": err, "ts": now}
    return ok, err


async def _check_marketplace() -> dict:
    """市场链路状态: GitLab 可达性 + 同步任务积压.

    ⚠️ **判定口径**: 市场链路"坏没坏"看的是 `failed_assets` ——
       资产表里 `sync_status='failed'` 的那几个, 也就是**还有活没推上去**。
       不是 `failed_jobs` (任务表里的历史失败条数)。

       为什么不能用 failed_jobs 判: 2026-10-22~26 GitLab 挂着那几天攒了 219 条
       failed job, 对应的资产**后来都被删了** —— 它们是纯历史残留, 没有一件
       待处理. 但 `failed_jobs == 0` 是**全量**计数 → 从那以后平台一直报
       "市场链路不健康", 哪怕现在一切正常. 监控告警永远亮着, 真出故障时反而
       没人看 —— 这在生产上是致命的。

       历史那 219 条**一条不删** (那是审计线索: 谁在什么时候传了什么失败了),
       只是不再参与健康判定。
    """
    out: dict = {
        "ok": True,
        "gitlab": {"ok": True, "error": None},
        "failed_jobs": 0,
        "failed_assets": 0,
        "pending_jobs": 0,
        "unpublished": 0,
        "error": None,
    }
    try:
        git_ok, git_err = await _probe_gitlab()
        out["gitlab"] = {"ok": git_ok, "error": git_err or None}
    except Exception as e:  # noqa: BLE001
        logger.warning("readiness: gitlab 探针异常: %s: %s", type(e).__name__, e)
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
            # ⚠️ 判定用这个, 不是 failed_jobs —— 见函数 docstring 的说明
            failed_assets = (
                await session.execute(
                    select(func.count()).select_from(Asset)
                    .where(Asset.sync_status == "failed")
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
        out["failed_assets"] = int(failed_assets)
        out["pending_jobs"] = int(pending)
        out["unpublished"] = int(unpublished)
    except Exception as e:  # noqa: BLE001
        logger.warning("readiness: 市场统计查询失败: %s: %s", type(e).__name__, e)
        out["error"] = f"{type(e).__name__}: {e}"

    # ⚠️ 判定用 failed_assets (还有活没推上去), 不是 failed_jobs (历史残留) —— 见上面
    out["ok"] = bool(out["gitlab"]["ok"]) and out["failed_assets"] == 0
    return out



# ---------------- external services ----------------

# ⚠️ 2026-10-25: Dify 下线后, 这个通用探针没人用了 —— 各服务自己带缓存
#    (RAGFlow 见 ragflow_client.probe, ReviewAgent 见 review_agent_client.probe).
#    真要加新的外部服务, 用各服务自己的探针, 别在这儿再堆一个通用的.


@router.get("/health/services")
async def health_services() -> dict:
    """聚合 RAGFlow / ReviewAgent 的可达性,前端顶栏 30s 轮询一次。

    RAGFlow 探针走 30s 缓存(见 _probe),不会真打外网 30 次/秒。

    ⚠️ 2026-10-25: Dify 已整个下线 (平台不再接入), 这里不再返回 dify 字段.
    """
    from app.core.ragflow_client import probe as rf_probe
    rf_status, _ = await rf_probe()

    # 代码检视侧栏心跳: pr-agent 版已下线, 改探 ReviewAgent (代码检视唯一后端).
    # 只在配过 base_url 时探, 没配就 off.
    from app.core import review_agent_client
    if await review_agent_client.is_configured():
        ra_status, _ = await review_agent_client.probe()
    else:
        ra_status = "off"

    return {"ragflow": rf_status, "review_agent": ra_status}
