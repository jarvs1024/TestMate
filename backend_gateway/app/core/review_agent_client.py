"""ReviewAgent telemetry SQLite client — 直读本地 SQLite 文件.

ReviewAgent (/Users/jarvs/ReviewAgent) 现在是 Python 库 + 本地 SQLite, 不跑 HTTP 服务.
为不引入新进程, 我们直接读它的 telemetry.db (docker compose 里 mount 进 backend 容器).
接口形态对齐 pr_agent_client (overview / list_mrs / mr_timeline / ...), 前端共用视图.

路径配置优先级: settings_store('review_agent.db_path') > env REVIEW_AGENT_DB_PATH > config 默认.
默认空表示未配置, 调用 is_configured() 返回 False.

SQLite 字段说明 (reviewagent/telemetry):
  mr_activity: project_id, mr_iid, title, author_username, source_branch, target_branch,
               state, created_at, updated_at, merged_at, author_sticky, last_review_at, ...
  suggestions: id, project_id, mr_iid, note_id, file_path, target_line, target_line_end,
               existing_code, improved_code, header, severity, head_sha, state,
               created_at, updated_at, applied_at, dismissed_at, dismissed_by, dismissed_reason,
               rule_keys, one_sentence_summary, importance, score, fingerprint, cohort_key,
               severity_source, label, posted_at
  review_runs: id, project_id, mr_iid, command, triggered_by, actor_username, started_at,
               finished_at, status, error, model, prompt_tokens, completion_tokens,
               total_tokens, duration_ms, rule_keys_cited, suggestion_count
  suggestion_actions: id, project_id, mr_iid, suggestion_note_id, file_path, target_line,
               action, actor_username, reason, validation_status, head_sha_posted,
               head_sha_current, created_at

immutable=1: 跨进程只读访问 + ReviewAgent 本体可能正在写, immutable 跳过 WAL/journal 写锁.
"""
from __future__ import annotations
import asyncio
import logging
import os
import sqlite3
from pathlib import Path
from typing import Any

from app.core.settings_store import get

logger = logging.getLogger(__name__)


async def _db_path() -> str:
    p = (await get("review_agent.db_path", "")) or os.environ.get("REVIEW_AGENT_DB_PATH", "")
    return p.strip()


async def is_configured() -> bool:
    p = await _db_path()
    return bool(p) and Path(p).exists()


def _query_sync(path: str, sql: str, params: tuple, fetchone: bool):
    """同步 query — 必须包到 asyncio.to_thread 里跑. fetchone=True 时只取第一行."""
    uri = f"file:{path}?mode=ro&immutable=1"
    conn = sqlite3.connect(uri, uri=True, timeout=5.0)
    conn.row_factory = sqlite3.Row
    try:
        cur = conn.execute(sql, params)
        rows = cur.fetchall()
        if fetchone:
            return dict(rows[0]) if rows else None
        return [dict(r) for r in rows]
    finally:
        conn.close()


async def _fetchall(sql: str, params: tuple = ()) -> list[dict]:
    p = await _db_path()
    if not p:
        return []
    return await asyncio.to_thread(_query_sync, p, sql, params, False)


async def _fetchone(sql: str, params: tuple = ()) -> dict | None:
    p = await _db_path()
    if not p:
        return None
    return await asyncio.to_thread(_query_sync, p, sql, params, True)


async def probe() -> tuple[str, str]:
    if not await is_configured():
        return "off", "未配置 db_path 或文件不存在"
    try:
        await _fetchall("SELECT 1 FROM mr_activity LIMIT 1")
        return "ok", "可读"
    except Exception as e:
        return "off", f"{type(e).__name__}: {e}"


# ===== 数据映射 =====

async def overview(since: str | None = None) -> dict:
    """汇总指标: MR / 建议 / runs / 严重等级分桶. 对齐 pr-agent /metrics/overview."""
    params: list[Any] = []
    where_sug = ""
    if since:
        where_sug = " WHERE created_at >= ?"
        params.append(since)

    mrs_total = await _fetchone("SELECT COUNT(*) AS n FROM mr_activity") or {"n": 0}
    mrs_open = await _fetchone("SELECT COUNT(*) AS n FROM mr_activity WHERE state='opened'") or {"n": 0}
    mrs_merged = await _fetchone("SELECT COUNT(*) AS n FROM mr_activity WHERE state='merged'") or {"n": 0}
    mrs_closed = await _fetchone("SELECT COUNT(*) AS n FROM mr_activity WHERE state='closed'") or {"n": 0}

    sug_total = await _fetchone(f"SELECT COUNT(*) AS n FROM suggestions{where_sug}", tuple(params)) or {"n": 0}
    sug_applied = await _fetchone(f"SELECT COUNT(*) AS n FROM suggestions WHERE state='applied'{(' AND created_at >= ?' if since else '')}", tuple(params)) or {"n": 0}
    sug_dismissed = await _fetchone(f"SELECT COUNT(*) AS n FROM suggestions WHERE state='dismissed'{(' AND created_at >= ?' if since else '')}", tuple(params)) or {"n": 0}
    sug_open = await _fetchone(f"SELECT COUNT(*) AS n FROM suggestions WHERE state='open'{(' AND created_at >= ?' if since else '')}", tuple(params)) or {"n": 0}

    total_n = int(sug_total["n"] or 0)
    applied_n = int(sug_applied["n"] or 0)
    dismissed_n = int(sug_dismissed["n"] or 0)
    open_n = int(sug_open["n"] or 0)
    adoption_rate = round(applied_n / total_n, 4) if total_n else 0.0
    dismissal_rate = round(dismissed_n / total_n, 4) if total_n else 0.0

    runs_total = await _fetchone("SELECT COUNT(*) AS n FROM review_runs") or {"n": 0}
    runs_failed = await _fetchone("SELECT COUNT(*) AS n FROM review_runs WHERE status='failed'") or {"n": 0}
    runs_total_n = int(runs_total["n"] or 0)
    runs_failed_n = int(runs_failed["n"] or 0)
    success_rate = round((runs_total_n - runs_failed_n) / runs_total_n, 4) if runs_total_n else 0.0

    sev_rows = await _fetchall(
        f"""SELECT COALESCE(severity, 'unspecified') AS severity,
                  COUNT(*) AS total,
                  SUM(CASE WHEN state='applied' THEN 1 ELSE 0 END) AS applied,
                  SUM(CASE WHEN state='dismissed' THEN 1 ELSE 0 END) AS dismissed,
                  SUM(CASE WHEN state='open' THEN 1 ELSE 0 END) AS open
            FROM suggestions{' WHERE created_at >= ?' if since else ''}
            GROUP BY COALESCE(severity, 'unspecified')""",
        tuple(params),
    )
    sev_breakdown: list[dict] = []
    for r in sev_rows:
        total = int(r["total"] or 0)
        applied = int(r["applied"] or 0)
        dismissed = int(r["dismissed"] or 0)
        sev_breakdown.append({
            "severity": r["severity"],
            "total": total,
            "applied": applied,
            "dismissed": dismissed,
            "open": int(r["open"] or 0),
            "adoption_rate": round(applied / total, 4) if total else 0.0,
            "dismissal_rate": round(dismissed / total, 4) if total else 0.0,
        })

    return {
        "since": since,
        "mrs": {
            "total": int(mrs_total["n"] or 0),
            "merged": int(mrs_merged["n"] or 0),
            "open": int(mrs_open["n"] or 0),
            "closed": int(mrs_closed["n"] or 0),
        },
        "suggestions": {
            "total": total_n,
            "applied": applied_n,
            "dismissed": dismissed_n,
            "open": open_n,
            "adoption_rate": adoption_rate,
            "dismissal_rate": dismissal_rate,
        },
        "runs": {
            "total": runs_total_n,
            "failed": runs_failed_n,
            "success_rate": success_rate,
        },
        "severity_breakdown": sev_breakdown,
    }


async def per_rule_stats(since: str | None = None) -> list[dict]:
    params: list[Any] = []
    where = ""
    if since:
        where = " WHERE created_at >= ?"
        params.append(since)
    rows = await _fetchall(f"SELECT rule_keys, state FROM suggestions{where}", tuple(params))
    bucket: dict[str, dict] = {}
    for r in rows:
        keys = [k.strip() for k in (r["rule_keys"] or "").split(",") if k.strip()]
        if not keys:
            keys = ["(no_rule_key)"]
        for k in keys:
            slot = bucket.setdefault(k, {"rule_key": k, "total": 0, "applied": 0, "dismissed": 0, "open": 0})
            slot["total"] += 1
            state = r["state"]
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
    mr_rows = await _fetchall(
        f"""SELECT project_id, mr_iid, author_username, author_sticky
            FROM mr_activity{('WHERE updated_at >= ?' if since else '')}""",
        (since,) if since else (),
    )
    sug_rows = await _fetchall(
        f"""SELECT project_id, mr_iid, state FROM suggestions
            {('WHERE created_at >= ?' if since else '')}""",
        (since,) if since else (),
    )
    by_mr: dict[tuple[int, int], dict] = {}
    for s in sug_rows:
        key = (int(s["project_id"]), int(s["mr_iid"]))
        slot = by_mr.setdefault(key, {"applied": 0, "dismissed": 0, "open": 0})
        state = s["state"]
        if state == "applied":
            slot["applied"] += 1
        elif state == "dismissed":
            slot["dismissed"] += 1
        elif state == "open":
            slot["open"] += 1
    by_author: dict[str, dict] = {}
    for r in mr_rows:
        author = (r["author_sticky"] or r["author_username"] or "unknown").strip()
        slot = by_author.setdefault(author, {
            "author": author, "mr_count": 0, "suggestion_count": 0,
            "applied": 0, "dismissed": 0,
        })
        slot["mr_count"] += 1
        s = by_mr.get((int(r["project_id"]), int(r["mr_iid"])), {})
        sug_total = int(s.get("applied", 0)) + int(s.get("dismissed", 0)) + int(s.get("open", 0))
        slot["suggestion_count"] += sug_total
        slot["applied"] += int(s.get("applied", 0))
        slot["dismissed"] += int(s.get("dismissed", 0))
    out = []
    for v in by_author.values():
        total = v["applied"] + v["dismissed"]
        v["adoption_rate"] = round(v["applied"] / total, 4) if total else 0.0
        out.append(v)
    out.sort(key=lambda x: -x["suggestion_count"])
    return out


async def severity_breakdown(since: str | None = None, pr_url: str | None = None) -> list[dict]:
    ov = await overview(since=since)
    return ov.get("severity_breakdown") or []


def _v2_state(db_state: str | None, updated_at: str | None) -> str:
    """ReviewAgent 没有 'updated' 状态. 基于 last_review_at / updated_at 时间窗补一个 (24h 内视为'刚更新')."""
    if not db_state:
        return "opened"
    if db_state != "opened":
        return db_state
    if not updated_at:
        return "opened"
    try:
        from datetime import datetime, timezone, timedelta
        ts = updated_at.replace("Z", "+00:00") if isinstance(updated_at, str) else None
        if not ts:
            return "opened"
        dt = datetime.fromisoformat(ts)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        if datetime.now(timezone.utc) - dt < timedelta(hours=24):
            return "updated"
    except Exception:
        pass
    return "opened"


async def list_mrs(
    limit: int = 50,
    project_id: int | None = None,
    state: str | None = None,
    since: str | None = None,
    offset: int = 0,
) -> list[dict]:
    """MR 列表, 附带最近一次 run + 建议计数 (对齐 pr-agent 拍平后的 MR row)."""
    params: list[Any] = []
    clauses: list[str] = []
    if project_id is not None:
        clauses.append("project_id = ?")
        params.append(project_id)
    if state:
        clauses.append("state = ?")
        params.append(state)
    if since:
        clauses.append("updated_at >= ?")
        params.append(since)
    where = (" WHERE " + " AND ".join(clauses)) if clauses else ""
    rows = await _fetchall(
        f"""SELECT project_id, mr_iid, title, author_username, author_sticky,
                   source_branch, target_branch, state,
                   created_at, updated_at, merged_at, last_review_at
            FROM mr_activity{where}
            ORDER BY updated_at DESC, mr_iid DESC""",
        tuple(params),
    )

    out: list[dict] = []
    for r in rows:
        pid, iid = int(r["project_id"]), int(r["mr_iid"])
        sug_rows = await _fetchall(
            "SELECT state, COUNT(*) AS n FROM suggestions WHERE project_id=? AND mr_iid=? GROUP BY state",
            (pid, iid),
        )
        sc = {"total": 0, "applied": 0, "dismissed": 0, "open": 0, "superseded": 0}
        for s in sug_rows:
            st = s["state"]
            n = int(s["n"] or 0)
            sc["total"] += n
            if st in sc:
                sc[st] = n
        last_run_row = await _fetchone(
            """SELECT id, command, status, model, started_at, finished_at, duration_ms, error, suggestion_count
               FROM review_runs WHERE project_id=? AND mr_iid=? ORDER BY started_at DESC LIMIT 1""",
            (pid, iid),
        )
        last_run = None
        if last_run_row:
            last_run = {
                "run_id": str(last_run_row.get("id")),
                "command": last_run_row.get("command"),
                "status": last_run_row.get("status"),
                "model": last_run_row.get("model"),
                "started_at": last_run_row.get("started_at"),
                "duration_ms": last_run_row.get("duration_ms"),
                "error": last_run_row.get("error"),
                "suggestion_count": last_run_row.get("suggestion_count"),
            }
        author = (r["author_sticky"] or r["author_username"] or "unknown")
        out.append({
            "project_id": pid,
            "mr_id": iid,
            "title": r["title"] or "",
            "author": author,
            "source_branch": r["source_branch"] or "",
            "target_branch": r["target_branch"] or "",
            "state": r["state"] or "opened",
            "opened_at": r["created_at"],
            "last_seen_at": r["updated_at"],
            "merged_at": r["merged_at"],
            "last_review_at": r["last_review_at"],
            "last_run": last_run,
            "suggestion_counts": sc,
            "_v2_state": _v2_state(r["state"], r["updated_at"]),
            "url": f"/-/merge_requests/{iid}",
        })

    return out[offset:offset + limit]


async def mr_timeline(project_id: int, mr_id: int) -> dict:
    """MR 详情: MR 元信息 + suggestions + runs + actions.

    用 note_id 作 suggestion ↔ actions 链接键 (ReviewAgent actions.suggestion_note_id = suggestions.note_id).
    """
    mr_row = await _fetchone(
        "SELECT * FROM mr_activity WHERE project_id=? AND mr_iid=?",
        (project_id, mr_id),
    )
    if not mr_row:
        raise RuntimeError(f"MR not found: {project_id}/{mr_id}")

    sug_rows = await _fetchall(
        """SELECT id, project_id, mr_iid, note_id, file_path, target_line, target_line_end,
                  existing_code, improved_code, header, severity, head_sha, state,
                  created_at, updated_at, applied_at, dismissed_at, dismissed_by,
                  dismissed_reason, rule_keys, one_sentence_summary, importance, score,
                  fingerprint, cohort_key, severity_source, label, posted_at
           FROM suggestions WHERE project_id=? AND mr_iid=?
           ORDER BY created_at ASC, id ASC""",
        (project_id, mr_id),
    )
    run_rows = await _fetchall(
        """SELECT id, project_id, mr_iid, command, triggered_by, actor_username,
                  started_at, finished_at, status, error, model, prompt_tokens,
                  completion_tokens, total_tokens, duration_ms, suggestion_count, rule_keys_cited
           FROM review_runs WHERE project_id=? AND mr_iid=?
           ORDER BY started_at DESC""",
        (project_id, mr_id),
    )

    actions: list[dict] = []
    if sug_rows:
        note_ids = [str(s["note_id"]) for s in sug_rows if s.get("note_id")]
        if note_ids:
            placeholders = ",".join("?" for _ in note_ids)
            act_rows = await _fetchall(
                f"""SELECT id, suggestion_note_id, action, actor_username, reason, created_at
                    FROM suggestion_actions
                    WHERE suggestion_note_id IN ({placeholders})
                    ORDER BY created_at DESC""",
                tuple(note_ids),
            )
            actions = [
                {
                    "id": int(r["id"]),
                    "suggestion_id": str(r["suggestion_note_id"]),
                    "action": r["action"],
                    "actor": r["actor_username"],
                    "note": r["reason"],
                    "at": r["created_at"],
                }
                for r in act_rows
            ]

    # suggestions 拍平到 V1 兼容字段 (id=null, suggestion_id=note_id 字符串)
    sugs_v1 = []
    for s in sug_rows:
        sugs_v1.append({
            "id": None,
            "suggestion_id": str(s["note_id"]),
            "file": s["file_path"],
            "line": s["target_line"],
            "label": s["label"] or s["header"],
            "header": s["header"],
            "importance": s["importance"],
            "score": s["score"],
            "severity": s["severity"] or "unknown",
            "severity_source": s["severity_source"],
            "rule_keys": [k.strip() for k in (s["rule_keys"] or "").split(",") if k.strip()],
            "one_sentence_summary": s["one_sentence_summary"],
            "state": s["state"],
            "posted_at": s["posted_at"] or s["created_at"],
            "applied_at": s["applied_at"],
            "dismissed_at": s["dismissed_at"],
            "dismissed_by": s["dismissed_by"],
            "dismissed_reason": s["dismissed_reason"],
        })

    runs_v1 = [
        {
            "run_id": str(r["id"]),
            "command": r["command"],
            "status": r["status"],
            "model": r["model"],
            "started_at": r["started_at"],
            "finished_at": r["finished_at"],
            "duration_ms": r["duration_ms"],
            "error": r["error"],
            "suggestion_count": r["suggestion_count"],
            "triggered_by": r["triggered_by"],
        }
        for r in run_rows
    ]

    return {
        "mr": {
            "project_id": int(mr_row["project_id"]),
            "mr_id": int(mr_row["mr_iid"]),
            "title": mr_row["title"] or "",
            "author": (mr_row["author_sticky"] or mr_row["author_username"] or ""),
            "source_branch": mr_row["source_branch"] or "",
            "target_branch": mr_row["target_branch"] or "",
            "state": mr_row["state"] or "opened",
            "opened_at": mr_row["created_at"],
            "merged_at": mr_row["merged_at"],
            "last_review_at": mr_row["last_review_at"],
            "url": f"/-/merge_requests/{mr_row['mr_iid']}",
        },
        "suggestions": sugs_v1,
        "runs": runs_v1,
        "actions": actions,
    }


async def mr_stats(project_id: int, mr_id: int) -> dict:
    tl = await mr_timeline(project_id, mr_id)
    sc: dict[str, int] = {"total": 0, "applied": 0, "dismissed": 0, "open": 0, "superseded": 0}
    for s in tl["suggestions"]:
        st = s.get("state") or "open"
        sc["total"] += 1
        if st in sc:
            sc[st] += 1
    adopted_imp = sum(1 for a in tl["actions"] if a["action"] == "adopted")
    sc["adopted_implicitly"] = adopted_imp
    last_run = tl["runs"][0] if tl["runs"] else None
    return {
        "suggestion_counts": sc,
        "runs": [last_run] if last_run else [],
    }


async def dismissals_by_rule(since: str | None = None) -> list[dict]:
    params: list[Any] = []
    where = " WHERE state='dismissed'"
    if since:
        where += " AND dismissed_at >= ?"
        params.append(since)
    rows = await _fetchall(
        f"SELECT rule_keys, dismissed_reason FROM suggestions{where}",
        tuple(params),
    )
    bucket: dict[str, dict] = {}
    for r in rows:
        keys = [k.strip() for k in (r["rule_keys"] or "").split(",") if k.strip()]
        if not keys:
            keys = ["(no_rule_key)"]
        reason = (r["dismissed_reason"] or "（未填写原因）").strip() or "（未填写原因）"
        for k in keys:
            slot = bucket.setdefault(k, {"rule_key": k, "dismissal_count": 0, "reasons": []})
            slot["dismissal_count"] += 1
            rs = next((rr for rr in slot["reasons"] if rr["reason"] == reason), None)
            if rs:
                rs["count"] += 1
            else:
                slot["reasons"].append({"reason": reason, "count": 1})
    for v in bucket.values():
        v["reasons"].sort(key=lambda r: -r["count"])
    return sorted(bucket.values(), key=lambda r: -r["dismissal_count"])
