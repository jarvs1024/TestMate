"""空间管理 API: 权限、掩码."""
import pytest
from httpx import ASGITransport, AsyncClient

from app.core import ragflow_spaces as rs
from app.core.security import create_access_token, hash_password
from app.db.session import AsyncSessionLocal
from app.main import app
from app.models.user import User, UserRole


async def _client(user: User) -> AsyncClient:
    token, _ = create_access_token(
        str(user.id), {"role": user.role.value, "username": user.username}
    )
    return AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://test",
        headers={"Authorization": f"Bearer {token}"},
    )


@pytest.fixture
async def admin():
    async with AsyncSessionLocal() as s:
        u = User(
            username="admin_sp",
            role=UserRole.admin,
            password_hash=hash_password("x"),
        )
        s.add(u)
        await s.commit()
        await s.refresh(u)
        return u


async def test_admin_create_list_and_mask(admin):
    async with await _client(admin) as c:
        r = await c.post(
            "/api/v1/kb/spaces", json={"name": "空间A", "api_key": "ragflow-aaaa-1111"}
        )
        assert r.status_code == 200, r.text
        sid = r.json()["space"]["id"]
        r = await c.get("/api/v1/kb/spaces")
        item = r.json()["items"][0]
        assert item["id"] == sid
        assert "is_default" not in item, "默认空间设置已去掉, 不再暴露默认标记"
        assert item["key_masked"].startswith("ragf")
        assert "aaaa" not in item["key_masked"]


async def test_non_admin_cannot_write(admin):
    await rs.create_space("已存在", "ragflow-aaaa-1111")
    async with AsyncSessionLocal() as s:
        u = User(
            username="viewer_sp",
            role=UserRole.viewer,
            password_hash=hash_password("x"),
        )
        s.add(u)
        await s.commit()
        await s.refresh(u)
    async with await _client(u) as c:
        r = await c.post(
            "/api/v1/kb/spaces", json={"name": "X", "api_key": "ragflow-xxxx-2222"}
        )
        assert r.status_code == 403
        r = await c.get("/api/v1/kb/spaces")
        assert r.status_code == 200
        assert "key_masked" not in r.json()["items"][0]


async def test_delete_any_space(admin):
    async with await _client(admin) as c:
        sid = (
            await c.post(
                "/api/v1/kb/spaces", json={"name": "临时", "api_key": "ragflow-dddd-1111"}
            )
        ).json()["space"]["id"]
        r = await c.delete(f"/api/v1/kb/spaces/{sid}")
        assert r.status_code == 200, r.text
        assert (await c.get("/api/v1/kb/spaces")).json()["items"] == []
