"""真实 Streamable HTTP 契约测试: 7 个知识库读工具。"""
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
from tests._mcp_protocol import call_tool_data, list_tools

READ_TOKEN = "kb-read-token"
ENDPOINT = "/mcp/kb"
READ_TOOLS = {
    "kb_dataset_list",
    "kb_document_list",
    "kb_document_search",
    "kb_document_chunks",
    "kb_document_status",
    "kb_search",
    "kb_health",
}


class _FakeRedis:
    async def eval(self, script, numkeys, *args):
        return [1, "ok"]


class _Verifier(TokenVerifier):
    def __init__(self, principals):
        self.principals = principals

    async def verify_token(self, token):
        principal = self.principals.get(token)
        if principal is None:
            return None
        return AccessToken(
            token=token,
            client_id=principal.client_id,
            scopes=sorted(principal.scopes),
            subject=str(principal.user.id),
            claims={"principal": principal},
        )


class FakeKB:
    def __init__(self) -> None:
        self.datasets = [
            {
                "id": "ds-1", "name": "技术文档", "description": "产品技术资料",
                "chunk_count": 3, "document_count": 2, "chunk_method": "naive",
                "embedding_model": "emb", "permission": "me", "status": "1",
            },
            {
                "id": "ds-2", "name": "协议文档", "description": "接口协议",
                "chunk_count": 1, "document_count": 1, "chunk_method": "manual",
                "embedding_model": "emb", "permission": "me", "status": "1",
            },
        ]
        self.docs = [
            {"id": "doc-1", "name": "a.md", "size": 10, "run": "DONE",
             "chunk_count": 2, "token_count": 20},
            {"id": "doc-2", "name": "b.md", "size": 20, "run": "RUNNING",
             "chunk_count": 0, "token_count": 0},
        ]
        self.runs = ["RUNNING", "DONE"]

    async def list_datasets(self, page=1, page_size=50):
        start = (page - 1) * page_size
        return self.datasets[start:start + page_size]

    async def list_documents(self, dataset_id, page=1, page_size=30,
                             orderby="create_time", desc=True, keywords="", run=""):
        docs = [d for d in self.docs if not keywords or keywords.lower() in d["name"].lower()]
        return {"docs": docs, "total": len(docs)}

    async def find_document(self, dataset_id, document_id):
        return next((d for d in self.docs if d["id"] == document_id), None)


@pytest.fixture
async def users():
    async with AsyncSessionLocal() as session:
        owner = User(username="kb-read-owner", password_hash="unused", role=UserRole.tester)
        viewer = User(username="kb-read-viewer", password_hash="unused", role=UserRole.viewer)
        session.add_all([owner, viewer])
        await session.commit()
        await session.refresh(owner)
        await session.refresh(viewer)
        return owner, viewer


@pytest.fixture
def fake_kb(monkeypatch):
    import app.api.kb as kb_mod

    fake = FakeKB()
    monkeypatch.setattr(kb_mod, "list_datasets", fake.list_datasets)
    monkeypatch.setattr(kb_mod, "list_documents", fake.list_documents)
    monkeypatch.setattr(kb_mod, "_find_document", fake.find_document)

    async def search_documents(keywords="", dataset_id="", limit=200, _user=None):
        items = [d for d in fake.docs if keywords.lower() in d["name"].lower()]
        return {"items": items, "total": len(items), "keywords": keywords,
                "datasets": [], "truncated": False}

    async def list_doc_chunks(dataset_id, document_id, page=1, page_size=100, keywords=""):
        return {"chunks": [{"id": "c-1", "content": "hello"}], "total": 1,
                "doc": {"id": document_id, "name": "a.md"}}

    async def retrieval(**kwargs):
        return {"total": 1, "chunks": [{"id": "c-1", "content": "hello",
                "similarity": 0.9}], "doc_aggs": [], "elapsed_ms": 7}

    async def probe():
        return "ok", "RAGFlow 可用"

    monkeypatch.setattr(kb_mod, "search_documents", search_documents)
    monkeypatch.setattr(kb_mod, "list_doc_chunks", list_doc_chunks)
    monkeypatch.setattr(kb_mod, "retrieval", retrieval)
    monkeypatch.setattr(kb_mod, "probe", probe)
    return fake


@pytest.fixture
def principals(users):
    _, viewer = users

    def principal(user, scopes):
        return Principal(user=user, client_id="kb-read-tests", scopes=frozenset(scopes))

    return {READ_TOKEN: principal(viewer, {"kb:read"})}


@asynccontextmanager
async def _client(principals):
    server = build_kb_server(
        public_base_url="http://test",
        allowed_hosts=["test"],
        redis_client=_FakeRedis(),
    )
    server._token_verifier = _Verifier(principals)
    dispatcher = build_dispatcher({"kb": server})
    app = Starlette(routes=[Mount("/mcp", app=dispatcher)])
    async with run_mcp_lifespan(dispatcher):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            yield client


async def test_tools_list_exposes_all_read_tools(principals):
    async with _client(principals) as client:
        result = await list_tools(client, READ_TOKEN, endpoint=ENDPOINT)
    names = {tool["name"] for tool in result["tools"]}
    assert READ_TOOLS <= names


async def test_dataset_list_paginates_and_filters(principals, fake_kb):
    async with _client(principals) as client:
        page = await call_tool_data(
            client, READ_TOKEN, "kb_dataset_list",
            {"page": 1, "page_size": 1}, endpoint=ENDPOINT,
        )
        filtered = await call_tool_data(
            client, READ_TOKEN, "kb_dataset_list",
            {"keyword": "协议"}, endpoint=ENDPOINT,
        )

    assert page["items"][0]["id"] == "ds-1"
    assert page["has_more"] is True
    assert [item["id"] for item in filtered["items"]] == ["ds-2"]


async def test_document_list_and_search(principals, fake_kb):
    async with _client(principals) as client:
        listed = await call_tool_data(
            client, READ_TOKEN, "kb_document_list", {"dataset_id": "ds-1"},
            endpoint=ENDPOINT,
        )
        searched = await call_tool_data(
            client, READ_TOKEN, "kb_document_search", {"keywords": "a"},
            endpoint=ENDPOINT,
        )

    assert listed["total"] == 2
    assert listed["docs"][0]["uploaded_by"] is None
    assert searched["total"] == 1
    assert searched["items"][0]["id"] == "doc-1"


async def test_chunks_search_and_health(principals, fake_kb):
    async with _client(principals) as client:
        chunks = await call_tool_data(
            client, READ_TOKEN, "kb_document_chunks",
            {"dataset_id": "ds-1", "document_id": "doc-1"}, endpoint=ENDPOINT,
        )
        result = await call_tool_data(
            client, READ_TOKEN, "kb_search",
            {"question": "hello", "dataset_ids": ["ds-1"]}, endpoint=ENDPOINT,
        )
        health = await call_tool_data(
            client, READ_TOKEN, "kb_health", {}, endpoint=ENDPOINT,
        )

    assert chunks["total"] == 1
    assert chunks["doc"]["id"] == "doc-1"
    assert result["total"] == 1
    assert result["elapsed_ms"] == 7
    assert health["status"] == "ok"


async def test_status_polls_until_done(principals, fake_kb, monkeypatch):
    import app.mcp.kb.adapter as adapter

    states = iter(["RUNNING", "RUNNING", "DONE"])

    async def fake_find(dataset_id, document_id):
        return {"id": document_id, "name": "a.md", "run": next(states, "DONE"),
                "progress": 1.0, "progress_msg": "", "chunk_count": 2, "token_count": 20}

    monkeypatch.setattr(fake_kb, "find_document", fake_find)
    import app.api.kb as kb_mod
    monkeypatch.setattr(kb_mod, "_find_document", fake_find)

    clock = {"now": 0.0}
    monkeypatch.setattr(adapter, "_monotonic", lambda: clock["now"])

    async def sleep(seconds):
        clock["now"] += seconds

    monkeypatch.setattr(adapter, "_sleep", sleep)

    async with _client(principals) as client:
        data = await call_tool_data(
            client, READ_TOKEN, "kb_document_status",
            {"dataset_id": "ds-1", "document_id": "doc-1", "wait_seconds": 10},
            endpoint=ENDPOINT,
        )

    assert data["run"] == "DONE"
    assert data["timed_out"] is False


async def test_status_timeout_returns_current_state(principals, fake_kb, monkeypatch):
    import app.mcp.kb.adapter as adapter

    async def fake_find(dataset_id, document_id):
        return {"id": document_id, "name": "a.md", "run": "RUNNING",
                "progress": 0.3, "progress_msg": "切片中", "chunk_count": 0, "token_count": 0}

    import app.api.kb as kb_mod
    monkeypatch.setattr(kb_mod, "_find_document", fake_find)

    clock = {"now": 0.0}
    monkeypatch.setattr(adapter, "_monotonic", lambda: clock["now"])

    async def sleep(seconds):
        clock["now"] += seconds

    monkeypatch.setattr(adapter, "_sleep", sleep)

    async with _client(principals) as client:
        data = await call_tool_data(
            client, READ_TOKEN, "kb_document_status",
            {"dataset_id": "ds-1", "document_id": "doc-1", "wait_seconds": 4},
            endpoint=ENDPOINT,
        )

    assert data["run"] == "RUNNING"
    assert data["timed_out"] is True
    assert data["progress_msg"] == "切片中"
