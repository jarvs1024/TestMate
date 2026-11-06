"""kb_document_write_ticket 的票面契约。"""
from __future__ import annotations

from contextlib import asynccontextmanager

import pytest
from httpx import ASGITransport, AsyncClient
from mcp.server.auth.provider import AccessToken, TokenVerifier
from starlette.applications import Starlette
from starlette.routing import Mount

from app.db.session import AsyncSessionLocal
from app.mcp.common.context import Principal
from app.mcp.common.server import build_dispatcher, run_mcp_lifespan
from app.mcp.kb.server import build_kb_server
from app.models.user import User, UserRole
from tests._mcp_protocol import call_tool, call_tool_data, list_tools
from tests.conftest import set_setting

ENDPOINT = "/mcp/kb"
TOKEN = "kb-ticket-writer"


class _FakeRedis:
    async def eval(self, script, numkeys, *args):
        return [1, "ok"]


class _Verifier(TokenVerifier):
    def __init__(self, principal):
        self.principal = principal

    async def verify_token(self, token):
        if token != TOKEN:
            return None
        return AccessToken(
            token=token, client_id="kb-ticket-tests",
            scopes=sorted(self.principal.scopes),
            subject=str(self.principal.user.id),
            claims={"principal": self.principal},
        )


@pytest.fixture
async def writer():
    async with AsyncSessionLocal() as session:
        user = User(username="kb-ticket-writer", password_hash="unused", role=UserRole.tester)
        session.add(user)
        await session.commit()
        await session.refresh(user)
        return user


@pytest.fixture
def fake_rf(monkeypatch):
    import app.api.kb as kb_mod
    from tests.test_kb_update_document import FakeRagflow

    rf = FakeRagflow()
    monkeypatch.setattr(kb_mod, "list_datasets", rf.list_datasets)
    return rf


@asynccontextmanager
async def _client(user):
    principal = Principal(user=user, client_id="kb-ticket-tests", scopes=frozenset({"kb:read", "kb:write"}))
    server = build_kb_server(
        public_base_url="http://test", allowed_hosts=["test"], redis_client=_FakeRedis()
    )
    server._token_verifier = _Verifier(principal)
    dispatcher = build_dispatcher({"kb": server})
    app = Starlette(routes=[Mount("/mcp", app=dispatcher)])
    async with (
        run_mcp_lifespan(dispatcher),
        AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client,
    ):
        yield client


async def test_tools_list_has_all_twelve(writer, fake_rf):
    async with _client(writer) as client:
        result = await list_tools(client, TOKEN, endpoint=ENDPOINT)
    assert len(result["tools"]) == 12
    names = {tool["name"] for tool in result["tools"]}
    assert "kb_document_write_ticket" in names


async def test_ticket_shape_and_reusable_flag(writer, fake_rf):
    await set_setting("extensions.public_base_url", "https://tm.example.com/")
    async with _client(writer) as client:
        data = await call_tool_data(
            client, TOKEN, "kb_document_write_ticket",
            {"dataset_id": "ds-naive"}, endpoint=ENDPOINT,
        )
    assert data["ticket"]
    assert data["upload_url"] == (
        "https://tm.example.com/api/v1/kb/datasets/ds-naive/documents/ticket-upload"
    )
    assert data["method"] == "POST"
    assert data["file_field"] == "file"
    assert data["replace_field"] == "document_id"
    assert data["expires_in"] == 1800
    assert data["reusable"] is True
    assert data["max_bytes_per_file"] == 20 * 1024 * 1024
    assert data["max_files_per_request"] == 5


async def test_ticket_for_missing_dataset_is_not_found(writer, fake_rf):
    async with _client(writer) as client:
        result = await call_tool(
            client, TOKEN, "kb_document_write_ticket",
            {"dataset_id": "missing"}, endpoint=ENDPOINT,
        )
    assert result["isError"] is True
    assert "数据集不存在" in result["content"][0]["text"]
