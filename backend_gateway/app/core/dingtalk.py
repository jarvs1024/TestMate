"""钉钉机器人通知 (自定义机器人 · 加签模式).

加签算法 (官方):
    timestamp = 毫秒时间戳
    string_to_sign = f"{timestamp}\\n{secret}"
    sign = url_quote_plus( base64( hmac_sha256(key=secret, msg=string_to_sign) ) )

最后一步 url_quote_plus **最易漏** —— 漏了会返回 "sign not match".

用法:
    from app.core.dingtalk import notify_market
    await notify_market("publish", name="SSD 日志医生", version="1.0.0", actor="jarvs")

失败一律只记日志, 绝不抛给调用方 —— 通知失败不应该让发布事务回滚.
但**失败不能就这么算了**: 每次尝试都落一张回执 (asset_notifications),
后台按指数退避重试, 前端能查到"这条通知到底送没送到".
"""
from __future__ import annotations

import asyncio
import base64
import hashlib
import hmac
import logging
import time
import urllib.parse
from datetime import datetime, timedelta
from typing import Any

import httpx
from sqlalchemy import select

from app.core.settings_store import get
from app.db.session import AsyncSessionLocal
from app.models.asset import AssetNotification

logger = logging.getLogger(__name__)

TIMEOUT = 10.0
# 单条通知最多自动重试几次
MAX_ATTEMPTS = 5
# 退避基数 (秒): 30s, 60s, 120s, 240s
RETRY_BASE_SEC = 30
# 重试扫描间隔 (秒)
RETRY_SCAN_SEC = 30

_worker: asyncio.Task | None = None


def sign(secret: str, timestamp_ms: int) -> str:
    """钉钉加签. 返回可直接放进 URL 的签名串."""
    string_to_sign = f"{timestamp_ms}\n{secret}"
    digest = hmac.new(
        secret.encode("utf-8"), string_to_sign.encode("utf-8"), hashlib.sha256
    ).digest()
    return urllib.parse.quote_plus(base64.b64encode(digest).decode("utf-8"))


def build_signed_url(webhook: str, secret: str) -> str:
    ts = int(round(time.time() * 1000))
    return (
        f"{webhook}{'&' if '?' in webhook else '?'}"
        f"timestamp={ts}&sign={sign(secret, ts)}"
    )


async def send_markdown(
    webhook: str,
    title: str,
    text: str,
    *,
    secret: str = "",
    at_mobiles: list[str] | None = None,
    is_at_all: bool = False,
) -> dict[str, Any]:
    """发一条 markdown 消息. 失败抛异常, 由调用方决定怎么处理."""
    url = build_signed_url(webhook, secret) if secret else webhook
    body: dict[str, Any] = {
        "msgtype": "markdown",
        "markdown": {"title": title, "text": text},
    }
    if at_mobiles or is_at_all:
        body["at"] = {
            "atMobiles": at_mobiles or [],
            "isAtAll": bool(is_at_all),
        }
    async with httpx.AsyncClient(timeout=TIMEOUT) as client:
        r = await client.post(url, json=body)
    if r.status_code >= 400:
        raise RuntimeError(f"钉钉 HTTP {r.status_code}: {r.text[:200]}")
    try:
        return r.json()
    except Exception:
        return {"raw": r.text[:200]}


# ---------- 市场通知 ----------

_EVENT_TEXT = {
    "publish": "🎉 新资产上架",
    "update": "📦 资产版本更新",
    "unpublish": "⚠️ 资产已下架",
    "delete": "🗑 资产已删除",
}

_SWITCH_KEY = {
    "publish": "dingtalk.notify_on_publish",
    "update": "dingtalk.notify_on_update",
    "unpublish": "dingtalk.notify_on_unpublish",
    "delete": "dingtalk.notify_on_delete",
}


async def _deliver(webhook: str, secret: str, title: str, text: str) -> None:
    await send_markdown(webhook, title, text, secret=secret)


async def notify_market(
    event: str,
    *,
    name: str,
    version: str = "",
    actor: str = "",
    detail: str = "",
    link: str = "",
    code: str = "",
) -> bool:
    """发一条市场通知. 返回是否发送成功 (失败只记日志, 不抛).

    event: publish | update | unpublish | delete
    """
    if event not in _EVENT_TEXT:
        logger.warning("dingtalk.notify_market 未知事件: %s", event)
        return False

    try:
        webhook = (await get("dingtalk.market_webhook", "")) or ""
        secret = (await get("dingtalk.market_secret", "")) or ""
        enabled = (await get(_SWITCH_KEY[event], "true")) or "true"
        if str(enabled).lower() not in ("true", "1", "yes", "on"):
            return False
        if not webhook:
            logger.info("dingtalk 未配置 market_webhook, 跳过通知 (%s)", event)
            return False
    except Exception as e:  # noqa: BLE001
        logger.warning("dingtalk 读取配置失败, 跳过通知: %s", e)
        return False

    lines = [f"### {_EVENT_TEXT[event]} · {name}"]
    if version:
        lines.append(f"- 版本: `{version}`")
    if actor:
        lines.append(f"- 操作人: {actor}")
    if detail:
        lines.append(f"- 说明: {detail}")
    if link:
        lines.append(f"- [查看详情]({link})")
    text = "\n".join(lines)
    title = f"{_EVENT_TEXT[event]} · {name}"

    # 先落回执 —— 哪怕进程在发送途中挂掉, 也知道"该发一条通知"
    row = await _create_receipt(event, code, name, title, text)
    ok = await _attempt(row, webhook, secret)
    return ok


async def _create_receipt(
    event: str, code: str, asset_name: str, title: str, text: str
) -> AssetNotification:
    row = AssetNotification(
        event=event,
        code=code or "",
        asset_name=asset_name or "",
        status="pending",
        title=title,
        text=text,
    )
    async with AsyncSessionLocal() as session:
        session.add(row)
        await session.commit()
        await session.refresh(row)
    return row


async def _attempt(
    row: AssetNotification, webhook: str, secret: str
) -> bool:
    """发一次并更新回执. 返回是否成功."""
    try:
        await _deliver(webhook, secret, row.title, row.text)
    except Exception as e:  # noqa: BLE001
        async with AsyncSessionLocal() as session:
            cur = await session.get(AssetNotification, row.id)
            if cur is not None:
                cur.status = "failed"
                cur.attempts = (cur.attempts or 0) + 1
                cur.error = f"{type(e).__name__}: {e}"[:1000]
                cur.last_attempt_at = datetime.utcnow()
                if cur.attempts < MAX_ATTEMPTS:
                    delay = RETRY_BASE_SEC ** min(cur.attempts, 4)
                    cur.next_retry_at = datetime.utcnow() + timedelta(seconds=delay)
                else:
                    cur.next_retry_at = None
                await session.commit()
        logger.warning(
            "dingtalk 通知发送失败 (将重试): event=%s code=%s err=%s",
            row.event, row.code, e,
        )
        return False

    async with AsyncSessionLocal() as session:
        cur = await session.get(AssetNotification, row.id)
        if cur is not None:
            cur.status = "sent"
            cur.attempts = (cur.attempts or 0) + 1
            cur.error = ""
            cur.last_attempt_at = datetime.utcnow()
            cur.next_retry_at = None
            await session.commit()
    logger.info("dingtalk 通知已发送: event=%s name=%s", row.event, row.asset_name)
    return True


async def list_notifications(limit: int = 50) -> tuple[list[AssetNotification], int]:
    """最近的回执 (新的在前). 返回 (列表, 总数)."""
    from sqlalchemy import func

    async with AsyncSessionLocal() as session:
        rows = (
            await session.execute(
                select(AssetNotification)
                .order_by(AssetNotification.id.desc())
                .limit(limit)
            )
        ).scalars().all()
        total = (
            await session.execute(select(func.count()).select_from(AssetNotification))
        ).scalar() or 0
    return list(rows), int(total)


# ---------- 失败重试 ----------

async def retry_failed_notifications() -> int:
    """重试到期的失败通知. 返回重试条数."""
    now = datetime.utcnow()
    async with AsyncSessionLocal() as session:
        rows = (
            await session.execute(
                select(AssetNotification)
                .where(
                    AssetNotification.status.in_(("pending", "failed")),
                    AssetNotification.attempts < MAX_ATTEMPTS,
                )
                .order_by(AssetNotification.id.asc())
                .limit(20)
            )
        ).scalars().all()
        due = [
            r for r in rows
            if r.next_retry_at is None or r.next_retry_at <= now
        ]

    if not due:
        return 0

    try:
        webhook = (await get("dingtalk.market_webhook", "")) or ""
        secret = (await get("dingtalk.market_secret", "")) or ""
    except Exception as e:  # noqa: BLE001
        logger.warning("dingtalk 重试读取配置失败: %s", e)
        return 0
    if not webhook:
        return 0

    n = 0
    for r in due:
        if await _attempt(r, webhook, secret):
            n += 1
    if n:
        logger.info("dingtalk 重试成功 %s 条", n)
    return n


async def _retry_loop() -> None:
    logger.info("dingtalk.retry worker running")
    while True:
        try:
            await asyncio.sleep(RETRY_SCAN_SEC)
            await retry_failed_notifications()
        except asyncio.CancelledError:
            raise
        except Exception:  # noqa: BLE001 — worker 不能因为单次失败崩掉
            logger.exception("dingtalk.retry 轮询异常 (已忽略)")


def start_retry_worker() -> None:
    """启动重试 worker (应用启动时调一次)."""
    global _worker
    if _worker is None or _worker.done():
        _worker = asyncio.create_task(_retry_loop())
        logger.info("dingtalk.retry worker started")
