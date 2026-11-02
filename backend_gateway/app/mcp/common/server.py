"""Authenticated FastMCP construction and the two-transport dispatcher."""
from __future__ import annotations

from contextlib import AsyncExitStack, asynccontextmanager
from typing import Any, AsyncIterator, Mapping
from urllib.parse import urlsplit

import redis.asyncio as aioredis
from mcp.server.auth.settings import AuthSettings
from mcp.server.fastmcp import FastMCP
from mcp.server.transport_security import TransportSecuritySettings
from starlette.applications import Starlette
from starlette.responses import JSONResponse
from starlette.routing import Mount, Route, get_route_path

from app.core.config import settings
from app.mcp.common.auth import McpTokenVerifier


def _configured_hosts(public_base_url: str, allowed_hosts: Any) -> list[str]:
    if isinstance(allowed_hosts, str):
        configured = [part.strip() for part in allowed_hosts.split(",")]
    else:
        configured = [str(part).strip() for part in (allowed_hosts or [])]
    public = urlsplit(public_base_url)
    if public.hostname:
        hostname = f"[{public.hostname}]" if ":" in public.hostname else public.hostname
        configured.extend((hostname, public.netloc))
    configured.extend(
        (
            "127.0.0.1",
            "127.0.0.1:*",
            "localhost",
            "localhost:*",
            "[::1]",
            "[::1]:*",
        )
    )
    return sorted({host for host in configured if host})


def _allowed_origins(public_base_url: str) -> list[str]:
    public = urlsplit(public_base_url)
    origins = {
        "http://127.0.0.1:*",
        "http://localhost:*",
        "http://[::1]:*",
        "https://127.0.0.1:*",
        "https://localhost:*",
        "https://[::1]:*",
    }
    if public.scheme and public.netloc:
        origins.add(f"{public.scheme}://{public.netloc}")
    return sorted(origins)


def build_mcp(
    domain: str,
    *,
    public_base_url: str,
    allowed_hosts: Any = (),
    redis_client: Any | None = None,
    server_name: str | None = None,
) -> FastMCP:
    """Build one domain using the installed SDK's real auth interfaces."""
    base = public_base_url.rstrip("/")
    mcp = FastMCP(
        server_name or f"testmate-{domain}",
        token_verifier=McpTokenVerifier(),
        auth=AuthSettings(
            issuer_url=base,
            resource_server_url=f"{base}/mcp/{domain}",
            required_scopes=[],
        ),
        stateless_http=True,
        json_response=True,
        streamable_http_path=f"/{domain}",
        transport_security=TransportSecuritySettings(
            enable_dns_rebinding_protection=True,
            allowed_hosts=_configured_hosts(base, allowed_hosts),
            allowed_origins=_allowed_origins(base),
        ),
    )
    mcp._testmate_redis = redis_client or aioredis.Redis(
        host=settings.REDIS_HOST,
        port=settings.REDIS_PORT,
        db=settings.REDIS_DB,
        decode_responses=True,
    )
    return mcp


class _LegacyPathAlias:
    """ASGI class (not a function) so Starlette keeps every HTTP method."""

    def __init__(self, app: Any, legacy: str, target: str) -> None:
        self._app = app
        self._legacy = legacy
        self._target = target

    async def __call__(self, scope, receive, send) -> None:
        if scope.get("type") == "http":
            scope = dict(scope)
            root_path = scope.get("root_path", "")
            relative = get_route_path(scope)
            if relative == self._legacy or relative.startswith(f"{self._legacy}/"):
                scope["path"] = root_path + self._target + relative[len(self._legacy):]
                scope["raw_path"] = scope["path"].encode()
        await self._app(scope, receive, send)


def _legacy_path_alias(app: Any, legacy: str, target: str) -> Any:
    """Serve an old MCP path from the renamed domain without a second server."""

    return _LegacyPathAlias(app, legacy, target)


class McpDispatcher:
    """A mountable dispatcher that is unavailable until lifespan configuration."""

    def __init__(self) -> None:
        self._app: Starlette | None = None
        self._domains: dict[str, FastMCP] = {}
        self.routes: list[Route | Mount] = []

    @property
    def domains(self) -> dict[str, FastMCP]:
        return self._domains

    def configure(self, domains: Mapping[str, FastMCP]) -> None:
        routes: list[Route | Mount] = []
        for domain, mcp in domains.items():
            path = f"/{domain}"
            streamable = mcp.streamable_http_app()
            sse = mcp.sse_app()
            routes.append(Route(path, endpoint=streamable))
            routes.append(Mount(path, app=sse))
            if domain == "extensions":
                routes.append(
                    Route("/skill", endpoint=_legacy_path_alias(streamable, "/skill", path))
                )
                routes.append(Mount("/skill", app=sse))
        self._domains = dict(domains)
        self.routes = routes
        self._app = Starlette(routes=routes)

    async def __call__(self, scope, receive, send) -> None:
        if self._app is None:
            if scope["type"] == "http":
                response = JSONResponse(
                    {"detail": "MCP is not configured"}, status_code=503
                )
                await response(scope, receive, send)
                return
            raise RuntimeError("MCP dispatcher is not configured")
        await self._app(scope, receive, send)


def build_dispatcher(domains: Mapping[str, FastMCP] | None = None) -> McpDispatcher:
    dispatcher = McpDispatcher()
    if domains is not None:
        dispatcher.configure(domains)
    return dispatcher


@asynccontextmanager
async def run_mcp_lifespan(
    domains: Mapping[str, FastMCP] | McpDispatcher,
) -> AsyncIterator[None]:
    """Enter every domain manager and let AsyncExitStack unwind all of them."""
    configured = domains.domains if isinstance(domains, McpDispatcher) else domains
    async with AsyncExitStack() as stack:
        for mcp in configured.values():
            await stack.enter_async_context(mcp.session_manager.run())
        yield
