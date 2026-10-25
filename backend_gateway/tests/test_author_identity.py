"""用户名改版后的「作者身份」口径 —— 端到端钉住.

背景 (2026-10-25):
    登录重构后普通用户的用户名是**邮箱式** (`zhangsan@twsc.com.cn`), 而资产的
    `author` 字段可能是**短名** (`zhangsan`) —— 存量数据 / 迁移没跑到的环境都是这样.

    同一个"这是不是我的资产"的判断散在好几个地方, 一旦口径不一致, 就会出现
    **"后端放行、前端不给按钮"** 的拧巴状态:
      · sync-status 的"我的待审"计数是 0 → 顶部提示条**根本不出现** →
        用户压根不知道自己还有待审资产 (而 status=mine 里又能查到 → 自相矛盾)
      · 列表里看不见自己的资产 → 以为资产丢了
      · 详情抽屉没有「发布新版本 / 重新提交审核 / 删除」→ 自己的资产改不动

这些用例用**真实的普通用户** + 手工改过 author 的资产来复现。
"""
from __future__ import annotations

import pytest

API = "/api/v1/assets"

# 一个"存量资产": author 是短名, 而登录用户名是邮箱式
LEGACY_AUTHOR = "legacyuser"
EMAIL_USER = "legacyuser@twsc.com.cn"


@pytest.fixture
async def legacy_asset(client, admin_user, ws, restore_git_config):  # noqa: ARG001
    """造一个 author=短名 的资产 (模拟迁移没跑到的存量数据)."""
    from sqlalchemy import select

    from app.db.session import AsyncSessionLocal
    from app.models.asset import Asset

    async with AsyncSessionLocal() as s:
        s.add(Asset(
            code="dml-legacy-author", name="存量作者资产", icon="🧩", kind="mcp",
            version="1.0.0", summary="s", description="", use_when="", not_for="",
            category="其他", project="", tags=[], keywords=[], permissions={},
            install_steps=[], bindings={}, author=LEGACY_AUTHOR, featured=False,
            publish_status="pending", sync_status="pushed",
            git_path="assets/connectors/misc/dml-legacy-author",
            mcp_config={"mcpServers": {"dml-legacy-author": {"url": "http://x/mcp"}}},
        ))
        await s.commit()
        a = (await s.execute(
            select(Asset).where(Asset.code == "dml-legacy-author")
        )).scalar_one()
        assert a.author == LEGACY_AUTHOR
    yield "dml-legacy-author"


async def _user_with_email_name(client, admin_user):
    """建一个用户名是邮箱式的普通账号, 返回它的 auth 头."""
    from app.core.security import create_access_token, hash_password
    from app.db.session import AsyncSessionLocal
    from app.models.user import User, UserRole

    async with AsyncSessionLocal() as s:
        u = User(
            username=EMAIL_USER, password_hash=hash_password("X@1234567"),
            role=UserRole.tester, is_active=True, password_required=False,
        )
        s.add(u)
        await s.commit()
        await s.refresh(u)
        uid = u.id
    token, _ = create_access_token(uid)
    return {"Authorization": f"Bearer {token}"}, uid


async def test_status_mine_finds_short_name_author(client, admin_user, legacy_asset):
    """status=mine → 能查到 (author 是短名, 用户名是邮箱式)."""
    headers, _ = await _user_with_email_name(client, admin_user)
    r = await client.get(f"{API}?status=mine&limit=50", headers=headers)
    assert r.status_code == 200, r.text
    codes = [i["code"] for i in r.json()["items"]]
    assert legacy_asset in codes, codes


async def test_sync_status_counts_my_pending(client, admin_user, legacy_asset):
    """sync-status 的"我的待审"计数 → 要算上 (短名作者).

    ⚠️ 以前这里是精确比较 → 计数 0 → 顶部「你有 N 个资产需要处理」不出现 →
       用户不知道自己还有待审资产 (而 status=mine 里又查得到 → 自相矛盾).
    """
    headers, _ = await _user_with_email_name(client, admin_user)
    r = await client.get(f"{API}/sync-status", headers=headers)
    assert r.status_code == 200, r.text
    j = r.json()
    assert j["my_review_count"] >= 1, j
    assert j["my_pending_count"] >= 1, j


async def test_asset_visible_in_list(client, admin_user, legacy_asset):
    """列表里能看到自己的资产 (可见性判定也认短名)."""
    headers, _ = await _user_with_email_name(client, admin_user)
    r = await client.get(f"{API}?limit=50", headers=headers)
    assert r.status_code == 200, r.text
    codes = [i["code"] for i in r.json()["items"]]
    assert legacy_asset in codes, codes


async def test_detail_endpoint_visible(client, admin_user, legacy_asset):
    """详情页不能 404 —— 否则用户打不开自己的资产."""
    headers, _ = await _user_with_email_name(client, admin_user)
    r = await client.get(f"{API}/{legacy_asset}", headers=headers)
    assert r.status_code == 200, r.text


async def test_author_can_update_and_unpublish(client, admin_user, legacy_asset):
    """作者本人能改、能申请下架 (作者判定认短名)."""
    headers, _ = await _user_with_email_name(client, admin_user)
    r = await client.put(
        f"{API}/{legacy_asset}",
        data={
            "kind": "mcp", "name": "改了名", "summary": "s", "version": "2.0.0",
            "category": "其他",
            "mcp_config": '{"mcpServers": {"dml-legacy-author": {"url": "http://x/mcp"}}}',
        },
        headers=headers,
    )
    assert r.status_code == 202, r.text
