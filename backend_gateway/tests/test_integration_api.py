"""集成凭据 REST API: 传输解密 → 登录验证 → 加密落库."""
from __future__ import annotations

import base64
import json
from datetime import UTC, datetime, timedelta

import httpx
import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import padding

from app.db.session import AsyncSessionLocal
from app.integrations import crypto
from app.integrations.pingcode import client as pingcode_client
from app.models.integration import IntegrationCredential

BASE = "/api/v1/integrations"
USERNAME = "demo-user"
PASSWORD = "p@ss-中文-123"


def _auth(user: dict) -> dict[str, str]:
    return {"Authorization": f"Bearer {user['token']}"}


def _session(**overrides) -> pingcode_client.PingCodeSession:
    values = {
        "access_token": "jwt-access-token",
        "team_id": "66209672995cb95d777b6aec",
        "display_name": "测试同学",
        "team_name": "天府团队",
        "cookies": {"s-66209672995cb95d777b6aec": "cookie-value"},
        "access_token_expires_at": datetime.now(UTC).replace(tzinfo=None)
        + timedelta(minutes=90),
    }
    values.update(overrides)
    return pingcode_client.PingCodeSession(**values)


def _fake_signin(result=None, error: Exception | None = None, calls: list | None = None):
    async def signin(username: str, password: str, **kwargs):
        if calls is not None:
            calls.append((username, password))
        if error is not None:
            raise error
        return result or _session()

    return signin


async def _encrypt_payload(client: httpx.AsyncClient, user: dict, payload: dict) -> str:
    response = await client.get(f"{BASE}/crypto/public-key", headers=_auth(user))
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["algorithm"] == "RSA-PKCS1v15"
    public_key = serialization.load_pem_public_key(body["public_key"].encode("ascii"))
    ciphertext = public_key.encrypt(
        json.dumps(payload, ensure_ascii=False).encode("utf-8"), padding.PKCS1v15()
    )
    return base64.b64encode(ciphertext).decode("ascii")


async def _clear_rate_limit(user_id: int) -> None:
    from app.integrations.redis import redis_client

    async with redis_client() as redis:
        keys = await redis.keys(f"integration:credential_attempts:{user_id}")
        if keys:
            await redis.delete(*keys)


async def _credential(user_id: int, provider: str = "pingcode") -> IntegrationCredential | None:
    async with AsyncSessionLocal() as session:
        rows = (
            await session.execute(
                IntegrationCredential.__table__.select().where(
                    IntegrationCredential.user_id == user_id,
                    IntegrationCredential.provider == provider,
                )
            )
        ).all()
        return rows[0] if rows else None


# ---------------- 鉴权与注册表 ----------------


async def test_endpoints_require_login(client: httpx.AsyncClient):
    for method, path in (
        ("get", "/providers"),
        ("get", "/crypto/public-key"),
        ("put", "/pingcode/credentials"),
        ("delete", "/pingcode/credentials"),
        ("post", "/pingcode/test"),
    ):
        response = await getattr(client, method)(f"{BASE}{path}")
        assert response.status_code == 401, (method, path, response.text)


async def test_providers_lists_pingcode_and_plm(client: httpx.AsyncClient, admin_user: dict):
    response = await client.get(f"{BASE}/providers", headers=_auth(admin_user))
    assert response.status_code == 200, response.text
    items = {item["code"]: item for item in response.json()["items"]}
    assert items["pingcode"]["enabled"] is True
    assert items["pingcode"]["bound"] is False
    assert items["plm"]["enabled"] is False


async def test_unknown_provider_returns_404(client: httpx.AsyncClient, admin_user: dict):
    response = await client.delete(f"{BASE}/jira/credentials", headers=_auth(admin_user))
    assert response.status_code == 404


async def test_plm_write_returns_409(client: httpx.AsyncClient, admin_user: dict):
    encrypted = await _encrypt_payload(
        client, admin_user, {"username": USERNAME, "password": PASSWORD}
    )
    response = await client.put(
        f"{BASE}/plm/credentials",
        json={"payload_encrypted": encrypted},
        headers=_auth(admin_user),
    )
    assert response.status_code == 409, response.text
    response = await client.post(f"{BASE}/plm/test", headers=_auth(admin_user))
    assert response.status_code == 409


# ---------------- 凭据写入 ----------------


async def test_put_credentials_logs_in_and_stores_encrypted(
    client: httpx.AsyncClient, admin_user: dict, monkeypatch
):
    calls: list[tuple[str, str]] = []
    monkeypatch.setattr(pingcode_client, "signin", _fake_signin(calls=calls))
    encrypted = await _encrypt_payload(
        client, admin_user, {"username": USERNAME, "password": PASSWORD}
    )

    response = await client.put(
        f"{BASE}/pingcode/credentials",
        json={"payload_encrypted": encrypted},
        headers=_auth(admin_user),
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["code"] == "pingcode"
    assert body["bound"] is True
    assert body["username"] == USERNAME
    assert body["status"] == "ok"
    assert PASSWORD not in response.text
    assert calls == [(USERNAME, PASSWORD)]

    async with AsyncSessionLocal() as session:
        record = await session.get(IntegrationCredential, body["id"])
    assert record is not None
    assert record.username == USERNAME
    assert record.secret_encrypted.startswith("v1:")
    assert PASSWORD not in record.secret_encrypted
    assert (
        crypto.decrypt_secret(
            record.secret_encrypted, user_id=admin_user["id"], provider="pingcode"
        )
        == PASSWORD
    )
    assert (
        crypto.decrypt_secret(
            record.token_encrypted, user_id=admin_user["id"], provider="pingcode"
        )
        == "jwt-access-token"
    )
    assert json.loads(
        crypto.decrypt_secret(
            record.cookies_encrypted, user_id=admin_user["id"], provider="pingcode"
        )
    ) == {"s-66209672995cb95d777b6aec": "cookie-value"}
    assert record.token_expires_at is not None
    assert record.last_login_at is not None
    assert record.login_failures == 0
    assert record.last_error is None


async def test_put_rejects_tampered_payload(client: httpx.AsyncClient, admin_user: dict, monkeypatch):
    monkeypatch.setattr(pingcode_client, "signin", _fake_signin())
    response = await client.put(
        f"{BASE}/pingcode/credentials",
        json={"payload_encrypted": "not-base64!!"},
        headers=_auth(admin_user),
    )
    assert response.status_code == 400
    assert await _credential(admin_user["id"]) is None


async def test_put_rejects_missing_fields(client: httpx.AsyncClient, admin_user: dict, monkeypatch):
    monkeypatch.setattr(pingcode_client, "signin", _fake_signin())
    encrypted = await _encrypt_payload(client, admin_user, {"username": USERNAME})
    response = await client.put(
        f"{BASE}/pingcode/credentials",
        json={"payload_encrypted": encrypted},
        headers=_auth(admin_user),
    )
    assert response.status_code == 400
    assert await _credential(admin_user["id"]) is None


async def test_put_rejects_invalid_field_values(
    client: httpx.AsyncClient, admin_user: dict, monkeypatch
):
    monkeypatch.setattr(pingcode_client, "signin", _fake_signin())
    await _clear_rate_limit(admin_user["id"])
    for payload in (
        {"username": "   ", "password": PASSWORD},
        {"username": USERNAME, "password": ""},
    ):
        encrypted = await _encrypt_payload(client, admin_user, payload)
        response = await client.put(
            f"{BASE}/pingcode/credentials",
            json={"payload_encrypted": encrypted},
            headers=_auth(admin_user),
        )
        assert response.status_code == 400, (payload, response.text)
    assert await _credential(admin_user["id"]) is None


async def test_put_does_not_store_on_login_failure(
    client: httpx.AsyncClient, admin_user: dict, monkeypatch
):
    monkeypatch.setattr(
        pingcode_client,
        "signin",
        _fake_signin(error=pingcode_client.PingCodeAuthError("账号或密码错误")),
    )
    encrypted = await _encrypt_payload(
        client, admin_user, {"username": USERNAME, "password": PASSWORD}
    )
    response = await client.put(
        f"{BASE}/pingcode/credentials",
        json={"payload_encrypted": encrypted},
        headers=_auth(admin_user),
    )
    assert response.status_code == 400
    assert "账号或密码错误" in response.text
    assert await _credential(admin_user["id"]) is None


async def test_put_upstream_unavailable_returns_502(
    client: httpx.AsyncClient, admin_user: dict, monkeypatch
):
    monkeypatch.setattr(
        pingcode_client,
        "signin",
        _fake_signin(error=pingcode_client.PingCodeUnavailable("connect timeout")),
    )
    encrypted = await _encrypt_payload(
        client, admin_user, {"username": USERNAME, "password": PASSWORD}
    )
    response = await client.put(
        f"{BASE}/pingcode/credentials",
        json={"payload_encrypted": encrypted},
        headers=_auth(admin_user),
    )
    assert response.status_code == 502


async def test_put_twice_updates_single_row(
    client: httpx.AsyncClient, admin_user: dict, monkeypatch
):
    monkeypatch.setattr(pingcode_client, "signin", _fake_signin())
    for password in ("first-pass", "second-pass"):
        encrypted = await _encrypt_payload(
            client, admin_user, {"username": USERNAME, "password": password}
        )
        response = await client.put(
            f"{BASE}/pingcode/credentials",
            json={"payload_encrypted": encrypted},
            headers=_auth(admin_user),
        )
        assert response.status_code == 200, response.text

    record = await _credential(admin_user["id"])
    assert record is not None
    assert (
        crypto.decrypt_secret(
            record.secret_encrypted, user_id=admin_user["id"], provider="pingcode"
        )
        == "second-pass"
    )


# ---------------- 测试连接与删除 ----------------


async def test_test_endpoint_forces_login(client: httpx.AsyncClient, admin_user: dict, monkeypatch):
    monkeypatch.setattr(pingcode_client, "signin", _fake_signin())
    encrypted = await _encrypt_payload(
        client, admin_user, {"username": USERNAME, "password": PASSWORD}
    )
    await client.put(
        f"{BASE}/pingcode/credentials",
        json={"payload_encrypted": encrypted},
        headers=_auth(admin_user),
    )

    calls: list[tuple[str, str]] = []
    monkeypatch.setattr(pingcode_client, "signin", _fake_signin(calls=calls))
    response = await client.post(f"{BASE}/pingcode/test", headers=_auth(admin_user))
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["display_name"] == "测试同学"
    assert body["team_name"] == "天府团队"
    assert body["login_at"]
    assert calls == [(USERNAME, PASSWORD)]
    assert "jwt-access-token" not in response.text


async def test_test_endpoint_without_credentials_returns_409(
    client: httpx.AsyncClient, admin_user: dict
):
    response = await client.post(f"{BASE}/pingcode/test", headers=_auth(admin_user))
    assert response.status_code == 409


async def test_test_endpoint_with_unreadable_secret_returns_409(
    client: httpx.AsyncClient, admin_user: dict, monkeypatch
):
    monkeypatch.setattr(pingcode_client, "signin", _fake_signin())
    encrypted = await _encrypt_payload(
        client, admin_user, {"username": USERNAME, "password": PASSWORD}
    )
    await client.put(
        f"{BASE}/pingcode/credentials",
        json={"payload_encrypted": encrypted},
        headers=_auth(admin_user),
    )
    async with AsyncSessionLocal() as session:
        record = (
            await session.execute(
                IntegrationCredential.__table__.select().where(
                    IntegrationCredential.user_id == admin_user["id"]
                )
            )
        ).one()
        await session.execute(
            IntegrationCredential.__table__.update()
            .where(IntegrationCredential.id == record.id)
            .values(secret_encrypted="v1:broken")
        )
        await session.commit()

    response = await client.post(f"{BASE}/pingcode/test", headers=_auth(admin_user))
    assert response.status_code == 409
    assert "重新配置" in response.text


async def test_delete_removes_credentials(client: httpx.AsyncClient, admin_user: dict, monkeypatch):
    monkeypatch.setattr(pingcode_client, "signin", _fake_signin())
    encrypted = await _encrypt_payload(
        client, admin_user, {"username": USERNAME, "password": PASSWORD}
    )
    await client.put(
        f"{BASE}/pingcode/credentials",
        json={"payload_encrypted": encrypted},
        headers=_auth(admin_user),
    )

    response = await client.delete(f"{BASE}/pingcode/credentials", headers=_auth(admin_user))
    assert response.status_code == 200
    assert await _credential(admin_user["id"]) is None

    providers = await client.get(f"{BASE}/providers", headers=_auth(admin_user))
    item = {item["code"]: item for item in providers.json()["items"]}["pingcode"]
    assert item["bound"] is False


async def test_credentials_are_isolated_per_user(
    client: httpx.AsyncClient, admin_user: dict, publisher_user: dict, monkeypatch
):
    monkeypatch.setattr(pingcode_client, "signin", _fake_signin())
    encrypted = await _encrypt_payload(
        client, admin_user, {"username": USERNAME, "password": PASSWORD}
    )
    await client.put(
        f"{BASE}/pingcode/credentials",
        json={"payload_encrypted": encrypted},
        headers=_auth(admin_user),
    )

    response = await client.get(f"{BASE}/providers", headers=_auth(publisher_user))
    item = {item["code"]: item for item in response.json()["items"]}["pingcode"]
    assert item["bound"] is False


# ---------------- 限流 ----------------


async def test_put_and_test_share_rate_limit(
    client: httpx.AsyncClient, admin_user: dict, monkeypatch
):
    await _clear_rate_limit(admin_user["id"])

    monkeypatch.setattr(pingcode_client, "signin", _fake_signin())
    statuses = []
    for _ in range(4):
        encrypted = await _encrypt_payload(
            client, admin_user, {"username": USERNAME, "password": PASSWORD}
        )
        response = await client.put(
            f"{BASE}/pingcode/credentials",
            json={"payload_encrypted": encrypted},
            headers=_auth(admin_user),
        )
        statuses.append(response.status_code)
    assert statuses[:3] == [200, 200, 200]
    assert statuses[3] == 429

    await _clear_rate_limit(admin_user["id"])
