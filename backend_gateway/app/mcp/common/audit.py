"""Sensitive-argument summaries and MCP tool-call audit persistence."""
from __future__ import annotations

import base64
import binascii
import hashlib
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.mcp.common.context import Principal
from app.models.mcp import McpToolCall


def _summary(value: Any) -> Any:
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    if isinstance(value, bytes):
        return {"bytes": len(value), "sha256": hashlib.sha256(value).hexdigest()}
    if isinstance(value, dict):
        return summarize_arguments(value)
    if isinstance(value, (list, tuple, set, frozenset)):
        return {"count": len(value)}
    return None


def summarize_arguments(arguments: dict[str, Any]) -> dict[str, Any]:
    """Retain metadata without persisting package bytes or file text."""
    out: dict[str, Any] = {}
    for key, value in arguments.items():
        if key == "package_base64":
            try:
                raw = base64.b64decode(value)
            except (binascii.Error, TypeError, ValueError):
                out[key] = {"invalid": True}
            else:
                out[key] = {
                    "bytes": len(raw),
                    "sha256": hashlib.sha256(raw).hexdigest(),
                }
        elif key == "files":
            if isinstance(value, dict):
                out[key] = {"paths": sorted(value), "count": len(value)}
            else:
                out[key] = {"invalid": True}
        else:
            out[key] = _summary(value)
    return out


async def record_audit(
    session: AsyncSession,
    *,
    principal: Principal,
    domain: str,
    tool: str,
    read_only: bool,
    success: bool,
    error: str | None,
    args_summary: dict[str, Any],
    duration: int,
) -> None:
    session.add(
        McpToolCall(
            user_id=principal.user.id,
            client_id=principal.client_id,
            domain=domain,
            tool=tool,
            read_only=read_only,
            success=success,
            error=error,
            args_summary=args_summary,
            duration=duration,
        )
    )
    await session.commit()
