"""MCP: space_id 透传、kb_space_list 与未知空间的中文报错."""
import pytest
from fastapi import HTTPException

from app.core import ragflow_spaces as rs
from app.mcp.common.errors import McpRuntimeError
from app.mcp.kb import adapter
from app.mcp.kb.tools import TOOL_SPECS


def test_all_kb_tools_accept_space_id():
    for spec in TOOL_SPECS:
        if spec.name == "kb_space_list":
            continue
        props = spec.input_schema["properties"]
        assert "space_id" in props, spec.name
        assert "space_id" not in spec.input_schema["required"], spec.name
        assert props["space_id"]["default"] == "", spec.name


@pytest.mark.asyncio
async def test_space_list_returns_spaces():
    await rs.create_space("空间A", "ragflow-aaaa-1111")
    result = await adapter.space_list(None)
    assert result["items"][0]["name"] == "空间A"
    assert result["default_id"].startswith("sp_")


@pytest.mark.asyncio
async def test_dataset_list_passes_space(monkeypatch):
    sp = await rs.create_space("空间A", "ragflow-aaaa-1111")
    seen: dict[str, str | None] = {}

    async def fake_items(page=1, page_size=50, keyword="", space_id=None):
        seen["space_id"] = space_id
        return []

    monkeypatch.setattr(adapter.kb, "_dataset_items", fake_items)
    result = await adapter.dataset_list(None, space_id=sp.id)
    assert seen["space_id"] == sp.id
    assert result["space_id"] == sp.id
    assert result["space_name"] == "空间A"


@pytest.mark.asyncio
async def test_empty_space_means_default(monkeypatch):
    await rs.create_space("空间A", "ragflow-aaaa-1111")
    seen: dict[str, str | None] = {"space_id": "unset"}

    async def fake_items(page=1, page_size=50, keyword="", space_id=None):
        seen["space_id"] = space_id
        return []

    monkeypatch.setattr(adapter.kb, "_dataset_items", fake_items)
    result = await adapter.dataset_list(None)
    assert seen["space_id"] is None, "空 space_id 要落到默认空间"
    assert result["space_id"] == "" and result["space_name"] == ""


@pytest.mark.asyncio
async def test_unknown_space_is_invalid_arguments(monkeypatch):
    await rs.create_space("空间A", "ragflow-aaaa-1111")

    async def fake_items(page=1, page_size=50, keyword="", space_id=None):
        return []

    monkeypatch.setattr(adapter.kb, "_dataset_items", fake_items)
    with pytest.raises(McpRuntimeError) as exc:
        await adapter.dataset_list(None, space_id="sp_nope")
    assert exc.value.code == "invalid_arguments"
    assert "用户空间不存在" in exc.value.message
    assert "空间A" in exc.value.message, "报错要列出可选空间, 便于调用方改参数"


@pytest.mark.asyncio
async def test_unknown_space_fails_before_touching_ragflow(monkeypatch):
    """未知空间必须在**调用业务函数之前**就报中文错误.

    ⚠️ kb 的 REST 包装层把底层异常统一转成 502, 到了 adapter 只剩
       「知识库服务暂时不可用」—— 用户看不出是自己传错了 space_id.
       所以 adapter 先 resolve 再动手, 这条用例守住顺序.
    """
    await rs.create_space("空间A", "ragflow-aaaa-1111")
    called = {"n": 0}

    async def fake_items(page=1, page_size=50, keyword="", space_id=None):
        called["n"] += 1
        raise HTTPException(status_code=502, detail="ragflow error: boom")

    monkeypatch.setattr(adapter.kb, "_dataset_items", fake_items)
    with pytest.raises(McpRuntimeError) as exc:
        await adapter.dataset_list(None, space_id="sp_nope")
    assert exc.value.code == "invalid_arguments"
    assert "用户空间不存在" in exc.value.message
    assert called["n"] == 0, "未知空间不该走到 RAGFlow 调用"


@pytest.mark.asyncio
async def test_write_tool_carries_space(monkeypatch):
    sp = await rs.create_space("空间A", "ragflow-aaaa-1111")

    async def fake_items(page=1, page_size=50, keyword="", space_id=None):
        return [{"id": "ds-1", "name": "库", "chunk_method": "naive"}]

    async def fake_upload(dataset_id, prepared, user, space_id=None):
        assert space_id == sp.id
        return {
            "ok": True,
            "uploaded": 1,
            "ingest_started": True,
            "docs": [{"id": "doc-1", "name": "a.md", "run": "UNSTART", "size": 1}],
        }

    monkeypatch.setattr(adapter.kb, "_dataset_items", fake_items)
    monkeypatch.setattr(adapter.kb, "upload_prepared_documents", fake_upload)
    ctx = type("Ctx", (), {"principal": type("P", (), {"user": object()})()})()
    result = await adapter.document_upload(
        ctx, dataset_id="ds-1", name="a.md", content="x", space_id=sp.id
    )
    assert result["space_id"] == sp.id
    assert result["space_name"] == "空间A"
