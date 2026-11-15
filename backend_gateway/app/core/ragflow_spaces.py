"""RAGFlow 用户空间: 多 key 解析、加解密、默认空间与旧配置迁移.

一把 RAGFlow API key = 一个用户空间. 所有调用方 (REST / MCP) 只传 ``space_id``,
凭据解析和默认空间回退都收敛在这里.
"""
from __future__ import annotations

import logging
import secrets

from sqlalchemy import select, update

from app.core.config import settings
from app.core.settings_store import get
from app.db.session import AsyncSessionLocal
from app.integrations.crypto import decrypt_secret, encrypt_secret
from app.models.ragflow_space import RagflowSpace

logger = logging.getLogger(__name__)

_PROVIDER = "ragflow-space"
_SYSTEM_ACTOR = 0
_KEY_PREFIX = "ragflow-"


class RagflowSpaceError(Exception):
    """空间不存在 / 重名 / 参数非法 —— 调用方转成中文错误."""

    def __init__(self, message: str, status_code: int = 422):
        super().__init__(message)
        self.message = message
        self.status_code = status_code


def new_space_id() -> str:
    return "sp_" + secrets.token_hex(4)


def encrypt_key(plaintext: str) -> str:
    return encrypt_secret(plaintext, user_id=_SYSTEM_ACTOR, provider=_PROVIDER)


def decrypt_key(cipher: str) -> str:
    return decrypt_secret(cipher, user_id=_SYSTEM_ACTOR, provider=_PROVIDER)


def _validate_key(api_key: str) -> str:
    key = (api_key or "").strip()
    if not key:
        raise RagflowSpaceError("API Key 不能为空")
    if not key.startswith(_KEY_PREFIX):
        raise RagflowSpaceError(f"API Key 必须以 {_KEY_PREFIX} 开头")
    return key


def _validate_name(name: str) -> str:
    n = (name or "").strip()
    if not n:
        raise RagflowSpaceError("空间名称不能为空")
    if len(n) > 64:
        raise RagflowSpaceError("空间名称最长 64 个字符")
    return n


async def list_spaces() -> list[RagflowSpace]:
    async with AsyncSessionLocal() as s:
        rows = await s.execute(
            select(RagflowSpace).order_by(RagflowSpace.created_at, RagflowSpace.id)
        )
        return list(rows.scalars().all())


async def get_space(space_id: str) -> RagflowSpace | None:
    if not space_id:
        return None
    async with AsyncSessionLocal() as s:
        return await s.get(RagflowSpace, space_id)


async def fallback_space() -> RagflowSpace | None:
    """未指定 space_id 时用的空间: 最早创建的那个.

    ⚠️ 不再提供「设为默认」—— 默认只能有一个, 又不能随便换, 不如固定成
       最早建的空间, 页面/MCP 想用别的就显式传 space_id.
    """
    async with AsyncSessionLocal() as s:
        return (
            await s.execute(
                select(RagflowSpace)
                .order_by(RagflowSpace.created_at, RagflowSpace.id)
                .limit(1)
            )
        ).scalar_one_or_none()


async def _hint() -> str:
    spaces = await list_spaces()
    return "、".join(f"{s.name}({s.id})" for s in spaces) or "（尚未配置任何空间）"


async def resolve(space_id: str | None) -> RagflowSpace | None:
    """解析空间; 空 = 最早创建的空间, 未知 id 报中文错误并列出可用空间."""
    if not space_id:
        return await fallback_space()
    sp = await get_space(space_id)
    if sp is None:
        raise RagflowSpaceError(
            f"用户空间不存在：{space_id}。可用空间：{await _hint()}", status_code=404
        )
    return sp


async def legacy_key() -> str:
    """旧配置里的 RAGFlow key —— DB 行优先, 再兜底 .env."""
    key = str((await get("ragflow.api_key", "")) or "").strip()
    if not key:
        key = str(settings.RAGFLOW_API_KEY or "").strip()
    return key


async def credential_for(space_id: str | None) -> tuple[str, str, RagflowSpace | None]:
    """返回 (base_url, api_key, space).

    一个空间都没有时回退旧配置 —— 保证未迁移环境行为跟改造前一致.
    """
    space = await resolve(space_id)
    base = str((await get("ragflow.base_url", "")) or "")
    if space is None:
        return base, await legacy_key(), None
    try:
        key = decrypt_key(space.api_key_cipher)
    except Exception as exc:  # noqa: BLE001
        logger.warning("空间 %s 的 API Key 解密失败: %s", space.id, exc)
        raise RagflowSpaceError(
            f"空间「{space.name}」的 API Key 无法解密，请在设置里重新填写", status_code=422
        ) from None
    return base, key, space


async def create_space(
    name: str,
    api_key: str,
    *,
    actor_id: int | None = None,
) -> RagflowSpace:
    name = _validate_name(name)
    api_key = _validate_key(api_key)
    async with AsyncSessionLocal() as s:
        exists = (
            await s.execute(select(RagflowSpace).where(RagflowSpace.name == name))
        ).scalar_one_or_none()
        if exists is not None:
            raise RagflowSpaceError(f"空间「{name}」已经存在，请换一个名称")
        row = RagflowSpace(
            id=new_space_id(),
            name=name,
            api_key_cipher=encrypt_key(api_key),
            created_by=actor_id,
        )
        s.add(row)
        await s.commit()
        await s.refresh(row)
        return row


async def update_space(
    space_id: str,
    *,
    name: str | None = None,
    api_key: str | None = None,
) -> RagflowSpace:
    async with AsyncSessionLocal() as s:
        row = await s.get(RagflowSpace, space_id)
        if row is None:
            raise RagflowSpaceError(
                f"用户空间不存在：{space_id}。可用空间：{await _hint()}", status_code=404
            )
        if name is not None:
            name = _validate_name(name)
            dup = (
                await s.execute(
                    select(RagflowSpace).where(
                        RagflowSpace.name == name, RagflowSpace.id != space_id
                    )
                )
            ).scalar_one_or_none()
            if dup is not None:
                raise RagflowSpaceError(f"空间「{name}」已经存在，请换一个名称")
            row.name = name
        if api_key:
            row.api_key_cipher = encrypt_key(_validate_key(api_key))
        await s.commit()
        await s.refresh(row)
        return row


async def delete_space(space_id: str) -> None:
    async with AsyncSessionLocal() as s:
        row = await s.get(RagflowSpace, space_id)
        if row is None:
            raise RagflowSpaceError(f"用户空间不存在：{space_id}", status_code=404)
        await s.delete(row)
        await s.commit()


async def ensure_legacy_space() -> None:
    """启动迁移: 没有任何空间时把旧 key 落成一个空间，并回填历史审计."""
    async with AsyncSessionLocal() as s:
        existing = (await s.execute(select(RagflowSpace).limit(1))).scalar_one_or_none()
        if existing is not None:
            return
    legacy = await legacy_key()
    if not legacy.startswith(_KEY_PREFIX) or "xxxxx" in legacy or "mock" in legacy:
        return
    try:
        sp = await create_space("默认空间", legacy)
    except RagflowSpaceError:
        logger.exception("旧 RAGFlow key 迁移失败")
        return

    from app.models.kb import KbAudit

    async with AsyncSessionLocal() as s:
        await s.execute(
            update(KbAudit)
            .where(KbAudit.space_id == "")
            .values(space_id=sp.id, space_name=sp.name)
        )
        await s.commit()
    logger.info("已把旧 RAGFlow key 迁移为用户空间 %s", sp.id)
