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
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import logging
import time
import urllib.parse
from typing import Any

import httpx

from app.core.settings_store import get

logger = logging.getLogger(__name__)

TIMEOUT = 10.0


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
}


async def notify_market(
    event: str,
    *,
    name: str,
    version: str = "",
    actor: str = "",
    detail: str = "",
    link: str = "",
) -> bool:
    """发一条市场通知. 返回是否发送成功 (失败只记日志, 不抛).

    event: publish | update | unpublish
    """
    if event not in _EVENT_TEXT:
        logger.warning("dingtalk.notify_market 未知事件: %s", event)
        return False

    try:
        webhook = (await get("dingtalk.market_webhook", "")) or ""
        secret = (await get("dingtalk.market_secret", "")) or ""
        switch_key = {
            "publish": "dingtalk.notify_on_publish",
            "update": "dingtalk.notify_on_update",
            "unpublish": "dingtalk.notify_on_unpublish",
        }[event]
        enabled = (await get(switch_key, "true")) or "true"
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

    try:
        await send_markdown(webhook, f"{_EVENT_TEXT[event]} · {name}", text, secret=secret)
        logger.info("dingtalk 通知已发送: event=%s name=%s", event, name)
        return True
    except Exception as e:  # noqa: BLE001 — 通知失败不影响主流程
        logger.warning("dingtalk 通知发送失败 (已忽略): event=%s err=%s", event, e)
        return False
