"""钉钉通知单元测试 —— 加签算法 / 消息拼装 / 送达回执 / 失败重试."""
from __future__ import annotations

import base64
import hashlib
import hmac
import urllib.parse

import pytest

from app.core import dingtalk


def _official_sign(secret: str, ts: int) -> str:
    """按钉钉官方文档独立实现一遍, 用来交叉验证我们的实现."""
    string_to_sign = f"{ts}\n{secret}"
    digest = hmac.new(
        secret.encode("utf-8"),
        string_to_sign.encode("utf-8"),
        hashlib.sha256,
    ).digest()
    return urllib.parse.quote_plus(base64.b64encode(digest).decode("utf-8"))


# ---------- 加签算法 ----------

def test_sign_matches_official_algorithm():
    secret = "SECtestsecret123"
    ts = 1599360473
    assert dingtalk.sign(secret, ts) == _official_sign(secret, ts)


def test_sign_is_urlencoded():
    """最后一步的 urlencode 最容易漏 —— 漏了钉钉直接回 "sign not match"."""
    out = dingtalk.sign("SECsecret", 1700000000)
    assert "%" in out or "+" not in out
    assert " " not in out


def test_sign_is_deterministic():
    assert dingtalk.sign("s", 100) == dingtalk.sign("s", 100)


def test_sign_changes_with_timestamp():
    assert dingtalk.sign("s", 100) != dingtalk.sign("s", 101)


def test_sign_changes_with_secret():
    assert dingtalk.sign("a", 100) != dingtalk.sign("b", 100)


def test_build_signed_url_appends_params():
    url = dingtalk.build_signed_url("https://oapi.dingtalk.com/robot/send?access_token=abc", "SECx")
    assert url.startswith("https://oapi.dingtalk.com/robot/send?access_token=abc&")
    assert "timestamp=" in url and "sign=" in url


def test_build_signed_url_handles_no_query():
    url = dingtalk.build_signed_url("https://oapi.dingtalk.com/robot/send", "SECx")
    assert "?timestamp=" in url


# ---------- 消息拼装 ----------

async def test_notify_market_records_receipt_on_success(monkeypatch):
    """发送成功 → 落一条 sent 回执."""
    sent: list[dict] = []

    async def fake_send(webhook, title, text, *, secret="", at_mobiles=None, at_user_ids=None, is_at_all=False):
        sent.append({"title": title, "text": text})
        return {"errcode": 0, "errmsg": "ok"}

    monkeypatch.setattr(dingtalk, "send_markdown", fake_send)
    monkeypatch.setattr(
        dingtalk, "get",
        _fake_get({"dingtalk.market_webhook": "http://x/hook", "dingtalk.notify_on_publish": "true"}),
    )

    ok = await dingtalk.notify_market(
        "publish", name="演示资产", version="1.0.0", actor="admin",
        detail="摘要", code="demo",
    )
    assert ok is True
    assert sent and "演示资产" in sent[0]["title"]

    from app.db.session import AsyncSessionLocal
    from app.models.asset import AssetNotification
    from sqlalchemy import select

    async with AsyncSessionLocal() as s:
        rows = (
            await s.execute(select(AssetNotification).order_by(AssetNotification.id.desc()))
        ).scalars().all()
    assert rows, "应有回执"
    assert rows[0].status == "sent"
    assert rows[0].code == "demo"
    assert rows[0].attempts == 1


async def test_notify_market_records_failure(monkeypatch):
    """发送失败 → 落一条 failed 回执, 带错误原因和下次重试时间."""
    async def fake_send(*a, **kw):
        raise RuntimeError("HTTP 500: boom")

    monkeypatch.setattr(dingtalk, "send_markdown", fake_send)
    monkeypatch.setattr(
        dingtalk, "get",
        _fake_get({"dingtalk.market_webhook": "http://x/hook", "dingtalk.notify_on_publish": "true"}),
    )

    ok = await dingtalk.notify_market("publish", name="失败用例", code="bad")
    assert ok is False

    from app.db.session import AsyncSessionLocal
    from app.models.asset import AssetNotification
    from sqlalchemy import select

    async with AsyncSessionLocal() as s:
        rows = (
            await s.execute(select(AssetNotification).order_by(AssetNotification.id.desc()))
        ).scalars().all()
    assert rows[0].status == "failed"
    assert "boom" in rows[0].error
    assert rows[0].next_retry_at is not None, "失败后应安排重试"


async def test_notify_market_prepends_keyword(monkeypatch):
    """关键词必须出现在消息里 —— 机器人校验不到就发不出去."""
    sent: list[dict] = []

    async def fake_send(webhook, title, text, *, secret="", at_mobiles=None, at_user_ids=None, is_at_all=False):
        sent.append({"title": title, "text": text})
        return {"errcode": 0}

    monkeypatch.setattr(dingtalk, "send_markdown", fake_send)
    monkeypatch.setattr(
        dingtalk, "get",
        _fake_get({
            "dingtalk.market_webhook": "http://x/hook",
            "dingtalk.market_keyword": "测试组",
            "dingtalk.notify_on_publish": "true",
        }),
    )

    await dingtalk.notify_market("publish", name="带关键词", code="kw")
    assert sent
    assert "测试组" in sent[0]["text"]
    assert "测试组" in sent[0]["title"]


async def test_notify_market_skips_when_not_configured(monkeypatch):
    """没配 webhook → 静默跳过, 不落回执 (不是一次失败)."""
    async def fake_send(*a, **kw):  # pragma: no cover - 不该被调用
        raise AssertionError("不该发消息")

    monkeypatch.setattr(dingtalk, "send_markdown", fake_send)
    # 开关是开的, 但 webhook 没配 → 依然跳过
    monkeypatch.setattr(
        dingtalk, "get",
        _fake_get({"dingtalk.notify_on_publish": "true"}),
    )

    assert await dingtalk.notify_market("publish", name="没配", code="x") is False

    from app.db.session import AsyncSessionLocal
    from app.models.asset import AssetNotification
    from sqlalchemy import select

    async with AsyncSessionLocal() as s:
        rows = (await s.execute(select(AssetNotification))).scalars().all()
    assert not rows


async def test_notify_market_default_is_off(monkeypatch):
    """⚠️ 默认**不通知** —— 开关没配 (老环境/新装) 时绝不能发消息.

    这条是"默认不通知"这条需求的护栏: 以前 switch 缺省是 true,
    老环境没这一行就会照发, 群里被刷屏.
    """
    async def fake_send(*a, **kw):  # pragma: no cover - 不该被调用
        raise AssertionError("默认不该发消息")

    monkeypatch.setattr(dingtalk, "send_markdown", fake_send)
    # 只配了 webhook, 没配任何通知开关
    monkeypatch.setattr(dingtalk, "get", _fake_get({"dingtalk.market_webhook": "http://x/hook"}))

    assert await dingtalk.notify_market("publish", name="默认关", code="x") is False

    from app.db.session import AsyncSessionLocal
    from app.models.asset import AssetNotification
    from sqlalchemy import select

    async with AsyncSessionLocal() as s:
        rows = (await s.execute(select(AssetNotification))).scalars().all()
    assert not rows, "开关默认关 → 不该有回执"


async def test_notify_switches_accept_bool_and_string(monkeypatch):
    """开关存成 JSON 布尔 / "true" 字符串 / 1, 都要认成"开"."""
    sent: list[str] = []

    async def fake_send(webhook, title, text, **kw):
        sent.append(title)
        return {"errcode": 0}

    for raw in (True, "true", "True", "1", "on", 1):
        sent.clear()
        monkeypatch.setattr(dingtalk, "send_markdown", fake_send)
        monkeypatch.setattr(
            dingtalk, "get",
            _fake_get({
                "dingtalk.market_webhook": "http://x/hook",
                "dingtalk.notify_on_publish": raw,
            }),
        )
        ok = await dingtalk.notify_market("publish", name="开", code="x")
        assert ok is True, f"{raw!r} 应认成开"
        assert sent, f"{raw!r} 应真的发出去了"

    for raw in (False, "false", "False", "0", "off", 0):
        sent.clear()
        monkeypatch.setattr(
            dingtalk, "get",
            _fake_get({
                "dingtalk.market_webhook": "http://x/hook",
                "dingtalk.notify_on_publish": raw,
            }),
        )
        ok = await dingtalk.notify_market("publish", name="关", code="x")
        assert ok is False, f"{raw!r} 应认成关"
        assert not sent, f"{raw!r} 不该发出去"


async def test_notify_market_respects_switch(monkeypatch):
    """开关关掉 → 不发."""
    async def fake_send(*a, **kw):  # pragma: no cover
        raise AssertionError("不该发消息")

    monkeypatch.setattr(dingtalk, "send_markdown", fake_send)
    monkeypatch.setattr(
        dingtalk, "get",
        _fake_get({
            "dingtalk.market_webhook": "http://x/hook",
            "dingtalk.notify_on_publish": "false",
        }),
    )
    assert await dingtalk.notify_market("publish", name="关了", code="x") is False


async def test_notify_market_rejects_unknown_event(monkeypatch):
    async def fake_send(*a, **kw):  # pragma: no cover
        raise AssertionError("不该发消息")

    monkeypatch.setattr(dingtalk, "send_markdown", fake_send)
    assert await dingtalk.notify_market("nope", name="x") is False


# ---------- 事件表 ----------

def test_all_events_have_text_and_switch():
    for ev in ("publish", "update", "unpublish", "delete", "review", "reject"):
        assert ev in dingtalk._EVENT_TEXT
        assert ev in dingtalk._SWITCH_KEY


# ---------- 重试 ----------

async def test_retry_failed_notifications(monkeypatch):
    """失败的通知会被重试, 成功后状态变 sent."""
    from app.core.settings_store import get
    from app.db.session import AsyncSessionLocal
    from app.models.asset import AssetNotification

    async with AsyncSessionLocal() as s:
        s.add(AssetNotification(
            event="publish", code="retry-me", asset_name="重试用例",
            status="failed", attempts=1, error="boom",
            title="t", text="x", next_retry_at=None,
        ))
        await s.commit()

    attempts: list[str] = []

    async def fake_send(webhook, title, text, *, secret="", at_mobiles=None, at_user_ids=None, is_at_all=False):
        attempts.append(text)
        return {"errcode": 0}

    monkeypatch.setattr(dingtalk, "send_markdown", fake_send)
    monkeypatch.setattr(
        dingtalk, "get",
        _fake_get({"dingtalk.market_webhook": "http://x/hook", "dingtalk.notify_on_publish": "true"}),
    )

    n = await dingtalk.retry_failed_notifications()
    assert n == 1
    assert attempts

    async with AsyncSessionLocal() as s:
        from sqlalchemy import select

        row = (await s.execute(select(AssetNotification))).scalar_one()
    assert row.status == "sent"
    assert row.attempts == 2
    assert row.next_retry_at is None


async def test_retry_skipped_when_switch_off(monkeypatch):
    """⚠️ 开关关了 → 之前排队的通知**不能再发** (否则关了还在刷屏).

    回执标成 skipped, 不再重试.
    """
    from app.db.session import AsyncSessionLocal
    from app.models.asset import AssetNotification

    async with AsyncSessionLocal() as s:
        s.add(AssetNotification(
            event="publish", code="skip-me", asset_name="开关关了",
            status="failed", attempts=1, error="boom",
            title="t", text="x", next_retry_at=None,
        ))
        await s.commit()

    attempts: list[str] = []

    async def fake_send(webhook, title, text, **kw):  # pragma: no cover - 不该被调用
        attempts.append(text)
        return {"errcode": 0}

    monkeypatch.setattr(dingtalk, "send_markdown", fake_send)
    # 开关是关的 (默认)
    monkeypatch.setattr(dingtalk, "get", _fake_get({"dingtalk.market_webhook": "http://x/hook"}))

    n = await dingtalk.retry_failed_notifications()
    assert n == 0
    assert not attempts, "开关关了不该再发"

    async with AsyncSessionLocal() as s:
        from sqlalchemy import select

        row = (await s.execute(select(AssetNotification))).scalar_one()
    assert row.status == "skipped"
    assert row.next_retry_at is None


async def test_retry_respects_max_attempts(monkeypatch):
    """重试用尽 → 不再重试 (否则会无限骚扰钉钉)."""
    from app.db.session import AsyncSessionLocal
    from app.models.asset import AssetNotification

    async with AsyncSessionLocal() as s:
        s.add(AssetNotification(
            event="publish", code="exhausted", asset_name="用尽",
            status="failed", attempts=dingtalk.MAX_ATTEMPTS,
            error="boom", title="t", text="x", next_retry_at=None,
        ))
        await s.commit()

    called = []

    async def fake_send(*a, **kw):
        called.append(1)
        return {"errcode": 0}

    monkeypatch.setattr(dingtalk, "send_markdown", fake_send)
    monkeypatch.setattr(dingtalk, "get", _fake_get({
        "dingtalk.market_webhook": "http://x/hook",
        "dingtalk.notify_on_publish": "true",
    }))

    n = await dingtalk.retry_failed_notifications()
    assert n == 0
    assert not called


async def test_retry_skips_not_yet_due(monkeypatch):
    """还没到重试时间的不动."""
    from datetime import datetime, timedelta

    from app.db.session import AsyncSessionLocal
    from app.models.asset import AssetNotification

    later = datetime.utcnow() + timedelta(hours=1)
    async with AsyncSessionLocal() as s:
        s.add(AssetNotification(
            event="publish", code="later", asset_name="未到期",
            status="failed", attempts=1, error="boom",
            title="t", text="x", next_retry_at=later,
        ))
        await s.commit()

    called = []

    async def fake_send(*a, **kw):
        called.append(1)
        return {"errcode": 0}

    monkeypatch.setattr(dingtalk, "send_markdown", fake_send)
    monkeypatch.setattr(dingtalk, "get", _fake_get({"dingtalk.market_webhook": "http://x/hook"}))

    assert await dingtalk.retry_failed_notifications() == 0
    assert not called


# ---------- 两个通知频道 (两个群) ----------

def test_event_to_channel_mapping():
    """审核群只收"要管理员处理"的事; 其余 (资产已经变了) 走市场群."""
    # 审核群: 需要管理员处理
    assert dingtalk._CHANNEL_OF_EVENT["review"] == "review"
    assert dingtalk._CHANNEL_OF_EVENT["unpublish_request"] == "review"
    # 市场群: 资产已经变了
    assert dingtalk._CHANNEL_OF_EVENT["publish"] == "market"
    assert dingtalk._CHANNEL_OF_EVENT["update"] == "market"
    assert dingtalk._CHANNEL_OF_EVENT["unpublish"] == "market"
    assert dingtalk._CHANNEL_OF_EVENT["reject"] == "market"
    assert dingtalk._CHANNEL_OF_EVENT["delete"] == "market"


async def test_notify_uses_channel_webhook(monkeypatch):
    """每个事件要发到**自己频道**的 webhook —— 审核通知不能跑到市场群去."""
    sent: list[tuple[str, str]] = []

    async def fake_send(webhook, title, text, *, secret="", at_mobiles=None, at_user_ids=None, is_at_all=False):
        sent.append((webhook, title))
        return {"errcode": 0}

    monkeypatch.setattr(dingtalk, "send_markdown", fake_send)

    async def _get(key, default=None):
        return {
            "dingtalk.notify_on_publish": "true",
            "dingtalk.notify_on_review": "true",
            "dingtalk.market_webhook": "http://market/hook",
            "dingtalk.review_webhook": "http://review/hook",
        }.get(key, default)

    monkeypatch.setattr(dingtalk, "get", _get)

    await dingtalk.notify_market("publish", name="a", code="x")
    await dingtalk.notify_market("review", name="b", code="y")

    hooks = [h for h, _ in sent]
    assert "http://market/hook" in hooks, hooks
    assert "http://review/hook" in hooks, hooks
    # 两条分别去了各自的群 (不能都去同一个)
    assert sent[0][0] == "http://market/hook", sent
    assert sent[1][0] == "http://review/hook", sent


async def test_notify_skips_when_channel_webhook_missing(monkeypatch):
    """频道没配 webhook → 该频道的通知静默跳过 (不影响另一个频道)."""
    sent: list[str] = []

    async def fake_send(webhook, title, text, **kw):
        sent.append(webhook)
        return {"errcode": 0}

    monkeypatch.setattr(dingtalk, "send_markdown", fake_send)

    async def _get(key, default=None):
        return {
            "dingtalk.notify_on_publish": "true",
            "dingtalk.notify_on_review": "true",
            "dingtalk.market_webhook": "http://market/hook",
            # 审核群没配
        }.get(key, default)

    monkeypatch.setattr(dingtalk, "get", _get)

    assert await dingtalk.notify_market("publish", name="a", code="x") is True
    assert await dingtalk.notify_market("review", name="b", code="y") is False
    assert sent == ["http://market/hook"]


async def test_retry_uses_each_row_channel(monkeypatch):
    """⚠️ 重试要**按事件**取频道 —— 审核类通知不能重试到市场群去."""
    from app.db.session import AsyncSessionLocal
    from app.models.asset import AssetNotification
    from sqlalchemy import select

    sent: list[tuple[str, str]] = []

    async def fake_send(webhook, title, text, **kw):
        sent.append((webhook, title))
        return {"errcode": 0}

    monkeypatch.setattr(dingtalk, "send_markdown", fake_send)

    async def _get(key, default=None):
        return {
            "dingtalk.notify_on_review": "true",
            "dingtalk.review_webhook": "http://review/hook",
            "dingtalk.market_webhook": "http://market/hook",
        }.get(key, default)

    monkeypatch.setattr(dingtalk, "get", _get)

    async with AsyncSessionLocal() as s:
        s.add(AssetNotification(
            event="review", code="retry-chan", asset_name="审核重试",
            status="failed", attempts=1, error="boom",
            title="t", text="x", next_retry_at=None,
        ))
        await s.commit()

    n = await dingtalk.retry_failed_notifications()
    assert n == 1
    assert sent and sent[0][0] == "http://review/hook", sent

    async with AsyncSessionLocal() as s:
        row = (await s.execute(select(AssetNotification))).scalar_one()
    assert row.status == "sent"


# ---------- 通知内容 (@人 / 资产类型) ----------

async def test_publish_at_all_and_kind_in_text(monkeypatch):
    """上架成功 → @所有人, 并且消息里要说清"这是个啥" (技能/插件)."""
    sent: list[dict] = []

    async def fake_send(webhook, title, text, *, secret="", at_mobiles=None,
                        at_user_ids=None, is_at_all=False):
        sent.append({"title": title, "text": text, "at": at_user_ids or [],
                     "all": is_at_all})
        return {"errcode": 0}

    monkeypatch.setattr(dingtalk, "send_markdown", fake_send)

    async def _get(key, default=None):
        return {
            "dingtalk.notify_on_publish": "true",
            "dingtalk.market_webhook": "http://market/hook",
        }.get(key, default)

    monkeypatch.setattr(dingtalk, "get", _get)

    ok = await dingtalk.notify_market(
        "publish", name="代码检视流水线", version="1.2.0", actor="jarvs",
        kind="plugin", category="自动代码", code="crp",
    )
    assert ok is True
    assert sent[0]["all"] is True, "上架成功要 @所有人"
    assert "@所有人" in sent[0]["text"], sent[0]["text"]
    assert "插件" in sent[0]["text"], sent[0]["text"]
    assert "自动代码" in sent[0]["text"], sent[0]["text"]
    assert "1.2.0" in sent[0]["text"], sent[0]["text"]


async def test_skill_kind_label_matches_ui(monkeypatch):
    """技能在 UI 上叫「技能」—— 通知里也得叫「技能」, 不能叫「技能包」.

    ⚠️ 两种叫法会让收到通知的人以为是两种东西 (2026-10-25).
    """
    sent: list[dict] = []

    async def fake_send(webhook, title, text, **kw):
        sent.append({"title": title, "text": text})
        return {"errcode": 0}

    monkeypatch.setattr(dingtalk, "send_markdown", fake_send)

    async def _get(key, default=None):
        return {
            "dingtalk.notify_on_publish": "true",
            "dingtalk.market_webhook": "http://market/hook",
        }.get(key, default)

    monkeypatch.setattr(dingtalk, "get", _get)

    await dingtalk.notify_market(
        "publish", name="技能演示", kind="skill", category="质量诊断", code="sk",
    )
    assert "类型: 技能" in sent[0]["text"], sent[0]["text"]
    assert "技能包" not in sent[0]["text"], sent[0]["text"]


async def test_title_override_changes_heading_but_not_event_key(monkeypatch):
    """标题可覆盖 (重新上架别写成「新资产上架」), 但**事件 key 不变**.

    ⚠️ 开关映射 (dingtalk.notify_on_publish 等) 靠事件 key ——
    改了 key 就等于改了开关行为.
    """
    sent: list[dict] = []

    async def fake_send(webhook, title, text, **kw):
        sent.append({"title": title, "text": text})
        return {"errcode": 0}

    monkeypatch.setattr(dingtalk, "send_markdown", fake_send)

    async def _get(key, default=None):
        return {
            "dingtalk.notify_on_publish": "true",
            "dingtalk.market_webhook": "http://market/hook",
        }.get(key, default)

    monkeypatch.setattr(dingtalk, "get", _get)

    await dingtalk.notify_market(
        "publish", name="老资产", code="old",
        detail="重新上架", title_override="🎉 资产重新上架",
    )
    assert "资产重新上架" in sent[0]["title"], sent[0]["title"]
    assert "新资产上架" not in sent[0]["title"], sent[0]["title"]
    assert "资产重新上架" in sent[0]["text"], sent[0]["text"]
    # 事件 key 没变 → 开关映射不变
    assert dingtalk._SWITCH_KEY["publish"] == "dingtalk.notify_on_publish"


async def test_reject_at_author_only(monkeypatch):
    """审核不通过 → 只 @发布者 (不是 @所有人)."""
    sent: list[dict] = []

    async def fake_send(webhook, title, text, *, secret="", at_mobiles=None,
                        at_user_ids=None, is_at_all=False):
        sent.append({"text": text, "at": at_user_ids or [], "all": is_at_all})
        return {"errcode": 0}

    monkeypatch.setattr(dingtalk, "send_markdown", fake_send)

    async def _get(key, default=None):
        return {
            "dingtalk.notify_on_reject": "true",
            "dingtalk.market_webhook": "http://market/hook",
        }.get(key, default)

    monkeypatch.setattr(dingtalk, "get", _get)

    ok = await dingtalk.notify_market(
        "reject", name="某技能", actor="admin", author="jarvs",
        kind="skill", code="demo",
    )
    assert ok is True
    assert sent[0]["all"] is False, "审核不通过不该 @所有人"
    assert sent[0]["at"] == ["jarvs"], sent[0]
    assert "@jarvs" in sent[0]["text"], sent[0]["text"]
    # ⚠️ 技能在 UI 上就叫「技能」—— 通知里曾经叫「技能包」, 两种叫法会让人以为是两种东西
    assert "类型: 技能" in sent[0]["text"], sent[0]["text"]


def test_parse_mentions():
    """重试时要能从正文还原 @ 了谁 (回执里没单独存 at 名单)."""
    at_all, users = dingtalk._parse_mentions("### 标题\n- 类型: 插件\n@所有人\n@jarvs")
    assert at_all is True
    assert users == ["jarvs"]
    at_all, users = dingtalk._parse_mentions("没有 @ 的消息")
    assert at_all is False and users == []


# ---------- 辅助 ----------

def _fake_get(values: dict[str, str]):
    """造一个替代 settings_store.get 的假实现."""
    async def _get(key: str, default: object = None) -> str:
        return values.get(key, default if default is not None else "")

    return _get
