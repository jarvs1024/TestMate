"""平台信息 (副标题 / 版本号 / 名称) —— **设置项驱动**, 不是写死的.

背景 (2026-10-31 第十八轮):
    页头那行「SSD 测试伙伴 · v0.1.0」两样都是写死的 ——
      · 副标题写死了 "SSD 测试伙伴" —— 但平台早就不只是 SSD 相关了
        (资产市场 / 软件库 / 知识库 / 代码检视看板 / 环境运维);
      · 版本号取的是后端 APP_VERSION (写死在 config.py), 改一次要发版.
    现在两样都变成设置项 (`general.platform_tagline` / `general.platform_version`),
    管理员在设置页改完立刻生效.

⚠️ 这个接口**公开可读** —— 页头在匿名状态下也显示 (工作台/市场/看板都是公开可读的),
   登录页更是. 所以它**不能**挂在 `get_current_user` 后面.
"""
from __future__ import annotations

import pytest

from app.api import platform
from app.core.settings_store import SETTING_SCHEMA


def _schema(key: str) -> dict:
    return next(s for s in SETTING_SCHEMA if s["key"] == key)


# ---------- 设置项本身 ----------

def test_platform_info_settings_exist_with_expected_defaults():
    """版本号默认 1.0.0 / 副标题默认「智能测试辅助平台」."""
    assert _schema("general.platform_version")["default"] == "1.0.0"
    assert _schema("general.platform_tagline")["default"] == "智能测试辅助平台"
    # 名称沿用已有的那个设置项 (默认值 = APP_NAME)
    assert _schema("general.platform_name")["default"]


def test_platform_info_settings_are_in_general_group():
    """⚠️ 三项都在「⚙️ 通用」组里 —— 跟平台显示名放一起, 管理员一处就能改完."""
    for key in ("general.platform_name", "general.platform_version", "general.platform_tagline"):
        assert _schema(key)["category"] == "general", key


def test_platform_info_settings_are_not_admin_only():
    """⚠️ **不能**标 admin_only —— 普通用户也得在页头看到版本号.

    标了就只有管理员看得到, 而页头给所有人显示.
    """
    for key in ("general.platform_name", "general.platform_version", "general.platform_tagline"):
        assert not _schema(key).get("admin_only"), key
        assert not _schema(key)["is_secret"], key


# ---------- 接口行为 ----------

async def test_platform_info_returns_current_values(monkeypatch):
    """读到设置项的值就返回它 (不是代码里的默认值)."""

    async def fake_get(key, default=None):
        return {
            "general.platform_name": "TestMate",
            "general.platform_version": "2.3.4",
            "general.platform_tagline": "资产协作平台",
        }.get(key, default)

    monkeypatch.setattr(platform, "get", fake_get)
    out = await platform.platform_info()
    assert out == {
        "name": "TestMate",
        "version": "2.3.4",
        "tagline": "资产协作平台",
    }


async def test_platform_info_falls_back_to_defaults_when_db_down(monkeypatch):
    """⚠️ DB 挂了 → 退回**代码里的默认值**, 绝不 500 (页头不能整块空白)."""

    async def boom(key, default=None):
        raise RuntimeError("MySQL 挂了")

    monkeypatch.setattr(platform, "get", boom)
    out = await platform.platform_info()
    assert out["version"] == "1.0.0"
    assert out["tagline"] == "智能测试辅助平台"
    assert out["name"]


async def test_platform_info_blank_value_falls_back(monkeypatch):
    """⚠️ 值被改成空串 → 也要兜底 —— 页头不能出现「· v」这种半截话."""

    async def fake_get(key, default=None):
        return "   " if key in ("general.platform_version", "general.platform_tagline") else "TestMate"

    monkeypatch.setattr(platform, "get", fake_get)
    out = await platform.platform_info()
    assert out["version"] == "1.0.0"
    assert out["tagline"] == "智能测试辅助平台"


async def test_platform_info_endpoint_is_public(client):
    """⚠️ **匿名可读** —— 页头在没登录时也要显示版本号."""
    r = await client.get("/api/v1/platform/info")
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["version"]
    assert body["tagline"]
