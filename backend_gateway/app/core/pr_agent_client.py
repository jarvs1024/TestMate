"""pr-agent telemetry API client — 配置从 DB 读, 兜底用 .env.

pr-agent 容器暴露 /api/v1/telemetry/* 端点 (FastAPI), 我们代理到前端,
让前端不用直接连 pr-agent (避免 token 泄漏 + 跨域).
"""
from __future__ import annotations
import logging
from typing import Any

import httpx

from app.core.settings_store import get, _rewrite_loopback

logger = logging.getLogger(__name__)

DEFAULT_BASE_URL = "http://127.0.0.1:5050"


async def _config() -> tuple[str, str]:
    """(base_url, token) 实时从 DB 读, 兜底用 .env.
    base_url 在容器内会被 _rewrite_loopback 把 127.0.0.1 改成 host.docker.internal.
    """
    base = (await get("pr_agent.base_url", "")) or ""
    token = (await get("pr_agent.api_token", "")) or ""
    if not base:
        base = DEFAULT_BASE_URL
    return _rewrite_loopback(base).rstrip("/"), token


async def _headers() -> dict[str, str]:
    _, token = await _config()
    h = {"Accept": "application/json"}
    if token:
        h["Authorization"] = f"Bearer {token}"
    return h


async def is_configured() -> bool:
    """pr-agent 是否配过 base_url (不论联通性, 只看配置)."""
    base, _ = await _config()
    return bool(base)


async def probe() -> tuple[str, str]:
    """探 pr-agent /health, 返回 (status, message).
    status: ok / warn / off
    """
    base, _ = await _config()
    if not base:
        return "off", "未配置 base_url"
    try:
        async with httpx.AsyncClient(timeout=3.0) as client:
            r = await client.get(f"{base}/api/v1/telemetry/health", headers=await _headers())
            if r.status_code == 200:
                data = r.json() or {}
                return "ok", f"{data.get('backend', '?')}"
            return "warn", f"HTTP {r.status_code}"
    except Exception as e:
        return "off", f"{type(e).__name__}"


async def _get(path: str, params: dict[str, Any] | None = None) -> Any:
    """透传 pr-agent telemetry 接口. 出错时抛 RuntimeError 给上层处理."""
    base, _ = await _config()
    url = f"{base}/api/v1/telemetry{path}"
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            r = await client.get(url, headers=await _headers(), params=params or {})
    except Exception as e:
        raise RuntimeError(f"pr-agent 不可达 ({base}): {type(e).__name__}: {e}")
    if r.status_code == 404:
        raise RuntimeError(f"pr-agent 404: {path}")
    if r.status_code >= 400:
        # 把 token 类敏感字段从错误信息里剥掉
        msg = r.text[:300] if r.text else ""
        raise RuntimeError(f"pr-agent HTTP {r.status_code}: {msg}")
    try:
        return r.json()
    except Exception as e:
        raise RuntimeError(f"pr-agent 返回非 JSON: {e}; body={r.text[:200]}")


async def overview(since: str | None = None) -> dict:
    params = {"since": since} if since else None
    return await _get("/metrics/overview", params)


async def per_rule_stats(since: str | None = None) -> list[dict]:
    params = {"since": since} if since else None
    return await _get("/metrics/rules", params)


async def per_author_stats(since: str | None = None) -> list[dict]:
    params = {"since": since} if since else None
    return await _get("/metrics/authors", params)


async def severity_breakdown(since: str | None = None, pr_url: str | None = None) -> list[dict]:
    """严重等级分桶 (critical / high / medium / low / unknown).
    pr_url 用于从 git provider 拉项目级 rule file (e.g. .agents/rules/*.md).
    """
    params: dict[str, Any] = {}
    if since: params["since"] = since
    if pr_url: params["pr_url"] = pr_url
    return await _get("/metrics/severity", params or None)


async def list_mrs(
    limit: int = 50,
    project_id: int | None = None,
    state: str | None = None,
    since: str | None = None,
) -> list[dict]:
    params: dict[str, Any] = {"limit": limit}
    if project_id is not None:
        params["project_id"] = project_id
    if state:
        params["state"] = state
    if since:
        params["since"] = since
    return await _get("/mrs", params)


async def mr_timeline(project_id: int, mr_id: int) -> dict:
    return await _get(f"/mrs/{project_id}/{mr_id}/timeline")


async def mr_stats(project_id: int, mr_id: int) -> dict:
    return await _get(f"/mrs/{project_id}/{mr_id}/stats")


async def dismissals_by_rule(since: str | None = None) -> list[dict]:
    """按 rule_key 聚合 dismiss 计数 + reason 分布 (来自 pr-agent /dismissals/by-rule).

    用于前端"近期被忽略规则"汇总卡. 透传 pr-agent 响应, 不做字段裁剪.
    """
    params = {"since": since} if since else None
    return await _get("/dismissals/by-rule", params)
