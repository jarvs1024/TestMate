"""Real MCP transport smoke tests for authentication, SSE, and host validation."""
from __future__ import annotations

import json
import re
from contextlib import asynccontextmanager
from typing import Any

import anyio
import pytest
from httpx import ASGITransport, AsyncClient, Request, Response
from mcp.server.auth.provider import AccessToken, TokenVerifier
from mcp.types import LATEST_PROTOCOL_VERSION
from starlette.applications import Starlette
from starlette.routing import Mount

from app.mcp.common.server import build_dispatcher, build_mcp, run_mcp_lifespan
from tests._mcp_protocol import _result, initialize

TOKEN = "transport-test-token"


class _TransportTokenVerifier(TokenVerifier):
    async def verify_token(self, token: str) -> AccessToken | None:
        if token != TOKEN:
            return None
        return AccessToken(
            token=token,
            client_id="transport-test-client",
            scopes=["extensions:read"],
            subject="1",
        )


def _initialize_payload() -> dict[str, Any]:
    return {
        "jsonrpc": "2.0",
        "id": 1,
        "method": "initialize",
        "params": {
            "protocolVersion": LATEST_PROTOCOL_VERSION,
            "capabilities": {},
            "clientInfo": {"name": "transport-smoke", "version": "1.0"},
        },
    }


@asynccontextmanager
async def _mcp_app():
    server = build_mcp(
        "extensions",
        public_base_url="http://test",
        allowed_hosts=["test"],
        server_name="testmate-extensions",
    )
    server._token_verifier = _TransportTokenVerifier()
    dispatcher = build_dispatcher({"extensions": server})
    app = Starlette(routes=[Mount("/mcp", app=dispatcher)])
    async with run_mcp_lifespan(dispatcher):
        yield app


@asynccontextmanager
async def _mcp_client():
    async with _mcp_app() as app:
        async with AsyncClient(
            transport=ASGITransport(app=app),
            base_url="http://test",
        ) as client:
            yield client


def _json_rpc_response(content_type: str, content: str) -> Response:
    return Response(
        200,
        headers={"Content-Type": content_type},
        content=content,
        request=Request("POST", "http://test/mcp/extensions"),
    )


def test_result_decodes_sse_json_rpc_success():
    response = _json_rpc_response(
        "text/event-stream; charset=utf-8",
        'event: message\r\ndata: {"jsonrpc":"2.0","id":7,'
        '"result":{"tools":[]}}\r\n\r\n',
    )

    assert _result(response, 7) == {"tools": []}


@pytest.mark.parametrize("content_type", ["application/json", "text/event-stream"])
def test_result_bounds_and_sanitizes_json_rpc_errors(content_type):
    token = "secret-token-value"
    sql = "SELECT * FROM credentials"
    payload = {
        "jsonrpc": "2.0",
        "id": 7,
        "error": {
            "code": -32001,
            "message": "Tool failed " + "x" * 500,
            "data": {"arguments": {"token": token}, "sql": sql},
        },
    }
    content = json.dumps(payload)
    if content_type == "text/event-stream":
        content = f"event: message\r\ndata: {content}\r\n\r\n"
    response = _json_rpc_response(content_type, content)

    with pytest.raises(AssertionError) as exc_info:
        _result(response, 7)

    detail = str(exc_info.value)
    assert "-32001" in detail
    assert "Tool failed" in detail
    assert len(detail) <= 240
    assert token not in detail
    assert sql not in detail
    assert "arguments" not in detail


async def test_unauthenticated_streamable_post_returns_401():
    async with _mcp_client() as client:
        response = await client.post(
            "/mcp/extensions",
            json=_initialize_payload(),
            headers={"Accept": "application/json, text/event-stream"},
        )

    assert response.status_code == 401


async def test_authenticated_streamable_post_initializes_mcp():
    async with _mcp_client() as client:
        result = await initialize(client, TOKEN)

    assert result["protocolVersion"] == LATEST_PROTOCOL_VERSION
    assert result["serverInfo"]["name"] == "testmate-extensions"


async def test_sse_first_endpoint_event_preserves_mounted_root_path():
    async with _mcp_app() as app:
        response_started = anyio.Event()
        first_event_received = anyio.Event()
        messages: list[dict[str, Any]] = []
        body = bytearray()

        scope = {
            "type": "http",
            "asgi": {"version": "3.0", "spec_version": "2.3"},
            "http_version": "1.1",
            "method": "GET",
            "scheme": "http",
            "path": "/mcp/extensions/sse",
            "raw_path": b"/mcp/extensions/sse",
            "query_string": b"",
            "root_path": "",
            "headers": [
                (b"host", b"test"),
                (b"authorization", f"Bearer {TOKEN}".encode()),
                (b"accept", b"text/event-stream"),
            ],
            "client": ("testclient", 123),
            "server": ("test", 80),
        }

        async def receive():
            await anyio.sleep_forever()

        async def send(message):
            messages.append(message)
            if message["type"] == "http.response.start":
                response_started.set()
            elif message["type"] == "http.response.body":
                body.extend(message.get("body", b""))
                if re.search(rb"\r?\n\r?\n", body):
                    first_event_received.set()

        async with anyio.create_task_group() as task_group:
            task_group.start_soon(app, scope, receive, send)
            try:
                with anyio.fail_after(5):
                    await response_started.wait()
                with anyio.fail_after(5):
                    await first_event_received.wait()
            finally:
                task_group.cancel_scope.cancel()

        start = next(
            message for message in messages if message["type"] == "http.response.start"
        )
        assert start["status"] == 200
        frame_end = re.search(rb"\r?\n\r?\n", body)
        assert frame_end is not None
        first_frame = body[: frame_end.start()].decode()
        match = re.fullmatch(
            r"event: endpoint\r?\ndata: "
            r"/mcp/extensions/messages/\?session_id=[0-9a-f]{32}",
            first_frame,
        )
        assert match is not None


async def test_invalid_host_is_rejected_with_421():
    async with _mcp_client() as client:
        response = await client.post(
            "/mcp/extensions",
            json=_initialize_payload(),
            headers={
                "Authorization": f"Bearer {TOKEN}",
                "Accept": "application/json, text/event-stream",
                "Host": "invalid.example",
            },
        )

    assert response.status_code == 421
