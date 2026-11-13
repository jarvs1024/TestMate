"""FastMCP server for the PLM domain."""
from __future__ import annotations

from typing import Any

from mcp.server.fastmcp import FastMCP

from app.mcp.common.server import build_mcp
from app.mcp.common.tool import register_tool
from app.mcp.plm.tools import TOOL_SPECS


def build_plm_server(
    *,
    public_base_url: str,
    allowed_hosts: Any = (),
    redis_client: Any | None = None,
) -> FastMCP:
    server = build_mcp(
        "plm",
        public_base_url=public_base_url,
        allowed_hosts=allowed_hosts,
        redis_client=redis_client,
        server_name="testmate-plm",
    )
    for spec in TOOL_SPECS:
        register_tool(server, "plm", spec, redis_client=redis_client)
    return server
