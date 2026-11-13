"""PingCode 会话续期、失败冷却与单飞 (mock transport, 不连内网)."""
from __future__ import annotations

import asyncio
import json
import uuid
from contextlib import asynccontextmanager
from datetime import datetime, timedelta

import httpx
import pytest
from sqlalchemy import select

from app.db.session import AsyncSessionLocal
from app.integrations import crypto
from app.integrations.pingcode import client, token_manager
from app.models.integration import IntegrationCredential
from app.models.user import User, UserRole

COOKIE = "s-66209672995cb95d777b6aec"
LOGIN_PATH = "/api/typhon/team/signin"
REFRESH_PATH = "/api/typhon/account/access-token"
PROLONG_PATH = "/api/typhon/passport/prolong-logged-state"
BUSINESS_PATH = "/api/agile/projects/select-options"
TEAM_ID = "66209672995cb95d777b6aec"


class FakeRedis:
    """只实现会话锁用到的 SET NX EX / GET / DELETE 语义."""

    def __init__(self) -> None:
        self.values: dict[str, str] = {}

    async def set(self, key: str, value: str, *, nx: bool = False, ex: int | None = None):
        if nx and key in self.values:
            return False
        self.values[key] = value
        return True

    async def get(self, key: str):
        return self.values.get(key)

    async def delete(self, key: str):
        self.values.pop(key, None)


@pytest.fixture
async def user():
    async with AsyncSessionLocal() as session:
        item = User(
            username=f"pc-token-{uuid.uuid4().hex[:8]}",
            password_hash="unused",
            role=UserRole.tester,
        )
        session.add(item)
        await session.commit()
        await session.refresh(item)
        return item


def _encrypt(value: str, user_id: int) -> str:
    return crypto.encrypt_secret(value, user_id=user_id, provider="pingcode")


async def _credential(
    user: User,
    *,
    token: str | None = "cached-token",
    expires_at: datetime | None = None,
    cookies: dict[str, str] | None = None,
    failures: int = 0,
    last_attempt_at: datetime | None = None,
    status: str = "ok",
) -> int:
    async with AsyncSessionLocal() as session:
        record = IntegrationCredential(
            user_id=user.id,
            provider="pingcode",
            username="demo-user",
            secret_encrypted=_encrypt("secret-pass", user.id),
            token_encrypted=_encrypt(token, user.id) if token else None,
            cookies_encrypted=_encrypt(
                json.dumps({COOKIE: "cookie-value"} if cookies is None else cookies),
                user.id,
            ),
            token_expires_at=expires_at or datetime.utcnow() - timedelta(minutes=1),
            status=status,
            login_failures=failures,
            last_attempt_at=last_attempt_at,
        )
        session.add(record)
        await session.commit()
        await session.refresh(record)
        return record.id


async def _record(user: User) -> IntegrationCredential:
    async with AsyncSessionLocal() as session:
        return (
            await session.execute(
                select(IntegrationCredential).where(
                    IntegrationCredential.user_id == user.id,
                    IntegrationCredential.provider == "pingcode",
                )
            )
        ).scalar_one()


def _manager(handler, redis: FakeRedis | None = None) -> token_manager.TokenManager:
    redis = redis or FakeRedis()

    @asynccontextmanager
    async def redis_factory():
        yield redis

    return token_manager.TokenManager(
        transport=httpx.MockTransport(handler),
        redis_factory=redis_factory,
        poll_interval=0.005,
        lock_timeout=5.0,
    )


def _ok(value=None, cookies: str | None = None) -> httpx.Response:
    headers = {"set-cookie": f"{COOKIE}=fresh-cookie; Path=/; HttpOnly"} if cookies else {}
    return httpx.Response(200, json={"code": 200, "data": {"value": value or {}}}, headers=headers)


def _router(calls: list[tuple[str, str]], *, refresh_ok: bool = True, signin_ok: bool = True):
    def handler(request: httpx.Request) -> httpx.Response:
        calls.append((request.method, request.url.path))
        if request.url.path == REFRESH_PATH:
            if not refresh_ok:
                return httpx.Response(401, json={"message": "expired"})
            return _ok({"access_token": "fresh-token"}, cookies="1")
        if request.url.path == LOGIN_PATH:
            if not signin_ok:
                return httpx.Response(200, json={"code": 401, "message": "账号或密码错误"})
            return _ok(
                {
                    "access_token": "login-token",
                    "team": {"_id": TEAM_ID, "name": "企业级产品中心"},
                    "user": {"name": "张三"},
                },
                cookies="1",
            )
        if request.url.path == PROLONG_PATH:
            return httpx.Response(200, json={"code": 200})
        if request.url.path == BUSINESS_PATH:
            return _ok([{"_id": "p1", "identifier": "TF2", "name": "TIANFU"}])
        raise AssertionError(f"unexpected {request.method} {request.url.path}")

    return handler


async def test_missing_credential_raises_not_configured(user):
    manager = _manager(_router([]))
    with pytest.raises(token_manager.IntegrationNotConfigured):
        await manager.ensure_session(user.id)


async def test_cached_session_skips_network(user):
    await _credential(user, expires_at=datetime.utcnow() + timedelta(minutes=30))

    def handler(request: httpx.Request) -> httpx.Response:
        raise AssertionError(f"cached session must not call {request.url.path}")

    session = await _manager(handler).ensure_session(user.id)

    assert session.access_token == "cached-token"
    assert session.cookies == {COOKIE: "cookie-value"}
    assert session.team_id == TEAM_ID


async def test_expired_session_refreshes_with_cookie(user):
    await _credential(user)
    calls: list[tuple[str, str]] = []

    session = await _manager(_router(calls)).ensure_session(user.id)

    assert (("GET", REFRESH_PATH) in calls)
    assert (("POST", LOGIN_PATH) not in calls)
    assert session.access_token == "fresh-token"
    record = await _record(user)
    assert record.status == "ok"
    assert record.login_failures == 0
    assert record.token_expires_at > datetime.utcnow() + timedelta(minutes=80)
    assert crypto.decrypt_secret(
        record.token_encrypted, user_id=user.id, provider="pingcode"
    ) == "fresh-token"
    assert json.loads(
        crypto.decrypt_secret(record.cookies_encrypted, user_id=user.id, provider="pingcode")
    ) == {COOKIE: "fresh-cookie"}


async def test_refresh_failure_falls_back_to_password_login(user):
    await _credential(user)
    calls: list[tuple[str, str]] = []

    session = await _manager(_router(calls, refresh_ok=False)).ensure_session(user.id)

    assert [path for _, path in calls].count(REFRESH_PATH) == 1
    assert [path for _, path in calls].count(LOGIN_PATH) == 1
    assert session.access_token == "login-token"
    assert session.display_name == "张三"
    assert session.team_name == "企业级产品中心"
    assert (await _record(user)).status == "ok"


async def test_login_failure_marks_reauth_required(user):
    await _credential(user)
    calls: list[tuple[str, str]] = []

    with pytest.raises(token_manager.IntegrationReauthRequired):
        await _manager(_router(calls, refresh_ok=False, signin_ok=False)).ensure_session(
            user.id
        )

    record = await _record(user)
    assert record.status == "reauth_required"
    assert record.login_failures == 1
    assert record.last_error
    assert "secret-pass" not in record.last_error


async def test_transient_login_failure_keeps_status_but_records_error(user):
    await _credential(user)

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(503, json={"message": "upstream down"})

    with pytest.raises(client.PingCodeUnavailable):
        await _manager(handler).ensure_session(user.id)

    record = await _record(user)
    assert record.status == "ok"
    assert record.login_failures == 1
    assert record.last_error
    assert record.last_attempt_at is not None


async def test_three_failures_enforce_five_minute_cooldown(user):
    await _credential(user, failures=3, last_attempt_at=datetime.utcnow())

    def handler(request: httpx.Request) -> httpx.Response:
        raise AssertionError("cooldown must not hit the network")

    with pytest.raises(token_manager.IntegrationReauthRequired):
        await _manager(handler).ensure_session(user.id)


async def test_cooldown_expires_and_allows_login(user):
    await _credential(user, failures=3, last_attempt_at=datetime.utcnow() - timedelta(minutes=6))
    calls: list[tuple[str, str]] = []

    session = await _manager(_router(calls, refresh_ok=False)).ensure_session(user.id)

    assert session.access_token == "login-token"
    assert (await _record(user)).login_failures == 0


async def test_concurrent_requests_share_one_login(user):
    await _credential(user, cookies={})
    calls: list[tuple[str, str]] = []
    manager = _manager(_router(calls, refresh_ok=False))

    sessions = await asyncio.gather(
        *(manager.ensure_session(user.id) for _ in range(10))
    )

    assert {session.access_token for session in sessions} == {"login-token"}
    assert [path for _, path in calls].count(LOGIN_PATH) == 1


async def test_force_refresh_ignores_valid_cache(user):
    await _credential(user, expires_at=datetime.utcnow() + timedelta(minutes=30))
    calls: list[tuple[str, str]] = []

    session = await _manager(_router(calls)).ensure_session(user.id, force=True)

    assert session.access_token == "fresh-token"
    paths = [path for _, path in calls]
    assert paths[0] == REFRESH_PATH
    assert LOGIN_PATH not in paths


async def test_request_retries_once_after_session_expiry(user):
    await _credential(user, expires_at=datetime.utcnow() + timedelta(minutes=30))
    calls: list[tuple[str, str]] = []
    business_calls = {"count": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append((request.method, request.url.path))
        if request.url.path == BUSINESS_PATH:
            business_calls["count"] += 1
            if business_calls["count"] == 1:
                return httpx.Response(401, json={"message": "expired"})
            return _ok([{"_id": "p1"}])
        if request.url.path == REFRESH_PATH:
            return _ok({"access_token": "fresh-token"}, cookies="1")
        if request.url.path == PROLONG_PATH:
            return httpx.Response(200, json={"code": 200})
        raise AssertionError(request.url.path)

    data = await _manager(handler).request(user.id, "GET", BUSINESS_PATH)

    assert data == [{"_id": "p1"}]
    assert business_calls["count"] == 2
    assert [path for _, path in calls].count(REFRESH_PATH) == 1


async def test_request_marks_reauth_when_retry_still_expired(user):
    await _credential(user, expires_at=datetime.utcnow() + timedelta(minutes=30))

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == BUSINESS_PATH:
            return httpx.Response(200, json={"code": 401, "message": "expired"})
        if request.url.path == REFRESH_PATH:
            return _ok({"access_token": "fresh-token"}, cookies="1")
        if request.url.path == PROLONG_PATH:
            return httpx.Response(200, json={"code": 200})
        raise AssertionError(request.url.path)

    with pytest.raises(token_manager.IntegrationReauthRequired):
        await _manager(handler).request(user.id, "GET", BUSINESS_PATH)

    record = await _record(user)
    assert record.status == "reauth_required"


async def test_client_request_sends_auth_headers_and_parses_value():
    seen: dict = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["headers"] = dict(request.headers)
        seen["params"] = dict(request.url.params)
        return _ok({"items": [1]})

    session = client.PingCodeSession(
        access_token="jwt-1",
        team_id=TEAM_ID,
        display_name="张三",
        team_name="团队",
        cookies={COOKIE: "cookie-value"},
        access_token_expires_at=datetime.utcnow() + timedelta(minutes=90),
    )
    api = client.PingCodeClient(session, transport=httpx.MockTransport(handler))

    data = await api.request("GET", BUSINESS_PATH, params={"can_create_work_item": 1})

    assert data == {"items": [1]}
    assert seen["headers"]["authorization"] == "Bearer jwt-1"
    assert seen["headers"]["x-team-id"] == TEAM_ID
    assert COOKIE in seen["headers"].get("cookie", "")
    assert seen["params"] == {"can_create_work_item": "1"}


@pytest.mark.parametrize(
    "response",
    [
        httpx.Response(401, json={"message": "expired"}),
        httpx.Response(200, json={"code": 401, "message": "expired"}),
    ],
)
async def test_client_request_maps_expiry(response):
    session = client.PingCodeSession(
        "jwt", TEAM_ID, "", "", {}, datetime.utcnow() + timedelta(minutes=90)
    )
    api = client.PingCodeClient(
        session, transport=httpx.MockTransport(lambda request: response)
    )
    with pytest.raises(client.PingCodeSessionExpired):
        await api.request("GET", BUSINESS_PATH)


async def test_client_request_maps_business_error():
    session = client.PingCodeSession(
        "jwt", TEAM_ID, "", "", {}, datetime.utcnow() + timedelta(minutes=90)
    )
    api = client.PingCodeClient(
        session,
        transport=httpx.MockTransport(
            lambda request: httpx.Response(
                200, json={"code": 400, "message": "参数不合法"}
            )
        ),
    )
    with pytest.raises(client.PingCodeBusinessError) as excinfo:
        await api.request("GET", BUSINESS_PATH)
    assert "参数不合法" in str(excinfo.value)


async def test_client_request_maps_http_500_to_unavailable():
    session = client.PingCodeSession(
        "jwt", TEAM_ID, "", "", {}, datetime.utcnow() + timedelta(minutes=90)
    )
    api = client.PingCodeClient(
        session,
        transport=httpx.MockTransport(lambda request: httpx.Response(500, text="boom")),
    )
    with pytest.raises(client.PingCodeUnavailable):
        await api.request("GET", BUSINESS_PATH)
