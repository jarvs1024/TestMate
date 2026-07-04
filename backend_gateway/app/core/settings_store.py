"""DB-backed settings 加载层。

设计:
- 优先级: 显式 env var > DB > 代码默认
- 后端代码不直接 import settings_store, 而是通过 get(key, default) 异步拿
- seed 把 .env 里的值首次落库, 后续 UI 改的就是 DB 里的
"""
from __future__ import annotations
import logging
from typing import Any

from app.core.config import settings

logger = logging.getLogger(__name__)


# ===== 静态注册表 (P0 阶段用, 后期改成查 DB schema) =====
# value_type 告诉前端怎么渲染: string / secret / bool / int / url
SETTING_SCHEMA: list[dict] = [
    {
        "key": "ragflow.base_url",
        "category": "knowledge",
        "value_type": "url",
        "default": settings.RAGFLOW_BASE_URL,
        "description": "RAGFlow API 基础地址 (例: http://host:9380/api/v1)",
        "is_secret": False,
    },
    {
        "key": "ragflow.api_key",
        "category": "knowledge",
        "value_type": "secret",
        "default": settings.RAGFLOW_API_KEY,
        "description": "RAGFlow API Key (ragflow-xxxxx)",
        "is_secret": True,
    },
    {
        "key": "dify.base_url",
        "category": "agents",
        "value_type": "url",
        "default": settings.DIFY_BASE_URL,
        "description": "Dify API 基础地址",
        "is_secret": False,
    },
    {
        "key": "dify.api_key",
        "category": "agents",
        "value_type": "secret",
        "default": settings.DIFY_API_KEY,
        "description": "Dify API Key (app-xxxxx)",
        "is_secret": True,
    },
    {
        "key": "dify.mock_mode",
        "category": "agents",
        "value_type": "bool",
        "default": settings.DIFY_MOCK,
        "description": "Dify mock 模式: 开则不调外部 Dify, 用 demo 流式返回 (沙箱环境用)",
        "is_secret": False,
    },
    {
        "key": "general.platform_name",
        "category": "general",
        "value_type": "string",
        "default": settings.APP_NAME,
        "description": "平台显示名 (顶栏 + 标题)",
        "is_secret": False,
    },
]


def get_schema() -> list[dict]:
    return SETTING_SCHEMA


# ===== DB 加载 / 兜底 =====

async def seed_defaults() -> None:
    """启动时: 把 SCHEMA 里有但 DB 里没有的, 用 .env default 落库."""
    from app.db.session import AsyncSessionLocal
    from app.models.system_setting import SystemSetting
    from sqlalchemy import select

    async with AsyncSessionLocal() as session:
        for s in SETTING_SCHEMA:
            existing = await session.get(SystemSetting, s["key"])
            if existing:
                continue
            row = SystemSetting(
                key=s["key"],
                value=s["default"] if isinstance(s["default"], (dict, list)) else {"v": s["default"]},
                category=s["category"],
                description=s["description"],
                is_secret=s["is_secret"],
            )
            session.add(row)
        await session.commit()


async def get(key: str, default: Any = None) -> Any:
    """读一个 key 的值, fallback 到 schema default / 传入 default."""
    from app.db.session import AsyncSessionLocal
    from app.models.system_setting import SystemSetting

    async with AsyncSessionLocal() as session:
        row = await session.get(SystemSetting, key)
        if row is None:
            schema = next((s for s in SETTING_SCHEMA if s["key"] == key), None)
            return schema["default"] if schema else default
        v = row.value
        return v.get("v", default) if isinstance(v, dict) else v


async def get_all() -> dict[str, Any]:
    """批量读所有 setting (DB 优先, 缺则用 schema default)."""
    from app.db.session import AsyncSessionLocal
    from app.models.system_setting import SystemSetting
    from sqlalchemy import select

    out: dict[str, Any] = {}
    async with AsyncSessionLocal() as session:
        result = await session.execute(select(SystemSetting))
        rows = {r.key: r for r in result.scalars().all()}
    for s in SETTING_SCHEMA:
        v = rows.get(s["key"])
        if v is None:
            out[s["key"]] = s["default"]
        else:
            raw = v.value
            out[s["key"]] = raw.get("v", s["default"]) if isinstance(raw, dict) else raw
    return out
