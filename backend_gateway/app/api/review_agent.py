"""/api/v1/review-agent — 透传 ReviewAgent telemetry SQLite 给前端.

ReviewAgent 不跑 HTTP 服务, 直接读它的本地 SQLite (db path 通过 env / settings_store 配).
字段尽量对齐 pr-agent /api/v1/pr-agent/*, 让前端 V2 视图几乎能复用 V1 代码.
"""
from __future__ import annotations
import asyncio
import logging
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query

from app.api.auth import get_current_user
from app.core import review_agent_client
from app.models.user import User

logger = logging.getLogger(__name__)
router = APIRouter()


def _unconfigured() -> None:
    raise HTTPException(
        status_code=503,
        detail="review-agent 未配置 (env REVIEW_AGENT_BASE_URL 或 settings_store \"review_agent.base_url\")",
    )


@router.get("/health")
async def health(_user: User = Depends(get_current_user)) -> dict:
    configured = await review_agent_client.is_configured()
    if not configured:
        return {"configured": False, "status": "off", "message": "未配置 base_url"}
    status, msg = await review_agent_client.probe()
    return {"configured": True, "status": status, "message": msg}


@router.get("/metrics/overview")
async def metrics_overview(
    since: Optional[str] = None,
    _user: User = Depends(get_current_user),
) -> dict:
    if not await review_agent_client.is_configured():
        return {"configured": False}
    try:
        return await review_agent_client.overview(since=since)
    except RuntimeError as e:
        raise HTTPException(status_code=502, detail=str(e))


@router.get("/metrics/rules")
async def metrics_rules(
    since: Optional[str] = None,
    _user: User = Depends(get_current_user),
) -> list[dict]:
    if not await review_agent_client.is_configured():
        return []
    try:
        return await review_agent_client.per_rule_stats(since=since)
    except RuntimeError as e:
        raise HTTPException(status_code=502, detail=str(e))


@router.get("/metrics/authors")
async def metrics_authors(
    since: Optional[str] = None,
    _user: User = Depends(get_current_user),
) -> list[dict]:
    if not await review_agent_client.is_configured():
        return []
    try:
        return await review_agent_client.per_author_stats(since=since)
    except RuntimeError as e:
        raise HTTPException(status_code=502, detail=str(e))


@router.get("/metrics/severity")
async def metrics_severity(
    since: Optional[str] = None,
    _user: User = Depends(get_current_user),
) -> list[dict]:
    if not await review_agent_client.is_configured():
        return []
    try:
        return await review_agent_client.severity_breakdown(since=since)
    except RuntimeError as e:
        raise HTTPException(status_code=502, detail=str(e))
    except Exception as e:
        logger.exception("metrics_severity unexpected error")
        raise HTTPException(status_code=502, detail=f"{type(e).__name__}: {e}")


@router.get("/mrs")
async def list_mrs(
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    project_id: Optional[int] = None,
    state: Optional[str] = None,
    since: Optional[str] = None,
    _user: User = Depends(get_current_user),
) -> dict:
    """MR 列表 + 每条 MR 的最近 run + 建议统计. 形态对齐 pr-agent /mrs.

    返回 {items: [...], failed_mr_count: N, total: N}.
    """
    if not await review_agent_client.is_configured():
        return {"items": [], "failed_mr_count": 0, "total": 0}
    try:
        all_items = await review_agent_client.list_mrs(
            limit=200, project_id=project_id, state=state, since=since,
        )
    except RuntimeError as e:
        raise HTTPException(status_code=502, detail=str(e))

    # failed MR 跨页扫出来给 banner 用 (banner 数字与列表同源, 不会出现 2 / 0 这种不一致).
    # 跟 page 是两份不同的过滤, 一致性优先.
    failed_items = [m for m in all_items if (m.get("last_run") or {}).get("status") == "failed"]
    failed = len(failed_items)
    total = len(all_items)
    page = all_items[offset:offset + limit]
    return {"items": page, "failed_mr_count": failed, "failed_items": failed_items, "total": total}


@router.get("/mrs/{project_id}/{mr_id}/timeline")
async def mr_timeline(
    project_id: int,
    mr_id: int,
    _user: User = Depends(get_current_user),
) -> dict:
    if not await review_agent_client.is_configured():
        raise HTTPException(status_code=503, detail="review-agent 未配置")
    try:
        return await review_agent_client.mr_timeline(project_id, mr_id)
    except RuntimeError as e:
        raise HTTPException(status_code=502, detail=str(e))


@router.get("/mrs/{project_id}/{mr_id}/stats")
async def mr_stats(
    project_id: int,
    mr_id: int,
    _user: User = Depends(get_current_user),
) -> dict:
    if not await review_agent_client.is_configured():
        raise HTTPException(status_code=503, detail="review-agent 未配置")
    try:
        return await review_agent_client.mr_stats(project_id, mr_id)
    except RuntimeError as e:
        raise HTTPException(status_code=502, detail=str(e))


@router.get("/dismissals/by-rule")
async def dismissals_by_rule(
    since: Optional[str] = None,
    _user: User = Depends(get_current_user),
) -> list[dict]:
    if not await review_agent_client.is_configured():
        _unconfigured()
    try:
        return await review_agent_client.dismissals_by_rule(since=since)
    except RuntimeError as e:
        raise HTTPException(status_code=502, detail=str(e))
