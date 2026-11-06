"""知识库核心函数: 数据集分页 / 关键词过滤 / 替换返回值。"""
from __future__ import annotations

import pytest

from tests.test_kb_update_document import FakeRagflow


class _PaginatedFake(FakeRagflow):
    async def list_datasets(self, page=1, page_size=50):
        items = list(self.datasets.values())
        start = (page - 1) * page_size
        return items[start:start + page_size]


@pytest.fixture
def fake_rf(monkeypatch):
    import app.api.kb as kb_mod

    rf = _PaginatedFake()
    for name in (
        "list_datasets", "list_documents", "upload_documents", "delete_documents",
        "update_document", "ingest_documents", "parse_documents",
    ):
        monkeypatch.setattr(kb_mod, name, getattr(rf, name))
    return rf


async def test_dataset_items_paginates(fake_rf):
    import app.api.kb as kb_mod

    fake_rf.datasets["ds-third"] = {
        "id": "ds-third", "name": "第三库", "description": "",
        "chunk_method": "naive", "embedding_model": "emb",
        "permission": "me", "document_count": 0, "chunk_count": 0,
    }

    first = await kb_mod._dataset_items(page=1, page_size=2)
    second = await kb_mod._dataset_items(page=2, page_size=2)

    assert len(first) == 2
    assert len(second) == 1
    assert {item["id"] for item in first + second} == {
        "ds-naive", "ds-manual", "ds-third"
    }


async def test_dataset_items_filters_by_name_or_description(fake_rf):
    import app.api.kb as kb_mod

    items = await kb_mod._dataset_items(page=1, page_size=50, keyword="协议")
    assert [item["id"] for item in items] == ["ds-manual"]
    assert items[0]["description"] == ""


async def test_replace_document_returns_submit_time_run(fake_rf):
    import app.api.kb as kb_mod
    from app.models.user import User, UserRole

    user = User(username="kb-core", password_hash="unused", role=UserRole.tester)
    created = await fake_rf.upload_documents(
        "ds-naive", [("a.txt", b"old", "text/plain")]
    )
    old_id = created[0]["id"]

    result = await kb_mod.replace_document(
        "ds-naive", old_id, "a.txt", b"new", "text/plain", user
    )

    assert result["ok"] is True
    assert result["updated"]["id"] != old_id
    assert result["updated"]["name"] == "a.txt"
    assert result["updated"]["run"] == "UNSTART"
    assert result["replaced"]["id"] == old_id
