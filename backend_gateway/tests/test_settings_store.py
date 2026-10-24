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

def test_notify_switches_default_off_in_schema():
    """⚠️ 核心需求: 六个通知开关的默认值必须都是"关"."""
    for key in NOTIFY_KEYS:
        item = next(s for s in SETTING_SCHEMA if s["key"] == key)
        assert item["value_type"] == "bool", f"{key} 应该是布尔开关"
        assert item["default"] is False, f"{key} 默认必须是关的, 实际={item['default']!r}"


def test_default_changes_registered():
    """改了默认值就必须登记迁移 —— 否则老环境永远不变."""
    for key in NOTIFY_KEYS:
        assert key in DEFAULT_CHANGES, f"{key} 改了默认值, 得登记 DEFAULT_CHANGES"
        old, new = DEFAULT_CHANGES[key]
        assert old == "true" and new is False


# ---------- seed_defaults ----------

async def test_seed_defaults_writes_notify_switches_off():
    """全新的库 → 六个开关都是关的."""
    await seed_defaults()
    values = await get_all()
    for key in NOTIFY_KEYS:
        assert values[key] is False, f"{key} 应该是关的, 实际={values[key]!r}"


async def test_seed_defaults_migrates_legacy_true_rows():
    """老环境: DB 里留着旧默认值 "true" → 启动时迁移成 false."""
    from app.db.session import AsyncSessionLocal
    from app.models.system_setting import SystemSetting

    async with AsyncSessionLocal() as s:
        for key in NOTIFY_KEYS:
            s.add(SystemSetting(key=key, value={"v": "true"}, category="notification",
                                description="", is_secret=False))
        await s.commit()

    await seed_defaults()

    values = await get_all()
    for key in NOTIFY_KEYS:
        assert values[key] is False, f"{key} 旧默认值应该被迁移成关, 实际={values[key]!r}"


async def test_seed_defaults_migrates_json_true_rows():
    """老环境里存成 JSON 布尔 true 的也一样要迁移."""
    from app.db.session import AsyncSessionLocal
    from app.models.system_setting import SystemSetting

    async with AsyncSessionLocal() as s:
        s.add(SystemSetting(key="dingtalk.notify_on_publish", value={"v": True},
                            category="notification", description="", is_secret=False))
        await s.commit()

    await seed_defaults()

    values = await get_all()
    assert values["dingtalk.notify_on_publish"] is False


async def test_seed_defaults_keeps_already_off_rows():
    """已经是关的行 → 不动它 (迁移要幂等)."""
    from app.db.session import AsyncSessionLocal
    from app.models.system_setting import SystemSetting

    async with AsyncSessionLocal() as s:
        s.add(SystemSetting(key="dingtalk.notify_on_publish", value={"v": False},
                            category="notification", description="", is_secret=False))
        await s.commit()

    await seed_defaults()
    await seed_defaults()  # 再跑一次也不能改

    values = await get_all()
    assert values["dingtalk.notify_on_publish"] is False


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
    # 没配过的开关也走默认值 (关)
    assert values["dingtalk.notify_on_publish"] is False


# ---------- 端点层: schema 的 is_default ----------

async def test_settings_schema_reports_bool_defaults_correctly(client, admin_user):
    """接口层: 开关显示成"开/关" + "已定制"标记算得对."""
    from app.db.session import AsyncSessionLocal
    from app.models.system_setting import SystemSetting

    async with AsyncSessionLocal() as s:
        s.add(SystemSetting(key="dingtalk.notify_on_publish", value={"v": "false"},
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
    assert pub["is_default"] is True, "值等于默认值就不该标「已定制」"

    upd = items["dingtalk.notify_on_update"]
    assert upd["value"] is False
