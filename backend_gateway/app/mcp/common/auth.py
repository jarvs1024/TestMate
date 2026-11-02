"""Verify MCP OAuth and static bearer tokens against current database state."""
from __future__ import annotations

import hashlib
import secrets
from datetime import datetime
from typing import Any

from jose import JWTError, jwt
from mcp.server.auth.provider import AccessToken, TokenVerifier
from sqlalchemy import select

from app.core.config import settings
from app.core.settings_store import get
from app.db.session import AsyncSessionLocal
from app.mcp.common.context import Principal
from app.mcp.common.oauth import OAuthError, allowed_scopes, normalize_scope
from app.models.mcp import McpApiToken, McpOAuthGrant
from app.models.user import User


async def _mcp_audience(public_base: str | None = None) -> str | None:
    if public_base is None:
        public_base = await get("extensions.public_base_url", "")
    base = str(public_base or "").strip().rstrip("/")
    return f"{base}/mcp" if base else None


def _user_id(claims: dict[str, Any]) -> int | None:
    subject = claims.get("sub")
    if not isinstance(subject, str) or not subject.isascii() or not subject.isdigit():
        return None
    try:
        return int(subject)
    except ValueError:
        return None


def _integer(claims: dict[str, Any], name: str) -> int | None:
    value = claims.get(name)
    if isinstance(value, bool) or not isinstance(value, int):
        return None
    return value


def _scopes(value: Any) -> set[str] | None:
    if not isinstance(value, list) or not all(isinstance(scope, str) for scope in value):
        return None
    return {normalize_scope(scope) for scope in value}


def _access_token(
    token: str,
    principal: Principal,
    scopes: list[str],
) -> AccessToken:
    return AccessToken(
        token=token,
        client_id=principal.client_id,
        scopes=scopes,
        subject=str(principal.user.id),
        claims={"principal": principal},
    )


async def issue_static_token(user: User, public_base: str | None = None) -> str:
    """Issue a static MCP JWT; its database record alone controls scopes/expiry."""
    audience = await _mcp_audience(public_base)
    if audience is None:
        raise OAuthError("invalid_request", "未配置 extensions.public_base_url")
    payload = {
        "sub": str(user.id),
        "token_version": int(user.token_version),
        "aud": audience,
        "typ": "mcp-static",
        "jti": secrets.token_urlsafe(32),
    }
    return jwt.encode(payload, settings.JWT_SECRET, algorithm=settings.JWT_ALGORITHM)


class McpTokenVerifier(TokenVerifier):
    """MCP SDK token verifier with live grant, user, and capability checks."""

    async def verify_token(self, token: str) -> AccessToken | None:
        if not isinstance(token, str) or not token:
            return None
        audience = await _mcp_audience()
        if audience is None:
            return None
        try:
            claims = jwt.decode(
                token,
                settings.JWT_SECRET,
                algorithms=[settings.JWT_ALGORITHM],
                audience=audience,
                options={"verify_exp": False},
            )
        except (JWTError, TypeError, ValueError):
            return None
        if claims.get("aud") != audience:
            return None
        token_type = claims.get("typ")
        if token_type == "mcp-oauth":
            return await self._verify_oauth(token, claims)
        if token_type == "mcp-static":
            return await self._verify_static(token, claims)
        return None

    async def _verify_oauth(
        self,
        token: str,
        claims: dict[str, Any],
    ) -> AccessToken | None:
        user_id = _user_id(claims)
        grant_id = _integer(claims, "grant_id")
        grant_version = _integer(claims, "grant_version")
        token_version = _integer(claims, "token_version")
        client_id = claims.get("client_id")
        token_scopes = _scopes(claims.get("scopes"))
        if (
            user_id is None
            or grant_id is None
            or grant_version is None
            or token_version is None
            or not isinstance(client_id, str)
            or not client_id
            or token_scopes is None
        ):
            return None

        async with AsyncSessionLocal() as session:
            user = await session.get(User, user_id)
            if user is None or not user.is_active or user.token_version != token_version:
                return None
            grant = await session.get(McpOAuthGrant, grant_id)
            if (
                grant is None
                or grant.user_id != user_id
                or grant.client_id != client_id
                or grant.version != grant_version
                or grant.revoked_at is not None
            ):
                return None
            grant_scopes = _scopes(grant.scopes)
            if grant_scopes is None:
                return None
            effective = [
                scope
                for scope in await allowed_scopes(user)
                if scope in token_scopes and scope in grant_scopes
            ]
            if not effective:
                return None
            principal = Principal(
                user=user,
                client_id=grant.client_id,
                scopes=frozenset(effective),
                grant_id=grant.id,
            )
            return _access_token(token, principal, effective)

    async def _verify_static(
        self,
        token: str,
        claims: dict[str, Any],
    ) -> AccessToken | None:
        user_id = _user_id(claims)
        token_version = _integer(claims, "token_version")
        if user_id is None or token_version is None:
            return None
        token_hash = hashlib.sha256(token.encode("ascii")).hexdigest()

        async with AsyncSessionLocal() as session:
            record = (
                await session.execute(
                    select(McpApiToken).where(McpApiToken.token_hash == token_hash)
                )
            ).scalar_one_or_none()
            now = datetime.utcnow()
            if (
                record is None
                or record.user_id != user_id
                or record.revoked_at is not None
                or (record.expires_at is not None and record.expires_at <= now)
            ):
                return None
            user = await session.get(User, user_id)
            if user is None or not user.is_active or user.token_version != token_version:
                return None
            record_scopes = _scopes(record.scopes)
            if record_scopes is None:
                return None
            effective = [
                scope for scope in await allowed_scopes(user) if scope in record_scopes
            ]
            if not effective:
                return None
            record.last_used_at = now
            await session.commit()
            principal = Principal(
                user=user,
                client_id=f"static:{record.id}",
                scopes=frozenset(effective),
                grant_id=None,
            )
            return _access_token(token, principal, effective)
