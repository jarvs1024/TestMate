"""/api/v1/pr-agent — 透传 pr-agent telemetry 给前端.

路径 / 字段跟 pr-agent /api/v1/telemetry/* 完全对齐,
前端不需要直接连 pr-agent (避免暴露 token / 跨域).
"""
from __future__ import annotations
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


@router.get("/mrs")
async def list_mrs(
    limit: int = Query(50, ge=1, le=200),
    project_id: Optional[int] = None,
    state: Optional[str] = None,
    since: Optional[str] = None,
    _user: User = Depends(get_current_user),
) -> list[dict]:
    if not await pr_agent_client.is_configured():
        return []
    try:
        return await pr_agent_client.list_mrs(
            limit=limit, project_id=project_id, state=state, since=since,
        )
    except RuntimeError as e:
        raise HTTPException(status_code=502, detail=str(e))


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
