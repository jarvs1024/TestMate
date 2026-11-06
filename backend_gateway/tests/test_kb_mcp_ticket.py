"""上传票: 先验票再读 body、可复用、绑定用户/数据集。"""
from __future__ import annotations

import io

import pytest
from starlette.requests import Request

from app.core.security import create_kb_upload_ticket
from tests.test_kb_update_document import FakeRagflow

API = "/api/v1"


@pytest.fixture
def fake_rf(monkeypatch):
    import app.api.kb as kb_mod

    rf = FakeRagflow()
    for name in (
        "list_datasets", "list_documents", "upload_documents", "delete_documents",
        "update_document", "ingest_documents", "parse_documents",
    ):
        monkeypatch.setattr(kb_mod, name, getattr(rf, name))
    return rf


async def _ticket(user_id, dataset_id="ds-naive", ttl_seconds=1800):
    from app.db.session import AsyncSessionLocal
    from app.models.user import User

    async with AsyncSessionLocal() as s:
        user = await s.get(User, user_id)
        token_version = int(user.token_version or 0)
    token, _ = create_kb_upload_ticket(
        user_id=user_id,
        token_version=token_version,
        dataset_id=dataset_id,
        ttl_seconds=ttl_seconds,
    )
    return token


def _files(*names, content=b"hello"):
    return [("file", (name, io.BytesIO(content), "text/plain")) for name in names]


async def _post(client, ticket, dataset_id="ds-naive", *, files=None, data=None):
    return await client.post(
        f"{API}/kb/datasets/{dataset_id}/documents/ticket-upload",
        files=files if files is not None else _files("a.txt"),
        data=data or {},
        headers={"X-KB-Upload-Ticket": ticket},
    )


async def test_ticket_uploads_and_is_reusable(client, publisher_user, fake_rf):
    ticket = await _ticket(publisher_user["id"])

    first = await _post(client, ticket, files=_files("a.txt"))
    second = await _post(client, ticket, files=_files("b.txt", "c.txt", "d.txt", "e.txt", "f.txt"))

    assert first.status_code == 200, first.text
    assert second.status_code == 200, second.text
    assert first.json()["uploaded"] == 1
    assert second.json()["uploaded"] == 5
    assert len(fake_rf.docs) == 6
    assert fake_rf.ingested


async def test_expired_ticket_can_be_replaced_and_prior_files_survive(client, publisher_user, fake_rf):
    expired = await _ticket(publisher_user["id"], ttl_seconds=-1)
    response = await _post(client, expired)
    assert response.status_code == 401

    fresh = await _ticket(publisher_user["id"])
    ok = await _post(client, fresh)
    assert ok.status_code == 200, ok.text
    assert len(fake_rf.docs) == 1


async def test_ticket_dataset_mismatch_is_forbidden(client, publisher_user, fake_rf):
    ticket = await _ticket(publisher_user["id"], dataset_id="ds-manual")
    response = await _post(client, ticket, dataset_id="ds-naive")
    assert response.status_code == 403


async def test_ticket_rejects_changed_token_version(client, publisher_user, fake_rf):
    from app.db.session import AsyncSessionLocal
    from app.models.user import User

    ticket = await _ticket(publisher_user["id"])
    async with AsyncSessionLocal() as s:
        user = await s.get(User, publisher_user["id"])
        user.token_version = (user.token_version or 0) + 1
        await s.commit()

    response = await _post(client, ticket)
    assert response.status_code == 403


async def test_ticket_rejects_disabled_user(client, publisher_user, fake_rf):
    from app.db.session import AsyncSessionLocal
    from app.models.user import User

    ticket = await _ticket(publisher_user["id"])
    async with AsyncSessionLocal() as s:
        user = await s.get(User, publisher_user["id"])
        user.is_active = False
        await s.commit()

    response = await _post(client, ticket)
    assert response.status_code == 403


async def test_ticket_rejects_viewer(client, stranger_user, fake_rf):
    ticket = await _ticket(stranger_user["id"])
    response = await _post(client, ticket)
    assert response.status_code == 403


async def test_invalid_ticket_is_rejected_before_body_is_read(
    client, publisher_user, monkeypatch
):
    async def _boom(self, *args, **kwargs):
        raise AssertionError("票无效时不应读取 body")

    monkeypatch.setattr(Request, "form", _boom)
    response = await _post(client, "not-a-ticket", files=_files("a.txt"))
    assert response.status_code == 401


async def test_ticket_enforces_per_file_limit(
    client, publisher_user, fake_rf, monkeypatch
):
    import app.api.kb as kb_mod

    monkeypatch.setattr(kb_mod, "MAX_UPLOAD_BYTES", 4)
    response = await _post(
        client, await _ticket(publisher_user["id"]),
        files=_files("big.txt", content=b"12345"),
    )
    assert response.status_code == 413


async def test_ticket_replace_mode_replaces_document(client, publisher_user, fake_rf):
    ticket = await _ticket(publisher_user["id"])
    created = await _post(client, ticket, files=_files("a.txt"))
    old_id = created.json()["docs"][0]["id"]

    replaced = await _post(
        client, ticket, files=_files("a.txt", content=b"new"),
        data={"document_id": old_id},
    )

    assert replaced.status_code == 200, replaced.text
    assert replaced.json()["replaced"]["id"] == old_id
    assert replaced.json()["updated"]["id"] != old_id
    assert fake_rf.ingested[-1] == [replaced.json()["updated"]["id"]]


async def test_ticket_replace_mode_rejects_missing_or_extra_documents(
    client, publisher_user, fake_rf
):
    ticket = await _ticket(publisher_user["id"])
    missing = await _post(
        client, ticket, files=_files("a.txt"), data={"document_id": "nope"}
    )
    assert missing.status_code == 404

    created = await _post(client, ticket, files=_files("a.txt"))
    old_id = created.json()["docs"][0]["id"]
    extra = await _post(
        client, ticket, files=_files("a.txt", "b.txt"), data={"document_id": old_id}
    )
    assert extra.status_code == 422


async def test_ticket_upload_writes_audit_rows(client, publisher_user, fake_rf):
    from sqlalchemy import func, select

    from app.db.session import AsyncSessionLocal
    from app.models.kb import KbAudit

    response = await _post(
        client, await _ticket(publisher_user["id"]), files=_files("a.txt")
    )
    assert response.status_code == 200, response.text

    async with AsyncSessionLocal() as s:
        count = (await s.execute(select(func.count()).select_from(KbAudit))).scalar_one()
        assert count == 1


async def test_missing_ticket_is_rejected_although_body_is_valid(
    client, publisher_user, fake_rf
):
    """没有票头时, 即使 multipart body 完全合法, 也先报票错误 (验票先于解析)."""
    response = await client.post(
        f"{API}/kb/datasets/ds-naive/documents/ticket-upload",
        files=_files("a.txt"),
    )
    assert response.status_code == 401
    assert response.json()["detail"] == "上传票无效或已过期"
    assert fake_rf.docs == []


async def test_non_upload_tokens_are_rejected_as_tickets(client, publisher_user, fake_rf):
    """签名有效但 typ 不是 kb-upload 的票/令牌 → 401 (错 typ)."""
    from app.core.security import (
        create_access_token,
        create_asset_download_ticket,
    )

    access_token, _ = create_access_token(publisher_user["id"])
    asset_ticket, _ = create_asset_download_ticket(
        user_id=publisher_user["id"], code="asset", version="1.0.0"
    )

    for wrong in (access_token, asset_ticket):
        response = await _post(client, wrong)
        assert response.status_code == 401
        assert response.json()["detail"] == "上传票无效或已过期"
    assert fake_rf.docs == []


async def test_ticket_rejects_more_than_five_files(client, publisher_user, fake_rf):
    """超过 MAX_UPLOAD_FILES 的批量 → 解析阶段 422 (通用表单错误)."""
    response = await _post(
        client,
        await _ticket(publisher_user["id"]),
        files=_files("a.txt", "b.txt", "c.txt", "d.txt", "e.txt", "f.txt"),
    )
    assert response.status_code == 422
    assert response.json()["detail"] == "上传表单格式错误"
    assert fake_rf.docs == []
