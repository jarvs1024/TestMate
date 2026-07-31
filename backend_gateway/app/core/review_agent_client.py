"""ReviewAgent telemetry HTTP client — 跟 pr_agent_client 同款 httpx 架构.

ReviewAgent 跑 HTTP 服务 (默认 host:3000), 后端容器走 host.docker.internal:3000.
base_url + api_token 实时从 settings_store 读, 兜底 .env.
返回字段尽量对齐 pr-agent schema, V2 视图可直接消费.
"""
from __future__ import annotations
import asyncio
import logging
import os
from datetime import datetime, timedelta, timezone
from typing import Any

import httpx

from app.core.settings_store import _rewrite_loopback, get

logger = logging.getLogger(__name__)

DEFAULT_BASE_URL = "http://127.0.0.1:3000"
V2_RECENT_WINDOW = timedelta(hours=24)


# ===== 配置/连接层 =====

async def _config() -> tuple[str, str]:
    """(base_url, token) — DB 优先, env 兜底, 代码默认兜底."""
    base = (
        (await get("review_agent.base_url", "")) or ""
        or os.environ.get("REVIEW_AGENT_BASE_URL", "") or ""
    )
    token = (
        (await get("review_agent.api_token", "")) or ""
        or os.environ.get("REVIEW_AGENT_API_TOKEN", "") or ""
    )
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
    base, _ = await _config()
    return bool(base)


async def probe() -> tuple[str, str]:
    """探 /api/v1/telemetry/health, 返回 (status, message)."""
    base, _ = await _config()
    if not base:
        return "off", "未配置 base_url"
    try:
        async with httpx.AsyncClient(timeout=3.0) as client:
            r = await client.get(f"{base}/api/v1/telemetry/health", headers=await _headers())
            if r.status_code == 200:
                data = r.json() or {}
                return "ok", (
                    f"backend={data.get('backend', '?')}, "
                    f"db={data.get('db_path', '?')}, "
                    f"mr={data.get('mr_records', '?')}, "
                    f"run={data.get('run_records', '?')}"
                )
            return "warn", f"HTTP {r.status_code}"
    except Exception as e:
        return "off", f"{type(e).__name__}: {e}"


async def _get(path: str, params: dict[str, Any] | None = None) -> Any:
    base, _ = await _config()
    url = f"{base}/api/v1/telemetry{path}"
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            r = await client.get(url, headers=await _headers(), params=params or {})
    except Exception as e:
        raise RuntimeError(f"review-agent 不可达 ({base}): {type(e).__name__}: {e}")
    if r.status_code == 404:
        raise RuntimeError(f"review-agent 404: {path}")
    if r.status_code >= 400:
        msg = r.text[:300] if r.text else ""
        raise RuntimeError(f"review-agent HTTP {r.status_code}: {msg}")
    try:
        return r.json()
    except Exception as e:
        raise RuntimeError(f"review-agent 返回非 JSON: {e}; body={r.text[:200]}")


# ===== pr-agent 字段兼容的 mapping 层 =====

def _v2_state(db_state: str | None, last_review_at: str | None) -> str:
    """ReviewAgent 没有 'updated' 标识. 基于 last_review_at 时间窗补 'updated' (24h 内)."""
    if not db_state:
        return "opened"
    if db_state != "opened":
        return db_state
    if not last_review_at:
        return "opened"
    try:
        ts_s = last_review_at
        if ts_s.endswith("Z"):
            ts_s = ts_s[:-1] + "+00:00"
        ts = datetime.fromisoformat(ts_s.split("+")[0].split(".")[0])
        if ts.tzinfo is None:
            ts = ts.replace(tzinfo=timezone.utc)
        now = datetime.now(timezone.utc)
        if now - ts <= V2_RECENT_WINDOW:
            return "updated"
    except Exception:
        return "opened"
    return "opened"


def _map_mr_row(m: dict) -> dict:
    return {
        "project_id": m.get("project_id"),
        "mr_id": m.get("mr_iid"),
        "title": m.get("title"),
        "author": m.get("author_sticky") or m.get("author_username") or "",
        "source_branch": m.get("source_branch"),
        "target_branch": m.get("target_branch"),
        "state": m.get("state") or "opened",
        "opened_at": m.get("created_at"),
        "last_seen_at": m.get("updated_at"),
        "merged_at": m.get("merged_at"),
        "url": m.get("url"),
        "_v2_state": _v2_state(m.get("state"), m.get("last_review_at")),
        "last_run": None,
        "suggestion_counts": None,
    }


# ===== 数据查询 API =====

async def overview(since: str | None = None) -> dict:
    """对齐 pr-agent /metrics/overview 形态: mrs / suggestions / runs / severity_breakdown."""
    params_mrs: dict[str, Any] = {"limit": 200}
    params_summary: dict[str, Any] = {}
    if since:
        params_mrs["since"] = since
        params_summary["since"] = since

    mrs_raw = await _get("/mrs", params_mrs) or {}
    items = mrs_raw.get("mrs") if isinstance(mrs_raw, dict) else (mrs_raw or [])
    state_count = {"opened": 0, "merged": 0, "closed": 0}
    for m in items:
        s = (m.get("state") or "opened").lower()
        if s in state_count:
            state_count[s] += 1
        else:
            state_count["closed"] += 1

    ov_data = await _get("/metrics/overview", params_summary or None) or {}
    by_status = ov_data.get("by_status") or {}
    runs_total = int(ov_data.get("total_runs") or 0)
    runs_failed = int(by_status.get("failed") or 0)
    runs_success_n = int(by_status.get("success") or 0)
    runs_skipped = int(by_status.get("skipped") or 0)
    success_rate = round((runs_success_n + runs_skipped) / runs_total, 4) if runs_total else 0.0

    sev_data = await _get("/metrics/severity") or {}
    sev_counts = sev_data.get("severity_counts") or {}

    sev_breakdown = [
        {
            "severity": sev,
            "total": int(total),
            "applied": 0,
            "dismissed": 0,
            "open": int(total),
            "superseded": 0,
            "adoption_rate": 0.0,
            "dismissal_rate": 0.0,
        }
        for sev, total in sev_counts.items()
    ]
    sev_breakdown.sort(key=lambda x: -x["total"])

    sug_total = sum(int(v or 0) for v in sev_counts.values())

    return {
        "since": since,
        "mrs": {
            "total": len(items),
            "merged": state_count["merged"],
            "open": state_count["opened"],
            "closed": state_count["closed"],
        },
        "suggestions": {
            "total": sug_total,
            "applied": 0,
            "dismissed": 0,
            "open": sug_total,
            "adoption_rate": 0.0,
            "dismissal_rate": 0.0,
        },
        "runs": {
            "total": runs_total,
            "failed": runs_failed,
            "success_rate": success_rate,
        },
        "severity_breakdown": sev_breakdown,
    }


async def per_rule_stats(since: str | None = None) -> list[dict]:
    """聚合真正的 rule_keys.

    ReviewAgent /metrics/rules 端点实际返回的 rule_key 是 severity
    (medium/high/critical) 串, 不是真正的 SSD-RULE-XXX 规则名.
    真正的规则名存在 suggestion.rule_keys 字段, 逗号分隔多键.
    改方案: 拉所有 MR 的 suggestions, 聚合 suggestion.rule_keys.

    per-MR 并发 (sem=8), since 暂不实现过滤 (留给 ReviewAgent 服务端补).
    """
    mrs_raw = await _get("/mrs", {"limit": 200}) or {}
    mrs_list = mrs_raw.get("mrs") if isinstance(mrs_raw, dict) else (mrs_raw or [])

    sem = asyncio.Semaphore(8)

    async def fetch_sugs(mr: dict) -> list[dict]:
        pid = mr.get("project_id")
        iid = mr.get("mr_iid")
        if pid is None or iid is None:
            return []
        async with sem:
            try:
                r = await _get(f"/mr/{pid}/{iid}/suggestions") or {}
                items = r.get("suggestions") if isinstance(r, dict) else (r or [])
                return items or []
            except Exception:
                return []

    nested = await asyncio.gather(*[fetch_sugs(m) for m in mrs_list])

    bucket: dict[str, dict] = {}
    for sugs in nested:
        for s in sugs or []:
            rule_keys_str = s.get("rule_keys") or ""
            rule_arr = [k.strip() for k in rule_keys_str.split(",") if k.strip()]
            if not rule_arr:
                rule_arr = ["(no_rule_key)"]
            state = s.get("state") or "open"
            for rk in rule_arr:
                slot = bucket.setdefault(rk, {
                    "rule_key": rk,
                    "total": 0,
                    "applied": 0,
                    "dismissed": 0,
                    "open": 0,
                })
                slot["total"] += 1
                if state == "applied":
                    slot["applied"] += 1
                elif state == "dismissed":
                    slot["dismissed"] += 1
                elif state == "open":
                    slot["open"] += 1

    out = []
    for v in bucket.values():
        v["adoption_rate"] = round(v["applied"] / v["total"], 4) if v["total"] else 0.0
        out.append(v)
    out.sort(key=lambda x: -x["total"])
    return out


async def per_author_stats(since: str | None = None) -> list[dict]:
    """/metrics/authors.{author, runs} → pr-agent AuthorStat 形状."""
    params: dict[str, Any] = {}
    if since:
        params["since"] = since
    data = await _get("/metrics/authors", params or None) or {}
    return [
        {
            "author": r.get("author"),
            "mr_count": 0,
            "suggestion_count": int(r.get("runs") or 0),
            "applied": 0,
            "dismissed": 0,
            "runs_by_command": {},
            "adoption_rate": 0.0,
        }
        for r in (data.get("authors") or [])
    ]


async def severity_breakdown(since: str | None = None, pr_url: str | None = None) -> list[dict]:
    """/metrics/severity → pr-agent severity_breakdown 形状."""
    params: dict[str, Any] = {}
    if since:
        params["since"] = since
    data = await _get("/metrics/severity", params or None) or {}
    counts = data.get("severity_counts") or {}
    out = [
        {
            "severity": sev,
            "total": int(total),
            "applied": 0,
            "dismissed": 0,
            "open": int(total),
            "superseded": 0,
            "adoption_rate": 0.0,
            "dismissal_rate": 0.0,
        }
        for sev, total in counts.items()
    ]
    out.sort(key=lambda x: -x["total"])
    return out


async def list_mrs(
    limit: int = 50, offset: int = 0, project_id: int | None = None,
    state: str | None = None, since: str | None = None,
) -> list[dict]:
    """/mrs → pr-agent MrRow 形态, 附 last_run + suggestion_counts.

    并发 (sem=8) 给每条 MR 拉 /mr/{}/+ /stats 补全 last_run/suggestion_counts.
    单条 MR 拉取失败不阻断列表.
    """
    params: dict[str, Any] = {"limit": max(limit + offset, 50)}
    if project_id is not None:
        params["project_id"] = project_id
    if state:
        params["state"] = state
    if since:
        params["since"] = since
    raw = await _get("/mrs", params) or {}
    items = raw.get("mrs") if isinstance(raw, dict) else (raw or [])
    rows = [_map_mr_row(m) for m in items]

    sem = asyncio.Semaphore(8)

    async def enrich(row: dict) -> None:
        pid, iid = row["project_id"], row["mr_id"]
        if pid is None or iid is None:
            return
        try:
            detail = await _get(f"/mr/{pid}/{iid}") or {}
            recent = detail.get("recent_runs") or []
            if recent:
                r = recent[0]
                row["last_run"] = {
                    "run_id": str(r.get("id") or ""),
                    "command": r.get("command"),
                    "status": r.get("status"),
                    "model": r.get("model"),
                    "started_at": r.get("started_at"),
                    "finished_at": r.get("finished_at"),
                    "duration_ms": r.get("duration_ms"),
                }
        except Exception:
            row["last_run"] = None
        try:
            stats = await _get(f"/mr/{pid}/{iid}/stats") or {}
            state_counts = stats.get("state_counts") or {}
            action_counts = stats.get("action_counts") or {}
            adopted = stats.get("adopted")
            if isinstance(adopted, int) and adopted > 0:
                applied = adopted
            else:
                applied = int(action_counts.get("applied", 0)) or int(state_counts.get("applied", 0))
            row["suggestion_counts"] = {
                "total": int(stats.get("total") or 0),
                "applied": applied,
                "dismissed": int(stats.get("dismissed") or 0),
                "open": int(stats.get("open") or 0),
                "superseded": 0,
            }
        except Exception:
            row["suggestion_counts"] = None

    async def bounded(row: dict) -> None:
        async with sem:
            await enrich(row)

    await asyncio.gather(*[bounded(r) for r in rows])
    return rows[offset:offset + limit]


# ===== V2 视图 TimelineResp 字段映射 =====
# MR (raw → MrRow) 字段映射借 _map_mr_row, suggestions / runs / actions
# 从 ReviewAgent 服务各端点单独拉 + 字段 rename, 拼成 pr-agent 兼容结构.

def _map_suggestion(s: dict) -> dict:
    """ReviewAgent /mr/{pid}/{iid}/suggestions[] → pr-agent SuggestionRow."""
    rule_keys = s.get("rule_keys") or ""
    rule_arr = [k.strip() for k in rule_keys.split(",") if k.strip()] if rule_keys else []
    importance = s.get("importance")
    score = s.get("score")
    return {
        "id": s.get("id"),
        "suggestion_id": s.get("note_id"),
        "file": s.get("file_path"),
        "line": s.get("target_line"),
        "label": s.get("header"),
        "importance": float(importance) if importance is not None else None,
        "score": float(score) if score is not None else None,
        "severity": (s.get("severity") or "unknown"),
        "severity_source": s.get("severity_source"),
        "rule_keys": rule_arr,
        "one_sentence_summary": s.get("one_sentence_summary"),
        "state": s.get("state"),
        "posted_at": s.get("created_at") or s.get("posted_at"),
        "applied_at": s.get("applied_at"),
        "dismissed_at": s.get("dismissed_at"),
        "dismissed_by": s.get("dismissed_by"),
        "dismissed_reason": s.get("dismissed_reason"),
    }


def _map_run(r: dict) -> dict:
    """ReviewAgent /mr/{pid}/{iid}/runs[] 或 /mr/{pid}/{iid}.recent_runs[] → pr-agent RunRow."""
    return {
        "run_id": str(r.get("id") or r.get("run_id") or ""),
        "command": r.get("command"),
        "status": r.get("status"),
        "model": r.get("model"),
        "started_at": r.get("started_at"),
        "finished_at": r.get("finished_at"),
        "duration_ms": r.get("duration_ms"),
        "error": r.get("error"),
        "suggestion_count": r.get("suggestion_count"),
        "triggered_by": r.get("triggered_by") or r.get("actor_username"),
    }


def _build_actions_from_events(events: list[dict]) -> list[dict]:
    """从 /timeline events 提取 suggestion_action → ActionRow.
    ReviewAgent event_type='suggestion_action' 的 event:
      {at, event_type, event_id, detail, state}
    不充分,没 actor / note, 所以本字段拼不出来就返回 [].
    """
    out = []
    for e in events or []:
        if e.get("event_type") == "suggestion_action":
            out.append({
                "id": int(e.get("event_id") or 0),
                "suggestion_id": str(e.get("detail") or ""),
                "action": e.get("state") or "adopted",
                "actor": None,
                "note": None,
                "at": e.get("at"),
            })
    return out


async def mr_timeline(project_id: int, mr_id: int) -> dict:
    """组装 TimelineResp 形态: mr / suggestions / runs / actions / events.

    并发拉 ReviewAgent 4 个端点补齐 V2 视图所需结构:
      - /mr/{pid}/{iid}          → mr detail (含 recent_runs 补 runs)
      - /mr/{pid}/{iid}/suggestions → 建议列表
      - /mr/{pid}/{iid}/runs         → 全部运行
      - /mr/{pid}/{iid}/timeline     → 原始 events
    单端点失败不阻断, 拉不到的字段留空.
    """
    base_tl = f"/mr/{project_id}/{mr_id}"
    async def _safe(path: str) -> Any:
        try:
            return await _get(path) or {}
        except Exception:
            return {}

    detail_res, sugs_res, runs_res, tl_res = await asyncio.gather(
        _safe(base_tl),
        _safe(base_tl + "/suggestions"),
        _safe(base_tl + "/runs"),
        _safe(base_tl + "/timeline"),
    )

    # mr
    mr_raw = detail_res.get("mr") or {}
    mr_row = _map_mr_row(mr_raw) if mr_raw else None

    # suggestions
    sug_items = sugs_res.get("suggestions") if isinstance(sugs_res, dict) else (sugs_res or [])
    suggestion_rows = [_map_suggestion(s) for s in (sug_items or [])]

    # runs: 优先用 /runs 详情, fallback 到 detail.recent_runs
    run_items = runs_res.get("runs") if isinstance(runs_res, dict) else (runs_res or [])
    run_rows = [_map_run(r) for r in (run_items or [])]
    if not run_rows:
        recent = detail_res.get("recent_runs") or []
        if recent:
            run_rows = [_map_run(r) for r in recent]

    # actions: 从 events 抽 suggestion_action events (字段可能不全)
    events = tl_res.get("events") if isinstance(tl_res, dict) else []
    action_rows = _build_actions_from_events(events)

    return {
        "mr": mr_row,
        "suggestions": suggestion_rows,
        "runs": run_rows,
        "actions": action_rows,
        "events": events or [],
        "summary": (tl_res.get("summary") if isinstance(tl_res, dict) else {}) or {},
    }


async def mr_stats(project_id: int, mr_id: int) -> dict:
    """透传 /mr/{pid}/{iid}/stats."""
    return await _get(f"/mr/{project_id}/{mr_id}/stats") or {}


async def dismissals_by_rule(since: str | None = None) -> list[dict]:
    """/dismissals/by-rule → pr-agent 形态."""
    params: dict[str, Any] = {}
    if since:
        params["since"] = since
    raw = await _get("/dismissals/by-rule", params or None) or {}
    rules = raw.get("rules") or []
    return [
        {
            "rule_key": r.get("rule_key"),
            "dismissal_count": int(r.get("dismissal_count") or 0),
            "reasons": r.get("reasons") or [],
        }
        for r in rules
    ]
