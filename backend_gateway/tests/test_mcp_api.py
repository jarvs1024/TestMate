"""Integration tests for the authenticated MCP consent, grant, and token APIs."""
from __future__ import annotations

import base64
import hashlib
from datetime import UTC, datetime, timedelta
from urllib.parse import parse_qs, urlsplit

import pytest

from app.db.session import AsyncSessionLocal
from app.mcp.common.auth import McpTokenVerifier
from app.models.mcp import McpApiToken, McpOAuthGrant
from tests.conftest import set_setting

PUBLIC_BASE = "http://127.0.0.1:8081/"
VERIFIER = "correct-verifier-1234567890"
REDIRECT_URI = "http://127.0.0.1:51234/callback"
TOKEN_METADATA_FIELDS = {
    "id",
    "name",
    "user_id",
    "username",
    "scopes",
    "expires_at",
    "revoked_at",
    "last_used_at",
    "created_at",
    "token",
}


@pytest.fixture(autouse=True)
async def _mcp_api_settings():
    await set_setting("marketplace.public_base_url", PUBLIC_BASE)
    await set_setting("marketplace.publisher_roles", "tester")


def _auth(user: dict) -> dict[str, str]:
    return {"Authorization": f"Bearer {user['token']}"}


def _challenge() -> str:
    return base64.urlsafe_b64encode(
        hashlib.sha256(VERIFIER.encode("ascii")).digest()
    ).rstrip(b"=").decode("ascii")


async def _register(client, redirect_uri: str = REDIRECT_URI) -> dict:
    response = await client.post(
        "/oauth/register",
        json={
            "client_name": "Task 5 API client",
            "redirect_uris": [redirect_uri],
            "token_endpoint_auth_method": "none",
            "grant_types": ["authorization_code"],
            "response_types": ["code"],
        },
    )
    assert response.status_code == 201, response.text
    return response.json()


def _authorization_params(registered: dict, **overrides) -> dict:
    params = {
        "client_id": registered["client_id"],
        "redirect_uri": registered["redirect_uris"][0],
        "response_type": "code",
        "scope": "market:read market:write",
        "code_challenge": _challenge(),
        "code_challenge_method": "S256",
        "state": "state with spaces/&",
    }
    params.update(overrides)
    return params


def _assert_oauth_error(response, error: str) -> None:
    assert response.status_code == 400, response.text
    payload = response.json()
    assert set(payload) == {"detail"}
    assert set(payload["detail"]) == {"error", "error_description"}
    assert payload["detail"]["error"] == error
    assert isinstance(payload["detail"]["error_description"], str)
    assert payload["detail"]["error_description"]


async def _grant(user_id: int, registered: dict, scopes: list[str]) -> McpOAuthGrant:
    async with AsyncSessionLocal() as session:
        grant = McpOAuthGrant(
            user_id=user_id,
            client_id=registered["client_id"],
            scopes=scopes,
            version=3,
            created_at=datetime(2026, 10, 31, 12, 0, 0),
            updated_at=datetime(2026, 10, 31, 12, 0, 0),
        )
        session.add(grant)
        await session.commit()
        await session.refresh(grant)
        return grant


async def _create_token(
    client,
    user: dict,
    **overrides,
) -> tuple[dict, dict]:
    payload = {
        "name": "CI static token",
        "scopes": ["market:read", "market:write"],
    }
    payload.update(overrides)
    response = await client.post(
        "/api/v1/mcp/tokens", json=payload, headers=_auth(user)
    )
    assert response.status_code == 201, response.text
    return response.json(), payload


async def test_viewer_preview_intersects_requested_scopes_with_current_capabilities(
    client, stranger_user
):
    registered = await _register(client)

    response = await client.get(
        "/api/v1/mcp/authorize/preview",
        params=_authorization_params(registered),
        headers=_auth(stranger_user),
    )

    assert response.status_code == 200, response.text
    assert response.json() == {
        "client_id": registered["client_id"],
        "client_name": "Task 5 API client",
        "redirect_uri": REDIRECT_URI,
        "scopes": ["market:read"],
        "response_type": "code",
        "code_challenge": _challenge(),
        "code_challenge_method": "S256",
        "state": "state with spaces/&",
    }


async def test_publisher_preview_includes_current_write_capability(
    client, publisher_user
):
    registered = await _register(client)

    response = await client.get(
        "/api/v1/mcp/authorize/preview",
        params=_authorization_params(registered),
        headers=_auth(publisher_user),
    )

    assert response.status_code == 200, response.text
    assert response.json()["scopes"] == ["market:read", "market:write"]


async def test_preview_oauth_errors_use_structured_http_detail(client, stranger_user):
    response = await client.get(
        "/api/v1/mcp/authorize/preview",
        params={"response_type": "code"},
        headers=_auth(stranger_user),
    )

    _assert_oauth_error(response, "invalid_request")


async def test_consent_rejects_any_scope_beyond_current_user_capability(
    client, stranger_user
):
    registered = await _register(client)

    response = await client.post(
        "/api/v1/mcp/authorize",
        json=_authorization_params(registered),
        headers=_auth(stranger_user),
    )

    _assert_oauth_error(response, "invalid_scope")


async def test_consent_callback_preserves_query_and_state_and_code_exchanges(
    client, publisher_user
):
    redirect_uri = f"{REDIRECT_URI}?existing=kept"
    registered = await _register(client, redirect_uri)
    params = _authorization_params(registered)

    response = await client.post(
        "/api/v1/mcp/authorize", json=params, headers=_auth(publisher_user)
    )

    assert response.status_code == 200, response.text
    assert set(response.json()) == {"callback_url"}
    callback_url = response.json()["callback_url"]
    assert callback_url.startswith(f"{redirect_uri}&")
    callback_query = parse_qs(urlsplit(callback_url).query)
    assert callback_query["existing"] == ["kept"]
    assert callback_query["state"] == ["state with spaces/&"]
    code = callback_query["code"][0]

    exchanged = await client.post(
        "/oauth/token",
        data={
            "grant_type": "authorization_code",
            "code": code,
            "client_id": registered["client_id"],
            "redirect_uri": redirect_uri,
            "code_verifier": VERIFIER,
        },
    )
    assert exchanged.status_code == 200, exchanged.text
    assert exchanged.json()["scope"] == "market:read market:write"


async def test_consent_omits_absent_state_from_callback(client, publisher_user):
    registered = await _register(client)
    params = _authorization_params(registered, state=None)
    del params["state"]

    response = await client.post(
        "/api/v1/mcp/authorize", json=params, headers=_auth(publisher_user)
    )

    assert response.status_code == 200, response.text
    assert "state" not in parse_qs(urlsplit(response.json()["callback_url"]).query)


async def test_grants_are_scoped_to_current_user_and_include_client_metadata(
    client, publisher_user, stranger_user
):
    registered = await _register(client)
    own = await _grant(publisher_user["id"], registered, ["market:read"])
    await _grant(stranger_user["id"], registered, ["market:read", "market:write"])

    response = await client.get("/api/v1/mcp/grants", headers=_auth(publisher_user))

    assert response.status_code == 200, response.text
    assert set(response.json()) == {"items"}
    assert len(response.json()["items"]) == 1
    item = response.json()["items"][0]
    assert set(item) == {
        "id",
        "client_id",
        "client_name",
        "scopes",
        "version",
        "revoked_at",
        "created_at",
        "updated_at",
    }
    assert item == {
        "id": own.id,
        "client_id": registered["client_id"],
        "client_name": "Task 5 API client",
        "scopes": ["market:read"],
        "version": 3,
        "revoked_at": None,
        "created_at": "2026-10-31T12:00:00Z",
        "updated_at": "2026-10-31T12:00:00Z",
    }


async def test_user_cannot_revoke_another_users_grant_and_own_revocation_keeps_history(
    client, publisher_user, stranger_user
):
    registered = await _register(client)
    own = await _grant(publisher_user["id"], registered, ["market:read"])
    other = await _grant(stranger_user["id"], registered, ["market:read"])

    forbidden = await client.delete(
        f"/api/v1/mcp/grants/{other.id}", headers=_auth(publisher_user)
    )
    missing = await client.delete(
        "/api/v1/mcp/grants/999999", headers=_auth(publisher_user)
    )
    revoked = await client.delete(
        f"/api/v1/mcp/grants/{own.id}", headers=_auth(publisher_user)
    )

    assert forbidden.status_code == 404, forbidden.text
    assert missing.status_code == 404, missing.text
    assert revoked.status_code == 200, revoked.text
    assert revoked.json() == {}
    async with AsyncSessionLocal() as session:
        assert (await session.get(McpOAuthGrant, other.id)).revoked_at is None
        persisted_own = await session.get(McpOAuthGrant, own.id)
        assert persisted_own is not None
        assert persisted_own.revoked_at is not None


async def test_tokens_are_self_service_and_scoped_to_creator(
    client, publisher_user, stranger_user
):
    created, _ = await _create_token(client, publisher_user, scopes=["market:read"])

    own = await client.get("/api/v1/mcp/tokens", headers=_auth(publisher_user))
    assert own.status_code == 200, own.text
    assert [item["id"] for item in own.json()["items"]] == [created["id"]]

    other = await client.get("/api/v1/mcp/tokens", headers=_auth(stranger_user))
    assert other.status_code == 200, other.text
    assert other.json()["items"] == []

    forbidden = await client.delete(
        f"/api/v1/mcp/tokens/{created['id']}", headers=_auth(stranger_user)
    )
    assert forbidden.status_code == 404, forbidden.text


async def test_token_scope_options_follow_current_capability(
    client, publisher_user, stranger_user
):
    publisher_scopes = await client.get(
        "/api/v1/mcp/tokens/scopes", headers=_auth(publisher_user)
    )
    stranger_scopes = await client.get(
        "/api/v1/mcp/tokens/scopes", headers=_auth(stranger_user)
    )

    assert publisher_scopes.status_code == 200, publisher_scopes.text
    assert publisher_scopes.json() == {"scopes": ["market:read", "market:write"]}
    assert stranger_scopes.status_code == 200, stranger_scopes.text
    assert stranger_scopes.json() == {"scopes": ["market:read"]}


async def test_token_creation_rejects_scopes_beyond_current_capability(
    client, stranger_user
):
    response = await client.post(
        "/api/v1/mcp/tokens",
        json={"name": "too powerful", "scopes": ["market:read", "market:write"]},
        headers=_auth(stranger_user),
    )

    assert response.status_code == 403, response.text
    assert "market:write" in response.json()["detail"]


async def test_static_token_plaintext_is_visible_and_db_stores_sha256(
    client, publisher_user
):
    created, _ = await _create_token(
        client,
        publisher_user,
        expires_at="2099-01-02T03:04:05Z",
    )

    assert set(created) == TOKEN_METADATA_FIELDS
    plaintext = created["token"]
    assert plaintext
    assert created["name"] == "CI static token"
    assert created["user_id"] == publisher_user["id"]
    assert created["username"] == publisher_user["username"]
    assert created["scopes"] == ["market:read", "market:write"]
    assert created["expires_at"] == "2099-01-02T03:04:05Z"
    assert created["revoked_at"] is None
    assert created["last_used_at"] is None
    assert created["created_at"].endswith("Z")

    async with AsyncSessionLocal() as session:
        stored = await session.get(McpApiToken, created["id"])
        assert stored is not None
        assert stored.token_hash == hashlib.sha256(plaintext.encode("ascii")).hexdigest()
        assert stored.token_hash != plaintext
        assert stored.token_value == plaintext

    verified = await McpTokenVerifier().verify_token(plaintext)
    assert verified is not None
    assert verified.scopes == ["market:read", "market:write"]

    listed = await client.get("/api/v1/mcp/tokens", headers=_auth(publisher_user))
    assert listed.status_code == 200, listed.text
    assert plaintext in listed.text
    assert len(listed.json()["items"]) == 1
    item = listed.json()["items"][0]
    assert set(item) == TOKEN_METADATA_FIELDS
    assert "token_hash" not in item
    assert item["id"] == created["id"]
    assert item["token"] == plaintext
    assert item["last_used_at"] is not None


async def test_repeated_static_token_issuance_creates_distinct_active_tokens(
    client, publisher_user
):
    first, _ = await _create_token(client, publisher_user)
    second, _ = await _create_token(client, publisher_user)

    assert first["id"] != second["id"]
    assert first["token"] != second["token"]
    first_hash = hashlib.sha256(first["token"].encode("ascii")).hexdigest()
    second_hash = hashlib.sha256(second["token"].encode("ascii")).hexdigest()
    assert first_hash != second_hash
    async with AsyncSessionLocal() as session:
        first_stored = await session.get(McpApiToken, first["id"])
        second_stored = await session.get(McpApiToken, second["id"])
        assert first_stored is not None
        assert second_stored is not None
        assert first_stored.token_hash == first_hash
        assert second_stored.token_hash == second_hash
        assert first_stored.token_value == first["token"]
        assert second_stored.token_value == second["token"]

    verifier = McpTokenVerifier()
    assert await verifier.verify_token(first["token"]) is not None
    assert await verifier.verify_token(second["token"]) is not None


async def test_static_token_deletion_invalidates_and_allows_replacement(
    client, publisher_user
):
    deleted, _ = await _create_token(client, publisher_user)
    verifier = McpTokenVerifier()
    assert await verifier.verify_token(deleted["token"]) is not None

    response = await client.delete(
        f"/api/v1/mcp/tokens/{deleted['id']}", headers=_auth(publisher_user)
    )
    assert response.status_code == 200, response.text
    assert response.json() == {}
    assert await verifier.verify_token(deleted["token"]) is None

    replacement, _ = await _create_token(client, publisher_user)

    assert replacement["id"] != deleted["id"]
    assert replacement["token"] != deleted["token"]
    assert await verifier.verify_token(replacement["token"]) is not None
    assert await verifier.verify_token(deleted["token"]) is None


async def test_deleted_static_token_is_removed_from_list_and_db(
    client, publisher_user
):
    created, _ = await _create_token(client, publisher_user)
    plaintext = created["token"]
    assert await McpTokenVerifier().verify_token(plaintext) is not None

    response = await client.delete(
        f"/api/v1/mcp/tokens/{created['id']}", headers=_auth(publisher_user)
    )

    assert response.status_code == 200, response.text
    assert response.json() == {}
    assert plaintext not in response.text
    assert await McpTokenVerifier().verify_token(plaintext) is None
    async with AsyncSessionLocal() as session:
        assert await session.get(McpApiToken, created["id"]) is None

    listed = await client.get("/api/v1/mcp/tokens", headers=_auth(publisher_user))
    assert listed.json()["items"] == []


async def test_expired_static_token_fails_verifier(client, publisher_user):
    created, _ = await _create_token(client, publisher_user)
    async with AsyncSessionLocal() as session:
        stored = await session.get(McpApiToken, created["id"])
        stored.expires_at = datetime.now(UTC).replace(tzinfo=None) - timedelta(seconds=1)
        await session.commit()

    assert await McpTokenVerifier().verify_token(created["token"]) is None


async def test_deleting_missing_static_token_returns_404(client, publisher_user):
    response = await client.delete(
        "/api/v1/mcp/tokens/999999", headers=_auth(publisher_user)
    )

    assert response.status_code == 404, response.text


@pytest.mark.parametrize(
    "overrides",
    [
        {"name": ""},
        {"name": "   "},
        {"scopes": []},
        {"scopes": "market:read"},
        {"scopes": ["market:read", "market:delete"]},
        {"expires_at": "not-a-date"},
        {"expires_at": "2000-01-01T00:00:00Z"},
    ],
)
async def test_static_token_input_validation(
    client, publisher_user, overrides: dict
):
    payload = {
        "name": "valid name",
        "scopes": ["market:read"],
    }
    payload.update(overrides)

    response = await client.post(
        "/api/v1/mcp/tokens", json=payload, headers=_auth(publisher_user)
    )

    assert response.status_code == 422, response.text
