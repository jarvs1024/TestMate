"""设置层单测 —— 布尔归一 / 默认值改版迁移 / 通知开关默认关闭.

背景: 2026-10-24 把「钉钉市场通知」改成**默认不通知**.
踩过的坑都固化在这里:
  - 改 SCHEMA 里的 default 不会改到老环境 (seed 只在 DB 没这一行时才写)
  - DB 里同一个开关可能存成 JSON 布尔 / "true" 字符串 / 1
  - 字符串 "false" 在前端 `!!v` 眼里是 true → 界面显示"开", 后端当"关"
"""
from __future__ import annotations

import pytest

from app.core import settings_store
from app.core.settings_store import (
    DEFAULT_CHANGES,
    SETTING_SCHEMA,
    get_all,
    seed_defaults,
    to_bool,
)

NOTIFY_KEYS = [
    "dingtalk.notify_on_publish",
    "dingtalk.notify_on_update",
    "dingtalk.notify_on_unpublish",
    "dingtalk.notify_on_delete",
    "dingtalk.notify_on_review",
    "dingtalk.notify_on_reject",
]

# 默认**打开**的三个: 上架 / 更新 / 下架 (市场动作, 大家要知道)
NOTIFY_ON_BY_DEFAULT = [
    "dingtalk.notify_on_publish",
    "dingtalk.notify_on_update",
    "dingtalk.notify_on_unpublish",
]
# 默认**关闭**的三个: 删除 / 待审核 / 驳回
NOTIFY_OFF_BY_DEFAULT = [
    "dingtalk.notify_on_delete",
    "dingtalk.notify_on_review",
    "dingtalk.notify_on_reject",
]


# ---------- to_bool ----------

@pytest.mark.parametrize(
    "raw,expected",
    [
        (True, True), (False, False),
        ("true", True), ("TRUE", True), ("True", True), ("1", True), ("yes", True), ("on", True),
        ("false", False), ("FALSE", False), ("0", False), ("no", False), ("off", False), ("", False),
        (1, True), (0, False),
        (None, False),
    ],
)
def test_to_bool(raw, expected):
    assert to_bool(raw) is expected


def test_to_bool_unrecognized_uses_default():
    """认不出的值 (比如 "maybe") 走 default, 不能瞎猜成真."""
    assert to_bool("maybe") is False
    assert to_bool("maybe", True) is True
    assert to_bool(None, True) is True


# ---------- schema 默认值 ----------

def test_notify_switches_defaults_in_schema():
    """⚠️ 需求: 上架 / 更新 / 下架 默认**开**; 删除 / 待审核 / 驳回 默认**关**."""
    for key in NOTIFY_ON_BY_DEFAULT:
        item = next(s for s in SETTING_SCHEMA if s["key"] == key)
        assert item["value_type"] == "bool", f"{key} 应该是布尔开关"
        assert item["default"] is True, f"{key} 默认必须是开的, 实际={item['default']!r}"
    for key in NOTIFY_OFF_BY_DEFAULT:
        item = next(s for s in SETTING_SCHEMA if s["key"] == key)
        assert item["value_type"] == "bool", f"{key} 应该是布尔开关"
        assert item["default"] is False, f"{key} 默认必须是关的, 实际={item['default']!r}"


def test_default_changes_registered():
    """改了默认值就必须登记迁移 —— 否则老环境永远不变."""
    for key in NOTIFY_ON_BY_DEFAULT:
        assert key in DEFAULT_CHANGES, f"{key} 改了默认值, 得登记 DEFAULT_CHANGES"
        old, new = DEFAULT_CHANGES[key]
        assert old is False and new is True, f"{key} 应登记 False → True, 实际={old!r} → {new!r}"
    # 默认没动的三个不用登记 (登记了也是空迁移, 还会刷无意义的日志)
    for key in NOTIFY_OFF_BY_DEFAULT:
        assert key not in DEFAULT_CHANGES, f"{key} 默认值没改, 不该登记迁移"


# ---------- seed_defaults ----------

async def test_seed_defaults_writes_notify_switches_with_new_defaults():
    """全新的库 → 上架/更新/下架 开, 删除/待审核/驳回 关."""
    await seed_defaults()
    values = await get_all()
    for key in NOTIFY_ON_BY_DEFAULT:
        assert values[key] is True, f"{key} 应该是开的, 实际={values[key]!r}"
    for key in NOTIFY_OFF_BY_DEFAULT:
        assert values[key] is False, f"{key} 应该是关的, 实际={values[key]!r}"


async def test_seed_defaults_migrates_off_rows_to_on():
    """老环境: DB 里是上一版默认 (关) → 启动时迁到新默认 (开)."""
    from app.db.session import AsyncSessionLocal
    from app.models.system_setting import SystemSetting

    async with AsyncSessionLocal() as s:
        for key in NOTIFY_ON_BY_DEFAULT:
            s.add(SystemSetting(key=key, value={"v": False}, category="notification",
                                description="", is_secret=False))
        for key in NOTIFY_OFF_BY_DEFAULT:
            s.add(SystemSetting(key=key, value={"v": False}, category="notification",
                                description="", is_secret=False))
        await s.commit()

    await seed_defaults()

    values = await get_all()
    for key in NOTIFY_ON_BY_DEFAULT:
        assert values[key] is True, f"{key} 应迁到新默认(开), 实际={values[key]!r}"
    for key in NOTIFY_OFF_BY_DEFAULT:
        assert values[key] is False, f"{key} 默认没变, 应保持关, 实际={values[key]!r}"


async def test_seed_defaults_migrates_string_false_rows():
    """老环境里存成字符串 "false" 的也一样要迁移 (布尔存法不统一)."""
    from app.db.session import AsyncSessionLocal
    from app.models.system_setting import SystemSetting

    async with AsyncSessionLocal() as s:
        s.add(SystemSetting(key="dingtalk.notify_on_publish", value={"v": "false"},
                            category="notification", description="", is_secret=False))
        await s.commit()

    await seed_defaults()

    values = await get_all()
    assert values["dingtalk.notify_on_publish"] is True


async def test_seed_defaults_keeps_already_on_rows():
    """本来就是开的行 → 不动它 (值不等于旧默认 = 用户自己设过)."""
    from app.db.session import AsyncSessionLocal
    from app.models.system_setting import SystemSetting

    async with AsyncSessionLocal() as s:
        s.add(SystemSetting(key="dingtalk.notify_on_publish", value={"v": True},
                            category="notification", description="", is_secret=False))
        await s.commit()

    await seed_defaults()
    await seed_defaults()  # 再跑一次也不能改

    values = await get_all()
    assert values["dingtalk.notify_on_publish"] is True


async def test_seed_defaults_normalizes_bool_strings():
    """bool 开关统一存成真正的 JSON 布尔 —— 字符串 "false" 前端会当"开"."""
    from app.db.session import AsyncSessionLocal
    from app.models.system_setting import SystemSetting

    async with AsyncSessionLocal() as s:
        s.add(SystemSetting(key="dingtalk.notify_on_delete", value={"v": "false"},
                            category="notification", description="", is_secret=False))
        await s.commit()

    await seed_defaults()

    async with AsyncSessionLocal() as s:
        row = await s.get(SystemSetting, "dingtalk.notify_on_delete")
        assert row is not None
        assert row.value == {"v": False}, f"DB 里应存真布尔, 实际={row.value!r}"


# ---------- get_all ----------

async def test_get_all_returns_real_booleans():
    """给前端的批量值: bool 一律是真布尔, 不能是字符串."""
    from app.db.session import AsyncSessionLocal
    from app.models.system_setting import SystemSetting

    async with AsyncSessionLocal() as s:
        s.add(SystemSetting(key="dingtalk.notify_on_review", value={"v": "true"},
                            category="notification", description="", is_secret=False))
        await s.commit()

    values = await get_all()
    assert values["dingtalk.notify_on_review"] is True
    assert isinstance(values["dingtalk.notify_on_review"], bool)
    # 没配过的开关也走默认值 (上架默认开)
    assert values["dingtalk.notify_on_publish"] is True


# ---------- 端点层: schema 的 is_default ----------

async def test_settings_schema_reports_bool_defaults_correctly(client, admin_user):
    """接口层: 开关显示成"开/关" + "已定制"标记算得对."""
    from app.db.session import AsyncSessionLocal
    from app.models.system_setting import SystemSetting

    async with AsyncSessionLocal() as s:
        # 上架 (默认开) 被手动关了 → 该标「已定制」
        s.add(SystemSetting(key="dingtalk.notify_on_publish", value={"v": "false"},
                            category="notification", description="", is_secret=False))
        # 删除 (默认关), 值跟默认一致 → 不该标「已定制」
        s.add(SystemSetting(key="dingtalk.notify_on_delete", value={"v": "false"},
                            category="notification", description="", is_secret=False))
        await s.commit()

    r = await client.get(
        "/api/v1/settings/schema",
        headers={"Authorization": f"Bearer {admin_user['token']}"},
    )
    assert r.status_code == 200
    items = {
        it["key"]: it
        for g in r.json()["groups"]
        for it in g["items"]
    }
    pub = items["dingtalk.notify_on_publish"]
    assert pub["value"] is False, "开关值必须是真布尔 (前端 !!'false' 会翻车)"
    assert pub["is_default"] is False, "跟默认(开)不一样 → 该标「已定制」"

    dele = items["dingtalk.notify_on_delete"]
    assert dele["value"] is False
    assert dele["is_default"] is True, "值等于默认值就不该标「已定制」"

    # 没配过的走默认值: 上架默认开
    upd = items["dingtalk.notify_on_update"]
    assert upd["value"] is True
    assert upd["is_default"] is True
