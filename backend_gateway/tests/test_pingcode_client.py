"""PingCode 登录客户端的契约解析 (mock transport, 不连内网)."""
from __future__ import annotations

import asyncio
import hashlib
import json
from datetime import datetime, timedelta

import httpx
import pytest

from app.integrations.pingcode import client

COOKIE = "s-66209672995cb95d777b6aec"


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
