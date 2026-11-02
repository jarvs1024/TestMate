"""Common MCP tool runtime: schema, authorization, quotas, audit, and mounting."""
from __future__ import annotations

import base64
import hashlib
import json
from contextlib import asynccontextmanager

import pytest
import redis.asyncio as aioredis
from httpx import ASGITransport, AsyncClient
from mcp import ClientSession
from mcp.client.streamable_http import streamablehttp_client
from mcp.server.auth.provider import AccessToken, TokenVerifier
from mcp.server.fastmcp import FastMCP
from sqlalchemy import select
from starlette.routing import Mount, Route

from app.core.config import settings
from app.db.session import AsyncSessionLocal
from app.mcp.common import tool as tool_runtime
from app.mcp.common.context import Principal
from app.mcp.common.errors import McpRuntimeError
from app.mcp.common.server import (
    build_dispatcher,
    build_mcp,
    run_mcp_lifespan,
)
from app.mcp.common.tool import ToolSpec, register_tool
from app.models.mcp import McpToolCall
from app.models.user import User, UserRole
from tests.conftest import set_setting


class FakeRedis:
    """Controllable Redis eval result; records the two principals and limits."""

    def __init__(self, result=None):
        self.result = result or [1, "ok"]
        self.calls = []

    async def eval(self, script, numkeys, *args):
        self.calls.append((script, numkeys, args))
        return self.result


class _PrincipalTokenVerifier(TokenVerifier):
    """Authenticate the fixed test bearer through the real MCP middleware."""

    def __init__(self, principal: Principal):
        self.principal = principal

    async def verify_token(self, token: str) -> AccessToken | None:
        if token != "runtime-test-token":
            return None
        return AccessToken(
            token=token,
            client_id=self.principal.client_id,
            scopes=sorted(self.principal.scopes),
            subject=str(self.principal.user.id),
            claims={"principal": self.principal},
        )


@pytest.fixture
async def principal():
    async with AsyncSessionLocal() as session:
        user = User(
            username="mcp-tool-runtime-user",
            password_hash="not-used",
            role=UserRole.tester,
        )
        session.add(user)
        await session.commit()
        await session.refresh(user)
        return Principal(
            user=user,
            client_id="client-runtime-test",
            scopes=frozenset({"extensions:read", "extensions:write"}),
        )


@pytest.fixture
async def real_redis():
    client = aioredis.Redis(
        host=settings.REDIS_HOST,
        port=settings.REDIS_PORT,
        db=settings.REDIS_DB,
        decode_responses=True,
    )
    await client.ping()
    try:
        yield client
    finally:
        await client.aclose()


def _spec(handler, **overrides) -> ToolSpec:
    values = {
        "name": "runtime_probe",
        "description": "Exercise the common runtime",
        "input_schema": {
            "type": "object",
            "properties": {
                "code": {"type": "string"},
                "note": {"type": ["string", "null"]},
                "package_base64": {"type": "string"},
                "files": {"type": "object"},
                "options": {"type": "object"},
            },
            "required": ["code"],
            "additionalProperties": False,
        },
        "scope": "extensions:read",
        "read_only": True,
        "handler": handler,
    }
    values.update(overrides)
    return ToolSpec(**values)


def _register(spec: ToolSpec, redis, principal: Principal) -> FastMCP:
    server = build_mcp(
        "extensions",
        public_base_url="http://test",
        allowed_hosts=["test"],
        redis_client=redis,
    )
    server._token_verifier = _PrincipalTokenVerifier(principal)
    register_tool(server, "extensions", spec, redis_client=redis)
    return server


@asynccontextmanager
async def _client_session(server: FastMCP):
    app = server.streamable_http_app()

    def client_factory(headers=None, timeout=None, auth=None):
        return AsyncClient(
            transport=ASGITransport(app=app),
            base_url="http://test",
            headers=headers,
            timeout=timeout,
            auth=auth,
            follow_redirects=True,
        )

    async with run_mcp_lifespan({"extensions": server}):
        async with streamablehttp_client(
            "http://test/extensions",
            headers={"Authorization": "Bearer runtime-test-token"},
            httpx_client_factory=client_factory,
        ) as (read_stream, write_stream, _):
            async with ClientSession(read_stream, write_stream) as session:
                await session.initialize()
                yield session


async def _call(server: FastMCP, **arguments):
    async with _client_session(server) as session:
        return await session.call_tool("runtime_probe", arguments)


def _result_json(result):
    assert result.isError is False
    assert len(result.content) == 1
    assert result.content[0].type == "text"
    return json.loads(result.content[0].text)


def _error_text(result) -> str:
    assert result.isError is True
    return "\n".join(item.text for item in result.content if item.type == "text")


async def _only_audit() -> McpToolCall:
    async with AsyncSessionLocal() as session:
        rows = (await session.execute(select(McpToolCall))).scalars().all()
        assert len(rows) == 1
        return rows[0]


async def _assert_no_audit() -> None:
    async with AsyncSessionLocal() as session:
        rows = (await session.execute(select(McpToolCall))).scalars().all()
        assert rows == []


async def test_registered_sdk_tool_uses_the_exact_declared_schema(principal):
    async def handler(ctx, **kwargs):
        return {"ok": True}

    spec = _spec(handler)
    server = _register(spec, FakeRedis(), principal)

    sdk_tool = server._tool_manager.get_tool(spec.name)
    assert sdk_tool is not None
    assert sdk_tool.parameters == spec.input_schema
    async with _client_session(server) as session:
        listed = await session.list_tools()
    assert len(listed.tools) == 1
    assert listed.tools[0].inputSchema == spec.input_schema


async def test_insufficient_scope_returns_safe_error_and_is_audited(principal):
    called = False

    async def handler(ctx, **kwargs):
        nonlocal called
        called = True
        return {"ok": True}

    limited = Principal(
        user=principal.user,
        client_id=principal.client_id,
        scopes=frozenset(),
    )
    server = _register(_spec(handler, scope="extensions:write"), FakeRedis(), limited)

    result = await _call(server, code="sensitive-code")

    message = _error_text(result)
    assert "scope" in message.lower()
    assert "sensitive-code" not in message
    assert "traceback" not in message.lower()
    assert called is False
    audit = await _only_audit()
    assert audit.success is False
    assert audit.error == "insufficient_scope"
    assert audit.domain == "extensions"
    assert audit.tool == "runtime_probe"
    assert audit.args_summary == {"code": "sensitive-code"}


@pytest.mark.parametrize(
    ("denied", "error"),
    [("user", "user_quota_exceeded"), ("client", "client_quota_exceeded")],
)
async def test_user_and_client_quota_failures_are_safe_and_audited(
    principal, denied, error
):
    called = False

    async def handler(ctx, **kwargs):
        nonlocal called
        called = True
        return {"ok": True}

    redis = FakeRedis([0, denied])
    server = _register(_spec(handler), redis, principal)

    result = await _call(server, code="quota-probe")

    message = _error_text(result)
    assert denied in message.lower()
    assert "quota" in message.lower()
    assert called is False
    audit = await _only_audit()
    assert audit.success is False
    assert audit.error == error


async def test_success_audit_uses_sensitive_argument_summaries(principal):
    package = b"package bytes that must never be audited"
    encoded = base64.b64encode(package).decode("ascii")
    files = {"z.txt": "secret z text", "a.txt": "secret a text"}
    observed = {}

    async def handler(ctx, **kwargs):
        observed["context"] = ctx
        observed["kwargs"] = kwargs
        return {"ok": True}

    server = _register(_spec(handler, read_only=False), FakeRedis(), principal)

    result = await _call(
        server,
        code="probe",
        package_base64=encoded,
        files=files,
        options={"tags": ["one", "two"], "enabled": True},
    )

    assert _result_json(result) == {"ok": True}
    assert observed["context"].principal is principal
    assert observed["kwargs"]["package_base64"] == encoded
    audit = await _only_audit()
    assert audit.success is True
    assert audit.error is None
    assert audit.read_only is False
    assert audit.duration >= 0
    assert audit.args_summary == {
        "code": "probe",
        "package_base64": {
            "bytes": len(package),
            "sha256": hashlib.sha256(package).hexdigest(),
        },
        "files": {"paths": ["a.txt", "z.txt"], "count": 2},
        "options": {"tags": {"count": 2}, "enabled": True},
    }
    stored = json.dumps(audit.args_summary)
    assert encoded not in stored
    assert package.decode() not in stored
    assert "secret z text" not in stored
    assert "secret a text" not in stored


async def test_nested_sensitive_arguments_are_recursively_redacted(principal):
    package = b"nested package bytes that must never be audited"
    encoded = base64.b64encode(package).decode("ascii")
    files = {"nested/z.txt": "nested secret z", "nested/a.txt": "nested secret a"}

    async def handler(ctx, **kwargs):
        return {"ok": True}

    server = _register(_spec(handler), FakeRedis(), principal)
    result = await _call(
        server,
        code="nested",
        options={"level": {"package_base64": encoded, "files": files}},
    )

    assert _result_json(result) == {"ok": True}
    audit = await _only_audit()
    assert audit.args_summary == {
        "code": "nested",
        "options": {
            "level": {
                "package_base64": {
                    "bytes": len(package),
                    "sha256": hashlib.sha256(package).hexdigest(),
                },
                "files": {
                    "paths": ["nested/a.txt", "nested/z.txt"],
                    "count": 2,
                },
            }
        },
    }
    stored = json.dumps(audit.args_summary)
    assert encoded not in stored
    assert package.decode() not in stored
    assert "nested secret z" not in stored
    assert "nested secret a" not in stored


@pytest.mark.parametrize(
    ("key", "value", "sensitive"),
    [
        ("files", 1, None),
        ("files", "nested-files-scalar-secret", "nested-files-scalar-secret"),
        ("files", ["nested-files-list-secret"], "nested-files-list-secret"),
        ("package_base64", 1, None),
        ("package_base64", ["nested-package-list-secret"], "nested-package-list-secret"),
        (
            "package_base64",
            {"payload": "nested-package-dict-secret"},
            "nested-package-dict-secret",
        ),
        ("package_base64", "not-base64!", "not-base64!"),
    ],
    ids=[
        "files-scalar",
        "files-string",
        "files-list",
        "package-scalar",
        "package-list",
        "package-dict",
        "package-malformed-string",
    ],
)
async def test_malformed_nested_sensitive_values_are_safe_and_audited(
    principal, key, value, sensitive
):
    async def handler(ctx, **kwargs):
        return {"ok": True}

    server = _register(_spec(handler), FakeRedis(), principal)
    result = await _call(server, code="malformed", options={key: value})

    message = "\n".join(item.text for item in result.content if item.type == "text")
    if sensitive is not None:
        assert sensitive not in message
    assert result.isError is False, message
    assert _result_json(result) == {"ok": True}
    audit = await _only_audit()
    assert audit.success is True
    assert audit.args_summary == {
        "code": "malformed",
        "options": {key: {"invalid": True}},
    }
    stored = json.dumps(audit.args_summary)
    if sensitive is not None:
        assert sensitive not in stored


@pytest.mark.parametrize(
    ("arguments", "sensitive", "expected_summary"),
    [
        (
            {"package_base64": "bWlzc2luZy1jb2RlLXNlY3JldA=="},
            "bWlzc2luZy1jb2RlLXNlY3JldA==",
            {
                "package_base64": {
                    "bytes": 19,
                    "sha256": hashlib.sha256(b"missing-code-secret").hexdigest(),
                }
            },
        ),
        ({"code": 73}, "73", {"code": {"invalid": True}}),
        (
            {"code": "probe", "extra": "unexpected-secret"},
            "unexpected-secret",
            {"code": {"invalid": True}, "extra": {"invalid": True}},
        ),
        (
            {"code": "probe", "files": "wrong-files-secret"},
            "wrong-files-secret",
            {"code": {"invalid": True}, "files": {"invalid": True}},
        ),
    ],
    ids=["missing-required", "wrong-type", "additional-property", "malformed-files"],
)
async def test_invalid_schema_arguments_are_safely_audited_and_never_reach_handler(
    principal, arguments, sensitive, expected_summary
):
    called = False

    async def handler(ctx, **kwargs):
        nonlocal called
        called = True
        return {"ok": True}

    server = _register(_spec(handler), FakeRedis(), principal)
    result = await _call(server, **arguments)

    message = _error_text(result)
    assert "invalid" in message.lower()
    assert sensitive not in message
    assert called is False
    audit = await _only_audit()
    assert audit.success is False
    assert audit.error == "invalid_arguments"
    assert audit.args_summary == expected_summary
    assert sensitive not in json.dumps(audit.args_summary)


async def test_optional_arguments_preserve_omitted_vs_explicit_null(principal):
    async def handler(ctx, **kwargs):
        return kwargs

    server = _register(_spec(handler), FakeRedis(), principal)

    async with _client_session(server) as session:
        omitted = await session.call_tool("runtime_probe", {"code": "omitted"})
        explicit = await session.call_tool(
            "runtime_probe", {"code": "explicit", "note": None}
        )

    assert _result_json(omitted) == {"code": "omitted"}
    assert _result_json(explicit) == {"code": "explicit", "note": None}


async def test_unexpected_handler_exception_does_not_leak_details(principal):
    secret = "secret-argument-value"

    async def handler(ctx, **kwargs):
        raise RuntimeError("SELECT * FROM users WHERE secret='database-secret'")

    server = _register(_spec(handler), FakeRedis(), principal)

    result = await _call(server, code=secret)

    message = _error_text(result)
    assert "database-secret" not in message
    assert secret not in message
    assert "SELECT" not in message
    assert "traceback" not in message.lower()
    audit = await _only_audit()
    assert audit.success is False
    assert audit.error == "RuntimeError"
    assert audit.args_summary == {"code": secret}


async def test_quota_defaults_and_settings_override(principal):
    from app.mcp.common.tool import CLIENT_QUOTA_SETTING, USER_QUOTA_SETTING

    async def handler(ctx, **kwargs):
        return {"ok": True}

    default_redis = FakeRedis()
    await _call(_register(_spec(handler), default_redis, principal), code="defaults")
    default_args = default_redis.calls[0][2]
    assert default_args[-2:] == ("1000", "200")

    await set_setting(USER_QUOTA_SETTING, "7")
    await set_setting(CLIENT_QUOTA_SETTING, "11")
    configured_redis = FakeRedis()
    await _call(
        _register(_spec(handler), configured_redis, principal), code="configured"
    )
    configured_args = configured_redis.calls[0][2]
    assert configured_args[-2:] == ("7", "11")


def _real_quota_keys(principal: Principal, now: int) -> tuple[list[str], str, str]:
    minute = now // 60
    user_prefix = f"mcp:quota:user:{principal.user.id}:"
    client_prefix = f"mcp:quota:client:{principal.user.id}:{principal.client_id}:"
    keys = [
        f"{prefix}{bucket}"
        for prefix in (user_prefix, client_prefix)
        for bucket in (minute - 1, minute)
    ]
    return keys, f"{user_prefix}{minute}", f"{client_prefix}{minute}"


async def test_real_redis_sliding_window_allows_and_expires_both_current_buckets(
    principal, real_redis, monkeypatch
):
    now = 1_699_999_995
    keys, user_current, client_current = _real_quota_keys(principal, now)
    minute = now // 60
    user_previous = f"mcp:quota:user:{principal.user.id}:{minute - 1}"
    await set_setting(tool_runtime.USER_QUOTA_SETTING, "10")
    await set_setting(tool_runtime.CLIENT_QUOTA_SETTING, "3")
    try:
        await real_redis.set(user_current, 2)
        await real_redis.set(user_previous, 4)
        await real_redis.set(client_current, 1)
        monkeypatch.setattr(tool_runtime.time, "time", lambda: now)

        await tool_runtime._consume_quota(real_redis, principal)

        assert await real_redis.get(user_current) == "3"
        assert await real_redis.get(client_current) == "2"
        assert 0 < await real_redis.ttl(user_current) <= 120
        assert 0 < await real_redis.ttl(client_current) <= 120
    finally:
        await real_redis.delete(*keys)


async def test_real_redis_weighted_previous_bucket_denies_without_dual_increment(
    principal, real_redis, monkeypatch
):
    now = 1_699_999_995
    keys, user_current, client_current = _real_quota_keys(principal, now)
    minute = now // 60
    user_previous = f"mcp:quota:user:{principal.user.id}:{minute - 1}"
    await set_setting(tool_runtime.USER_QUOTA_SETTING, "10")
    await set_setting(tool_runtime.CLIENT_QUOTA_SETTING, "100")
    try:
        await real_redis.set(user_current, 2)
        await real_redis.set(user_previous, 11)
        monkeypatch.setattr(tool_runtime.time, "time", lambda: now)

        with pytest.raises(McpRuntimeError) as caught:
            await tool_runtime._consume_quota(real_redis, principal)

        assert caught.value.code == "user_quota_exceeded"
        assert await real_redis.get(user_current) == "2"
        assert await real_redis.get(client_current) is None
    finally:
        await real_redis.delete(*keys)


async def test_real_redis_client_denial_does_not_increment_user_bucket(
    principal, real_redis, monkeypatch
):
    now = 1_699_999_995
    keys, user_current, client_current = _real_quota_keys(principal, now)
    minute = now // 60
    client_previous = (
        f"mcp:quota:client:{principal.user.id}:{principal.client_id}:{minute - 1}"
    )
    await set_setting(tool_runtime.USER_QUOTA_SETTING, "10")
    await set_setting(tool_runtime.CLIENT_QUOTA_SETTING, "2")
    try:
        await real_redis.set(user_current, 1)
        await real_redis.set(client_current, 1)
        await real_redis.set(client_previous, 2)
        monkeypatch.setattr(tool_runtime.time, "time", lambda: now)

        with pytest.raises(McpRuntimeError) as caught:
            await tool_runtime._consume_quota(real_redis, principal)

        assert caught.value.code == "client_quota_exceeded"
        assert await real_redis.get(user_current) == "1"
        assert await real_redis.get(client_current) == "1"
    finally:
        await real_redis.delete(*keys)


async def test_unconfigured_dispatcher_returns_503():
    dispatcher = build_dispatcher()
    async with AsyncClient(
        transport=ASGITransport(app=dispatcher), base_url="http://test"
    ) as client:
        response = await client.post("/skill", json={})
    assert response.status_code == 503


async def test_dispatcher_uses_exact_streamable_route_and_sse_mount(principal):
    domain = build_mcp(
        "extensions",
        public_base_url="http://test:8081",
        allowed_hosts=["test", "test:8081"],
    )
    dispatcher = build_dispatcher({"extensions": domain})

    assert len(dispatcher.routes) == 4
    assert isinstance(dispatcher.routes[0], Route)
    assert dispatcher.routes[0].path == "/extensions"
    assert isinstance(dispatcher.routes[1], Mount)
    assert dispatcher.routes[1].path == "/extensions"
    assert dispatcher.routes[2].path == "/skill"  # Legacy alias route.
    assert dispatcher.routes[3].path == "/skill"  # Legacy alias SSE mount.
    assert domain.settings.streamable_http_path == "/extensions"
    assert domain.settings.mount_path == "/"  # Outer mounts provide /mcp/extensions.
    assert domain.settings.stateless_http is True
    assert domain.settings.json_response is True


class _RecordingAsgiApp:
    def __init__(self) -> None:
        self.paths: list[str] = []

    async def __call__(self, scope, receive, send) -> None:
        from starlette.responses import JSONResponse

        self.paths.append(scope["path"])
        await JSONResponse({"path": scope["path"], "method": scope["method"]})(
            scope, receive, send
        )


class _FakeDomain:
    def __init__(self, app: _RecordingAsgiApp) -> None:
        self._app = app

    def streamable_http_app(self):
        return self._app

    def sse_app(self):
        return self._app


async def test_legacy_skill_alias_forwards_post_to_extensions():
    from fastapi import FastAPI

    app = _RecordingAsgiApp()
    dispatcher = build_dispatcher({"extensions": _FakeDomain(app)})
    outer = FastAPI()
    outer.mount("/mcp", dispatcher)

    async with AsyncClient(
        transport=ASGITransport(app=outer), base_url="http://test"
    ) as client:
        response = await client.post("/mcp/skill")

    assert response.status_code == 200
    assert response.json() == {"path": "/mcp/extensions", "method": "POST"}


async def test_lifespan_enters_and_exits_every_domain_symmetrically():
    events = []

    class SessionManager:
        def __init__(self, name):
            self.name = name

        @asynccontextmanager
        async def run(self):
            events.append(f"enter:{self.name}")
            try:
                yield
            finally:
                events.append(f"exit:{self.name}")

    class Domain:
        def __init__(self, name):
            self.session_manager = SessionManager(name)

    domains = {"one": Domain("one"), "two": Domain("two")}
    with pytest.raises(LookupError):
        async with run_mcp_lifespan(domains):
            assert events == ["enter:one", "enter:two"]
            raise LookupError("stop the lifespan test")
    assert events == ["enter:one", "enter:two", "exit:two", "exit:one"]
