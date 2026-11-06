"""Authenticated REST APIs for MCP consent, grants, and static tokens."""
from __future__ import annotations

import hashlib
from datetime import UTC, datetime
from typing import Any
from urllib.parse import urlencode, urlsplit

from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel, Field, field_validator
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.auth import get_current_user
from app.db.session import get_session
from app.mcp.common.auth import issue_static_token
from app.mcp.common.oauth import (
    SCOPE_HINT,
    SUPPORTED_SCOPES,
    OAuthError,
    allowed_scopes,
    create_authorization_code,
    validate_authorization,
)
from app.models.mcp import McpApiToken, McpOAuthClient, McpOAuthGrant
from app.models.user import User
from app.schemas.base import UTCModel

router = APIRouter()


class GrantOut(UTCModel):
    id: int
    client_id: str
    client_name: str
    scopes: list[str]
    version: int
    revoked_at: datetime | None
    created_at: datetime
    updated_at: datetime


class GrantListOut(UTCModel):
    items: list[GrantOut]


class TokenOut(UTCModel):
    id: int
    name: str
    user_id: int
    username: str
    scopes: list[str]
    expires_at: datetime | None
    revoked_at: datetime | None
    last_used_at: datetime | None
    created_at: datetime
    token: str | None


class TokenListOut(UTCModel):
    items: list[TokenOut]


class TokenCreate(BaseModel):
    name: str = Field(min_length=1, max_length=128)
    scopes: list[str]
    expires_at: datetime | None = None

    @field_validator("name")
    @classmethod
    def validate_name(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("name 不能为空")
        return value

    @field_validator("scopes")
    @classmethod
    def validate_scopes(cls, value: list[str]) -> list[str]:
        if not value or any(scope not in SUPPORTED_SCOPES for scope in value):
            raise ValueError(f"scopes 必须是 {SCOPE_HINT} 的非空子集")
        return value

    @field_validator("expires_at")
    @classmethod
    def validate_expiry(cls, value: datetime | None) -> datetime | None:
        if value is None:
            return None
        aware = value.replace(tzinfo=UTC) if value.tzinfo is None else value
        aware = aware.astimezone(UTC)
        if aware <= datetime.now(UTC):
            raise ValueError("expires_at 必须晚于当前时间")
        return aware.replace(tzinfo=None)


def _oauth_error(exc: OAuthError) -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_400_BAD_REQUEST,
        detail={"error": exc.error, "error_description": exc.description},
    )


async def _json_object(request: Request) -> dict[str, Any]:
    try:
        value = await request.json()
    except ValueError as exc:
        raise OAuthError("invalid_request", "请求 JSON 格式错误") from exc
    if not isinstance(value, dict):
        raise OAuthError("invalid_request", "授权参数必须是对象")
    return value


def _grant_out(grant: McpOAuthGrant, client_name: str) -> GrantOut:
    return GrantOut(
        id=grant.id,
        client_id=grant.client_id,
        client_name=client_name,
        scopes=grant.scopes,
        version=grant.version,
        revoked_at=grant.revoked_at,
        created_at=grant.created_at,
        updated_at=grant.updated_at,
    )


def _token_out(record: McpApiToken, username: str) -> TokenOut:
    return TokenOut(
        id=record.id,
        name=record.name,
        user_id=record.user_id,
        username=username,
        scopes=record.scopes,
        expires_at=record.expires_at,
        revoked_at=record.revoked_at,
        last_used_at=record.last_used_at,
        created_at=record.created_at,
        token=record.token_value,
    )


@router.get("/authorize/preview")
async def authorize_preview(
    request: Request,
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
):
    try:
        validated = await validate_authorization(request.query_params, session)
        permitted = await allowed_scopes(user)
        scopes = [scope for scope in validated["scopes"] if scope in permitted]
        if not scopes:
            raise OAuthError("invalid_scope", "当前用户无可授予 scope")
    except OAuthError as exc:
        raise _oauth_error(exc) from exc
    return {
        "client_id": validated["client_id"],
        "client_name": validated["client_name"],
        "redirect_uri": validated["redirect_uri"],
        "scopes": scopes,
        "response_type": "code",
        "code_challenge": validated["code_challenge"],
        "code_challenge_method": "S256",
        "state": validated["state"],
    }


@router.post("/authorize")
async def authorize(
    request: Request,
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
):
    try:
        params = await _json_object(request)
        code = await create_authorization_code(params, user, session)
    except OAuthError as exc:
        raise _oauth_error(exc) from exc

    redirect_uri = str(params["redirect_uri"])
    callback_params = {"code": code}
    if params.get("state") is not None:
        callback_params["state"] = params["state"]
    separator = "&" if urlsplit(redirect_uri).query else "?"
    return {"callback_url": f"{redirect_uri}{separator}{urlencode(callback_params)}"}


@router.get("/grants", response_model=GrantListOut)
async def list_grants(
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
):
    result = await session.execute(
        select(McpOAuthGrant, McpOAuthClient.client_name)
        .join(McpOAuthClient, McpOAuthClient.client_id == McpOAuthGrant.client_id)
        .where(McpOAuthGrant.user_id == user.id)
        .order_by(McpOAuthGrant.id)
    )
    return {
        "items": [
            _grant_out(grant, client_name)
            for grant, client_name in result.all()
        ]
    }


@router.delete("/grants/{grant_id}")
async def revoke_grant(
    grant_id: int,
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
):
    grant = (
        await session.execute(
            select(McpOAuthGrant).where(
                McpOAuthGrant.id == grant_id,
                McpOAuthGrant.user_id == user.id,
            )
        )
    ).scalar_one_or_none()
    if grant is None:
        raise HTTPException(status_code=404, detail="授权不存在")
    if grant.revoked_at is None:
        grant.revoked_at = datetime.utcnow()
        await session.commit()
    return {}


@router.get("/tokens/scopes")
async def token_scopes(user: User = Depends(get_current_user)):
    return {"scopes": await allowed_scopes(user)}


@router.get("/tokens", response_model=TokenListOut)
async def list_tokens(
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
):
    result = await session.execute(
        select(McpApiToken, User.username)
        .join(User, User.id == McpApiToken.user_id)
        .where(McpApiToken.user_id == user.id)
        .order_by(McpApiToken.id)
    )
    return {
        "items": [
            _token_out(record, username) for record, username in result.all()
        ]
    }


@router.post(
    "/tokens",
    response_model=TokenOut,
    status_code=status.HTTP_201_CREATED,
)
async def create_token(
    payload: TokenCreate,
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
):
    permitted = await allowed_scopes(user)
    denied = [scope for scope in payload.scopes if scope not in permitted]
    if denied:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=f"当前账号无权授予 {', '.join(denied)}",
        )
    try:
        plaintext = await issue_static_token(user)
    except OAuthError as exc:
        raise _oauth_error(exc) from exc

    record = McpApiToken(
        name=payload.name,
        token_hash=hashlib.sha256(plaintext.encode("ascii")).hexdigest(),
        token_value=plaintext,
        user_id=user.id,
        scopes=payload.scopes,
        expires_at=payload.expires_at,
    )
    session.add(record)
    await session.commit()
    await session.refresh(record)
    return _token_out(record, user.username)


@router.delete("/tokens/{token_id}")
async def delete_static_token(
    token_id: int,
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
):
    record = (
        await session.execute(
            select(McpApiToken).where(
                McpApiToken.id == token_id,
                McpApiToken.user_id == user.id,
            )
        )
    ).scalar_one_or_none()
    if record is None:
        raise HTTPException(status_code=404, detail="Token 不存在")
    await session.delete(record)
    await session.commit()
    return {}
