"""/api/v1/settings — DB-backed 配置读写 + 测试连接."""
from __future__ import annotations
import logging
import httpx

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select

from app.api.auth import get_current_user
from app.core.settings_store import SETTING_SCHEMA, get, get_all
from app.db.session import AsyncSessionLocal
from app.models.system_setting import SystemSetting
from app.models.user import User
from app.schemas.system_setting import (
    SettingGroupOut, SettingOut, SettingUpdateIn, SettingTestOut,
)

logger = logging.getLogger(__name__)
router = APIRouter()


# ===== 分组显示 =====
CATEGORY_LABELS: dict[str, str] = {
    "agents":     "🤖 智能体 / Dify",
    "knowledge":  "📚 知识库 / RAGFlow",
    "notification": "🔔 通知 / 钉钉",
    "general":    "⚙️ 通用",
    "search":     "🔎 知识检索",
}


def _mask(v: Any, is_secret: bool) -> Any:
    if not is_secret:
        return v
    if not v:
        return ""
    s = str(v)
    if len(s) <= 8:
        return "••••"
    return s[:4] + "•" * max(4, len(s) - 8) + s[-4:]


@router.get("/schema")
async def get_schema(_user: User = Depends(get_current_user)) -> dict:
    """返回所有 setting 的 schema + 当前 DB 值 (secret 掩码)."""
    values = await get_all()
    by_cat: dict[str, list[dict]] = {}
    for s in SETTING_SCHEMA:
        item = {
            "key": s["key"],
            "value": _mask(values.get(s["key"], s["default"]), s["is_secret"]),
            "value_type": s["value_type"],
            "description": s["description"],
            "is_secret": s["is_secret"],
            "is_default": values.get(s["key"]) == s["default"],
        }
        by_cat.setdefault(s["category"], []).append(item)
    groups = [
        SettingGroupOut(category=cat, label=CATEGORY_LABELS.get(cat, cat), items=items).model_dump()
        for cat, items in by_cat.items()
    ]
    return {"groups": groups, "total": sum(len(g["items"]) for g in groups)}


@router.put("/{key}", response_model=SettingOut)
async def update_setting(
    key: str, payload: SettingUpdateIn,
    user: User = Depends(get_current_user),
) -> SettingOut:
    """改一个 setting. admin only."""
    if user.role.value != "admin":
        raise HTTPException(status_code=403, detail="admin only")
    schema = next((s for s in SETTING_SCHEMA if s["key"] == key), None)
    if not schema:
        raise HTTPException(status_code=404, detail=f"unknown setting '{key}'")
    if schema["is_secret"] and not payload.update_secret and (payload.value == "" or payload.value is None):
        # 留空 = 不改
        async with AsyncSessionLocal() as session:
            row = await session.get(SystemSetting, key)
            return SettingOut.model_validate(row) if row else _empty_out(key, schema)
    async with AsyncSessionLocal() as session:
        row = await session.get(SystemSetting, key)
        if row is None:
            row = SystemSetting(
                key=key,
                value={"v": payload.value},
                category=schema["category"],
                description=schema["description"],
                is_secret=schema["is_secret"],
                updated_by=user.id,
            )
            session.add(row)
        else:
            row.value = {"v": payload.value}
            row.updated_by = user.id
        await session.commit()
        await session.refresh(row)
        return SettingOut.model_validate(row)


def _empty_out(key: str, schema: dict) -> SettingOut:
    from datetime import datetime
    return SettingOut(
        key=key, value=schema["default"], category=schema["category"],
        description=schema["description"], is_secret=schema["is_secret"],
        updated_by=None, updated_at=datetime.utcnow(),
    )


# ===== 测试连接 =====

@router.post("/test/ragflow", response_model=SettingTestOut)
async def test_ragflow(_user: User = Depends(get_current_user)) -> SettingTestOut:
    """用当前 DB (或 fallback env) 的 ragflow 配置打 datasets 端点."""
    base_url = (await get("ragflow.base_url", "")) or ""
    api_key = await get("ragflow.api_key", "") or ""
    if not base_url or "xxxxx" in api_key or "mock" in api_key:
        return SettingTestOut(ok=False, status="off", message="未配置或仍在 mock 占位", detail=None)
    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            r = await client.get(
                f"{base_url.rstrip('/')}/datasets?page=1&page_size=1",
                headers={"Authorization": f"Bearer {api_key}"},
            )
            if r.status_code >= 500:
                return SettingTestOut(ok=False, status="warn", message=f"HTTP {r.status_code}", detail=None)
            data = r.json()
            if data.get("code") != 0:
                return SettingTestOut(ok=False, status="warn", message=data.get("message", "RAGFlow 返回错误"), detail=data)
            total = len(data.get("data") or [])
            return SettingTestOut(ok=True, status="ok", message=f"连通 · 可访问 {total} 个数据集", detail={"datasets": total})
    except Exception as e:
        return SettingTestOut(ok=False, status="off", message=f"不可达: {type(e).__name__}: {e}", detail=None)


@router.post("/test/dify", response_model=SettingTestOut)
async def test_dify(_user: User = Depends(get_current_user)) -> SettingTestOut:
    """用当前 DB (或 fallback env) 的 dify 配置测 mock 模式 + URL 可达."""
    base_url = (await get("dify.base_url", "")) or ""
    api_key = await get("dify.api_key", "") or ""
    mock = bool(await get("dify.mock_mode", False))
    if mock:
        return SettingTestOut(ok=True, status="ok", message="mock 模式开启 · 不连外部 Dify", detail={"mode": "mock"})
    if not base_url or "xxxxx" in api_key or "mock" in api_key:
        return SettingTestOut(ok=False, status="off", message="未配置或仍在 mock 占位", detail=None)
    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            r = await client.get(
                base_url.rstrip("/").replace("/v1", "/"),
                headers={"Authorization": f"Bearer {api_key}"},
            )
            if r.status_code < 500:
                return SettingTestOut(ok=True, status="ok", message=f"连通 · HTTP {r.status_code}", detail=None)
            return SettingTestOut(ok=False, status="warn", message=f"HTTP {r.status_code}", detail=None)
    except Exception as e:
        return SettingTestOut(ok=False, status="off", message=f"不可达: {type(e).__name__}: {e}", detail=None)
