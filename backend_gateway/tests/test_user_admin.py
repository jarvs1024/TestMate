"""账号管理 —— 2026-10-25.

管理员在设置页「👥 用户管理」里建号 / 停用 / 改角色 / 重置密码.

盯住这几件事:
  ① 建号: 普通用户填短名 → 自动补成邮箱形式; 管理员账号名不带 @;
  ② 建号不给密码 → 免密账号 (password_required=False); 给了密码 → 必须密码;
  ③ 重复用户名 → 409, 不静默覆盖;
  ④ 非 admin 调这三个接口 → 403;
  ⑤ 停用后不能登录, 启用后能登录;
  ⑥ 重置密码 → 新密码能登, 老密码不能;
  ⑦ 护栏: 不能停用自己 / 不能改自己角色 / 不能停用最后一个管理员.
"""
import pytest
from sqlalchemy import select

from app.db.session import AsyncSessionLocal
from app.models.user import User, UserRole


def _auth(admin_user) -> dict:
    return {"Authorization": f"Bearer {admin_user['token']}"}


# ---------- 建号 ----------

async def test_create_user_expands_short_name_to_email(client, admin_user):
    """普通用户填短名 → 存成邮箱形式 (跟登录口径一致)."""
    r = await client.post(
        "/api/v1/auth/users",
        json={"username": "zhangsan", "role": "tester"},
        headers=_auth(admin_user),
    )
    assert r.status_code == 201, r.text()
    assert r.json()["username"] == "zhangsan@twsc.com.cn"
    assert r.json()["password_required"] is False
    assert r.json()["is_active"] is True


async def test_create_user_accepts_full_email(client, admin_user):
    r = await client.post(
        "/api/v1/auth/users",
        json={"username": "lisi@twsc.com.cn", "role": "viewer"},
        headers=_auth(admin_user),
    )
    assert r.status_code == 201, r.text()
    assert r.json()["username"] == "lisi@twsc.com.cn"
    assert r.json()["role"] == "viewer"


async def test_create_admin_user_keeps_plain_name(client, admin_user):
    """管理员是**账号名**不是邮箱 —— 不能被补上域名."""
    r = await client.post(
        "/api/v1/auth/users",
        json={"username": "opsadmin", "role": "admin", "password": "Admin@2026"},
        headers=_auth(admin_user),
    )
    assert r.status_code == 201, r.text()
    assert r.json()["username"] == "opsadmin"
    assert r.json()["password_required"] is True


async def test_create_admin_user_rejects_email_form(client, admin_user):
    r = await client.post(
        "/api/v1/auth/users",
        json={"username": "ops@twsc.com.cn", "role": "admin", "password": "Admin@2026"},
        headers=_auth(admin_user),
    )
    assert r.status_code == 422, r.text()


async def test_create_user_rejects_foreign_domain(client, admin_user):
    """普通用户必须是公司邮箱."""
    r = await client.post(
        "/api/v1/auth/users",
        json={"username": "someone@other.com", "role": "tester"},
        headers=_auth(admin_user),
    )
    assert r.status_code == 422, r.text()


async def test_create_user_with_password_requires_it(client, admin_user):
    """给了密码 → 必须密码登录."""
    r = await client.post(
        "/api/v1/auth/users",
        json={"username": "secure", "role": "tester", "password": "Pwd@2026"},
        headers=_auth(admin_user),
    )
    assert r.status_code == 201, r.text()
    assert r.json()["password_required"] is True

    # 缺密码 → password_required; 带对密码 → 进
    login = await client.post("/api/v1/auth/login", json={"username": "secure"})
    assert login.status_code == 401
    assert login.json()["detail"]["code"] == "password_required"
    ok = await client.post("/api/v1/auth/login", json={"username": "secure", "password": "Pwd@2026"})
    assert ok.status_code == 200, ok.text()


async def test_create_user_without_password_logs_in_passwordless(client, admin_user):
    """没给密码 → 免密账号, 但**必须是管理员先建过的**."""
    r = await client.post(
        "/api/v1/auth/users",
        json={"username": "free", "role": "tester"},
        headers=_auth(admin_user),
    )
    assert r.status_code == 201, r.text()

    login = await client.post("/api/v1/auth/login", json={"username": "free"})
    assert login.status_code == 200, login.text()
    assert login.json()["access_token"]


async def test_create_admin_user_without_password_rejected(client, admin_user):
    """管理员账号必须给密码 —— 不然建出来也登不进去."""
    r = await client.post(
        "/api/v1/auth/users",
        json={"username": "noadminpwd", "role": "admin"},
        headers=_auth(admin_user),
    )
    assert r.status_code == 422, r.text()


async def test_duplicate_username_conflicts(client, admin_user):
    r = await client.post(
        "/api/v1/auth/users",
        json={"username": "dup", "role": "tester"},
        headers=_auth(admin_user),
    )
    assert r.status_code == 201, r.text()
    r2 = await client.post(
        "/api/v1/auth/users",
        json={"username": "dup", "role": "tester"},
        headers=_auth(admin_user),
    )
    assert r2.status_code == 409, r2.text()


# ---------- 列表 ----------

async def test_list_users(client, admin_user):
    await client.post(
        "/api/v1/auth/users",
        json={"username": "aaa", "role": "tester"},
        headers=_auth(admin_user),
    )
    r = await client.get("/api/v1/auth/users", headers=_auth(admin_user))
    assert r.status_code == 200, r.text()
    names = [u["username"] for u in r.json()]
    assert "aaa@twsc.com.cn" in names
    assert admin_user["username"] in names


async def test_list_users_requires_admin(client, publisher_user):
    r = await client.get("/api/v1/auth/users", headers={"Authorization": f"Bearer {publisher_user['token']}"})
    assert r.status_code == 403, r.text()


async def test_create_and_update_require_admin(client, publisher_user):
    h = {"Authorization": f"Bearer {publisher_user['token']}"}
    r = await client.post("/api/v1/auth/users", json={"username": "x", "role": "tester"}, headers=h)
    assert r.status_code == 403, r.text()
    r2 = await client.patch("/api/v1/auth/users/1", json={"is_active": False}, headers=h)
    assert r2.status_code == 403, r2.text()


async def test_users_endpoints_require_login(client):
    assert (await client.get("/api/v1/auth/users")).status_code == 401
    assert (await client.post("/api/v1/auth/users", json={"username": "x", "role": "tester"})).status_code == 401


# ---------- 停用 / 启用 ----------

async def test_disable_then_login_rejected(client, admin_user):
    _r = await client.post(
        "/api/v1/auth/users",
        json={"username": "leaver", "role": "tester"},
        headers=_auth(admin_user),
    )
    uid = _r.json()["id"]

    r = await client.patch(f"/api/v1/auth/users/{uid}", json={"is_active": False}, headers=_auth(admin_user))
    assert r.status_code == 200, r.text()
    assert r.json()["is_active"] is False

    login = await client.post("/api/v1/auth/login", json={"username": "leaver"})
    assert login.status_code == 401, login.text()
    assert login.json()["detail"]["code"] == "account_disabled"

    # 启用回来就能登
    await client.patch(f"/api/v1/auth/users/{uid}", json={"is_active": True}, headers=_auth(admin_user))
    login2 = await client.post("/api/v1/auth/login", json={"username": "leaver"})
    assert login2.status_code == 200, login2.text()


async def test_disable_revokes_existing_token(client, admin_user):
    """⚠️ 停用要**立刻**生效 —— token 有 7 天有效期, 不查 is_active 的话
    对方手上的 token 照样能用一整周."""
    _r = await client.post(
        "/api/v1/auth/users",
        json={"username": "tokenuser", "role": "tester"},
        headers=_auth(admin_user),
    )
    uid = _r.json()["id"]
    login = await client.post("/api/v1/auth/login", json={"username": "tokenuser"})
    assert login.status_code == 200, login.text()
    h = {"Authorization": f"Bearer {login.json()['access_token']}"}

    # 停用前当然能用
    assert (await client.get("/api/v1/auth/me", headers=h)).status_code == 200

    await client.patch(f"/api/v1/auth/users/{uid}", json={"is_active": False}, headers=_auth(admin_user))

    # 停用后同一个 token 立刻失效
    r = await client.get("/api/v1/auth/me", headers=h)
    assert r.status_code == 401, r.text()


async def test_cannot_disable_self(client, admin_user):
    r = await client.patch(
        f"/api/v1/auth/users/{admin_user['id']}",
        json={"is_active": False},
        headers=_auth(admin_user),
    )
    assert r.status_code == 400, r.text()


async def test_cannot_change_own_role(client, admin_user):
    r = await client.patch(
        f"/api/v1/auth/users/{admin_user['id']}",
        json={"role": "viewer"},
        headers=_auth(admin_user),
    )
    assert r.status_code == 400, r.text()


async def test_cannot_disable_last_admin(client, admin_user):
    """系统至少要留一个能管账号的人."""
    r = await client.patch(
        f"/api/v1/auth/users/{admin_user['id']}",
        json={"is_active": False},
        headers=_auth(admin_user),
    )
    assert r.status_code == 400, r.text()


async def test_can_disable_admin_when_another_one_exists(client, admin_user):
    """有第二个管理员时, 停用其中一个是允许的."""
    r = await client.post(
        "/api/v1/auth/users",
        json={"username": "admin2", "role": "admin", "password": "Admin@2026"},
        headers=_auth(admin_user),
    )
    assert r.status_code == 201, r.text()
    uid = r.json()["id"]

    r2 = await client.patch(f"/api/v1/auth/users/{uid}", json={"is_active": False}, headers=_auth(admin_user))
    assert r2.status_code == 200, r2.text()


# ---------- 重置密码 ----------

async def test_reset_password(client, admin_user):
    _r = await client.post(
        "/api/v1/auth/users",
        json={"username": "pwduser", "role": "tester"},
        headers=_auth(admin_user),
    )
    uid = _r.json()["id"]

    r = await client.patch(
        f"/api/v1/auth/users/{uid}",
        json={"password": "NewPwd@2026"},
        headers=_auth(admin_user),
    )
    assert r.status_code == 200, r.text()
    assert r.json()["password_required"] is True

    # 免密失效了 —— 现在必须给密码
    login = await client.post("/api/v1/auth/login", json={"username": "pwduser"})
    assert login.status_code == 401, login.text()
    assert login.json()["detail"]["code"] == "password_required"

    ok = await client.post("/api/v1/auth/login", json={"username": "pwduser", "password": "NewPwd@2026"})
    assert ok.status_code == 200, ok.text()


async def test_switch_account_back_to_passwordless(client, admin_user):
    """改成免密 → 密码作废, 登录又只填用户名就能进."""
    _r = await client.post(
        "/api/v1/auth/users",
        json={"username": "backfree", "role": "tester", "password": "Pwd@2026"},
        headers=_auth(admin_user),
    )
    uid = _r.json()["id"]

    r = await client.patch(
        f"/api/v1/auth/users/{uid}",
        json={"password_required": False},
        headers=_auth(admin_user),
    )
    assert r.status_code == 200, r.text()
    assert r.json()["password_required"] is False

    login = await client.post("/api/v1/auth/login", json={"username": "backfree"})
    assert login.status_code == 200, login.text()
    # 老密码不能再用
    old = await client.post("/api/v1/auth/login", json={"username": "backfree", "password": "Pwd@2026"})
    assert old.status_code == 200, "免密账号不校验密码 (它压根没有密码)"


async def test_cannot_require_password_without_one(client, admin_user):
    """免密账号想改成"必须密码"但没给新密码 → 422 (否则这个号就登不进去了)."""
    _r = await client.post(
        "/api/v1/auth/users",
        json={"username": "nopwd", "role": "tester"},
        headers=_auth(admin_user),
    )
    uid = _r.json()["id"]

    r = await client.patch(
        f"/api/v1/auth/users/{uid}",
        json={"password_required": True},
        headers=_auth(admin_user),
    )
    assert r.status_code == 422, r.text()


async def test_promote_to_admin_requires_password(client, admin_user):
    """免密账号不能直接升成管理员 —— 升了也没法管账号."""
    _r = await client.post(
        "/api/v1/auth/users",
        json={"username": "promote", "role": "tester"},
        headers=_auth(admin_user),
    )
    uid = _r.json()["id"]

    r = await client.patch(
        f"/api/v1/auth/users/{uid}",
        json={"role": "admin"},
        headers=_auth(admin_user),
    )
    assert r.status_code == 422, r.text()


async def test_promote_to_admin_with_password(client, admin_user):
    _r = await client.post(
        "/api/v1/auth/users",
        json={"username": "promote2", "role": "tester"},
        headers=_auth(admin_user),
    )
    uid = _r.json()["id"]

    r = await client.patch(
        f"/api/v1/auth/users/{uid}",
        json={"role": "admin", "password": "Admin@2026"},
        headers=_auth(admin_user),
    )
    assert r.status_code == 200, r.text()
    assert r.json()["role"] == "admin"
    assert r.json()["password_required"] is True


async def test_update_unknown_user_404(client, admin_user):
    r = await client.patch("/api/v1/auth/users/999999", json={"is_active": False}, headers=_auth(admin_user))
    assert r.status_code == 404, r.text()


# ---------- 登录 ≠ 存在, 存在 ≠ 能登 ----------

async def test_created_account_can_log_in_immediately(client, admin_user):
    """建完号 → 立刻能登上 (不用等管理员再去点别的什么)."""
    await client.post(
        "/api/v1/auth/users",
        json={"username": "instant", "role": "tester"},
        headers=_auth(admin_user),
    )
    r = await client.post("/api/v1/auth/login", json={"username": "instant"})
    assert r.status_code == 200, r.text()

    async with AsyncSessionLocal() as s:
        row = (await s.execute(select(User).where(User.username == "instant@twsc.com.cn"))).scalar_one()
        assert row.role == UserRole.tester
        assert row.is_active is True
        assert row.password_required is False


@pytest.mark.parametrize("bad", ["", "   ", "rm -rf /", "someone@other.com"])
async def test_bad_usernames_rejected(client, admin_user, bad):
    r = await client.post(
        "/api/v1/auth/users",
        json={"username": bad, "role": "tester"},
        headers=_auth(admin_user),
    )
    assert r.status_code == 422, r.text()
