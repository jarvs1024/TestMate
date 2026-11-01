"""HTTP integration tests for MCP OAuth routes and discovery metadata."""
from __future__ import annotations

import base64
import hashlib
import uuid
from urllib.parse import urlencode

import pytest
from jose import jwt
from sqlalchemy import select

from app.core.config import settings
from app.db.session import AsyncSessionLocal
from app.mcp.common import oauth
from app.models.mcp import McpOAuthGrant
from app.models.user import User, UserRole
from tests.conftest import set_setting

PUBLIC_BASE = "http://127.0.0.1:8081/"
ISSUER = "http://127.0.0.1:8081"
VERIFIER = "correct-verifier-1234567890"
REDIRECT_URI = "http://127.0.0.1:51234/callback"


def _challenge() -> str:
    return base64.urlsafe_b64encode(
        hashlib.sha256(VERIFIER.encode("ascii")).digest()
    ).rstrip(b"=").decode("ascii")


@pytest.fixture(autouse=True)
async def _oauth_settings():
    await set_setting("marketplace.public_base_url", PUBLIC_BASE)
    await set_setting("marketplace.publisher_roles", "tester")


async def _register(client, **overrides) -> dict:
    metadata = {
        "client_name": "Qoder HTTP test client",
        "redirect_uris": [REDIRECT_URI],
        "token_endpoint_auth_method": "none",
        "grant_types": ["authorization_code"],
        "response_types": ["code"],
    }
    metadata.update(overrides)
    response = await client.post("/oauth/register", json=metadata)
    assert response.status_code == 201, response.text
    return response.json()


def _authorization_params(client_metadata: dict, **overrides) -> dict:
    params = {
        "client_id": client_metadata["client_id"],
        "redirect_uri": REDIRECT_URI,
        "response_type": "code",
        "scope": "market:read market:write",
        "code_challenge": _challenge(),
        "code_challenge_method": "S256",
        "state": "state with spaces/&",
    }
    params.update(overrides)
    return params


async def _user() -> User:
    async with AsyncSessionLocal() as session:
        user = User(
            username=f"oauth-http-{uuid.uuid4().hex}",
            password_hash="not-used-by-oauth-http-tests",
            role=UserRole.tester,
            is_active=True,
            token_version=7,
        )
        session.add(user)
        await session.commit()
        await session.refresh(user)
        return user


async def _code(client, client_metadata: dict) -> tuple[str, User]:
    user = await _user()
    code = await oauth.create_authorization_code(
        _authorization_params(client_metadata), user
    )
    return code, user


async def _exchange(client, client_metadata: dict) -> tuple[dict, User]:
    code, user = await _code(client, client_metadata)
    response = await client.post(
        "/oauth/token",
        data={
            "grant_type": "authorization_code",
            "code": code,
            "client_id": client_metadata["client_id"],
            "redirect_uri": REDIRECT_URI,
            "code_verifier": VERIFIER,
        },
    )
    assert response.status_code == 200, response.text
    return response.json(), user


def _assert_oauth_error(response, error: str | None = None) -> None:
    assert response.status_code == 400, response.text
    assert response.headers["content-type"].startswith("application/json")
    payload = response.json()
    assert set(payload) == {"error", "error_description"}
    assert isinstance(payload["error_description"], str)
    assert payload["error_description"]
    if error is not None:
        assert payload["error"] == error


async def test_authorization_server_metadata_advertises_internal_http_issuer(client):
    response = await client.get("/.well-known/oauth-authorization-server")

    assert response.status_code == 200
    assert response.json() == {
        "issuer": ISSUER,
        "authorization_endpoint": f"{ISSUER}/oauth/authorize",
        "token_endpoint": f"{ISSUER}/oauth/token",
        "registration_endpoint": f"{ISSUER}/oauth/register",
        "revocation_endpoint": f"{ISSUER}/oauth/revoke",
        "scopes_supported": ["market:read", "market:write"],
        "response_types_supported": ["code"],
        "grant_types_supported": ["authorization_code"],
        "token_endpoint_auth_methods_supported": ["none"],
        "code_challenge_methods_supported": ["S256"],
    }


async def test_protected_resource_metadata_targets_mcp_skill(client):
    response = await client.get("/.well-known/oauth-protected-resource/mcp/skill")

    assert response.status_code == 200
    assert response.json() == {
        "resource": f"{ISSUER}/mcp/skill",
        "authorization_servers": [ISSUER],
        "scopes_supported": ["market:read", "market:write"],
        "bearer_methods_supported": ["header"],
    }


async def test_register_returns_task2_client_metadata_with_201(client):
    registered = await _register(client)

    assert registered["client_id"]
    assert registered == {
        "client_id": registered["client_id"],
        "client_name": "Qoder HTTP test client",
        "redirect_uris": [REDIRECT_URI],
        "token_endpoint_auth_method": "none",
        "grant_types": ["authorization_code"],
        "response_types": ["code"],
        "scope": "market:read market:write",
    }
    assert "client_secret" not in registered


async def test_register_oauth_error_uses_protocol_json_shape(client):
    response = await client.post(
        "/oauth/register",
        json={
            "redirect_uris": ["https://example.com/callback"],
            "token_endpoint_auth_method": "none",
            "grant_types": ["authorization_code"],
            "response_types": ["code"],
        },
    )

    _assert_oauth_error(response, "invalid_redirect_uri")


async def test_register_malformed_json_is_not_a_server_error(client):
    response = await client.post(
        "/oauth/register",
        content=b"{not-json",
        headers={"content-type": "application/json"},
    )

    _assert_oauth_error(response, "invalid_request")


async def test_authorize_redirects_to_spa_with_original_validated_query(client):
    registered = await _register(client)
    params = _authorization_params(registered)

    response = await client.get("/oauth/authorize", params=params)

    assert response.status_code == 302
    assert response.headers["location"] == f"/connect/authorize?{urlencode(params)}"
    assert "code" not in params


async def test_authorize_validation_error_uses_protocol_json_shape(client):
    response = await client.get("/oauth/authorize", params={"response_type": "code"})

    _assert_oauth_error(response, "invalid_request")


async def test_token_exchanges_real_form_authorization_code(client):
    registered = await _register(client)
    code, user = await _code(client, registered)

    response = await client.post(
        "/oauth/token",
        data={
            "grant_type": "authorization_code",
            "code": code,
            "client_id": registered["client_id"],
            "redirect_uri": REDIRECT_URI,
            "code_verifier": VERIFIER,
        },
    )

    assert response.status_code == 200, response.text
    payload = response.json()
    assert set(payload) == {"access_token", "token_type", "scope"}
    assert payload["token_type"] == "bearer"
    assert payload["scope"] == "market:read market:write"
    claims = jwt.decode(
        payload["access_token"],
        settings.JWT_SECRET,
        algorithms=[settings.JWT_ALGORITHM],
        audience=f"{ISSUER}/mcp",
    )
    assert claims["sub"] == str(user.id)
    assert claims["client_id"] == registered["client_id"]


async def test_token_rejects_unsupported_grant_type(client):
    response = await client.post(
        "/oauth/token",
        data={"grant_type": "client_credentials"},
    )

    _assert_oauth_error(response, "unsupported_grant_type")


@pytest.mark.parametrize("missing", ["code", "client_id", "redirect_uri", "code_verifier"])
async def test_token_missing_required_fields_uses_protocol_json_shape(client, missing):
    form = {
        "grant_type": "authorization_code",
        "code": "code",
        "client_id": "client",
        "redirect_uri": REDIRECT_URI,
        "code_verifier": VERIFIER,
    }
    del form[missing]

    response = await client.post("/oauth/token", data=form)

    _assert_oauth_error(response, "invalid_request")


async def test_revoke_returns_empty_object_and_revokes_persisted_grant(client):
    registered = await _register(client)
    token, user = await _exchange(client, registered)

    response = await client.post(
        "/oauth/revoke", data={"token": token["access_token"]}
    )

    assert response.status_code == 200, response.text
    assert response.json() == {}
    async with AsyncSessionLocal() as session:
        grant = (
            await session.execute(
                select(McpOAuthGrant).where(
                    McpOAuthGrant.user_id == user.id,
                    McpOAuthGrant.client_id == registered["client_id"],
                )
            )
        ).scalar_one()
        assert grant.revoked_at is not None


@pytest.mark.parametrize(
    ("path", "content"),
    [
        ("/oauth/token", b"\xff"),
        ("/oauth/revoke", b"\xff"),
    ],
)
async def test_malformed_form_is_not_a_server_error(client, path, content):
    response = await client.post(
        path,
        content=content,
        headers={"content-type": "application/x-www-form-urlencoded"},
    )

    _assert_oauth_error(response, "invalid_request")


async def test_revoke_requires_token(client):
    response = await client.post("/oauth/revoke", data={})

    _assert_oauth_error(response, "invalid_request")
