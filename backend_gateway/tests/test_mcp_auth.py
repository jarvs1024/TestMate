"""MCP bearer-token verification against current users, grants, and policies."""
from __future__ import annotations

import hashlib
import uuid
from datetime import datetime, timedelta

import pytest
from jose import jwt
from mcp.server.auth.provider import AccessToken

from app.core.config import settings
from app.core.security import create_access_token
from app.db.session import AsyncSessionLocal
from app.mcp.common import auth, oauth
from app.mcp.common.context import Principal
from app.models.mcp import McpApiToken, McpOAuthClient, McpOAuthGrant
from app.models.user import User, UserRole
from tests.conftest import set_setting

PUBLIC_BASE = "http://127.0.0.1:8081/"
AUDIENCE = "http://127.0.0.1:8081/mcp"
ALL_SCOPES = ["market:read", "market:write"]
DELETE = object()


@pytest.fixture(autouse=True)
async def _auth_settings():
    await set_setting("marketplace.public_base_url", PUBLIC_BASE)
    await set_setting("marketplace.publisher_roles", "tester")


async def _user(
    *,
    role: UserRole = UserRole.tester,
    active: bool = True,
    token_version: int = 7,
) -> User:
    async with AsyncSessionLocal() as session:
        user = User(
            username=f"mcp-auth-{uuid.uuid4().hex}",
            password_hash="not-used-by-mcp-auth-tests",
            role=role,
            is_active=active,
            token_version=token_version,
        )
        session.add(user)
        await session.commit()
        await session.refresh(user)
        return user


async def _oauth_credential(
    user: User | None = None,
    *,
    scopes: list[str] | None = None,
) -> tuple[str, McpOAuthGrant, User]:
    user = user or await _user()
    client_id = f"client-{uuid.uuid4().hex}"
    async with AsyncSessionLocal() as session:
        grant = McpOAuthGrant(
            user_id=user.id,
            client_id=client_id,
            scopes=list(scopes if scopes is not None else ALL_SCOPES),
            version=1,
        )
        session.add(
            McpOAuthClient(
                client_id=client_id,
                client_name="MCP auth test client",
                redirect_uris=["http://127.0.0.1:51234/callback"],
                scopes=ALL_SCOPES,
            )
        )
        session.add(grant)
        await session.commit()
        await session.refresh(grant)
    token = await oauth.issue_access_token(user, grant, PUBLIC_BASE)
    return token, grant, user


async def _static_credential(
    user: User | None = None,
    *,
    scopes: list[str] | None = None,
) -> tuple[str, McpApiToken, User]:
    user = user or await _user()
    token = await auth.issue_static_token(user, PUBLIC_BASE)
    async with AsyncSessionLocal() as session:
        record = McpApiToken(
            name="MCP auth test token",
            token_hash=hashlib.sha256(token.encode("ascii")).hexdigest(),
            user_id=user.id,
            scopes=list(scopes if scopes is not None else ALL_SCOPES),
        )
        session.add(record)
        await session.commit()
        await session.refresh(record)
    return token, record, user


def _decode_without_audience(token: str) -> dict:
    return jwt.decode(
        token,
        settings.JWT_SECRET,
        algorithms=[settings.JWT_ALGORITHM],
        options={"verify_aud": False},
    )


def _resign(
    token: str,
    *,
    secret: str | None = None,
    **changes,
) -> str:
    claims = _decode_without_audience(token)
    for key, value in changes.items():
        if value is DELETE:
            claims.pop(key, None)
        else:
            claims[key] = value
    return jwt.encode(
        claims,
        secret or settings.JWT_SECRET,
        algorithm=settings.JWT_ALGORITHM,
    )


async def _update_user(user_id: int, **changes) -> None:
    async with AsyncSessionLocal() as session:
        user = await session.get(User, user_id)
        assert user is not None
        for key, value in changes.items():
            setattr(user, key, value)
        await session.commit()


async def _update_grant(grant_id: int, **changes) -> None:
    async with AsyncSessionLocal() as session:
        grant = await session.get(McpOAuthGrant, grant_id)
        assert grant is not None
        for key, value in changes.items():
            setattr(grant, key, value)
        await session.commit()


async def _update_static(record_id: int, **changes) -> None:
    async with AsyncSessionLocal() as session:
        record = await session.get(McpApiToken, record_id)
        assert record is not None
        for key, value in changes.items():
            setattr(record, key, value)
        await session.commit()


async def test_valid_oauth_token_returns_sdk_access_token_and_current_principal():
    token, grant, user = await _oauth_credential()

    result = await auth.McpTokenVerifier().verify_token(token)

    assert isinstance(result, AccessToken)
    assert result.token == token
    assert result.client_id == grant.client_id
    assert result.scopes == ALL_SCOPES
    assert result.claims is not None
    principal = result.claims["principal"]
    assert isinstance(principal, Principal)
    assert principal.user.id == user.id
    assert principal.user.username == user.username
    assert principal.client_id == grant.client_id
    assert principal.grant_id == grant.id
    assert principal.scopes == frozenset(ALL_SCOPES)


async def test_platform_login_jwt_is_not_an_mcp_access_token():
    user = await _user()
    platform_token, _ = create_access_token(user.id)

    assert await auth.McpTokenVerifier().verify_token(platform_token) is None


@pytest.mark.parametrize("mutation", ["no_aud", "wrong_aud", "wrong_typ", "wrong_signature"])
async def test_oauth_rejects_invalid_audience_type_or_signature(mutation: str):
    token, _, _ = await _oauth_credential()
    if mutation == "no_aud":
        token = _resign(token, aud=DELETE)
    elif mutation == "wrong_aud":
        token = _resign(token, aud="http://example.test/mcp")
    elif mutation == "wrong_typ":
        token = _resign(token, typ="mcp-static")
    else:
        token = _resign(token, secret="a-wrong-signing-secret-that-is-long-enough")

    assert await auth.McpTokenVerifier().verify_token(token) is None


@pytest.mark.parametrize(
    ("claim", "value"),
    [
        ("sub", DELETE),
        ("client_id", DELETE),
        ("grant_id", DELETE),
        ("grant_version", DELETE),
        ("token_version", DELETE),
        ("scopes", DELETE),
        ("sub", "not-an-integer"),
        ("client_id", ""),
        ("grant_id", "1"),
        ("grant_version", True),
        ("token_version", 1.5),
        ("scopes", "market:read"),
        ("scopes", ["market:read", 3]),
    ],
)
async def test_oauth_rejects_missing_or_malformed_required_claims(claim, value):
    token, _, _ = await _oauth_credential()
    token = _resign(token, **{claim: value})

    assert await auth.McpTokenVerifier().verify_token(token) is None


@pytest.mark.parametrize("credential_type", ["mcp-oauth", "mcp-static"])
@pytest.mark.parametrize("subject", ["²", "9" * 5000])
async def test_malformed_signed_subjects_return_none(credential_type: str, subject: str):
    if credential_type == "mcp-oauth":
        token, _, _ = await _oauth_credential()
        record = None
    else:
        token, record, _ = await _static_credential()
    token = _resign(token, sub=subject)
    if record is not None:
        await _update_static(
            record.id,
            token_hash=hashlib.sha256(token.encode("ascii")).hexdigest(),
        )

    assert await auth.McpTokenVerifier().verify_token(token) is None


async def test_oauth_rejects_revoked_grant():
    token, grant, _ = await _oauth_credential()
    await _update_grant(grant.id, revoked_at=datetime.utcnow())

    assert await auth.McpTokenVerifier().verify_token(token) is None


async def test_oauth_rejects_old_grant_version_after_reauthorization():
    token, grant, _ = await _oauth_credential()
    await _update_grant(grant.id, version=grant.version + 1)

    assert await auth.McpTokenVerifier().verify_token(token) is None


@pytest.mark.parametrize("binding", ["user", "client", "grant"])
async def test_oauth_rejects_grant_binding_mismatch(binding: str):
    token, grant, _ = await _oauth_credential()
    if binding == "user":
        other_user = await _user()
        token = _resign(token, sub=str(other_user.id))
    elif binding == "client":
        token = _resign(token, client_id="a-different-client")
    else:
        token = _resign(token, grant_id=grant.id + 10000)

    assert await auth.McpTokenVerifier().verify_token(token) is None


@pytest.mark.parametrize("change", ["inactive", "token_version"])
async def test_oauth_rejects_inactive_user_or_changed_token_version(change: str):
    token, _, user = await _oauth_credential()
    if change == "inactive":
        await _update_user(user.id, is_active=False)
    else:
        await _update_user(user.id, token_version=user.token_version + 1)

    assert await auth.McpTokenVerifier().verify_token(token) is None


async def test_oauth_uses_current_db_role_and_intersects_current_capabilities():
    token, _, user = await _oauth_credential()
    await _update_user(user.id, role=UserRole.viewer)

    result = await auth.McpTokenVerifier().verify_token(token)

    assert result is not None
    assert result.scopes == ["market:read"]
    principal = result.claims["principal"]
    assert principal.user.role == UserRole.viewer
    assert principal.scopes == frozenset({"market:read"})


async def test_oauth_intersects_token_scopes_with_current_grant_scopes():
    token, grant, _ = await _oauth_credential()
    await _update_grant(grant.id, scopes=["market:read"])

    result = await auth.McpTokenVerifier().verify_token(token)

    assert result is not None
    assert result.scopes == ["market:read"]
    assert result.claims["principal"].scopes == frozenset({"market:read"})


async def test_write_only_oauth_token_is_rejected_after_write_capability_is_lost():
    token, _, user = await _oauth_credential(scopes=["market:write"])
    await _update_user(user.id, role=UserRole.viewer)

    assert await auth.McpTokenVerifier().verify_token(token) is None


async def test_valid_static_token_returns_db_scoped_principal_and_has_no_jwt_scopes():
    token, record, user = await _static_credential()

    result = await auth.McpTokenVerifier().verify_token(token)

    assert isinstance(result, AccessToken)
    assert result.token == token
    assert result.client_id == f"static:{record.id}"
    assert result.scopes == ALL_SCOPES
    principal = result.claims["principal"]
    assert isinstance(principal, Principal)
    assert principal.user.id == user.id
    assert principal.client_id == f"static:{record.id}"
    assert principal.grant_id is None
    assert principal.scopes == frozenset(ALL_SCOPES)
    claims = jwt.decode(
        token,
        settings.JWT_SECRET,
        algorithms=[settings.JWT_ALGORITHM],
        audience=AUDIENCE,
    )
    jti = claims.pop("jti")
    assert isinstance(jti, str)
    assert jti
    assert claims == {
        "sub": str(user.id),
        "token_version": user.token_version,
        "aud": AUDIENCE,
        "typ": "mcp-static",
    }


@pytest.mark.parametrize("change", ["revoked", "expired", "token_version", "inactive"])
async def test_static_rejects_revocation_expiry_and_current_user_invalidation(change: str):
    token, record, user = await _static_credential()
    if change == "revoked":
        await _update_static(record.id, revoked_at=datetime.utcnow())
    elif change == "expired":
        await _update_static(record.id, expires_at=datetime.utcnow() - timedelta(seconds=1))
    elif change == "token_version":
        await _update_user(user.id, token_version=user.token_version + 1)
    else:
        await _update_user(user.id, is_active=False)

    assert await auth.McpTokenVerifier().verify_token(token) is None


@pytest.mark.parametrize("mutation", ["wrong_aud", "wrong_typ", "wrong_signature", "wrong_sub"])
async def test_static_rejects_invalid_jwt_bindings(mutation: str):
    token, record, user = await _static_credential()
    if mutation == "wrong_aud":
        token = _resign(token, aud="http://example.test/mcp")
    elif mutation == "wrong_typ":
        token = _resign(token, typ="mcp-oauth")
    elif mutation == "wrong_signature":
        token = _resign(token, secret="a-wrong-signing-secret-that-is-long-enough")
    else:
        token = _resign(token, sub=str(user.id + 10000))
    await _update_static(
        record.id,
        token_hash=hashlib.sha256(token.encode("ascii")).hexdigest(),
    )

    assert await auth.McpTokenVerifier().verify_token(token) is None


async def test_static_intersects_db_scopes_with_current_capabilities_and_updates_last_used():
    token, record, user = await _static_credential()
    await _update_user(user.id, role=UserRole.viewer)

    result = await auth.McpTokenVerifier().verify_token(token)

    assert result is not None
    assert result.scopes == ["market:read"]
    assert result.claims["principal"].scopes == frozenset({"market:read"})
    async with AsyncSessionLocal() as session:
        stored = await session.get(McpApiToken, record.id)
        assert stored is not None
        assert stored.last_used_at is not None
