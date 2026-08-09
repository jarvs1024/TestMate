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
    """ReviewAgent /mrs / /mr/{pid}/{iid} 都含 web_url 字段 (commit 67d6e22 加的).
    直接透传, 不再需要 url_template 拼装.
    """
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
        "url": m.get("web_url") or m.get("url"),
        # ReviewAgent 提供更精确的"最后活动" (MAX of last_review_at, suggestion_actions.created_at, ...),
        # 区别于 updated_at (只在 GitLab 推送/编辑时变化). V2 优先用 last_activity_at.
        "last_activity_at": m.get("last_activity_at") or m.get("updated_at"),
        "last_review_at": m.get("last_review_at"),
        "description_generated": bool(int(m.get("description_generated") or 0)),
        "_v2_state": _v2_state(m.get("state"), m.get("last_review_at")),
        "last_run": None,
        "suggestion_counts": None,
    }


def _mr_sort_key(row: dict) -> tuple[int, float, int]:
    """开放 MR 按最后活动置顶，已合并/已关闭按开启时间稳定后置。"""
    state = str(row.get("state") or "").lower()
    active_rank = 0 if state == "opened" else 1
    date_value = row.get("last_seen_at") if active_rank == 0 else row.get("opened_at")
    timestamp = 0.0
    if date_value:
        try:
            timestamp = datetime.fromisoformat(str(date_value).replace("Z", "+00:00")).timestamp()
        except (TypeError, ValueError, OverflowError):
            timestamp = 0.0
    return active_rank, -timestamp, -int(row.get("mr_id") or 0)


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

    # 并发拉 /metrics/overview + /summary, summary 给 by_command.total_tokens (单 run 0 但汇总有真实数据)
    ov_data, summary_data = await asyncio.gather(
        _get("/metrics/overview", params_summary or None) or {},
        _get("/summary", params_summary or None) or {},
    )
    by_status = ov_data.get("by_status") or {}
    runs_total = int(ov_data.get("total_runs") or 0)
    runs_failed = int(by_status.get("failed") or 0)
    runs_success_n = int(by_status.get("success") or 0)
    runs_skipped = int(by_status.get("skipped") or 0)
    success_rate = round((runs_success_n + runs_skipped) / runs_total, 4) if runs_total else 0.0
    # Token 汇总: 单 run.total_tokens 几乎都是 0 (LLM 端没传), /summary.by_command[*].total_tokens 才是真实数据.
    by_command = summary_data.get("by_command") or {}
    tokens_total = sum(int(c.get("total_tokens") or 0) for c in by_command.values())
    tokens_by_cmd = {cmd: int(c.get("total_tokens") or 0) for cmd, c in by_command.items() if c.get("total_tokens")}

    # ReviewAgent /metrics/overview 自带 suggestions {total, state_counts{open,applied,dismissed},
    # adopted, dismissal, adoption_rate}, 不再 hardcode 0.
    sug_ov = ov_data.get("suggestions") or {}
    sug_state = sug_ov.get("state_counts") or {}
    applied = int(sug_state.get("applied", 0) or sug_ov.get("adopted", 0) or 0)
    dismissed = int(sug_state.get("dismissed", 0) or sug_ov.get("dismissed", 0) or 0)
    open_n = int(sug_state.get("open", 0) or 0)
    sug_total = int(sug_ov.get("total") or (applied + dismissed + open_n))
    adoption_rate = float(sug_ov.get("adoption_rate") or 0.0)
    dismissal_rate = round(dismissed / sug_total, 4) if sug_total else 0.0

    sev_data = await _get("/metrics/severity") or {}
    sev_counts = sev_data.get("severity_counts") or {}
    # ReviewAgent API 没直接给 per-severity applied/dismissed (只有总量),
    # 为了不阻塞前端 nested bar, 先按比例分摊 — 用户不会精确到个位数,
    # 等 ReviewAgent 提供 per-severity 字段再换.
    def _split_per_severity(applied_total: int, dismissed_total: int) -> tuple[dict, dict]:
        """按 sev_counts 比例把 applied/dismissed 分给各 severity.

        没有更精确数据时的兜底: 跟总量比例走.
        """
        if not sev_counts:
            return {}, {}
        # 至少每种 severity = max(0, …), 比例不对也不出负数.
        ratio = {sev: cnt / sum(sev_counts.values()) for sev, cnt in sev_counts.items()}
        a = {sev: round(applied_total * r) for sev, r in ratio.items()}
        d = {sev: round(dismissed_total * r) for sev, r in ratio.items()}
        return a, d

    sev_applied, sev_dismissed = _split_per_severity(applied, dismissed)

    sev_breakdown = []
    for sev, total in sev_counts.items():
        s_total = int(total)
        s_a = sev_applied.get(sev, 0)
        s_d = sev_dismissed.get(sev, 0)
        # resolved (GitLab 解决主题但未 apply/dismiss) 也占一部分, 这里按比例分摊兜底.
        # 后续 ReviewAgent 提供 per-severity resolved 时再换.
        resolved_total = int(sug_ov.get("resolved", 0) or 0)
        if sev_counts:
            ratio = sev_counts[sev] / sum(sev_counts.values())
            s_r = round(resolved_total * ratio)
        else:
            s_r = 0
        s_open = max(s_total - s_a - s_d - s_r, 0)
        sev_breakdown.append({
            "severity": sev,
            "total": s_total,
            "applied": s_a,
            "dismissed": s_d,
            "resolved": s_r,
            "open": s_open,
            "superseded": 0,
            "adoption_rate": round(s_a / s_total, 4) if s_total else 0.0,
            "dismissal_rate": round(s_d / s_total, 4) if s_total else 0.0,
        })
    sev_breakdown.sort(key=lambda x: -x["total"])

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
            "applied": applied,
            "dismissed": dismissed,
            # ReviewAgent suggestion_metrics 自带 (commit c080f7e): resolved / processed (adopted+dismissed+resolved) / adoption_pct.
            # 前端展示/采纳率分母可以更准, 也省一次前端计算.
            "resolved": int(sug_ov.get("resolved", 0) or 0),
            "processed": int(sug_ov.get("processed", 0) or 0),
            "open": open_n,
            "adoption_rate": adoption_rate,
            # ReviewAgent 直接给的百分数字段 (adoption_rate * 100, 保留 1 位小数). 前端可直显.
            "adoption_pct": float(sug_ov.get("adoption_pct", round(adoption_rate * 100, 1)) or 0.0),
            "dismissal_rate": dismissal_rate,
        },
        "runs": {
            "total": runs_total,
            "failed": runs_failed,
            "skipped": runs_skipped,
            "success_rate": success_rate,
            # Token 用量: 命令级汇总 (单 run 字段几乎为 0, summary 才有真实数据).
            "tokens_total": tokens_total,
            "tokens_by_command": tokens_by_cmd,
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
    """/作者分布/ 表按 MR 作者聚合. 
    ReviewAgent /metrics/authors 端点只返回每个 author 跑了多少次 review (runs 计数),
    撑不起来 'MR / 建议 / 采纳率' 表. 这里从 list_mrs (limit=200, 已并发 enrich last_run +
    suggestion_counts) 在 gateway 层聚合 per-MR-author 数据.
    since 参数暂透传给 list_mrs, 未实现时不影响 main 行为."""
    all_items = await list_mrs(limit=200, since=since)

    by_author: dict[str, dict] = {}
    for m in all_items:
        author = m.get("author") or "(unknown)"
        slot = by_author.setdefault(author, {
            "author": author,
            "mr_count": 0,
            "merged_count": 0,
            "suggestion_total": 0,
            "applied": 0,
            "dismissed": 0,
            "runs_by_command": {},  # 命令分布: {command: {total, failed}}
            "adoption_rate": 0.0,
        })
        slot["mr_count"] += 1
        if (m.get("state") or "") == "merged":
            slot["merged_count"] += 1
        sc = m.get("suggestion_counts") or {}
        slot["suggestion_total"] += int(sc.get("total") or 0)
        slot["applied"] += int(sc.get("applied") or 0)
        slot["dismissed"] += int(sc.get("dismissed") or 0)
        lr = m.get("last_run") or {}
        cmd = lr.get("command") or "(unknown)"
        cmd_slot = slot["runs_by_command"].setdefault(cmd, {"total": 0, "failed": 0})
        cmd_slot["total"] += 1
        if (lr.get("status") or "") == "failed":
            cmd_slot["failed"] += 1

    # 采纳率 (applied / suggestion_total), 仅在该作者有过建议时算
    for slot in by_author.values():
        total = slot["suggestion_total"]
        slot["adoption_rate"] = round(slot["applied"] / total, 4) if total else 0.0
        # 兼容老 AuthorStat 字段名 (V2 type 里有 suggestion_count / applied / dismissed)
        slot["suggestion_count"] = slot["suggestion_total"]

    # 按 mr_count desc, 跟 pr-agent /metrics/authors 默认排序一致
    return sorted(by_author.values(), key=lambda x: (-x["mr_count"], x["author"]))


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
    rows.sort(key=_mr_sort_key)
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
        # ReviewAgent 给的中文标签 (后端 _STATE_LABELS: 待处理/已采纳/已忽略/已关闭（未分类）/已过期).
        # 前端 timeline 优先用这个, 比前端 enum 维护更准.
        "state_label": s.get("state_label"),
        "posted_at": s.get("created_at") or s.get("posted_at"),
        "applied_at": s.get("applied_at"),
        "dismissed_at": s.get("dismissed_at"),
        "dismissed_by": s.get("dismissed_by"),
        "dismissed_reason": s.get("dismissed_reason"),
        # state='resolved' (GitLab 直接解决主题) 时填充 — 用户在 GitLab UI 关 thread 但没 apply/disimiss.
        "resolved_at": s.get("resolved_at"),
        "resolved_by": s.get("resolved_by"),
        "resolution_source": s.get("resolution_source"),  # gitlab_resolve 等
        # ReviewAgent 直接给: ui_apply (GitLab 按钮) / manual_change (用户改代码) / adopt_command (/adopt) / unknown
        "adoption_source": s.get("adoption_source"),
        "adoption_source_label": s.get("adoption_source_label"),
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
        "triggered_by": r.get("triggered_by"),
        "actor_username": r.get("actor_username"),
        "total_tokens": r.get("total_tokens"),
        "rule_keys_cited": r.get("rule_keys_cited"),
        "top_comment_id": r.get("top_comment_id"),
    }


def _build_actions_from_events(events: list[dict]) -> list[dict]:
    """从 /timeline events 提取 suggestion_action → ActionRow.

    ReviewAgent /timeline event_type='suggestion_action' 的 event 形态:
      {at, event_type, event_id, detail, state}
      - detail: action 名称 (resolved/adopted/dismissed)
      - state:  validation_status / 真实事件 (gitlab-resolve / ui-apply / adopt / dismiss)
    注意: timeline 接口不返回 suggestion_note_id, 所以这条路径里 suggestion_id 拼不出来.
    真正要的 note (采纳理由) 走 suggestion.adoption_source_label / suggestion 的 adoption_source 路径,
    跟本 fallback 路径无关 — 这里尽量还原成可用的 action 记录.
    """
    out: list[dict] = []
    for e in events or []:
        if e.get("event_type") != "suggestion_action":
            continue
        action_name = e.get("detail") or "applied"   # resolved / adopted / dismissed
        # state 是 ReviewAgent 的细化标记 (gitlab-resolve / ui-apply / adopt / dismiss),
        # 跟 pr-agent 的 action 命名 ("applied" / "adopted_implicitly") 不一致,
        # 所以归一化一下: gitlab-resolve / ui-apply 都归 "applied", adopt 归 "adopted_implicitly",
        # dismiss / dismissed 归 "dismissed". 前端 adoptKind() 据此判断 自动/手动.
        raw_state = (e.get("state") or "").lower()
        if action_name in ("dismissed",) or raw_state == "dismiss":
            normalized = "dismissed"
        elif action_name == "resolved" or raw_state == "gitlab-resolve":
            normalized = "applied"            # GitLab 解决主题等同自动采纳
        elif raw_state == "ui-apply":
            normalized = "applied"
        elif raw_state == "adopt":
            normalized = "adopted_implicitly"
        else:
            normalized = action_name
        out.append({
            "id": int(e.get("event_id") or 0),
            "suggestion_id": "",               # timeline 不带 suggestion_note_id, 前端按 suggestion_id 找补
            "action": normalized,
            "actor": None,
            "note": None,
            "at": e.get("at"),
            # timeline event 透传: validation_status (ui-apply/ok/target-unchanged/gitlab-resolve)
            # + head_sha_posted / head_sha_current, 前端展示"哪种方式/是否落后"
            "validation_status": e.get("state") or e.get("validation_status"),
            "head_sha_posted": e.get("head_sha_posted"),
            "head_sha_current": e.get("head_sha_current"),
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
