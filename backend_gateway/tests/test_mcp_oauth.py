"""MCP OAuth DCR, authorization-code, grant, and JWT lifecycle."""
from __future__ import annotations

import asyncio
import base64
import hashlib
import uuid

import pytest
from jose import jwt
from sqlalchemy import Insert, Select, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.db.session import AsyncSessionLocal
from app.mcp.common import oauth
from app.mcp.common.oauth import OAuthError
from app.models.mcp import McpOAuthClient, McpOAuthGrant
from app.models.user import User, UserRole
from tests.conftest import set_setting


PUBLIC_BASE = "http://127.0.0.1:8081/"
AUDIENCE = "http://127.0.0.1:8081/mcp"
VERIFIER = "correct-verifier-1234567890"


def _challenge(verifier: str = VERIFIER) -> str:
    return base64.urlsafe_b64encode(
        hashlib.sha256(verifier.encode("ascii")).digest()
    ).rstrip(b"=").decode("ascii")


def _decode(token: str) -> dict:
    return jwt.decode(
        token,
        settings.JWT_SECRET,
        algorithms=[settings.JWT_ALGORITHM],
        audience=AUDIENCE,
    )


@pytest.fixture(autouse=True)
async def _public_base_url():
    await set_setting("extensions.public_base_url", PUBLIC_BASE)


async def _user(*, role: UserRole = UserRole.tester, active: bool = True) -> User:
    async with AsyncSessionLocal() as session:
        user = User(
            username=f"oauth-{uuid.uuid4().hex}",
            password_hash="not-used-by-oauth-tests",
            role=role,
            is_active=active,
            token_version=7,
        )
        session.add(user)
        await session.commit()
        await session.refresh(user)
        return user


async def _register(**overrides) -> dict:
    metadata = {
        "client_name": "Qoder test client",
        "redirect_uris": ["http://127.0.0.1:51234/callback"],
        "token_endpoint_auth_method": "none",
        "grant_types": ["authorization_code"],
        "response_types": ["code"],
    }
    metadata.update(overrides)
    return await oauth.register_client(metadata)


def _params(client: dict, *, scopes: str = "extensions:read extensions:write") -> dict:
    return {
        "client_id": client["client_id"],
        "redirect_uri": client["redirect_uris"][0],
        "response_type": "code",
        "scope": scopes,
        "code_challenge": _challenge(),
        "code_challenge_method": "S256",
        "state": "state-123",
    }


async def _create_code(
    user: User,
    client: dict,
    *,
    scopes: str = "extensions:read extensions:write",
) -> str:
    return await oauth.create_authorization_code(_params(client, scopes=scopes), user)


async def _exchange(code: str, client: dict, **overrides) -> dict:
    params = {
        "code": code,
        "client_id": client["client_id"],
        "redirect_uri": client["redirect_uris"][0],
        "code_verifier": VERIFIER,
        "public_base": PUBLIC_BASE,
    }
    params.update(overrides)
    return await oauth.exchange_code(**params)


async def _exchange_pair_concurrently(
    codes: tuple[str, str],
    client: dict,
    monkeypatch,
) -> tuple[dict, dict]:
    """Force the legacy grant reads to overlap without replacing real DB work."""
    barrier_release = asyncio.Event()
    arrived = 0
    original_execute = AsyncSession.execute

    async with AsyncSessionLocal() as first, AsyncSessionLocal() as second:
        participant_ids = {id(first), id(second)}
        upserted_session_ids = set()

        async def execute(session, statement, *args, **kwargs):
            nonlocal arrived
            if (
                isinstance(statement, Insert)
                and statement.table == McpOAuthGrant.__table__
            ):
                upserted_session_ids.add(id(session))
            is_grant_read = isinstance(statement, Select) and any(
                description["entity"] is McpOAuthGrant
                for description in statement.column_descriptions
            )
            if (
                id(session) in participant_ids
                and id(session) not in upserted_session_ids
                and is_grant_read
            ):
                arrived += 1
                if arrived == 2:
                    barrier_release.set()
                await barrier_release.wait()
            return await original_execute(session, statement, *args, **kwargs)

        monkeypatch.setattr(AsyncSession, "execute", execute)
        try:
            return await asyncio.gather(
                _exchange(codes[0], client, session=first),
                _exchange(codes[1], client, session=second),
            )
        finally:
            monkeypatch.setattr(AsyncSession, "execute", original_execute)


@pytest.mark.parametrize(
    "redirect_uri",
    [
        "http://127.0.0.1:51234/callback",
        "http://localhost:51234/callback",
        "http://[::1]:51234/callback",
    ],
)
async def test_register_client_accepts_http_loopback_and_defaults_all_scopes(
    redirect_uri: str,
):
    registered = await _register(redirect_uris=[redirect_uri])

    assert registered["token_endpoint_auth_method"] == "none"
    assert "client_secret" not in registered
    assert registered["scope"] == "extensions:read extensions:write"
    async with AsyncSessionLocal() as session:
        stored = await session.get(McpOAuthClient, registered["client_id"])
        assert stored is not None
        assert stored.redirect_uris == [redirect_uri]
        assert stored.scopes == ["extensions:read", "extensions:write"]


@pytest.mark.parametrize(
    "redirect_uri",
    [
        "https://127.0.0.1:51234/callback",
        "http://10.0.0.5:51234/callback",
        "http://example.com/callback",
        "http://127.0.0.1.evil.example/callback",
        "http://evil.example@127.0.0.1/callback",
    ],
)
async def test_register_client_rejects_non_http_or_non_loopback_redirects(
    redirect_uri: str,
):
    with pytest.raises(OAuthError) as exc_info:
        await _register(redirect_uris=[redirect_uri])

    assert exc_info.value.error == "invalid_redirect_uri"


@pytest.mark.parametrize(
    "override",
    [
        {"token_endpoint_auth_method": "client_secret_basic"},
        {"client_secret": "must-not-be-issued-or-accepted"},
    ],
)
async def test_register_client_rejects_confidential_client_shape(override: dict):
    with pytest.raises(OAuthError) as exc_info:
        await _register(**override)

    assert exc_info.value.error == "invalid_client_metadata"


@pytest.mark.parametrize(
    "override",
    [
        {"grant_types": ["client_credentials"]},
        {"response_types": ["token"]},
    ],
)
async def test_register_client_rejects_unsupported_flow(override: dict):
    with pytest.raises(OAuthError) as exc_info:
        await _register(**override)

    assert exc_info.value.error == "invalid_client_metadata"


async def test_register_client_accepts_sdk_interactive_defaults():
    registered = await oauth.register_client(
        {
            "client_name": "Qoder MCP client",
            "redirect_uris": ["http://127.0.0.1:51234/callback"],
            "token_endpoint_auth_method": "none",
            "grant_types": ["authorization_code", "refresh_token"],
            "response_types": ["code"],
            "application_type": "native",
            "scope": "extensions:read extensions:write",
        }
    )

    assert registered["grant_types"] == ["authorization_code"]
    assert registered["response_types"] == ["code"]


async def test_register_client_rejects_unsupported_scope():
    with pytest.raises(OAuthError) as exc_info:
        await _register(scope="extensions:read admin:write")

    assert exc_info.value.error == "invalid_scope"


async def test_validate_authorization_normalizes_registered_request():
    client = await _register()

    validated = await oauth.validate_authorization(_params(client))

    assert validated["client_id"] == client["client_id"]
    assert validated["redirect_uri"] == client["redirect_uris"][0]
    assert validated["scopes"] == ["extensions:read", "extensions:write"]
    assert validated["code_challenge"] == _challenge()
    assert validated["code_challenge_method"] == "S256"
    assert validated["state"] == "state-123"


@pytest.mark.parametrize(
    "override",
    [
        {"redirect_uri": "http://localhost:51234/not-registered"},
        {"code_challenge_method": "plain"},
        {"code_challenge": ""},
        {"response_type": "token"},
        {"scope": "extensions:read unknown:scope"},
    ],
)
async def test_validate_authorization_rejects_unbound_or_non_s256_requests(
    override: dict,
):
    client = await _register()
    params = _params(client)
    params.update(override)

    with pytest.raises(OAuthError):
        await oauth.validate_authorization(params)


async def test_allowed_scopes_uses_current_publish_policy_and_user_state():
    user = await _user()
    await set_setting("extensions.publisher_roles", "tester")
    assert await oauth.allowed_scopes(user) == ["extensions:read", "extensions:write"]

    await set_setting("extensions.publisher_roles", "")
    assert await oauth.allowed_scopes(user) == ["extensions:read"]

    user.is_active = False
    assert await oauth.allowed_scopes(user) == []


async def test_create_authorization_code_rejects_scope_user_cannot_publish():
    client = await _register()
    user = await _user(role=UserRole.viewer)
    await set_setting("extensions.publisher_roles", "")

    with pytest.raises(OAuthError) as exc_info:
        await _create_code(user, client, scopes="extensions:read extensions:write")

    assert exc_info.value.error == "invalid_scope"


async def test_exchange_code_rejects_wrong_pkce_verifier():
    client = await _register()
    user = await _user()
    code = await _create_code(user, client)

    with pytest.raises(OAuthError) as exc_info:
        await _exchange(code, client, code_verifier="wrong-verifier")

    assert exc_info.value.error == "invalid_grant"


async def test_exchange_code_rejects_second_use():
    client = await _register()
    user = await _user()
    code = await _create_code(user, client)
    await _exchange(code, client)

    with pytest.raises(OAuthError) as exc_info:
        await _exchange(code, client)

    assert exc_info.value.error == "invalid_grant"


@pytest.mark.parametrize("binding", ["client_id", "redirect_uri"])
async def test_exchange_code_enforces_client_and_redirect_binding(binding: str):
    client = await _register()
    user = await _user()
    code = await _create_code(user, client)
    wrong_value = (
        "another-client"
        if binding == "client_id"
        else "http://localhost:51234/another-callback"
    )

    with pytest.raises(OAuthError) as exc_info:
        await _exchange(code, client, **{binding: wrong_value})

    assert exc_info.value.error == "invalid_grant"


async def test_exchange_code_rejects_code_older_than_five_minutes(monkeypatch):
    now = [1_000.0]
    monkeypatch.setattr(oauth.time, "time", lambda: now[0])
    client = await _register()
    user = await _user()
    code = await _create_code(user, client)
    now[0] += 301

    with pytest.raises(OAuthError) as exc_info:
        await _exchange(code, client)

    assert exc_info.value.error == "invalid_grant"


async def test_exchange_code_persists_grant_and_issues_no_exp_mcp_jwt():
    client = await _register()
    user = await _user()
    code = await _create_code(user, client)

    result = await _exchange(code, client)
    claims = _decode(result["access_token"])

    assert result["token_type"] == "bearer"
    assert result["scope"] == "extensions:read extensions:write"
    assert "exp" not in claims
    assert claims == {
        "sub": str(user.id),
        "client_id": client["client_id"],
        "grant_id": claims["grant_id"],
        "grant_version": 1,
        "token_version": 7,
        "scopes": ["extensions:read", "extensions:write"],
        "aud": AUDIENCE,
        "typ": "mcp-oauth",
    }
    assert isinstance(claims["grant_id"], int)
    async with AsyncSessionLocal() as session:
        grant = await session.get(McpOAuthGrant, claims["grant_id"])
        assert grant is not None
        assert grant.user_id == user.id
        assert grant.client_id == client["client_id"]
        assert grant.scopes == ["extensions:read", "extensions:write"]
        assert grant.version == 1
        assert grant.revoked_at is None


async def test_exchange_code_applies_publish_policy_again_before_issuing():
    client = await _register()
    user = await _user()
    await set_setting("extensions.publisher_roles", "tester")
    code = await _create_code(user, client)
    await set_setting("extensions.publisher_roles", "")

    result = await _exchange(code, client)
    claims = _decode(result["access_token"])

    assert claims["scopes"] == ["extensions:read"]
    assert result["scope"] == "extensions:read"
    async with AsyncSessionLocal() as session:
        grant = await session.get(McpOAuthGrant, claims["grant_id"])
        assert grant is not None
        assert grant.scopes == ["extensions:read"]


async def test_reauthorization_increments_version_and_does_not_revive_old_token():
    client = await _register()
    user = await _user()
    old_token = (await _exchange(await _create_code(user, client), client))["access_token"]
    old_claims = _decode(old_token)
    await oauth.revoke_token(old_token)

    async with AsyncSessionLocal() as session:
        revoked = await session.get(McpOAuthGrant, old_claims["grant_id"])
        assert revoked is not None
        assert revoked.revoked_at is not None

    new_token = (await _exchange(await _create_code(user, client), client))["access_token"]
    new_claims = _decode(new_token)

    assert new_claims["grant_id"] == old_claims["grant_id"]
    assert new_claims["grant_version"] == old_claims["grant_version"] + 1
    assert old_claims["grant_version"] == 1
    async with AsyncSessionLocal() as session:
        grant = await session.get(McpOAuthGrant, old_claims["grant_id"])
        assert grant is not None
        assert grant.revoked_at is None
        assert grant.version == new_claims["grant_version"]
        assert grant.version != old_claims["grant_version"]
        stored = await session.execute(select(McpOAuthGrant).where(
            McpOAuthGrant.user_id == user.id,
            McpOAuthGrant.client_id == client["client_id"],
        ))
        assert len(stored.scalars().all()) == 1


async def test_concurrent_reauthorization_assigns_distinct_versions(monkeypatch):
    client = await _register()
    user = await _user()
    initial = await _exchange(await _create_code(user, client), client)
    assert _decode(initial["access_token"])["grant_version"] == 1
    codes = (
        await _create_code(user, client),
        await _create_code(user, client),
    )

    results = await _exchange_pair_concurrently(codes, client, monkeypatch)
    claims = [_decode(result["access_token"]) for result in results]

    assert {claim["grant_version"] for claim in claims} == {2, 3}
    async with AsyncSessionLocal() as session:
        grant = (
            await session.execute(
                select(McpOAuthGrant).where(
                    McpOAuthGrant.user_id == user.id,
                    McpOAuthGrant.client_id == client["client_id"],
                )
            )
        ).scalar_one()
        assert grant.version == 3
        assert {claim["grant_id"] for claim in claims} == {grant.id}


async def test_concurrent_first_exchange_creates_one_grant_with_distinct_versions(
    monkeypatch,
):
    client = await _register()
    user = await _user()
    codes = (
        await _create_code(user, client),
        await _create_code(user, client),
    )

    results = await _exchange_pair_concurrently(codes, client, monkeypatch)
    claims = [_decode(result["access_token"]) for result in results]

    assert {claim["grant_version"] for claim in claims} == {1, 2}
    async with AsyncSessionLocal() as session:
        grants = (
            (
                await session.execute(
                    select(McpOAuthGrant).where(
                        McpOAuthGrant.user_id == user.id,
                        McpOAuthGrant.client_id == client["client_id"],
                    )
                )
            )
            .scalars()
            .all()
        )
        assert len(grants) == 1
        assert grants[0].version == 2
        assert {claim["grant_id"] for claim in claims} == {grants[0].id}
