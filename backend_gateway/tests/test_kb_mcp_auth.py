"""MCP 令牌只能调 /mcp/kb，不能当登录令牌调 REST。"""
from __future__ import annotations

import hashlib
from contextlib import asynccontextmanager

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from app.api import kb as kb_api
from app.db.session import AsyncSessionLocal
from app.mcp.common import auth, oauth
from app.mcp.common.server import build_dispatcher, run_mcp_lifespan
from app.mcp.kb.server import build_kb_server
from app.models.mcp import McpApiToken, McpOAuthClient, McpOAuthGrant
from app.models.user import User, UserRole
from tests._mcp_protocol import list_tools
from tests.conftest import set_setting

PUBLIC_BASE = "http://test"
ENDPOINT = "/mcp/kb"


class _FakeRedis:
    async def eval(self, script, numkeys, *args):
        return [1, "ok"]


@pytest.fixture(autouse=True)
async def _settings():
    await set_setting("extensions.public_base_url", PUBLIC_BASE)
    await set_setting("mcp.allowed_hosts", "test")


@pytest.fixture
async def user():
    async with AsyncSessionLocal() as session:
        u = User(username="kb-auth-user", password_hash="unused", role=UserRole.tester)
        session.add(u)
        await session.commit()
        await session.refresh(u)
        return u


async def _static_token(user: User, scopes=("kb:read",)) -> str:
    token = await auth.issue_static_token(user, PUBLIC_BASE)
    async with AsyncSessionLocal() as session:
        session.add(
            McpApiToken(
                name="kb-auth-static",
                token_hash=hashlib.sha256(token.encode("ascii")).hexdigest(),
                user_id=user.id,
                scopes=list(scopes),
            )
        )
        await session.commit()
    return token


async def _oauth_token(user: User, scopes=("kb:read",)) -> str:
    async with AsyncSessionLocal() as session:
        client_id = "kb-auth-client"
        session.add(
            McpOAuthClient(
                client_id=client_id,
                client_name="kb auth client",
                redirect_uris=["http://127.0.0.1:51234/callback"],
                scopes=["kb:read", "kb:write"],
            )
        )
        grant = McpOAuthGrant(user_id=user.id, client_id=client_id, scopes=list(scopes), version=1)
        session.add(grant)
        await session.commit()
        await session.refresh(grant)
    return await oauth.issue_access_token(user, grant, PUBLIC_BASE)


@asynccontextmanager
async def _app(monkeypatch):
    import app.api.kb as kb_mod

    async def list_datasets(page=1, page_size=50):
        return [{"id": "ds-1", "name": "技术文档", "description": "",
                 "chunk_method": "naive", "embedding_model": "emb",
                 "permission": "me", "document_count": 0, "chunk_count": 0}]

    monkeypatch.setattr(kb_mod, "list_datasets", list_datasets)

    server = build_kb_server(
        public_base_url=PUBLIC_BASE, allowed_hosts=["test"], redis_client=_FakeRedis()
    )
    dispatcher = build_dispatcher({"kb": server})
    app = FastAPI()
    app.include_router(kb_api.router, prefix="/api/v1/kb")
    app.mount("/mcp", dispatcher)
    async with (
        run_mcp_lifespan(dispatcher),
        AsyncClient(transport=ASGITransport(app=app), base_url=PUBLIC_BASE) as client,
    ):
        yield client


@pytest.mark.parametrize("kind", ["static", "oauth"])
async def test_mcp_token_cannot_call_rest_but_can_call_kb_mcp(user, monkeypatch, kind):
    token = await _static_token(user) if kind == "static" else await _oauth_token(user)

    async with _app(monkeypatch) as client:
        rest = await client.get(
            "/api/v1/kb/datasets", headers={"Authorization": f"Bearer {token}"}
        )
        tools = await list_tools(client, token, endpoint=ENDPOINT)

    assert rest.status_code == 401, rest.text
    assert len(tools["tools"]) == 12


async def test_platform_login_token_still_works_on_rest(user, monkeypatch):
    from app.core.security import create_access_token

    token, _ = create_access_token(user.id)

    async with _app(monkeypatch) as client:
        rest = await client.get(
            "/api/v1/kb/datasets", headers={"Authorization": f"Bearer {token}"}
        )

    assert rest.status_code == 200, rest.text
    assert rest.json()["items"][0]["id"] == "ds-1"
