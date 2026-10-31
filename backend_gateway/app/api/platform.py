"""平台对外信息 —— 副标题 + 版本号 (页头 / 登录页用).

⚠️ 为什么单独一个模块:
    设置接口 (`GET /api/v1/settings/schema`) **要登录**, 而且普通用户看不到
    管理员专属项. 但页头这行字在**匿名**状态下也显示 (工作台 / 市场 / 看板
    都是公开可读的), 登录页更是 —— 如果版本号只能从设置接口拿,
    匿名用户看到的页头就会缺一截.

⚠️ 为什么**公开可读**不构成风险:
    这两项就是"平台叫什么、什么版本" —— 桌面上摆着的名片, 不是凭据.
    真要收紧, 该收紧的是 webhook / api_key 那些 (见 settings.py 的
    _ADMIN_ONLY_SETTING_RE), 它们**不**走这个接口.
"""
from __future__ import annotations

import logging

from fastapi import APIRouter

from app.core.settings_store import SETTING_SCHEMA, get

logger = logging.getLogger(__name__)
router = APIRouter()

VERSION_KEY = "general.platform_version"
TAGLINE_KEY = "general.platform_tagline"
NAME_KEY = "general.platform_name"


def _schema_default(key: str) -> str:
    """设置项在代码里的默认值 —— DB 读不到时的兜底."""
    s = next((x for x in SETTING_SCHEMA if x["key"] == key), None)
    return str((s or {}).get("default") or "")


async def _safe(key: str) -> str:
    """读一个设置项 —— **任何异常都退回默认值**, 绝不把这个接口搞挂.

    ⚠️ DB 挂了就该退回默认值, 而不是让页头整个空白 / 500.
    """
    fallback = _schema_default(key)
    try:
        v = await get(key, fallback)
    except Exception as e:  # noqa: BLE001 — 取不到就兜底, 不该 500
        logger.warning("platform.info: 读 %s 失败, 用默认值: %s", key, e)
        return fallback
    s = str(v or "").strip()
    return s or fallback


@router.get("/info")
async def platform_info() -> dict:
    """平台信息 —— 名称 + 副标题 + 版本号.

    ⚠️ **不要加登录校验**: 匿名用户也要看得到页头那行字.
    """
    return {
        "name": await _safe(NAME_KEY),
        "version": await _safe(VERSION_KEY),
        "tagline": await _safe(TAGLINE_KEY),
    }
