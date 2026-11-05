"""ReviewAgent 评审失败 → 钉钉代码检视群 (轮询检测 worker).

⚠️ 为什么是**轮询**: ReviewAgent 是外部服务, TestMate 只读它的 telemetry API,
   失败的 run 记录在 ReviewAgent 那边, 没有任何推送通道 —— 只能定期扫
   "最近结束的 run" 来发现失败.

检测窗口 (防止噪音):
    只处理 ``finished_at`` 落在 ``[窗口起点, now]`` 里的失败 run,
    窗口起点 = max(上次扫描时刻, now - LOOKBACK).
    - 上次扫描时刻初始化为 **worker 启动时刻** → 启动时不会把历史失败全刷一遍;
    - LOOKBACK 兜底单轮扫描被拖长的情况 (比如 ReviewAgent 短暂不可达后恢复);
    - 停机期间 (backend 整个没在跑) 漏掉的失败**不补发** —— 那段时间的通知
      本来就没人收, 补发也是"迟到的假警报".
    - 最终由 ``dingtalk.notify_review_failure`` 按 run_id 查重, 双保险.

发送与重试: 复用 dingtalk 的回执体系 (asset_notifications 表 + retry worker 指数退避).
"""
from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timedelta, timezone
from typing import Any

from app.core import review_agent_client

logger = logging.getLogger(__name__)

# 扫描间隔 (秒)
SCAN_INTERVAL_SEC = 120
# 回看窗口 (秒): 一轮扫描被拖长时, 往回补看多少
LOOKBACK_SEC = 10 * 60
# MR "最近有活动" 的判定余量 —— 防止边界上刚结束的 run 被活动过滤漏掉
ACTIVITY_MARGIN_SEC = 300
# 并发拉 MR 详情的上限
DETAIL_SEM = 4

_worker: asyncio.Task | None = None
# 上一轮扫描的时刻 (窗口起点) —— 由 worker 循环初始化; None = 尚未扫过 (只认"现在"之后的失败)
_last_scan: datetime | None = None


def _parse_ts(v: Any) -> datetime | None:
    """ReviewAgent 的时间戳 (ISO 字符串, 可能带 Z) → aware datetime."""
    if not v:
        return None
    try:
        s = str(v).strip()
        if s.endswith("Z"):
            s = s[:-1] + "+00:00"
        ts = datetime.fromisoformat(s)
        if ts.tzinfo is None:
            ts = ts.replace(tzinfo=timezone.utc)
        return ts
    except (TypeError, ValueError):
        return None


async def scan_failed_runs(now: datetime | None = None) -> int:
    """扫一遍 ReviewAgent 最近失败的 run, 发钉钉通知. 返回通知了几条."""
    if not await review_agent_client.is_configured():
        return 0

    now = now or datetime.now(timezone.utc)
    window_start = max(_last_scan or now, now - timedelta(seconds=LOOKBACK_SEC))
    activity_cutoff = now - timedelta(seconds=LOOKBACK_SEC + ACTIVITY_MARGIN_SEC)

    try:
        raw = await review_agent_client._get("/mrs", {"limit": 200}) or {}
    except Exception as e:  # noqa: BLE001
        logger.warning("review_failure 扫描: 拉 MR 列表失败 (%s)", e)
        return 0
    items = raw.get("mrs") if isinstance(raw, dict) else (raw or [])
    if not isinstance(items, list):
        return 0

    # 只看最近有活动的 MR —— 全部 200 条都拉详情每轮 200 个请求, 太吵.
    candidates: list[dict] = []
    for m in items:
        if not isinstance(m, dict):
            continue
        pid, iid = m.get("project_id"), m.get("mr_iid")
        if pid is None or iid is None:
            continue
        last_act = _parse_ts(m.get("last_activity_at") or m.get("updated_at"))
        if last_act is not None and last_act >= activity_cutoff:
            candidates.append(m)

    if not candidates:
        _last_scan = now
        return 0

    from app.core import dingtalk

    sem = asyncio.Semaphore(DETAIL_SEM)

    async def check_one(m: dict) -> int:
        pid, iid = m["project_id"], m["mr_iid"]
        async with sem:
            try:
                detail = await review_agent_client._get(f"/mr/{pid}/{iid}") or {}
            except Exception as e:  # noqa: BLE001
                logger.debug("review_failure 扫描: MR %s/%s 详情拉取失败 (%s)", pid, iid, e)
                return 0
        runs = detail.get("recent_runs") or []
        if not isinstance(runs, list):
            return 0
        title = str(m.get("title") or "").strip() or f"MR !{iid}"
        author = str(
            m.get("author_sticky") or m.get("author_username")
            or (detail.get("mr") or {}).get("author_sticky")
            or (detail.get("mr") or {}).get("author_username")
            or ""
        )
        link = str(
            m.get("web_url") or (detail.get("mr") or {}).get("web_url") or ""
        )
        sent = 0
        for r in runs:
            if not isinstance(r, dict):
                continue
            if str(r.get("status") or "") != "failed":
                continue
            finished = _parse_ts(r.get("finished_at"))
            if finished is None or not (window_start <= finished <= now):
                continue
            run_id = str(r.get("id") or "").strip()
            if not run_id:
                logger.debug("review_failure 扫描: run 缺 id, 无法去重, 跳过")
                continue
            error = str(r.get("error") or "").strip() or "未知错误"
            command = str(r.get("command") or "").strip()
            code = f"{pid}:{iid}:{run_id}"
            try:
                ok = await dingtalk.notify_review_failure(
                    code=code,
                    name=f"!{iid} {title}",
                    author=author,
                    detail=(f"[{command}] {error}" if command else error)[:200],
                    link=link,
                )
            except Exception as e:  # noqa: BLE001
                logger.exception("review_failure 通知异常: code=%s (%s)", code, e)
                continue
            if ok:
                sent += 1
        return sent

    results = await asyncio.gather(*[check_one(m) for m in candidates])
    _last_scan = now
    n = sum(results)
    if n:
        logger.info("review_failure 扫描: 发现 %d 条新的失败 run, 已通知", n)
    return n


async def _loop() -> None:
    global _last_scan
    _last_scan = datetime.now(timezone.utc)
    logger.info("review_failure.worker running (interval=%ss)", SCAN_INTERVAL_SEC)
    while True:
        try:
            await asyncio.sleep(SCAN_INTERVAL_SEC)
            await scan_failed_runs()
        except asyncio.CancelledError:
            raise
        except Exception:  # noqa: BLE001 — worker 不能因为单次失败崩掉
            logger.exception("review_failure 轮询异常 (已忽略)")


def start_review_failure_worker() -> None:
    """启动评审失败检测 worker (应用启动时调一次)."""
    global _worker
    if _worker is None or _worker.done():
        _worker = asyncio.create_task(_loop())
        logger.info("review_failure.worker started")
