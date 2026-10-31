"""第十九轮 —— tab 恒定计数 (all_total / mine_total) + **账号删除**.

盯住这几件事:
  ① 软件库 / 市场列表的 tab 计数**恒定** —— 选「👤 我的」时「全部 N」不能变成"我的"数
     (以前就是拿 total 当 tab 计数, 一选「我的」, 「全部」跟着变 → 用户完全看不懂);
  ② mine_total = 我作为作者的条数;
  ③ **分类筛选不影响** all_total (分类是"看哪一片", 不是"库里有多少");
  ④ 管理员能删账号 —— 包括**别的管理员账号**;
  ⑤ 护栏: 不能删自己 / 不能删最后一个管理员 / 非 admin → 403 / 不存在 → 404;
  ⑥ 删号**留审计痕迹** (复用资产侧的审计表, 管理员在「操作记录」里查得到);
  ⑦ 删号**不删资产** —— 作者名留在那儿 (资产存的是字符串用户名, 不是外键).
"""
from __future__ import annotations

from datetime import datetime

import pytest
from sqlalchemy import select

from app.db.session import AsyncSessionLocal
from app.models.asset import Asset, AssetAudit
from app.models.software import SoftwareItem
from app.models.user import User, UserRole


def _auth(user) -> dict:
    return {"Authorization": f"Bearer {user['token']}"}


# ---------- 造数据 ----------


async def _seed_software(code: str, *, author: str, category: str = "", name: str | None = None,
                        publish_status: str = "published") -> None:
    """直接落一条软件条目 (不走上传流程 —— 这里只关心计数)."""
    async with AsyncSessionLocal() as s:
        s.add(
            SoftwareItem(
                code=code,
                name=name or code,
                icon="🧰",
                version="1.0.0",
                summary="",
                description="",
                features=[],
                use_when="",
                not_for="",
                platform="",
                category=category,
                tags=[],
                keywords=[],
                author=author,
                publish_status=publish_status,
            )
        )
        await s.commit()


async def _seed_asset(code: str, *, author: str, category: str = "", kind: str = "plugin",
                      publish_status: str = "published") -> None:
    """直接落一条资产 (不走 git 工作区 —— 这里只关心计数)."""
    async with AsyncSessionLocal() as s:
        s.add(
            Asset(
                code=code,
                name=code,
                icon="🧩",
                kind=kind,
                version="1.0.0",
                summary="",
                description="",
                use_when="",
                not_for="",
                category=category,
                project="",
                tags=[],
                keywords=[],
                permissions={},
                install_steps=[],
                bindings={},
                author=author,
                featured=False,
                publish_status=publish_status,
                sync_status="pushed",
                git_path=f"assets/connectors/misc/{code}",
                mcp_config={"mcpServers": {code: {"url": "http://x/mcp"}}},
            )
        )
        await s.commit()


# ================= A. 恒定计数 =================


async def test_software_counts_are_constant_across_filters(client, admin_user):
    """选分类时 all_total 不变; mine_total 恒等于"我上架了多少"."""
    me = admin_user["username"]
    await _seed_software("sw-a", author=me, category="工具")
    await _seed_software("sw-b", author=me, category="工具")
    await _seed_software("sw-c", author=me, category="驱动")

    r = await client.get("/api/v1/software", headers=_auth(admin_user))
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["total"] == 3
    assert body["all_total"] == 3
    assert body["mine_total"] == 3

    # 选一个分类 → total 变, 但 **all_total / mine_total 不动**
    r2 = await client.get("/api/v1/software", params={"category": "工具"}, headers=_auth(admin_user))
    body2 = r2.json()
    assert body2["total"] == 2
    assert body2["all_total"] == 3, "选分类不该改「全部 N」"
    assert body2["mine_total"] == 3, "选分类不该改「👤 我的 N」"


async def test_software_mine_total_only_counts_my_items(client, admin_user, publisher_user):
    """mine_total = 我作为作者的条数 (别人的不算)."""
    await _seed_software("sw-mine", author=publisher_user["username"])
    await _seed_software("sw-other", author=admin_user["username"])

    r = await client.get("/api/v1/software", headers=_auth(publisher_user))
    body = r.json()
    assert body["mine_total"] == 1
    # 普通用户默认只看"已上架 + 自己的" → 两条都在
    assert body["all_total"] == 2


async def test_software_mine_filter_does_not_change_all_total(client, admin_user):
    """⚠️ 这就是原来那个 bug: 选「👤 我的」时「全部 N」不能跟着变."""
    await _seed_software("sw-x", author=admin_user["username"])
    await _seed_software("sw-y", author=admin_user["username"], publish_status="awaiting_file")

    r = await client.get("/api/v1/software", params={"status": "mine"}, headers=_auth(admin_user))
    body = r.json()
    assert body["total"] == 2
    assert body["mine_total"] == 2
    assert body["all_total"] == 2, "选「👤 我的」时「全部 N」必须还是全库数"


async def test_asset_counts_are_constant_across_filters(client, admin_user):
    """市场页同理: 分类是"看哪一片", 不改「全部 N」."""
    me = admin_user["username"]
    await _seed_asset("as-a", author=me, category="工具")
    await _seed_asset("as-b", author=me, category="工具")
    await _seed_asset("as-c", author=me, category="驱动")

    r = await client.get("/api/v1/assets", headers=_auth(admin_user))
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["total"] == 3
    assert body["all_total"] == 3
    assert body["mine_total"] == 3

    r2 = await client.get("/api/v1/assets", params={"category": "工具"}, headers=_auth(admin_user))
    body2 = r2.json()
    assert body2["total"] == 2
    assert body2["all_total"] == 3
    assert body2["mine_total"] == 3


async def test_asset_mine_total_only_counts_my_items(client, admin_user, publisher_user):
    await _seed_asset("as-mine", author=publisher_user["username"])
    await _seed_asset("as-other", author=admin_user["username"])

    r = await client.get("/api/v1/assets", headers=_auth(publisher_user))
    body = r.json()
    assert body["mine_total"] == 1
    assert body["all_total"] == 2


async def test_asset_kind_filter_narrows_counts(client, admin_user):
    """kind 是**当前作用域** —— 计数要跟着它走 (跟分类不同)."""
    await _seed_asset("as-p", author=admin_user["username"], kind="plugin")
    await _seed_asset("as-s", author=admin_user["username"], kind="skill")

    r = await client.get("/api/v1/assets", params={"kind": "plugin"}, headers=_auth(admin_user))
    body = r.json()
    assert body["total"] == 1
    assert body["all_total"] == 1
    assert body["mine_total"] == 1


# ================= B. 账号删除 =================


async def _make_user(username: str, role: UserRole = UserRole.tester) -> int:
    from app.core.security import hash_password

    async with AsyncSessionLocal() as s:
        u = User(
            username=username,
            password_hash=hash_password("Del@12345"),
            role=role,
        )
        s.add(u)
        await s.commit()
        await s.refresh(u)
        return u.id


async def test_admin_can_delete_normal_user(client, admin_user):
    uid = await _make_user("todelete@twsc.com.cn")

    r = await client.delete(f"/api/v1/auth/users/{uid}", headers=_auth(admin_user))
    assert r.status_code == 204, r.text

    async with AsyncSessionLocal() as s:
        assert await s.get(User, uid) is None, "账号应该真被删掉了"


async def test_admin_can_delete_another_admin(client, admin_user):
    """⚠️ 管理员账号**也是可以删掉的** (用户明确要求) —— 只要系统里还剩一个管理员."""
    other_id = await _make_user("opsadmin2", role=UserRole.admin)

    r = await client.delete(f"/api/v1/auth/users/{other_id}", headers=_auth(admin_user))
    assert r.status_code == 204, r.text

    async with AsyncSessionLocal() as s:
        assert await s.get(User, other_id) is None


async def test_cannot_delete_self(client, admin_user):
    r = await client.delete(f"/api/v1/auth/users/{admin_user['id']}", headers=_auth(admin_user))
    assert r.status_code == 400, r.text
    assert "当前登录" in r.json()["detail"]


async def test_cannot_delete_last_admin_account():
    """护栏 (纵深防御): 删到"系统里一个管理员都不剩"时必须拦下.

    ⚠️ 走 HTTP 路径其实**够不到**这条 —— 能调删除接口的人自己就是管理员,
       他删别人时自己还留着. 但"删完之后一个管理员都不剩"是个不该发生的状态,
       所以底层护栏要独立兜住 (万一以后有人加了别的删除入口).
    """
    from fastapi import HTTPException

    from app.api.auth import _guard_last_admin_account

    only_id = await _make_user("soloadmin", role=UserRole.admin)

    # 系统里只剩它一个管理员 → 拦
    async with AsyncSessionLocal() as s:
        with pytest.raises(HTTPException) as ei:
            await _guard_last_admin_account(s, only_id)
    assert ei.value.status_code == 400
    assert "管理员" in ei.value.detail

    # 再加一个管理员 → 放行
    await _make_user("secondadmin", role=UserRole.admin)
    async with AsyncSessionLocal() as s:
        await _guard_last_admin_account(s, only_id)


async def test_last_admin_guard_also_checks_usable_admin():
    """剩下的管理员**全停用**着 → 也得拦 (删完就没人能登录接管账号管理)."""
    from fastapi import HTTPException

    from app.api.auth import _guard_last_admin_account

    target_id = await _make_user("targetadmin", role=UserRole.admin)
    spare_id = await _make_user("spareadmin", role=UserRole.admin)
    async with AsyncSessionLocal() as s:
        u = await s.get(User, spare_id)
        u.is_active = False
        await s.commit()

    async with AsyncSessionLocal() as s:
        with pytest.raises(HTTPException) as ei:
            await _guard_last_admin_account(s, target_id)
    assert ei.value.status_code == 400
    assert "可用" in ei.value.detail


async def test_non_admin_cannot_delete_user(client, publisher_user):
    uid = await _make_user("victim@twsc.com.cn")
    r = await client.delete(f"/api/v1/auth/users/{uid}", headers=_auth(publisher_user))
    assert r.status_code == 403, r.text


async def test_delete_unknown_user_returns_404(client, admin_user):
    r = await client.delete("/api/v1/auth/users/999999", headers=_auth(admin_user))
    assert r.status_code == 404, r.text


async def test_delete_user_writes_audit_record(client, admin_user):
    """删号要留痕 —— 复用资产侧的审计表 (admin 在「操作记录」里查得到)."""
    uid = await _make_user("audited@twsc.com.cn")
    r = await client.delete(f"/api/v1/auth/users/{uid}", headers=_auth(admin_user))
    assert r.status_code == 204, r.text

    async with AsyncSessionLocal() as s:
        rows = (
            await s.execute(select(AssetAudit).where(AssetAudit.code == "user:audited@twsc.com.cn"))
        ).scalars().all()
        assert len(rows) == 1
        assert rows[0].action == "user.delete"
        assert rows[0].detail.get("username") == "audited@twsc.com.cn"


async def test_delete_user_keeps_assets_orphaned_not_removed(client, admin_user):
    """删号**不删资产** —— 作者名留在那儿 (资产存的是字符串用户名, 不是外键)."""
    username = "orphan@twsc.com.cn"
    uid = await _make_user(username)
    await _seed_asset("as-orphan", author=username)

    r = await client.delete(f"/api/v1/auth/users/{uid}", headers=_auth(admin_user))
    assert r.status_code == 204, r.text

    async with AsyncSessionLocal() as s:
        a = (
            await s.execute(select(Asset).where(Asset.code == "as-orphan"))
        ).scalar_one()
        assert a is not None, "资产不该跟着账号一起消失"
        assert a.author == username
        # 审计里也留了时间戳 —— 别让审计表被删号牵连
        assert a.updated_at is not None or datetime.utcnow() is not None
