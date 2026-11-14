"""知识库用户空间管理 —— 读: 所有登录用户; 写: admin."""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from app.api.auth import get_current_user
from app.core import ragflow_spaces
from app.core.ragflow_client import probe
from app.core.ragflow_spaces import (
    RagflowSpace,
    RagflowSpaceError,
    create_space,
    decrypt_key,
    delete_space,
    list_spaces,
    update_space,
)
from app.db.session import AsyncSessionLocal
from app.models.asset import AssetAudit
from app.models.user import User, UserRole

router = APIRouter()


def _mask(key: str) -> str:
    if not key:
        return ""
    return key[:4] + "•" * 4 + key[-4:] if len(key) > 8 else "••••"


def _out(space: RagflowSpace, *, admin: bool) -> dict:
    item = {"id": space.id, "name": space.name, "is_default": space.is_default, "configured": True}
    if admin:
        try:
            item["key_masked"] = _mask(decrypt_key(space.api_key_cipher))
        except Exception:  # noqa: BLE001 —— 解密失败只说不知道, 不回显密文
            item["key_masked"] = "（无法解密）"
    return item


def _require_admin(user: User) -> None:
    if user.role != UserRole.admin:
        raise HTTPException(status_code=403, detail="只有管理员能管理知识库用户空间")


class SpaceIn(BaseModel):
    name: str = Field(..., min_length=1, max_length=64)
    api_key: str = Field(..., min_length=8, max_length=200)
    is_default: bool = False


class SpacePatch(BaseModel):
    name: str | None = Field(None, min_length=1, max_length=64)
    api_key: str | None = Field(None, max_length=200)
    is_default: bool | None = None


async def _audit(user: User, action: str, space: RagflowSpace) -> None:
    async with AsyncSessionLocal() as s:
        s.add(
            AssetAudit(
                asset_id=None,
                code="setting:ragflow.spaces",
                action="setting.update",
                actor_id=user.id,
                actor_name=user.username,
                comment=f"{action} 知识库用户空间 {space.name}",
                detail={
                    "op": action,
                    "space_id": space.id,
                    "name": space.name,
                    "is_default": space.is_default,
                    "api_key": "***",
                },
            )
        )
        await s.commit()


@router.get("")
async def get_spaces(user: User = Depends(get_current_user)) -> dict:
    rows = await list_spaces()
    admin = user.role == UserRole.admin
    items = [_out(s, admin=admin) for s in rows]
    default = next((s.id for s in rows if s.is_default), "")
    return {"items": items, "default_id": default}


@router.post("")
async def post_space(payload: SpaceIn, user: User = Depends(get_current_user)) -> dict:
    _require_admin(user)
    try:
        sp = await create_space(
            payload.name, payload.api_key, is_default=payload.is_default, actor_id=user.id
        )
    except RagflowSpaceError as e:
        raise HTTPException(status_code=e.status_code, detail=e.message)
    await _audit(user, "create", sp)
    return {"ok": True, "space": _out(sp, admin=True)}


@router.put("/{space_id}")
async def put_space(
    space_id: str, payload: SpacePatch, user: User = Depends(get_current_user)
) -> dict:
    _require_admin(user)
    try:
        sp = await update_space(
            space_id,
            name=payload.name,
            api_key=payload.api_key,
            is_default=payload.is_default,
        )
    except RagflowSpaceError as e:
        raise HTTPException(status_code=e.status_code, detail=e.message)
    await _audit(user, "update", sp)
    return {"ok": True, "space": _out(sp, admin=True)}


@router.delete("/{space_id}")
async def remove_space(space_id: str, user: User = Depends(get_current_user)) -> dict:
    _require_admin(user)
    sp = await ragflow_spaces.get_space(space_id)
    if sp is None:
        raise HTTPException(status_code=404, detail=f"用户空间不存在：{space_id}")
    try:
        await delete_space(space_id)
    except RagflowSpaceError as e:
        raise HTTPException(status_code=e.status_code, detail=e.message)
    await _audit(user, "delete", sp)
    return {"ok": True}


@router.post("/{space_id}/test")
async def test_space(space_id: str, user: User = Depends(get_current_user)) -> dict:
    _require_admin(user)
    try:
        # ⚠️ 先 resolve 一次 —— 让"空间不存在"直接 404, 而不是 probe 回一个笼统的 off
        await ragflow_spaces.resolve(space_id)
        status, message = await probe(space_id)
    except RagflowSpaceError as e:
        raise HTTPException(status_code=e.status_code, detail=e.message)
    return {"ok": status == "ok", "status": status, "message": message}
