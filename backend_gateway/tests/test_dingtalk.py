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
        "publish", name="技能演示", kind="skill", category="质量保障", code="sk",
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
            # ⚠️ 2026-10-31 (第十三轮): 钉钉要的是 **userid**, 不是平台账号名 ——
            #    所以 atUserIds 里放的是映射表查出来的 userid.
            "dingtalk.userid_map": "jarvs=manager1234",
        }.get(key, default)

    monkeypatch.setattr(dingtalk, "get", _get)

    ok = await dingtalk.notify_market(
        "reject", name="某技能", actor="admin", author="jarvs",
        kind="skill", code="demo",
    )
    assert ok is True
    assert sent[0]["all"] is False, "审核不通过不该 @所有人"
    assert sent[0]["at"] == ["manager1234"], sent[0]
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


# ---------- 审核类通知的窗口合并 (2026-10-28) ----------
#
# 背景: 审核通知是「要人去做一件事」, 十几个人同时上架就是十几条消息刷屏.
# 做法: 首条照常发 (带详情), 窗口内的其余攒起来, 窗口末发一条汇总.
#
# ⚠️ 只合并**审核类** (review / unpublish_request):
#    市场群那几类是「资产已经变了」的事实通告且 @所有人, 合并会让人漏看.

def _review_settings(window: str = "60") -> dict[str, str]:
    return {
        "dingtalk.review_webhook": "http://x/hook",
        "dingtalk.notify_on_review": "true",
        "dingtalk.notify_on_unpublish_request": "true",
        "dingtalk.aggregate_window_seconds": window,
    }


async def _receipts() -> list:
    """所有回执 (按 id 升序) —— 断言用."""
    from app.db.session import AsyncSessionLocal
    from app.models.asset import AssetNotification
    from sqlalchemy import select

    async with AsyncSessionLocal() as s:
        rows = (
            await s.execute(select(AssetNotification).order_by(AssetNotification.id.asc()))
        ).scalars().all()
    return list(rows)


async def _backdate_last_sent(seconds: int = 120) -> None:
    """把最近一条**已发出**的回执时间往前挪 —— 模拟窗口已经过去.

    ⚠️ 不这么干就只能干等 60 秒 —— 单测不能真等.
    """
    from datetime import datetime, timedelta

    from app.db.session import AsyncSessionLocal
    from app.models.asset import AssetNotification
    from sqlalchemy import select

    async with AsyncSessionLocal() as s:
        row = (
            await s.execute(
                select(AssetNotification)
                .where(AssetNotification.status.in_(("sent", "summary_sent")))
                .order_by(AssetNotification.id.desc())
                .limit(1)
            )
        ).scalars().first()
        if row is not None:
            row.created_at = datetime.utcnow() - timedelta(seconds=seconds)
            await s.commit()


def _collector() -> tuple[list[dict], object]:
    """造一个收集发送内容的假 send_markdown."""
    sent: list[dict] = []

    async def fake_send(webhook, title, text, *, secret="", at_mobiles=None,
                        at_user_ids=None, is_at_all=False):
        sent.append({"webhook": webhook, "title": title, "text": text})
        return {"errcode": 0, "errmsg": "ok"}

    return sent, fake_send


async def test_review_first_in_window_sends_normally(monkeypatch):
    """窗口内**第一条**照常发 —— 管理员得第一时间知道有人上传了."""
    sent, fake_send = _collector()
    monkeypatch.setattr(dingtalk, "send_markdown", fake_send)
    monkeypatch.setattr(dingtalk, "get", _fake_get(_review_settings()))

    ok = await dingtalk.notify_market(
        "review", name="资产甲", code="a", kind="skill", category="效率工具",
    )
    assert ok is True
    assert len(sent) == 1, sent
    assert "资产甲" in sent[0]["title"], sent[0]
    rows = await _receipts()
    assert rows[-1].status == "sent", rows[-1].status


async def test_review_second_in_window_is_aggregated(monkeypatch):
    """窗口内**第二条**不单独发 —— 攒起来等汇总 (回执还是要留痕)."""
    sent, fake_send = _collector()
    monkeypatch.setattr(dingtalk, "send_markdown", fake_send)
    monkeypatch.setattr(dingtalk, "get", _fake_get(_review_settings()))

    await dingtalk.notify_market("review", name="资产甲", code="a")
    await dingtalk.notify_market("review", name="资产乙", code="b")

    assert len(sent) == 1, f"窗口内不该发第二条: {sent}"
    rows = await _receipts()
    assert rows[-1].status == "aggregated", rows[-1].status
    assert rows[-1].code == "b"


async def test_aggregated_flush_sends_one_summary(monkeypatch):
    """窗口到期 → 发**一条**汇总, 被合并的几条标成「已并入汇总」."""
    sent, fake_send = _collector()
    monkeypatch.setattr(dingtalk, "send_markdown", fake_send)
    monkeypatch.setattr(dingtalk, "get", _fake_get(_review_settings()))

    await dingtalk.notify_market("review", name="甲", code="a")
    await dingtalk.notify_market("review", name="乙", code="b")
    await dingtalk.notify_market("review", name="丙", code="c")
    assert len(sent) == 1

    # 窗口还没到 → 不发汇总
    assert await dingtalk.flush_aggregated_notifications() == 0
    assert len(sent) == 1

    # 窗口到了 → 一条汇总
    await _backdate_last_sent(120)
    assert await dingtalk.flush_aggregated_notifications() == 1
    assert len(sent) == 2, sent
    assert "另有 2 个" in sent[1]["text"], sent[1]["text"]
    # 汇总里要能看到那两个资产的详情 (不然只剩一个数字, 还得自己去翻)
    assert "乙" in sent[1]["text"] and "丙" in sent[1]["text"], sent[1]["text"]

    rows = await _receipts()
    assert rows[-1].status == "summary_sent", rows[-1].status
    merged = [r for r in rows if r.code in ("b", "c")]
    assert merged and all(r.status == "aggregated_sent" for r in merged), [
        (r.code, r.status) for r in merged
    ]


async def test_market_events_are_not_aggregated(monkeypatch):
    """市场群的「资产已经变了」**不合并** —— 谁上架了什么都要看得见."""
    sent, fake_send = _collector()
    monkeypatch.setattr(dingtalk, "send_markdown", fake_send)
    monkeypatch.setattr(
        dingtalk, "get",
        _fake_get({
            "dingtalk.market_webhook": "http://x/hook",
            "dingtalk.notify_on_publish": "true",
            "dingtalk.aggregate_window_seconds": "60",
        }),
    )

    await dingtalk.notify_market("publish", name="甲", code="a")
    await dingtalk.notify_market("publish", name="乙", code="b")
    assert len(sent) == 2, f"市场通告不该被合并: {sent}"


async def test_aggregate_window_zero_disables_merging(monkeypatch):
    """窗口设 0 → 恢复一个资产一条消息 (管理员要能关掉合并)."""
    sent, fake_send = _collector()
    monkeypatch.setattr(dingtalk, "send_markdown", fake_send)
    monkeypatch.setattr(dingtalk, "get", _fake_get(_review_settings("0")))

    await dingtalk.notify_market("review", name="甲", code="a")
    await dingtalk.notify_market("review", name="乙", code="b")
    assert len(sent) == 2, f"窗口=0 不该合并: {sent}"


async def test_review_and_unpublish_request_aggregate_separately(monkeypatch):
    """上架审核和下架申请是**两件事** —— 不能混进同一轮汇总."""
    sent, fake_send = _collector()
    monkeypatch.setattr(dingtalk, "send_markdown", fake_send)
    monkeypatch.setattr(dingtalk, "get", _fake_get(_review_settings()))

    await dingtalk.notify_market("review", name="甲", code="a")
    await dingtalk.notify_market("unpublish_request", name="乙", code="b")
    assert len(sent) == 2, f"两类事件不该互相合并: {sent}"
    assert "甲" in sent[0]["title"] and "乙" in sent[1]["title"], sent


async def test_aggregated_rows_are_not_retried_as_pending(monkeypatch):
    """「已并入汇总」的行**不能**被重试 worker 当成待发通知再发一遍."""
    sent, fake_send = _collector()
    monkeypatch.setattr(dingtalk, "send_markdown", fake_send)
    monkeypatch.setattr(dingtalk, "get", _fake_get(_review_settings()))

    await dingtalk.notify_market("review", name="甲", code="a")
    await dingtalk.notify_market("review", name="乙", code="b")
    await _backdate_last_sent(120)
    await dingtalk.flush_aggregated_notifications()
    n = len(sent)

    # 重试 worker 再跑一轮 —— 不该冒出新的发送 (之前只发 1 条 + 1 条汇总)
    await dingtalk.retry_failed_notifications()
    assert len(sent) == n, f"汇总过的通知被重发了一遍: {sent}"


async def _clear_backoff() -> None:
    """清掉失败回执的**退避时间** —— 模拟"退避已经过了".

    ⚠️ 不这么干就只能干等 30 秒 —— 单测不能真等.
    """
    from app.db.session import AsyncSessionLocal
    from app.models.asset import AssetNotification
    from sqlalchemy import select

    async with AsyncSessionLocal() as s:
        rows = (
            await s.execute(
                select(AssetNotification).where(AssetNotification.status == "failed")
            )
        ).scalars().all()
        for row in rows:
            row.next_retry_at = None
        await s.commit()


async def test_failed_summary_is_reused_not_duplicated(monkeypatch):
    """汇总发送失败 → **复用**那条回执重试, 不新建 (否则群里收到两条一样的)."""
    calls: list[str] = []

    async def flaky_send(webhook, title, text, *, secret="", at_mobiles=None,
                         at_user_ids=None, is_at_all=False):
        calls.append(title)
        if len(calls) == 2:
            raise RuntimeError("网络抖了一下")
        return {"errcode": 0, "errmsg": "ok"}

    monkeypatch.setattr(dingtalk, "send_markdown", flaky_send)
    monkeypatch.setattr(dingtalk, "get", _fake_get(_review_settings()))

    await dingtalk.notify_market("review", name="甲", code="a")
    await dingtalk.notify_market("review", name="乙", code="b")
    await _backdate_last_sent(120)

    # 第一次汇总 → 失败 (第 2 次调用抛异常)
    assert await dingtalk.flush_aggregated_notifications() == 0
    rows = await _receipts()
    summaries = [r for r in rows if "另有" in (r.title or "")]
    assert len(summaries) == 1, f"汇总回执不该新建: {[(r.id, r.title) for r in summaries]}"

    # 退避没到 → 不硬发 (把这条重试让给退避逻辑)
    await _backdate_last_sent(120)
    assert await dingtalk.flush_aggregated_notifications() == 0
    assert len(calls) == 2, f"退避期内不该再发: {calls}"

    # 退避到了 → 复用同一条回执, 这次发成功
    await _clear_backoff()
    await _backdate_last_sent(120)
    assert await dingtalk.flush_aggregated_notifications() == 1
    rows = await _receipts()
    summaries = [r for r in rows if "另有" in (r.title or "")]
    assert len(summaries) == 1, f"汇总回执被重复创建了: {[(r.id, r.title) for r in summaries]}"
    assert summaries[0].status == "summary_sent", summaries[0].status


async def test_retry_worker_does_not_send_summary_receipts(monkeypatch):
    """汇总回执**归聚合 worker 管** —— 重试 worker 不能抢着发 (会重发一遍)."""
    sent, fake_send = _collector()
    monkeypatch.setattr(dingtalk, "send_markdown", fake_send)
    monkeypatch.setattr(dingtalk, "get", _fake_get(_review_settings()))

    await dingtalk.notify_market("review", name="甲", code="a")
    await dingtalk.notify_market("review", name="乙", code="b")
    await _backdate_last_sent(120)

    # 汇总发送失败 → 回执留在 pending/failed
    async def boom(*a, **kw):
        raise RuntimeError("发不出去")
    monkeypatch.setattr(dingtalk, "send_markdown", boom)
    await dingtalk.flush_aggregated_notifications()

    # 重试 worker 跑一轮 —— 不该把这条汇总发出去
    sent.clear()
    monkeypatch.setattr(dingtalk, "send_markdown", fake_send)
    await dingtalk.retry_failed_notifications()
    assert sent == [], f"重试 worker 抢发了汇总: {sent}"


# ---------- 辅助 ----------

def _fake_get(values: dict[str, str]):
    """造一个替代 settings_store.get 的假实现."""
    async def _get(key: str, default: object = None) -> str:
        return values.get(key, default if default is not None else "")

    return _get
