"""外部系统凭据 API: 公钥下发、凭据 CRUD、测试连接."""
from __future__ import annotations

import json
import logging
from datetime import datetime
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.auth import get_current_user
from app.db.session import get_session
from app.integrations import credentials, crypto
from app.integrations.pingcode import client as pingcode_client
from app.integrations.redis import redis_client
from app.integrations.providers import Provider, get_provider
from app.models.integration import IntegrationCredential
from app.models.user import User

router = APIRouter()
logger = logging.getLogger(__name__)

RATE_LIMIT = 3
RATE_WINDOW_SECONDS = 10
_UNBOUND = "unbound"
_PLM_DISABLED = "PLM 集成尚未接入"

_transport_keypair: crypto.TransportKeyPair | None = None


def _transport() -> crypto.TransportKeyPair:
    global _transport_keypair
    if _transport_keypair is None:
        _transport_keypair = crypto.generate_transport_keypair()
    return _transport_keypair


async def _enforce_rate_limit(user_id: int) -> None:
    """PUT 与 test 共用限流: 同一用户 10 秒最多 3 次."""
    key = f"integration:credential_attempts:{user_id}"
    try:
        async with redis_client() as redis:
            count = await redis.incr(key)
            if count == 1:
                await redis.expire(key, RATE_WINDOW_SECONDS)
    except Exception as exc:  # noqa: BLE001
        # Redis 故障不阻断业务; 限流只是防爆破的附加层.
        logger.warning("integration rate limit unavailable: %s", type(exc).__name__)
        return
    if count > RATE_LIMIT:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail=f"操作过于频繁, 请 {RATE_WINDOW_SECONDS} 秒后再试",
        )


def _provider_or_404(code: str) -> Provider:
    provider = get_provider(code)
    if provider is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="未知的平台")
    return provider


def _provider_out(provider: Provider, record: IntegrationCredential | None) -> dict[str, Any]:
    return {
        "id": record.id if record else None,
        "code": provider.code,
        "name": provider.name,
        "enabled": provider.enabled,
        "bound": record is not None,
        "username": record.username if record else None,
        "status": record.status if record else _UNBOUND,
        "last_login_at": record.last_login_at if record else None,
        "last_error": record.last_error if record else None,
    }


def _decode_payload(encrypted: str) -> tuple[str, str]:
    try:
        plaintext = crypto.decrypt_transport(encrypted, _transport().private_key)
    except crypto.IntegrationCryptoError as exc:
        raise HTTPException(status_code=400, detail="凭据密文无效") from exc
    try:
        data = json.loads(plaintext)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail="凭据格式错误") from exc
    if not isinstance(data, dict):
        raise HTTPException(status_code=400, detail="凭据格式错误")
    username = data.get("username")
    password = data.get("password")
    if not isinstance(username, str) or not username.strip():
        raise HTTPException(status_code=400, detail="账号不能为空")
    if not isinstance(password, str) or not password:
        raise HTTPException(status_code=400, detail="密码不能为空")
    return username.strip(), password


class CredentialsIn(BaseModel):
    payload_encrypted: str


@router.get("/providers")
async def list_providers(
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
):
    from app.integrations.providers import PROVIDERS

    records = await credentials.list_for_user(session, user.id)
    return {"items": [_provider_out(p, records.get(p.code)) for p in PROVIDERS]}


@router.get("/crypto/public-key")
async def public_key(user: User = Depends(get_current_user)):
    return {"algorithm": "RSA-PKCS1v15", "public_key": _transport().public_pem}


@router.put("/{provider_code}/credentials")
async def put_credentials(
    provider_code: str,
    body: CredentialsIn,
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
):
    provider = _provider_or_404(provider_code)
    if not provider.enabled:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=_PLM_DISABLED)
    await _enforce_rate_limit(user.id)

    username, password = _decode_payload(body.payload_encrypted)
    try:
        login = await pingcode_client.signin(username, password)
    except pingcode_client.PingCodeAuthError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except pingcode_client.PingCodeUnavailable as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc

    record = await credentials.save_login(
        session,
        user_id=user.id,
        provider=provider.code,
        username=username,
        password=password,
        login=login,
    )
    return _provider_out(provider, record)


@router.delete("/{provider_code}/credentials")
async def delete_credentials(
    provider_code: str,
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
):
    provider = _provider_or_404(provider_code)
    await credentials.delete(session, user.id, provider.code)
    return {}


@router.post("/{provider_code}/test")
async def test_connection(
    provider_code: str,
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
):
    provider = _provider_or_404(provider_code)
    if not provider.enabled:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=_PLM_DISABLED)
    await _enforce_rate_limit(user.id)

    record = await credentials.get(session, user.id, provider.code)
    if record is None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT, detail="尚未配置该系统的凭据"
        )
    try:
        password = credentials.password_of(record)
    except crypto.IntegrationCryptoError as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="凭据无法解密，请重新配置",
        ) from exc
    try:
        login = await pingcode_client.signin(record.username, password)
    except pingcode_client.PingCodeAuthError as exc:
        await credentials.record_failure(session, record, str(exc))
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except pingcode_client.PingCodeUnavailable as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc

    record = await credentials.save_login(
        session,
        user_id=user.id,
        provider=provider.code,
        username=record.username,
        password=password,
        login=login,
    )
    login_at: datetime = record.last_login_at
    return {
        "display_name": login.display_name,
        "team_name": login.team_name,
        "login_at": login_at,
    }
