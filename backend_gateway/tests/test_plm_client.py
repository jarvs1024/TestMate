"""PLM 服务端登录客户端: CAS 流程、RSA 加密与业务解码."""
from __future__ import annotations

import math
from datetime import datetime, timedelta

import httpx
import pytest

from app.integrations.plm import client


CAS_HTML = """
<html><script>
var modulus = "00c1a2b3c4d5e6f708192a3b4c5d6e7f8091a2b3c4d5e6f708192a3b4c5d6e7f"
  + "8091a2b3c4d5e6f708192a3b4c5d6e7f8091a2b3c4d5e6f708192a3b4c5d6e7f";
var exponent = "10001";
var randomvalue = "rand-123";
</script><form><input name="password"></form></html>
"""

TIP_HTML = '<html><script>location.href="/cas/tip?pswCheckType=firstWarnPsw";</script></html>'
LOGIN_JS = '<html><script>location.href="/login?ticket=ST-1";</script></html>'


def _session(**overrides) -> client.PlmSession:
    values = {
        "access_token": "token",
        "username": "sso-user",
        "display_name": "sso-user",
        "cookies": {"orgId": "org-1", "tenantid": "impwzqgp", "XSRF-TOKEN": "csrf!x"},
        "access_token_expires_at": datetime.now() + timedelta(minutes=90),
    }
    values.update(overrides)
    return client.PlmSession(**values)


def _login_transport():
    seen: dict[str, object] = {"posts": 0, "gets": []}

    def handler(request: httpx.Request) -> httpx.Response:
        path = request.url.path
        seen["gets"].append(path)
        if path == "/cas/login":
            if "ticket" in request.url.params:
                return httpx.Response(200, text=LOGIN_JS)
            if request.method == "POST":
                seen["posts"] += 1
                return httpx.Response(200, text=TIP_HTML)
            return httpx.Response(200, text=CAS_HTML)
        if path == "/cas/tip":
            return httpx.Response(
                200,
                text='<html><script>location.href="/login";</script></html>',
            )
        if path == "/login" and "ticket" not in request.url.params:
            return httpx.Response(
                302, headers={"location": "/cas/login?ticket=ST-1"}
            )
        if path == "/login":
            return httpx.Response(
                200,
                text="<html>home</html>",
                headers=[
                    ("set-cookie", "orgId=org-1; Path=/"),
                    ("set-cookie", "tenantid=impwzqgp; Path=/"),
                    ("set-cookie", "yht_access_token=access; Path=/"),
                ],
            )
        return httpx.Response(404)

    return httpx.MockTransport(handler), seen


async def test_signin_follows_cas_and_collects_session():
    transport, seen = _login_transport()
    session = await client.signin(
        "sso-user", "secret", transport=transport, verify=False
    )

    assert seen["posts"] == 1
    assert session.org_id == "org-1"
    assert session.tenant_id == "impwzqgp"
    assert session.cookies["yht_access_token"] == "access"
    assert session.access_token == "access"
    assert session.access_token_expires_at > datetime.utcnow()


async def test_signin_reports_wrong_password():
    def handler(request: httpx.Request) -> httpx.Response:
        if request.method == "POST":
            return httpx.Response(
                200,
                text='<html><div id="msg">用户名或密码错误</div><input name="password"></html>',
            )
        return httpx.Response(200, text=CAS_HTML)

    with pytest.raises(client.PlmAuthError) as excinfo:
        await client.signin(
            "sso-user", "bad", transport=httpx.MockTransport(handler), verify=False
        )
    assert "密码" in str(excinfo.value)


async def test_signin_requires_cas_page_vars():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, text="<html>maintenance</html>")

    with pytest.raises(client.PlmUnavailable):
        await client.signin(
            "sso-user", "secret", transport=httpx.MockTransport(handler), verify=False
        )


async def test_js_rsa_encrypt_matches_js_chunking():
    modulus = "00c1" + "ab" * 63
    n = int(modulus, 16)
    chunk = 2 * (((n.bit_length() + 15) // 16) - 1)
    password = "p" * (chunk + 10)

    encrypted = client.js_rsa_encrypt(password, modulus, "10001")

    blocks = encrypted.split(" ")
    assert len(blocks) == math.ceil(len(password) / chunk)
    first = password.encode()[:chunk]
    assert blocks[0] == format(pow(int.from_bytes(first, "little"), 0x10001, n), "x")


def _client(handler) -> client.PlmClient:
    return client.PlmClient(
        _session(), transport=httpx.MockTransport(handler), verify=False
    )


async def test_client_unwraps_data_and_sends_csrf():
    seen: dict[str, str] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["csrf"] = request.headers.get("x-csrf-token", "")
        seen["domain"] = request.headers.get("domain-key", "")
        return httpx.Response(200, json={"code": "200", "data": {"ok": True}})

    result = await _client(handler).request(
        "POST", "/yonbip-mm-plmrd/bill/list", json={}
    )

    assert result == {"ok": True}
    assert seen["csrf"] == "csrf"
    assert seen["domain"] == "IMP-BASE"


async def test_client_maps_business_errors_and_session_expiry():
    def business(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"code": "999", "message": "必填字段缺失"})

    with pytest.raises(client.PlmBusinessError) as excinfo:
        await _client(business).request("POST", "/bill/save", json={})
    assert "必填字段缺失" in str(excinfo.value)

    def expired(request: httpx.Request) -> httpx.Response:
        return httpx.Response(401, json={"code": 401})

    with pytest.raises(client.PlmSessionExpired):
        await _client(expired).request("GET", "/bill/detail", params={"id": "1"})

    def login_page(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200, headers={"content-type": "text/html"}, text='<input name="password">'
        )

    with pytest.raises(client.PlmSessionExpired):
        await _client(login_page).request("GET", "/bill/detail", params={"id": "1"})


async def test_download_rejects_foreign_host():
    with pytest.raises(client.PlmBusinessError):
        await _client(lambda request: httpx.Response(200)).download(
            "https://evil.example.com/file"
        )
