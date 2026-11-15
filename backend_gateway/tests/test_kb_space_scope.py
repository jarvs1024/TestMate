"""知识库 REST 按 X-KB-Space 切空间; 审计记录空间维度."""
import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select

from app.api import kb as kb_api
from app.core import ragflow_spaces as rs
from app.core.security import create_kb_upload_ticket, decode_kb_upload_ticket
from app.db.session import AsyncSessionLocal
from app.main import app
from app.models.kb import KbAudit


async def _client(token: str) -> AsyncClient:
    return AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://test",
        headers={"Authorization": f"Bearer {token}"},
    )


async def test_dataset_list_uses_space_header(monkeypatch, admin_user):
    a = await rs.create_space("空间A", "ragflow-aaaa-1111")
    b = await rs.create_space("空间B", "ragflow-bbbb-2222")
    seen: list[str | None] = []

    async def fake_items(page=1, page_size=50, keyword="", space_id=None):
        seen.append(space_id)
        return []

    monkeypatch.setattr(kb_api, "_dataset_items", fake_items)
    async with await _client(admin_user["token"]) as c:
        await c.get("/api/v1/kb/datasets")
        await c.get("/api/v1/kb/datasets", headers={"X-KB-Space": b.id})
    assert seen == [None, b.id]


async def test_unknown_space_returns_chinese_error(admin_user):
    await rs.create_space("空间A", "ragflow-aaaa-1111")
    async with await _client(admin_user["token"]) as c:
        r = await c.get("/api/v1/kb/datasets", headers={"X-KB-Space": "sp_nope"})
    assert r.status_code == 404, r.text
    detail = r.json()["detail"]
    assert "用户空间不存在" in detail
    assert "空间A" in detail, "报错要列出可用空间, 不能只说找不到"


async def test_audit_records_space(admin_user):
    sp = await rs.create_space("空间A", "ragflow-aaaa-1111")
    async with AsyncSessionLocal() as s:
        from app.models.user import User

        user = await s.get(User, admin_user["id"])
    await kb_api._audit(
        action="upload", user=user, dataset_id="d1", space_id=sp.id
    )
    async with AsyncSessionLocal() as s:
        row = (await s.execute(select(KbAudit))).scalars().first()
    assert row.space_id == sp.id
    assert row.space_name == "空间A", "空间名是快照, 不能只存 id"


async def test_audit_filter_by_space(admin_user):
    a = await rs.create_space("空间A", "ragflow-aaaa-1111")
    b = await rs.create_space("空间B", "ragflow-bbbb-2222")
    async with AsyncSessionLocal() as s:
        from app.models.user import User

        user = await s.get(User, admin_user["id"])
    await kb_api._audit(action="upload", user=user, dataset_id="d1", space_id=a.id)
    await kb_api._audit(action="upload", user=user, dataset_id="d2", space_id=b.id)

    async with await _client(admin_user["token"]) as c:
        all_rows = (await c.get("/api/v1/kb/audits")).json()
        only_b = (await c.get("/api/v1/kb/audits", params={"space_id": b.id})).json()

    assert all_rows["total"] == 2
    assert only_b["total"] == 1
    item = only_b["items"][0]
    assert item["space_id"] == b.id and item["space_name"] == "空间B"


async def test_upload_ticket_carries_space(admin_user):
    ticket, _ = create_kb_upload_ticket(
        user_id=admin_user["id"],
        token_version=0,
        dataset_id="ds-1",
        space_id="sp_abc123",
    )
    claims = decode_kb_upload_ticket(ticket)
    assert claims and claims["sid"] == "sp_abc123"


async def test_upload_ticket_without_space_stays_compatible(admin_user):
    ticket, _ = create_kb_upload_ticket(
        user_id=admin_user["id"], token_version=0, dataset_id="ds-1"
    )
    claims = decode_kb_upload_ticket(ticket)
    assert claims and claims["sid"] == ""


async def test_health_probes_current_space(monkeypatch, admin_user):
    b = await rs.create_space("空间B", "ragflow-bbbb-2222")
    seen: list[str | None] = []

    async def fake_probe(space_id=None):
        seen.append(space_id)
        return ("ok", "正常")

    monkeypatch.setattr(kb_api, "probe", fake_probe)
    async with await _client(admin_user["token"]) as c:
        r = await c.get("/api/v1/kb/health", headers={"X-KB-Space": b.id})
    assert r.status_code == 200
    assert seen == [b.id]


@pytest.mark.parametrize("path", ["/api/v1/kb/health", "/api/v1/kb/datasets"])
async def test_non_admin_can_switch_space(path, monkeypatch, stranger_user):
    sp = await rs.create_space("空间A", "ragflow-aaaa-1111")
    seen: list[str | None] = []

    async def fake_probe(space_id=None):
        seen.append(space_id)
        return ("ok", "正常")

    async def fake_items(page=1, page_size=50, keyword="", space_id=None):
        seen.append(space_id)
        return []

    monkeypatch.setattr(kb_api, "probe", fake_probe)
    monkeypatch.setattr(kb_api, "_dataset_items", fake_items)
    async with await _client(stranger_user["token"]) as c:
        r = await c.get(path, headers={"X-KB-Space": sp.id})
    assert r.status_code == 200, r.text
    assert seen == [sp.id], "切换空间所有登录用户可用, 不必是 admin"
