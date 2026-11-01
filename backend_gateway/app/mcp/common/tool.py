"""Tool registration with scope checks, Redis quotas, and safe auditing."""
from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Any, Awaitable, Callable

import jsonschema
from mcp.server.auth.middleware.auth_context import get_access_token
from mcp.server.fastmcp import Context, FastMCP
from mcp.server.fastmcp.exceptions import ToolError
from mcp.server.fastmcp.utilities.func_metadata import ArgModelBase
from pydantic import ConfigDict

from app.core.settings_store import get
from app.db.session import AsyncSessionLocal
from app.mcp.common.audit import record_audit, summarize_arguments
from app.mcp.common.context import McpContext, Principal
from app.mcp.common.errors import McpRuntimeError, safe_error

USER_QUOTA_SETTING = "mcp.quota.user_per_minute"
CLIENT_QUOTA_SETTING = "mcp.quota.client_per_minute"
DEFAULT_USER_QUOTA = 1000
DEFAULT_CLIENT_QUOTA = 200


class _RawToolArguments(ArgModelBase):
    """Pass JSON arguments through without dropping omitted optional keys."""

    model_config = ConfigDict(extra="allow")

    def model_dump_one_level(self) -> dict[str, Any]:
        return dict(self.__pydantic_extra__ or {})


# Two minute buckets approximate a sliding sixty-second window. The Lua script
# checks both principals and increments both current buckets atomically.
_QUOTA_SCRIPT = """
local now = tonumber(ARGV[1])
local user_limit = tonumber(ARGV[2])
local client_limit = tonumber(ARGV[3])
local minute = math.floor(now / 60)
local weight = (60 - (now % 60)) / 60
local function usage(prefix)
    local current = tonumber(redis.call('GET', prefix .. tostring(minute)) or '0')
    local previous = tonumber(redis.call('GET', prefix .. tostring(minute - 1)) or '0')
    return current + previous * weight
end
if usage(KEYS[1]) >= user_limit then
    return {0, 'user'}
end
if usage(KEYS[2]) >= client_limit then
    return {0, 'client'}
end
for _, prefix in ipairs({KEYS[1], KEYS[2]}) do
    local key = prefix .. tostring(minute)
    redis.call('INCR', key)
    redis.call('EXPIRE', key, 120)
end
return {1, 'ok'}
"""


@dataclass(frozen=True, slots=True)
class ToolSpec:
    name: str
    description: str
    input_schema: dict[str, Any]
    scope: str
    read_only: bool
    handler: Callable[[McpContext], Awaitable[Any]]


async def _positive_limit(key: str, default: int) -> int:
    try:
        value = int(await get(key, default))
    except (TypeError, ValueError):
        return default
    return value if value > 0 else default


def _denied_principal(value: Any) -> str:
    if isinstance(value, bytes):
        value = value.decode("ascii", errors="replace")
    return str(value)


async def _consume_quota(redis_client: Any, principal: Principal) -> None:
    user_limit, client_limit = await _positive_limit(
        USER_QUOTA_SETTING, DEFAULT_USER_QUOTA
    ), await _positive_limit(CLIENT_QUOTA_SETTING, DEFAULT_CLIENT_QUOTA)
    user_key = f"mcp:quota:user:{principal.user.id}:"
    client_key = f"mcp:quota:client:{principal.user.id}:{principal.client_id}:"
    result = await redis_client.eval(
        _QUOTA_SCRIPT,
        2,
        user_key,
        client_key,
        str(int(time.time())),
        str(user_limit),
        str(client_limit),
    )
    allowed = bool(result and int(result[0]))
    if allowed:
        return
    denied = _denied_principal(result[1] if len(result) > 1 else "user")
    if denied == "client":
        raise McpRuntimeError(
            "client_quota_exceeded", "Client quota exceeded; retry later."
        )
    raise McpRuntimeError("user_quota_exceeded", "User quota exceeded; retry later.")


def _principal() -> Principal:
    token = get_access_token()
    claims = token.claims if token is not None else None
    principal = claims.get("principal") if isinstance(claims, dict) else None
    if not isinstance(principal, Principal):
        raise McpRuntimeError("authentication_required", "Authentication required.")
    return principal


def register_tool(
    mcp: FastMCP,
    domain: str,
    spec: ToolSpec,
    *,
    redis_client: Any | None = None,
) -> None:
    """Register one tool and replace inferred parameters with its real schema."""
    redis_client = redis_client or getattr(mcp, "_testmate_redis", None)
    if redis_client is None:
        raise RuntimeError("MCP Redis client is not configured")

    async def _tool(context: Context, **kwargs):
        started = time.monotonic()
        principal = _principal()
        args_summary = summarize_arguments(kwargs)
        async with AsyncSessionLocal() as session:
            try:
                try:
                    jsonschema.validate(instance=kwargs, schema=spec.input_schema)
                except jsonschema.ValidationError:
                    args_summary = {
                        key: (
                            value
                            if key in {"package_base64", "files"}
                            else {"invalid": True}
                        )
                        for key, value in args_summary.items()
                    }
                    raise McpRuntimeError(
                        "invalid_arguments", "Invalid tool arguments."
                    ) from None
                if spec.scope not in principal.scopes:
                    raise McpRuntimeError(
                        "insufficient_scope", "Insufficient scope for this tool."
                    )
                await _consume_quota(redis_client, principal)
                result = await spec.handler(
                    McpContext(principal=principal, session=session), **kwargs
                )
            except Exception as exc:
                error = safe_error(exc)
                await session.rollback()
                try:
                    await record_audit(
                        session,
                        principal=principal,
                        domain=domain,
                        tool=spec.name,
                        read_only=spec.read_only,
                        success=False,
                        error=error.code,
                        args_summary=args_summary,
                        duration=int((time.monotonic() - started) * 1000),
                    )
                except Exception:
                    await session.rollback()
                    raise ToolError("Tool execution failed.") from None
                raise ToolError(error.message) from None
            try:
                await record_audit(
                    session,
                    principal=principal,
                    domain=domain,
                    tool=spec.name,
                    read_only=spec.read_only,
                    success=True,
                    error=None,
                    args_summary=args_summary,
                    duration=int((time.monotonic() - started) * 1000),
                )
            except Exception:
                await session.rollback()
                raise ToolError("Tool execution failed.") from None
            return result

    mcp.add_tool(
        _tool,
        name=spec.name,
        description=spec.description,
        structured_output=False,
    )
    sdk_tool = mcp._tool_manager.get_tool(spec.name)
    if sdk_tool is None:
        raise RuntimeError("MCP SDK tool registration failed")
    sdk_tool.fn_metadata.arg_model = _RawToolArguments
    sdk_tool.parameters = spec.input_schema
