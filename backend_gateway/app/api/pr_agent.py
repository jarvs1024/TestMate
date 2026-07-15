"""/api/v1/pr-agent — 透传 pr-agent telemetry 给前端.

路径 / 字段跟 pr-agent /api/v1/telemetry/* 完全对齐,
前端不需要直接连 pr-agent (避免暴露 token / 跨域).
"""
from __future__ import annotations
import asyncio
import logging
from typing import Any, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select

from app.api.auth import get_current_user
from app.core import pr_agent_client
from app.core.config import settings
from app.core.settings_store import get
from app.models.user import User

logger = logging.getLogger(__name__)
router = APIRouter()


def _unconfigured() -> None:
    raise HTTPException(
        status_code=503,
        detail="pr-agent 未配置 (Settings → 代码检视 / 或 .env PR_AGENT_BASE_URL)",
    )


@router.get("/health")
async def health(_user: User = Depends(get_current_user)) -> dict:
    """健康检查: 是否配了 + 是否能连上."""
    configured = await pr_agent_client.is_configured()
    if not configured:
        return {"configured": False, "status": "off", "message": "未配置 base_url"}
    status, msg = await pr_agent_client.probe()
    return {"configured": True, "status": status, "message": msg}


@router.get("/metrics/overview")
async def metrics_overview(
    since: Optional[str] = None,
    _user: User = Depends(get_current_user),
) -> dict:
    if not await pr_agent_client.is_configured():
        return {"configured": False}
    try:
        return await pr_agent_client.overview(since=since)
    except RuntimeError as e:
        raise HTTPException(status_code=502, detail=str(e))


@router.get("/metrics/rules")
async def metrics_rules(
    since: Optional[str] = None,
    _user: User = Depends(get_current_user),
) -> list[dict]:
    if not await pr_agent_client.is_configured():
        return []
    try:
        return await pr_agent_client.per_rule_stats(since=since)
    except RuntimeError as e:
        raise HTTPException(status_code=502, detail=str(e))


@router.get("/metrics/authors")
async def metrics_authors(
    since: Optional[str] = None,
    _user: User = Depends(get_current_user),
) -> list[dict]:
    if not await pr_agent_client.is_configured():
        return []
    try:
        return await pr_agent_client.per_author_stats(since=since)
    except RuntimeError as e:
        raise HTTPException(status_code=502, detail=str(e))


@router.get("/metrics/severity")
async def metrics_severity(
    since: Optional[str] = None,
    pr_url: Optional[str] = None,
    _user: User = Depends(get_current_user),
) -> list[dict]:
    """严重等级分桶. 见 pr_agent.telemetry.store.severity_breakdown."""
    if not await pr_agent_client.is_configured():
        return []
    try:
        return await pr_agent_client.severity_breakdown(since=since, pr_url=pr_url)
    except RuntimeError as e:
        raise HTTPException(status_code=502, detail=str(e))
    except Exception as e:
        # 兜底: AttributeError / TypeError 等 (例如 client 缺方法) — 不要无声 500
        logger.exception("metrics_severity unexpected error")
        raise HTTPException(status_code=502, detail=f"{type(e).__name__}: {e}")


@router.get("/mrs")
async def list_mrs(
    limit: int = Query(50, ge=1, le=200),
    project_id: Optional[int] = None,
    state: Optional[str] = None,
    since: Optional[str] = None,
    _user: User = Depends(get_current_user),
) -> dict:
    """MR 列表 + 每条 MR 的最近一次 run (含失败状态) + 建议统计.

    返回 {items: [...], failed_mr_count: N, total: N}.
    每条 MR 拍平:
      - last_run         自 /mrs/{pid}/{mr_id}/stats.runs[0], 字段: run_id / command /
                         status / model / started_at / duration_ms / error / suggestion_count
      - suggestion_counts 自 stats.suggestion_counts, 字段: total / applied / dismissed / open
    stats 调用失败时 last_run / suggestion_counts 置 None, 不影响其他 MR.
    """
    if not await pr_agent_client.is_configured():
        return {"items": [], "failed_mr_count": 0, "total": 0}
    try:
        mrs = await pr_agent_client.list_mrs(
            limit=limit, project_id=project_id, state=state, since=since,
        )
    except RuntimeError as e:
        raise HTTPException(status_code=502, detail=str(e))

    async def _attach_last_run(mr: dict) -> dict:
        try:
            stats = await pr_agent_client.mr_stats(int(mr["project_id"]), int(mr["mr_id"]))
            # 1) last_run
            runs = stats.get("runs") or []
            if runs:
                r0 = runs[0]
                mr["last_run"] = {
                    "run_id": r0.get("run_id"),
                    "command": r0.get("command"),
                    "status": r0.get("status"),
                    "model": r0.get("model"),
                    "started_at": r0.get("started_at"),
                    "duration_ms": r0.get("duration_ms"),
                    "error": r0.get("error"),
                    "suggestion_count": r0.get("suggestion_count"),
                }
            else:
                mr["last_run"] = None
            # 2) suggestion_counts (前端列展示用)
            sc = stats.get("suggestion_counts") or {}
            mr["suggestion_counts"] = {
                "total": int(sc.get("total", 0) or 0),
                "applied": int(sc.get("applied", 0) or 0),
                "dismissed": int(sc.get("dismissed", 0) or 0),
                "open": int(sc.get("open", 0) or 0),
            }
        except Exception:
            # stats 拉失败不阻断, last_run / suggestion_counts 置 None
            mr["last_run"] = None
            mr["suggestion_counts"] = None
        return mr

    items = await asyncio.gather(*[_attach_last_run(m) for m in mrs])
    failed = sum(1 for m in items if (m.get("last_run") or {}).get("status") == "failed")
    return {"items": items, "failed_mr_count": failed, "total": len(items)}


@router.get("/mrs/{project_id}/{mr_id}/timeline")
async def mr_timeline(
    project_id: int,
    mr_id: int,
    _user: User = Depends(get_current_user),
) -> dict:
    if not await pr_agent_client.is_configured():
        raise HTTPException(status_code=503, detail="pr-agent 未配置")
    try:
        return await pr_agent_client.mr_timeline(project_id, mr_id)
    except RuntimeError as e:
        raise HTTPException(status_code=502, detail=str(e))


@router.get("/mrs/{project_id}/{mr_id}/stats")
async def mr_stats(
    project_id: int,
    mr_id: int,
    _user: User = Depends(get_current_user),
) -> dict:
    if not await pr_agent_client.is_configured():
        raise HTTPException(status_code=503, detail="pr-agent 未配置")
    try:
        return await pr_agent_client.mr_stats(project_id, mr_id)
    except RuntimeError as e:
        raise HTTPException(status_code=502, detail=str(e))
