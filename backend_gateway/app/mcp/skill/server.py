"""FastMCP server for the skill domain, mountable through build_dispatcher."""
from __future__ import annotations

from typing import Any

from mcp.server.fastmcp import FastMCP

from app.mcp.common.server import build_mcp
from app.mcp.common.tool import register_tool
from app.mcp.skill.tools import TOOL_SPECS


def build_skill_server(
    *,
    public_base_url: str,
    allowed_hosts: Any = (),
    redis_client: Any | None = None,
) -> FastMCP:
    server = build_mcp(
        "extensions",
        public_base_url=public_base_url,
        allowed_hosts=allowed_hosts,
        redis_client=redis_client,
        server_name="testmate-extensions",
    )
    for spec in TOOL_SPECS:
        register_tool(server, "extensions", spec, redis_client=redis_client)
    return server
