"""Minimal JSON-RPC helpers that exercise MCP over Streamable HTTP."""
from __future__ import annotations

import json
from typing import Any

from httpx import AsyncClient
from mcp.types import LATEST_PROTOCOL_VERSION

_ENDPOINT = "/mcp/extensions"


def _headers(token: str) -> dict[str, str]:
    return {
        "Authorization": f"Bearer {token}",
        "Accept": "application/json, text/event-stream",
        "Content-Type": "application/json",
    }


def _result(response, request_id: int) -> dict[str, Any]:
    response.raise_for_status()
    content_type = response.headers.get("content-type", "").split(";", 1)[0].strip().lower()
    if content_type == "application/json":
        payload = response.json()
    elif content_type == "text/event-stream":
        data_lines = []
        for line in response.text.splitlines():
            if line.startswith("data:"):
                data_lines.append(line[5:].removeprefix(" "))
            elif not line and data_lines:
                break
        if not data_lines:
            raise AssertionError("SSE JSON-RPC response had no data payload")
        payload = json.loads("\n".join(data_lines))
    else:
        raise AssertionError(f"Unsupported JSON-RPC Content-Type: {content_type or '<missing>'}")

    assert payload["jsonrpc"] == "2.0"
    assert payload["id"] == request_id
    if "error" in payload:
        error = payload["error"] if isinstance(payload["error"], dict) else {}
        code = error.get("code", "unknown")
        if isinstance(code, bool) or not isinstance(code, (int, str)):
            code = "unknown"
        code_text = " ".join(str(code).split())[:32]
        message = error.get("message", "Request failed")
        if not isinstance(message, str):
            message = "Request failed"
        message_text = " ".join(message.split())[:160]
        raise AssertionError(f"JSON-RPC error {code_text}: {message_text}")
    return payload["result"]


async def _initialize(
    client: AsyncClient, token: str, endpoint: str = _ENDPOINT
) -> tuple[dict[str, Any], dict[str, str]]:
    headers = _headers(token)
    response = await client.post(
        endpoint,
        json={
            "jsonrpc": "2.0",
            "id": 1,
            "method": "initialize",
            "params": {
                "protocolVersion": LATEST_PROTOCOL_VERSION,
                "capabilities": {},
                "clientInfo": {"name": "testmate-protocol-tests", "version": "1.0"},
            },
        },
        headers=headers,
    )
    result = _result(response, 1)

    session_id = response.headers.get("mcp-session-id")
    if session_id:
        headers["mcp-session-id"] = session_id
    headers["mcp-protocol-version"] = result["protocolVersion"]

    initialized = await client.post(
        endpoint,
        json={"jsonrpc": "2.0", "method": "notifications/initialized"},
        headers=headers,
    )
    initialized.raise_for_status()
    assert initialized.status_code == 202
    return result, headers


async def initialize(
    client: AsyncClient, token: str, endpoint: str = _ENDPOINT
) -> dict[str, Any]:
    """Perform a complete MCP initialize/initialized handshake."""
    result, _ = await _initialize(client, token, endpoint)
    return result


async def _rpc(
    client: AsyncClient,
    token: str,
    method: str,
    params: dict[str, Any] | None = None,
    endpoint: str = _ENDPOINT,
) -> dict[str, Any]:
    _, headers = await _initialize(client, token, endpoint)
    request: dict[str, Any] = {"jsonrpc": "2.0", "id": 2, "method": method}
    if params is not None:
        request["params"] = params
    response = await client.post(endpoint, json=request, headers=headers)
    return _result(response, 2)


async def list_tools(
    client: AsyncClient, token: str, endpoint: str = _ENDPOINT
) -> dict[str, Any]:
    """Return the real tools/list result over MCP Streamable HTTP."""
    return await _rpc(client, token, "tools/list", {}, endpoint)


async def call_tool(
    client: AsyncClient,
    token: str,
    name: str,
    args: dict[str, Any],
    endpoint: str = _ENDPOINT,
) -> dict[str, Any]:
    """Return the real tools/call result over MCP Streamable HTTP."""
    return await _rpc(
        client,
        token,
        "tools/call",
        {"name": name, "arguments": args},
        endpoint,
    )


async def call_tool_data(
    client: AsyncClient,
    token: str,
    name: str,
    args: dict[str, Any],
    endpoint: str = _ENDPOINT,
) -> dict[str, Any]:
    """Remove only the MCP content envelope and return a tool's JSON object."""
    result = await call_tool(client, token, name, args, endpoint)
    assert result.get("isError") is not True, result
    assert len(result["content"]) == 1
    assert result["content"][0]["type"] == "text"
    data = json.loads(result["content"][0]["text"])
    assert isinstance(data, dict), data
    return data
