"""真实 Streamable HTTP 契约测试: 文本写工具与「已提交」语义。"""
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
from tests.test_kb_update_document import FakeRagflow

ENDPOINT = "/mcp/kb"
WRITE_TOKEN = "kb-write-token"
READ_TOKEN = "kb-read-token"


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


class FakeKB(FakeRagflow):
    def __init__(self) -> None:
        super().__init__()
        self.created_datasets: list[dict] = []

    async def create_dataset(self, name, description="", **kwargs):
        ds = {
            "id": f"ds-new-{len(self.datasets) + 1}", "name": name,
            "description": description, "chunk_method": kwargs.get("chunk_method", "naive"),
            "embedding_model": "emb", "permission": "me",
            "document_count": 0, "chunk_count": 0,
        }
        self.datasets[ds["id"]] = ds
        self.created_datasets.append(ds)
        return ds

    async def update_dataset(self, dataset_id, **kwargs):
        return self.datasets.get(dataset_id, {})


@pytest.fixture
def fake_kb(monkeypatch):
    import app.api.kb as kb_mod

    fake = FakeKB()
    for name in (
        "list_datasets", "list_documents", "upload_documents", "delete_documents",
        "update_document", "ingest_documents", "parse_documents",
    ):
        monkeypatch.setattr(kb_mod, name, getattr(fake, name))
    monkeypatch.setattr(kb_mod, "create_dataset", fake.create_dataset)
    monkeypatch.setattr(kb_mod, "update_dataset", fake.update_dataset)
    return fake


@pytest.fixture
async def users():
    async with AsyncSessionLocal() as session:
        tester = User(username="kb-write-tester", password_hash="unused", role=UserRole.tester)
        viewer = User(username="kb-write-viewer", password_hash="unused", role=UserRole.viewer)
        session.add_all([tester, viewer])
        await session.commit()
        await session.refresh(tester)
        await session.refresh(viewer)
        return tester, viewer


@pytest.fixture
def principals(users):
    tester, viewer = users

    def principal(user, scopes):
        return Principal(user=user, client_id="kb-write-tests", scopes=frozenset(scopes))

    return {
        WRITE_TOKEN: principal(tester, {"kb:read", "kb:write"}),
        READ_TOKEN: principal(viewer, {"kb:read"}),
    }


@asynccontextmanager
async def _client(principals):
    server = build_kb_server(
        public_base_url="http://test", allowed_hosts=["test"],
        redis_client=_FakeRedis(),
    )
    server._token_verifier = _Verifier(principals)
    dispatcher = build_dispatcher({"kb": server})
    app = Starlette(routes=[Mount("/mcp", app=dispatcher)])
    async with (
        run_mcp_lifespan(dispatcher),
        AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client,
    ):
        yield client


async def test_tools_list_exposes_write_tools(principals, fake_kb):
    async with _client(principals) as client:
        result = await list_tools(client, WRITE_TOKEN, endpoint=ENDPOINT)
    names = {tool["name"] for tool in result["tools"]}
    assert {
        "kb_dataset_create", "kb_document_upload",
        "kb_document_update", "kb_document_reparse",
    } <= names


async def test_dataset_create(principals, fake_kb):
    async with _client(principals) as client:
        data = await call_tool_data(
            client, WRITE_TOKEN, "kb_dataset_create",
            {"name": "新库", "description": "说明", "chunk_method": "naive"},
            endpoint=ENDPOINT,
        )
    assert data["ok"] is True
    assert data["dataset"]["name"] == "新库"
    assert fake_kb.created_datasets


async def test_upload_returns_submitted_without_waiting_for_parse(principals, fake_kb):
    async with _client(principals) as client:
        data = await call_tool_data(
            client, WRITE_TOKEN, "kb_document_upload",
            {"dataset_id": "ds-naive", "name": "a.md", "content": "# hello"},
            endpoint=ENDPOINT,
        )
    assert data["ok"] is True
    assert data["state"] == "submitted"
    assert data["uploaded"] == 1
    assert data["docs"][0]["run"] == "UNSTART"
    assert data["ingest_started"] is True
    assert fake_kb.ingested


async def test_upload_rejects_binary_extension(principals, fake_kb):
    async with _client(principals) as client:
        data = await call_tool_data(
            client, WRITE_TOKEN, "kb_document_upload",
            {"dataset_id": "ds-naive", "name": "a.pdf", "content": "not really a pdf"},
            endpoint=ENDPOINT,
        )
    assert data["ok"] is False
    assert data["state"] == "failed"
    assert data["errors"][0]["error"] == "invalid_document_type"
    assert "kb_document_write_ticket" in data["errors"][0]["message"]
    assert fake_kb.docs == []


async def test_upload_batch_partial_failure_keeps_successes(principals, fake_kb, monkeypatch):
    from app.mcp.kb import adapter

    monkeypatch.setattr(adapter, "MAX_MCP_INLINE_BYTES", 10)
    async with _client(principals) as client:
        data = await call_tool_data(
            client, WRITE_TOKEN, "kb_document_upload",
            {
                "dataset_id": "ds-naive",
                "documents": [
                    {"name": "ok1.md", "content": "short"},
                    {"name": "big.md", "content": "x" * 11},
                    {"name": "ok2.md", "content": "short"},
                ],
            },
            endpoint=ENDPOINT,
        )
    assert data["ok"] is False
    assert data["state"] == "partial"
    assert data["uploaded"] == 2
    assert data["failed"] == 1
    assert data["errors"][0]["name"] == "big.md"
    assert len(fake_kb.docs) == 2
    assert fake_kb.ingested


async def test_update_reports_replaced_old_id(principals, fake_kb):
    created = await fake_kb.upload_documents("ds-naive", [("a.md", b"old", "text/plain")])
    old_id = created[0]["id"]

    async with _client(principals) as client:
        data = await call_tool_data(
            client, WRITE_TOKEN, "kb_document_update",
            {"dataset_id": "ds-naive", "document_id": old_id, "content": "new"},
            endpoint=ENDPOINT,
        )
    assert data["ok"] is True
    assert data["state"] == "submitted"
    assert data["replaced"] == old_id
    assert data["docs"][0]["document_id"] != old_id
    assert data["docs"][0]["name"] == "a.md"


async def test_update_batch_replaces_both(principals, fake_kb):
    first = await fake_kb.upload_documents("ds-naive", [("a.md", b"a", "text/plain")])
    second = await fake_kb.upload_documents("ds-naive", [("b.md", b"b", "text/plain")])

    async with _client(principals) as client:
        data = await call_tool_data(
            client, WRITE_TOKEN, "kb_document_update",
            {
                "dataset_id": "ds-naive",
                "documents": [
                    {"document_id": first[0]["id"], "content": "a2"},
                    {"document_id": second[0]["id"], "content": "b2"},
                ],
            },
            endpoint=ENDPOINT,
        )
    assert data["updated"] == 2
    assert sorted(data["replaced"]) == sorted([first[0]["id"], second[0]["id"]])
    assert len({doc["document_id"] for doc in data["docs"]}) == 2


async def test_reparse_returns_without_waiting(principals, fake_kb):
    created = await fake_kb.upload_documents("ds-naive", [("a.md", b"x", "text/plain")])
    doc_id = created[0]["id"]

    async with _client(principals) as client:
        data = await call_tool_data(
            client, WRITE_TOKEN, "kb_document_reparse",
            {"dataset_id": "ds-naive", "document_id": doc_id},
            endpoint=ENDPOINT,
        )
    assert data["ok"] is True
    assert data["state"] == "submitted"
    assert data["run"] in {"UNSTART", "RUNNING"}
    assert fake_kb.parsed[-1] == [doc_id]


async def test_write_tools_reject_read_only_token(principals, fake_kb):
    async with _client(principals) as client:
        upload = await call_tool(
            client, READ_TOKEN, "kb_document_upload",
            {"dataset_id": "ds-naive", "name": "a.md", "content": "x"},
            endpoint=ENDPOINT,
        )
        create = await call_tool(
            client, READ_TOKEN, "kb_dataset_create", {"name": "x"}, endpoint=ENDPOINT
        )
    assert upload["isError"] is True
    assert create["isError"] is True
    assert "Insufficient scope" in upload["content"][0]["text"]


async def test_unknown_dataset_is_not_found(principals, fake_kb):
    async with _client(principals) as client:
        result = await call_tool(
            client, WRITE_TOKEN, "kb_document_upload",
            {"dataset_id": "missing", "name": "a.md", "content": "x"},
            endpoint=ENDPOINT,
        )
    assert result["isError"] is True
    assert "数据集不存在" in result["content"][0]["text"]


async def test_ragflow_failure_maps_to_kb_unavailable(principals, fake_kb, monkeypatch):
    import app.api.kb as kb_mod

    async def boom(*args, **kwargs):
        raise RuntimeError("http://ragflow.internal:9380 key=secret")

    monkeypatch.setattr(kb_mod, "upload_prepared_documents", boom)

    async with _client(principals) as client:
        data = await call_tool_data(
            client, WRITE_TOKEN, "kb_document_upload",
            {"dataset_id": "ds-naive", "name": "a.md", "content": "x"},
            endpoint=ENDPOINT,
        )
    assert data["ok"] is False
    assert data["errors"][0]["error"] == "kb_unavailable"
    assert data["errors"][0]["message"] == "知识库服务暂时不可用，请稍后重试。"
    assert "ragflow.internal" not in str(data)


# ============ 修复轮 1: 零提交 / 批量上限 / replaced / ingest_started ============


async def test_upload_zero_created_docs_is_reported_as_failure(
    principals, fake_kb, monkeypatch
):
    """F1: RAGFlow 返回空 data 时核心函数仍 ok=True —— 不能谎报提交成功。"""
    import app.api.kb as kb_mod

    async def empty(dataset_id, prepared, user):
        return {
            "ok": True, "uploaded": 0, "ingest_started": False, "warning": "", "docs": [],
        }

    monkeypatch.setattr(kb_mod, "upload_prepared_documents", empty)

    async with _client(principals) as client:
        data = await call_tool_data(
            client, WRITE_TOKEN, "kb_document_upload",
            {"dataset_id": "ds-naive", "name": "a.md", "content": "x"},
            endpoint=ENDPOINT,
        )
    assert data["ok"] is False
    assert data["state"] == "failed"
    assert data["uploaded"] == 0
    assert data["errors"][0]["error"] == "kb_unavailable"


async def test_update_rejects_batch_over_total_bytes(principals, fake_kb, monkeypatch):
    """F2: 批量更新的文本总量也要挡 8 MB。"""
    from app.mcp.kb import adapter

    first = await fake_kb.upload_documents("ds-naive", [("a.md", b"a", "text/plain")])
    second = await fake_kb.upload_documents("ds-naive", [("b.md", b"b", "text/plain")])
    monkeypatch.setattr(adapter, "MAX_MCP_BATCH_BYTES", 10)

    async with _client(principals) as client:
        result = await call_tool(
            client, WRITE_TOKEN, "kb_document_update",
            {
                "dataset_id": "ds-naive",
                "documents": [
                    {"document_id": first[0]["id"], "content": "abcdef"},
                    {"document_id": second[0]["id"], "content": "abcdef"},
                ],
            },
            endpoint=ENDPOINT,
        )
    assert result["isError"] is True
    text = result["content"][0]["text"]
    assert "8 MB" in text
    assert not fake_kb.patched


async def test_update_missing_document_has_no_replaced_key(principals, fake_kb):
    """F3: 一篇都没替换成功时不该返回 replaced=[]。"""
    async with _client(principals) as client:
        data = await call_tool_data(
            client, WRITE_TOKEN, "kb_document_update",
            {"dataset_id": "ds-naive", "document_id": "nope", "content": "x"},
            endpoint=ENDPOINT,
        )
    assert data["ok"] is False
    assert "replaced" not in data


async def test_docs_carry_per_document_ingest_started(principals, fake_kb):
    """F4: 每篇文档都要带自己的 ingest_started。"""
    async with _client(principals) as client:
        uploaded = await call_tool_data(
            client, WRITE_TOKEN, "kb_document_upload",
            {"dataset_id": "ds-naive", "name": "a.md", "content": "x"},
            endpoint=ENDPOINT,
        )
    assert uploaded["docs"][0]["ingest_started"] is True

    doc_id = uploaded["docs"][0]["document_id"]
    async with _client(principals) as client:
        reparsed = await call_tool_data(
            client, WRITE_TOKEN, "kb_document_reparse",
            {"dataset_id": "ds-naive", "document_id": doc_id},
            endpoint=ENDPOINT,
        )
    assert reparsed["docs"][0]["ingest_started"] is True


async def test_upload_overlong_name_keeps_extension(principals, fake_kb):
    """F5: 名字被截断后仍要保住扩展名 —— 别把 .md 丢了。"""
    name = "a" * 260 + ".md"
    async with _client(principals) as client:
        data = await call_tool_data(
            client, WRITE_TOKEN, "kb_document_upload",
            {"dataset_id": "ds-naive", "name": name, "content": "x"},
            endpoint=ENDPOINT,
        )
    assert data["ok"] is True
    assert data["docs"][0]["name"].endswith(".md")


async def test_reparse_unknown_dataset_reports_dataset_not_found(principals, fake_kb):
    """F6: 未知 dataset 应报「数据集不存在」, 不是「文档不存在」。"""
    async with _client(principals) as client:
        result = await call_tool(
            client, WRITE_TOKEN, "kb_document_reparse",
            {"dataset_id": "missing", "document_id": "doc-1"},
            endpoint=ENDPOINT,
        )
    assert result["isError"] is True
    assert "数据集不存在" in result["content"][0]["text"]


async def test_update_batch_partial_failure(principals, fake_kb):
    """F7-1: 批量更新部分失败 —— 成功的那篇仍要报 replaced。

    失败项能找到旧文档时要带出它的名字 (name 不能一律是 ""); 找不到的文档
    名字确实未知, 仍保持 ""。
    """
    created = await fake_kb.upload_documents("ds-naive", [("a.md", b"a", "text/plain")])
    good_id = created[0]["id"]
    # 假 RAGFlow 不校验扩展名 —— 塞一篇 .pdf 进来, 让 _prepare_text 在找到文档之后才失败
    binary = await fake_kb.upload_documents(
        "ds-naive", [("scan.pdf", b"%PDF", "application/pdf")]
    )
    binary_id = binary[0]["id"]

    async with _client(principals) as client:
        data = await call_tool_data(
            client, WRITE_TOKEN, "kb_document_update",
            {
                "dataset_id": "ds-naive",
                "documents": [
                    {"document_id": good_id, "content": "a2"},
                    {"document_id": binary_id, "content": "b2"},
                    {"document_id": "missing-doc", "content": "c2"},
                ],
            },
            endpoint=ENDPOINT,
        )
    assert data["ok"] is False
    assert data["state"] == "partial"
    assert data["updated"] == 1
    assert data["replaced"] == [good_id]
    failures = {error["document_id"]: error for error in data["errors"]}
    assert failures[binary_id]["error"] == "invalid_document_type"
    assert failures[binary_id]["name"] == "scan.pdf"
    assert failures["missing-doc"]["error"] == "not_found"
    assert failures["missing-doc"]["name"] == ""


async def test_update_rejects_more_than_five_documents(principals, fake_kb):
    """F7-2: documents 超过 5 篇要被挡下, 且调用方能看到 1..5 的说明。

    ⚠️ 传输层第一道闸是 ToolSpec 的 ``maxItems: 5`` (报 "Invalid tool arguments."),
       adapter 自己的 ``_upload_items`` 式检查在 schema 放行后才会走到 —— 两处都断言。
    """
    from app.mcp.common.errors import McpRuntimeError
    from app.mcp.kb import adapter

    items = [{"document_id": f"doc-{index}", "content": "x"} for index in range(6)]
    async with _client(principals) as client:
        result = await call_tool(
            client, WRITE_TOKEN, "kb_document_update",
            {"dataset_id": "ds-naive", "documents": items},
            endpoint=ENDPOINT,
        )
    assert result["isError"] is True

    with pytest.raises(McpRuntimeError) as excinfo:
        await adapter.document_update(None, dataset_id="ds-naive", documents=items)
    assert "1..5" in excinfo.value.message
    assert not fake_kb.patched


def test_write_tool_descriptions_teach_the_tradeoffs():
    """F7-3/4: 描述里必须讲清 id 会变化 / 旧文档被删除 / 用 status 查解析。"""
    from app.mcp.kb.tools import TOOL_SPECS

    descriptions = {spec.name: spec.description for spec in TOOL_SPECS}
    update = descriptions["kb_document_update"]
    assert "document_id" in update
    assert "删除" in update
    assert "kb_document_status" in descriptions["kb_document_upload"]
