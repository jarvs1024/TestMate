"""钉钉通知 —— **消息内容与开关** (2026-10-30 · 第十一轮 · 问题2/3/4).

用户要求:
    ② 「插件技能连接编辑信息就不需要通知到钉钉了」
    ③ 「软件库的上架和发布新版本需要通知到钉钉, 钉钉在设置中配置,
        上架和发布新版本共有一个配置」
    ④ 「完成钉钉推送的通知信息, 上架补充发描述 比如是干嘛的, 发布更新, 补充更新了啥等,
        信息要区分是插件技能还是连接还是软件包, 最后附上连接……消息简洁明了, 好看」

⚠️ 这里全部走**干跑** (`preview_market_message`) —— 只拼字符串, 不碰 webhook.
   所以**绝对不往公司真实钉钉群发消息**.
"""
from __future__ import annotations

from app.core import dingtalk


def _fake_get(values: dict[str, str]):
    """造一个替代 settings_store.get 的假实现."""
    async def _get(key: str, default: object = None) -> str:
        return values.get(key, default if default is not None else "")

    return _get


# ---------- 事件表 ----------


def test_software_events_registered():
    """软件库的两个事件要在事件表里 (不然 notify_market 直接拒)."""
    for ev in ("software_publish", "software_update"):
        assert ev in dingtalk._EVENT_TEXT, ev
        assert ev in dingtalk._SWITCH_KEY, ev
        assert ev in dingtalk._CHANNEL_OF_EVENT, ev


def test_software_events_share_one_switch():
    """⚠️ 用户要求「上架和发布新版本**共有一个配置**」—— 两个事件必须指向同一开关."""
    assert (
        dingtalk._SWITCH_KEY["software_publish"]
        == dingtalk._SWITCH_KEY["software_update"]
        == "dingtalk.notify_on_software"
    )


def test_software_events_go_to_market_channel():
    """软件库的通知走**市场群** (同一个机器人) —— 用户原话「可以用市场的通知中配置的钉钉信息」."""
    assert dingtalk._CHANNEL_OF_EVENT["software_publish"] == "market"
    assert dingtalk._CHANNEL_OF_EVENT["software_update"] == "market"


def test_software_kind_label():
    """通知里要能区分「软件包」跟插件/技能/连接器."""
    assert dingtalk._KIND_LABEL["software"] == "软件包"
    assert dingtalk._KIND_LABEL["plugin"] == "插件"
    assert dingtalk._KIND_LABEL["skill"] == "技能"
    assert dingtalk._KIND_LABEL["mcp"] == "连接器"


# ---------- 消息内容 ----------


async def test_publish_message_has_summary_and_market_link(monkeypatch):
    """市场上架 → 带**简介** (这玩意儿是干嘛的) + 市场链接."""
    monkeypatch.setattr(
        dingtalk, "get",
        _fake_get({"dingtalk.notify_base_url": "http://127.0.0.1:8081"}),
    )
    r = await dingtalk.preview_market_message(
        "publish", name="代码检视流水线", version="1.0.0", actor="zhangsan",
        kind="plugin", category="流程规范", code="dml-code-review",
        summary="一键串联: 取 MR diff → 送检视 → 回写评论 → 汇总结果",
    )
    text = r["text"]
    assert "代码检视流水线" in text
    assert "插件" in text, "要说明这是插件"
    assert "流程规范" in text, "要带分类"
    assert "1.0.0" in text
    assert "zhangsan" in text, "要说明是谁干的"
    # ⚠️ 上架 → 标签是「说明」, 内容是简介
    assert "说明: 一键串联" in text
    # ⚠️ 链接指向市场
    assert "http://127.0.0.1:8081/market" in text
    assert "去市场看看" in text


async def test_update_message_label_is_update(monkeypatch):
    """发布新版本 → 标签是「更新」 (这次改了啥)."""
    monkeypatch.setattr(
        dingtalk, "get",
        _fake_get({"dingtalk.notify_base_url": "http://127.0.0.1:8081"}),
    )
    r = await dingtalk.preview_market_message(
        "update", name="代码检视流水线", version="1.2.0", actor="zhangsan",
        kind="plugin", summary="支持批量 MR 检视",
    )
    assert "更新: 支持批量 MR 检视" in r["text"]
    assert "说明:" not in r["text"], "有简介时不该再出现「说明」行"


async def test_software_publish_message(monkeypatch):
    """软件库上架 → 类型是**软件包** + 软件库链接 + 简介."""
    monkeypatch.setattr(
        dingtalk, "get",
        _fake_get({"dingtalk.notify_base_url": "http://127.0.0.1:8081"}),
    )
    r = await dingtalk.preview_market_message(
        "software_publish", name="E2E 演示软件", version="1.0.0", actor="zhangsan",
        kind="software", category="工具", code="e2e-demo",
        summary="e2e 走通用的演示软件",
    )
    text = r["text"]
    assert "软件包" in text, "类型要说清楚是软件包"
    assert "工具" in text
    assert "说明: e2e 走通用的演示软件" in text
    assert "http://127.0.0.1:8081/software" in text, "软件库 → /software"
    assert "去软件库看看" in text


async def test_software_update_message_carries_release_notes(monkeypatch):
    """软件库发新版本 → 带**更新说明** (这次改了啥)."""
    monkeypatch.setattr(
        dingtalk, "get",
        _fake_get({"dingtalk.notify_base_url": "http://127.0.0.1:8081"}),
    )
    r = await dingtalk.preview_market_message(
        "software_update", name="E2E 演示软件", version="1.0.3", actor="zhangsan",
        kind="software", summary="e2e 走通用的演示软件",
        release_notes="修了日志解析在超长行上的截断问题",
    )
    text = r["text"]
    assert "更新: 修了日志解析在超长行上的截断问题" in text
    assert "说明:" not in text, "有更新说明时不该再出现「说明」行"
    assert "http://127.0.0.1:8081/software" in text


async def test_release_notes_wins_over_summary(monkeypatch):
    """两个都传 → 更新说明优先 (更新事件更该说"改了啥")."""
    monkeypatch.setattr(dingtalk, "get", _fake_get({}))
    r = await dingtalk.preview_market_message(
        "software_update", name="X", version="1.0.0",
        summary="简介", release_notes="更新说明",
    )
    assert "更新: 更新说明" in r["text"]
    assert "简介" not in r["text"]


async def test_detail_used_when_no_summary(monkeypatch):
    """没有简介/更新说明 → 退回 detail (老逻辑: 这次操作发生了什么)."""
    monkeypatch.setattr(dingtalk, "get", _fake_get({}))
    r = await dingtalk.preview_market_message(
        "reject", name="X", version="1.0.0", detail="审核不通过, 简介写得太笼统",
    )
    assert "说明: 审核不通过, 简介写得太笼统" in r["text"]


async def test_no_link_without_base_url(monkeypatch):
    """没有基地址 → **不给链接** (别发一个打不开的地址)."""
    monkeypatch.setattr(dingtalk, "get", _fake_get({}))
    r = await dingtalk.preview_market_message(
        "publish", name="X", version="1.0.0", kind="plugin", summary="简介",
    )
    assert "](http" not in r["text"]
    assert "/market" not in r["text"]


async def test_link_falls_back_to_public_base_url(monkeypatch):
    """没配通知专用基地址 → 回落 `marketplace.public_base_url`."""
    monkeypatch.setattr(
        dingtalk, "get",
        _fake_get({"marketplace.public_base_url": "http://public.example.com"}),
    )
    r = await dingtalk.preview_market_message(
        "publish", name="X", version="1.0.0", kind="plugin", summary="简介",
    )
    assert "http://public.example.com/market" in r["text"]


async def test_explicit_link_wins(monkeypatch):
    """显式传了 link → 用它 (不再自动拼)."""
    monkeypatch.setattr(
        dingtalk, "get",
        _fake_get({"dingtalk.notify_base_url": "http://127.0.0.1:8081"}),
    )
    r = await dingtalk.preview_market_message(
        "publish", name="X", version="1.0.0", kind="plugin", summary="简介",
        link="http://other/thing",
    )
    assert "http://other/thing" in r["text"]
    assert "/market" not in r["text"]


async def test_preview_does_not_send(monkeypatch):
    """⚠️ 预览**绝不能**发消息 —— 一行网络请求都不许有."""
    calls: list = []

    async def boom(*a, **kw):
        calls.append(a)
        raise AssertionError("预览不该发消息!")

    monkeypatch.setattr(dingtalk, "send_markdown", boom)
    monkeypatch.setattr(dingtalk, "get", _fake_get({}))
    r = await dingtalk.preview_market_message(
        "software_publish", name="X", version="1.0.0", kind="software", summary="简介",
    )
    assert r["text"]
    assert calls == [], "预览发了消息!"


async def test_software_switch_off_skips(monkeypatch):
    """「上架 / 发版本 共用一个开关」—— 关掉时两个事件都不发."""
    sent: list = []

    async def fake_send(webhook, title, text, **kw):
        sent.append(title)
        return {"errcode": 0, "errmsg": "ok"}

    monkeypatch.setattr(dingtalk, "send_markdown", fake_send)
    monkeypatch.setattr(
        dingtalk, "get",
        _fake_get({
            "dingtalk.market_webhook": "http://x/hook",
            "dingtalk.notify_on_software": "false",
        }),
    )
    assert await dingtalk.notify_market(
        "software_publish", name="A", version="1.0.0", kind="software") is False
    assert await dingtalk.notify_market(
        "software_update", name="A", version="1.1.0", kind="software") is False
    assert sent == [], "开关关着还发了消息"


async def test_software_switch_on_sends_both(monkeypatch):
    """开关打开 → 上架和发版本**都**发."""
    sent: list = []

    async def fake_send(webhook, title, text, **kw):
        sent.append(title)
        return {"errcode": 0, "errmsg": "ok"}

    monkeypatch.setattr(dingtalk, "send_markdown", fake_send)
    monkeypatch.setattr(
        dingtalk, "get",
        _fake_get({
            "dingtalk.market_webhook": "http://x/hook",
            "dingtalk.notify_on_software": "true",
        }),
    )
    assert await dingtalk.notify_market(
        "software_publish", name="A", version="1.0.0", kind="software") is True
    assert await dingtalk.notify_market(
        "software_update", name="A", version="1.1.0", kind="software") is True
    assert len(sent) == 2, sent


async def test_software_events_do_not_at_all(monkeypatch):
    """软件库通知**不 @所有人** —— 太吵."""
    sent: list = []

    async def fake_send(webhook, title, text, **kw):
        sent.append(text)
        return {"errcode": 0, "errmsg": "ok"}

    monkeypatch.setattr(dingtalk, "send_markdown", fake_send)
    monkeypatch.setattr(
        dingtalk, "get",
        _fake_get({
            "dingtalk.market_webhook": "http://x/hook",
            "dingtalk.notify_on_software": "true",
        }),
    )
    await dingtalk.notify_market(
        "software_publish", name="A", version="1.0.0", kind="software")
    assert "@所有人" not in sent[0], sent[0]
