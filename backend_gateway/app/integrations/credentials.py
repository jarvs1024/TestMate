"""integration_credentials 的读写与加解密."""
from __future__ import annotations

import json
from datetime import datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.integrations import crypto
from app.integrations.pingcode.client import PingCodeSession
from app.models.integration import IntegrationCredential


async def get(session: AsyncSession, user_id: int, provider: str) -> IntegrationCredential | None:
    return (
        await session.execute(
            select(IntegrationCredential).where(
                IntegrationCredential.user_id == user_id,
                IntegrationCredential.provider == provider,
            )
        )
    ).scalar_one_or_none()


async def list_for_user(session: AsyncSession, user_id: int) -> dict[str, IntegrationCredential]:
    rows = (
        await session.execute(
            select(IntegrationCredential).where(IntegrationCredential.user_id == user_id)
        )
    ).scalars()
    return {row.provider: row for row in rows}


def password_of(record: IntegrationCredential) -> str:
    return crypto.decrypt_secret(
        record.secret_encrypted, user_id=record.user_id, provider=record.provider
    )


async def save_login(
    session: AsyncSession,
    *,
    user_id: int,
    provider: str,
    username: str,
    password: str,
    login: PingCodeSession,
) -> IntegrationCredential:
    record = await get(session, user_id, provider)
    if record is None:
        record = IntegrationCredential(user_id=user_id, provider=provider)
        session.add(record)
    now = datetime.utcnow()
    record.username = username
    record.secret_encrypted = crypto.encrypt_secret(
        password, user_id=user_id, provider=provider
    )
    record.token_encrypted = crypto.encrypt_secret(
        login.access_token, user_id=user_id, provider=provider
    )
    record.cookies_encrypted = crypto.encrypt_secret(
        json.dumps(login.cookies, ensure_ascii=False), user_id=user_id, provider=provider
    )
    record.token_expires_at = login.access_token_expires_at
    record.status = "ok"
    record.last_login_at = now
    record.last_attempt_at = now
    record.last_error = None
    record.login_failures = 0
    await session.commit()
    await session.refresh(record)
    return record


async def save_session(
    session: AsyncSession,
    record: IntegrationCredential,
    login: PingCodeSession,
) -> IntegrationCredential:
    """写回刷新得到的 token/cookie, 不动密码与用户名."""
    now = datetime.utcnow()
    record.token_encrypted = crypto.encrypt_secret(
        login.access_token, user_id=record.user_id, provider=record.provider
    )
    record.cookies_encrypted = crypto.encrypt_secret(
        json.dumps(login.cookies, ensure_ascii=False),
        user_id=record.user_id,
        provider=record.provider,
    )
    record.token_expires_at = login.access_token_expires_at
    record.status = "ok"
    record.last_attempt_at = now
    record.last_error = None
    record.login_failures = 0
    await session.commit()
    await session.refresh(record)
    return record


async def record_failure(
    session: AsyncSession,
    record: IntegrationCredential,
    message: str,
    *,
    needs_reauth: bool = True,
) -> None:
    """记录一次失败; 网络类瞬时故障不应把状态打成需重新登录."""
    record.login_failures = (record.login_failures or 0) + 1
    record.last_attempt_at = datetime.utcnow()
    record.last_error = message[:500]
    if needs_reauth:
        record.status = "reauth_required"
    await session.commit()


async def delete(session: AsyncSession, user_id: int, provider: str) -> bool:
    record = await get(session, user_id, provider)
    if record is None:
        return False
    await session.delete(record)
    await session.commit()
    return True
