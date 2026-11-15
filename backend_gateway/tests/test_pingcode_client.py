"""PingCode 登录客户端: 登录契约解析与登录态下的真实用户名解析."""
from __future__ import annotations

import asyncio
import hashlib
import json
from datetime import datetime, timedelta

import httpx
import pytest

from app.integrations.pingcode import client

COOKIE = "s-66209672995cb95d777b6aec"


def _session(**overrides) -> client.PingCodeSession:
    values = {
        "access_token": "tok",
        "team_id": "team-1",
        "display_name": "642355511",
        "team_name": "企业级产品中心",
        "cookies": {"s-team-1": "cookie"},
        "access_token_expires_at": datetime.utcnow() + timedelta(minutes=30),
    }
    values.update(overrides)
    return client.PingCodeSession(**values)


async def test_fetch_display_name_prefers_chinese_name():
    seen: dict[str, str] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["path"] = request.url.path
        seen["auth"] = request.headers.get("authorization", "")
        seen["cookie"] = request.headers.get("cookie", "")
        return httpx.Response(
            200,
            json={"data": {"me": {"name": "642355511", "display_name": "贾克江"}}},
        )

    name = await client.fetch_display_name(
        _session(), base_url="http://pingcode.test", transport=httpx.MockTransport(handler)
    )

    assert name == "贾克江"
    assert seen["path"] == "/api/typhon/account/me"
    assert seen["auth"] == "Bearer tok"
    assert seen["cookie"] == "s-team-1=cookie"


async def test_fetch_display_name_returns_empty_when_identity_unavailable():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(500, json={"message": "boom"})

    name = await client.fetch_display_name(
        _session(), base_url="http://pingcode.test", transport=httpx.MockTransport(handler)
    )

    assert name == ""


async def test_signin_sends_md5_and_parses_session():
    seen: dict = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["path"] = request.url.path
        seen["body"] = json.loads(request.content)
        return httpx.Response(
            200,
            json={
                "code": 200,
                "data": {
                    "value": {
                        "access_token": "jwt-token",
                        "team": {"_id": "66209672995cb95d777b6aec", "name": "企业级产品中心"},
                        "user": {"name": "张三"},
                    }
                },
            },
            headers={"set-cookie": f"{COOKIE}=cookie-value; Path=/; HttpOnly"},
        )

    session = await client.signin(
        "demo-user", "p@ss-123", transport=httpx.MockTransport(handler)
    )

    assert seen["path"] == "/api/typhon/team/signin"
    assert seen["body"] == {
        "signin_name": "demo-user",
        "password": hashlib.md5(b"p@ss-123").hexdigest(),
        "captcha_code": "",
        "captcha_id": "",
    }
    assert session.access_token == "jwt-token"
    assert session.team_id == "66209672995cb95d777b6aec"
    assert session.team_name == "企业级产品中心"
    assert session.display_name == "张三"
    assert session.cookies == {COOKIE: "cookie-value"}
    assert session.access_token_expires_at > datetime.utcnow() + timedelta(minutes=80)


async def test_signin_falls_back_to_configured_team_and_username():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"code": 200, "data": {"value": {"access_token": "t"}}})

    session = await client.signin("u1", "p", transport=httpx.MockTransport(handler))
    assert session.team_id
    assert session.display_name == "u1"


@pytest.mark.parametrize("status_code", [400, 401, 403])
async def test_signin_maps_http_auth_errors(status_code: int):
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(status_code, json={"message": "bad"})

    with pytest.raises(client.PingCodeAuthError):
        await client.signin("u", "p", transport=httpx.MockTransport(handler))


async def test_signin_maps_business_code_401():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"code": 401, "message": "密码错误"})

    with pytest.raises(client.PingCodeAuthError):
        await client.signin("u", "p", transport=httpx.MockTransport(handler))


async def test_signin_maps_other_business_error_to_unavailable():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"code": 500, "message": "boom"})

    with pytest.raises(client.PingCodeUnavailable):
        await client.signin("u", "p", transport=httpx.MockTransport(handler))


async def test_signin_maps_network_error_to_unavailable():
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectTimeout("timeout", request=request)

    with pytest.raises(client.PingCodeUnavailable):
        await client.signin("u", "p", transport=httpx.MockTransport(handler))


async def test_signin_requires_access_token():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"code": 200, "data": {"value": {}}})

    with pytest.raises(client.PingCodeUnavailable):
        await client.signin("u", "p", transport=httpx.MockTransport(handler))


async def test_signin_bypasses_environment_proxy(monkeypatch):
    """内网 PingCode 必须绕过系统/环境代理 —— macOS 系统代理会把 10.x 也劫持."""

    async def handler(reader, writer):
        await reader.readuntil(b"\r\n\r\n")
        body = json.dumps(
            {
                "code": 200,
                "data": {
                    "value": {
                        "access_token": "t",
                        "team": {"_id": "t1", "name": "T"},
                        "user": {"name": "N"},
                    }
                },
            }
        ).encode()
        writer.write(
            b"HTTP/1.1 200 OK\r\nContent-Type: application/json\r\nContent-Length: "
            + str(len(body)).encode()
            + b"\r\nConnection: close\r\n\r\n"
            + body
        )
        await writer.drain()
        writer.close()

    server = await asyncio.start_server(handler, "127.0.0.1", 0)
    port = server.sockets[0].getsockname()[1]
    for name in ("HTTP_PROXY", "http_proxy", "HTTPS_PROXY", "https_proxy", "ALL_PROXY", "all_proxy"):
        monkeypatch.setenv(name, "http://127.0.0.1:1")
    monkeypatch.setenv("NO_PROXY", "")
    monkeypatch.setenv("no_proxy", "")
    try:
        session = await client.signin(
            "u1", "p", base_url=f"http://127.0.0.1:{port}", timeout=5
        )
    finally:
        server.close()
        await server.wait_closed()

    assert session.access_token == "t"


# ---------- 可达性探针 (侧栏服务状态用) ----------

async def test_probe_reports_ok_on_any_http_response():
    """只要 TCP/TLS 能握手并拿到 HTTP 响应, 就算可达 —— 401 也是可达."""

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(401, json={"message": "auth required"})

    status, message = await client.probe(
        base_url="http://pingcode.test", transport=httpx.MockTransport(handler)
    )

    assert status == "ok"
    assert message == "正常"


async def test_probe_reports_warn_when_server_errors():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(503, text="maintenance")

    status, message = await client.probe(
        base_url="http://pingcode.test", transport=httpx.MockTransport(handler)
    )

    assert status == "warn"
    assert "503" in message


async def test_probe_reports_unavailable_on_network_error():
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("refused", request=request)

    status, message = await client.probe(
        base_url="http://pingcode.test", transport=httpx.MockTransport(handler)
    )

    assert status == "off"
    assert "不可达" in message
