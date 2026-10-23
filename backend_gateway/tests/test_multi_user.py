"""多用户场景的权限边界.

背景: 市场是**多人共享**的仓库. 之前的写操作只查"是不是发布者"(白名单),
于是**任何在白名单里的用户都能下架/删除/更新别人的资产** —— 越权.

这里锁住三条边界:
  1. 改资产 (更新版本/下架/彻底删除) 只有**作者本人**或**管理员**能做
  2. 审核 (通过/驳回) 管理员或有授权的**审核人**能做
  3. 列表可见性: 别人只看得到在架的; 审核人/管理员才看得到全部待审
"""
from __future__ import annotations

from tests.test_market_api import _enable_publisher, _upload

API = "/api/v1/assets"


async def _publish_asset(client, auth, pauth, code):
    """发布者上传一个资产 (免审直接上架), 返回 (code, author)."""
    r = await _upload(client, pauth, code=code)
    assert r.status_code == 202, f"上传失败: {r.status_code} {r.text[:200]}"
    return code


async def test_publisher_cannot_unpublish_others_asset(
    client, auth, ws, restore_git_config, publisher_user, stranger_user,  # noqa: ARG001
):
    """别人上传的资产, 白名单用户**不能**下架."""
    from tests.conftest import set_setting

    await set_setting("marketplace.review.enabled", "false")
    await _enable_publisher(publisher_user)
    pauth = {"Authorization": f"Bearer {publisher_user['token']}"}
    await _publish_asset(client, auth, pauth, "own-demo")

    # stranger 也在白名单里, 但他不是作者
    await set_setting("marketplace.publisher_usernames",
                      f"{publisher_user['username']},{stranger_user['username']}")
    sauth = {"Authorization": f"Bearer {stranger_user['token']}"}

    r = await client.post(f"{API}/own-demo/unpublish", data={"comment": "乱下架"},
                          headers=sauth)
    assert r.status_code == 403, r.text
    assert "自己上传" in r.json()["detail"], r.text

    # 资产还在架
    d = await client.get(f"{API}/own-demo", headers=auth)
    assert d.json()["publish_status"] == "published", d.text


async def test_publisher_cannot_delete_others_asset(
    client, auth, ws, restore_git_config, publisher_user, stranger_user,  # noqa: ARG001
):
    """别人上传的资产, 白名单用户**不能**彻底删除."""
    from tests.conftest import set_setting

    await set_setting("marketplace.review.enabled", "false")
    await _enable_publisher(publisher_user)
    pauth = {"Authorization": f"Bearer {publisher_user['token']}"}
    await _publish_asset(client, auth, pauth, "own-demo2")

    await set_setting("marketplace.publisher_usernames",
                      f"{publisher_user['username']},{stranger_user['username']}")
    sauth = {"Authorization": f"Bearer {stranger_user['token']}"}

    r = await client.delete(f"{API}/own-demo2", headers=sauth)
    assert r.status_code == 403, r.text
    # 资产还在
    d = await client.get(f"{API}/own-demo2", headers=auth)
    assert d.status_code == 200, d.text


async def test_publisher_cannot_update_others_asset(
    client, auth, ws, restore_git_config, publisher_user, stranger_user,  # noqa: ARG001
):
    """别人上传的资产, 白名单用户**不能**发新版本覆盖掉."""
    from tests.conftest import set_setting

    await set_setting("marketplace.review.enabled", "false")
    await _enable_publisher(publisher_user)
    pauth = {"Authorization": f"Bearer {publisher_user['token']}"}
    await _publish_asset(client, auth, pauth, "own-demo3")

    await set_setting("marketplace.publisher_usernames",
                      f"{publisher_user['username']},{stranger_user['username']}")
    sauth = {"Authorization": f"Bearer {stranger_user['token']}"}

    r = await client.put(
        f"{API}/own-demo3",
        data={"kind": "skill", "name": "被覆盖了", "summary": "s", "version": "9.9.9"},
        headers=sauth,
    )
    assert r.status_code == 403, r.text
    d = await client.get(f"{API}/own-demo3", headers=auth)
    assert d.json()["version"] == "1.0.0", d.text


async def test_author_can_unpublish_own_asset(
    client, auth, ws, restore_git_config, publisher_user,  # noqa: ARG001
):
    """作者本人当然能下架自己的资产."""
    from tests.conftest import set_setting

    await set_setting("marketplace.review.enabled", "false")
    await _enable_publisher(publisher_user)
    pauth = {"Authorization": f"Bearer {publisher_user['token']}"}
    await _publish_asset(client, auth, pauth, "own-ok")

    r = await client.post(f"{API}/own-ok/unpublish", data={"comment": "自己下架"},
                          headers=pauth)
    assert r.status_code == 200, r.text
    d = await client.get(f"{API}/own-ok", headers=auth)
    assert d.json()["publish_status"] == "unpublished", d.text


async def test_admin_can_delete_others_asset(
    client, auth, ws, restore_git_config, publisher_user,  # noqa: ARG001
):
    """管理员是运营者 —— 可以清理任何人的资产."""
    from tests.conftest import set_setting

    await set_setting("marketplace.review.enabled", "false")
    await _enable_publisher(publisher_user)
    pauth = {"Authorization": f"Bearer {publisher_user['token']}"}
    await _publish_asset(client, auth, pauth, "admin-demo")

    r = await client.delete(f"{API}/admin-demo", headers=auth)
    assert r.status_code == 200, r.text
    d = await client.get(f"{API}/admin-demo", headers=auth)
    assert d.status_code == 404, d.text


# ---------- 审核人 ----------

async def test_normal_publisher_cannot_review(
    client, auth, ws, restore_git_config, publisher_user,  # noqa: ARG001
):
    """白名单用户**不是**审核人 —— 不能审别人的资产."""
    from tests.conftest import set_setting

    await set_setting("marketplace.review.enabled", "true")
    await _enable_publisher(publisher_user)
    pauth = {"Authorization": f"Bearer {publisher_user['token']}"}
    await _publish_asset(client, auth, pauth, "rev-demo")

    r = await client.post(f"{API}/rev-demo/review", data={"decision": "approve"},
                          headers=pauth)
    assert r.status_code == 403, r.text


async def test_reviewer_can_approve(
    client, auth, ws, restore_git_config, publisher_user, stranger_user,  # noqa: ARG001
):
    """被授权的审核人 (不是 admin) 也能审 —— 团队里 admin 一个人审不过来."""
    from tests.conftest import set_setting

    await set_setting("marketplace.review.enabled", "true")
    await set_setting("marketplace.review.reviewer_usernames", stranger_user["username"])
    await _enable_publisher(publisher_user)
    pauth = {"Authorization": f"Bearer {publisher_user['token']}"}
    await _publish_asset(client, auth, pauth, "rev-ok")

    sauth = {"Authorization": f"Bearer {stranger_user['token']}"}
    r = await client.post(f"{API}/rev-ok/review", data={"decision": "approve"},
                          headers=sauth)
    assert r.status_code == 200, r.text
    d = await client.get(f"{API}/rev-ok", headers=auth)
    assert d.json()["publish_status"] == "published", d.text


async def test_reviewer_sees_all_pending_assets(
    client, auth, ws, restore_git_config, publisher_user, stranger_user,  # noqa: ARG001
):
    """审核人在「待审核」筛选里看得到**别人**的待审资产 (普通用户只看自己的)."""
    from tests.conftest import set_setting

    await set_setting("marketplace.review.enabled", "true")
    await set_setting("marketplace.review.reviewer_usernames", stranger_user["username"])
    await _enable_publisher(publisher_user)
    pauth = {"Authorization": f"Bearer {publisher_user['token']}"}
    await _publish_asset(client, auth, pauth, "rev-list")

    sauth = {"Authorization": f"Bearer {stranger_user['token']}"}
    r = await client.get(f"{API}?status=pending&limit=100", headers=sauth)
    assert r.status_code == 200, r.text
    codes = [i["code"] for i in r.json()["items"]]
    assert "rev-list" in codes, f"审核人应看得到别人的待审资产, 实际: {codes}"
    # 详情上要带上"我可以审"的标记 (前端据此显示审核按钮)
    item = next(i for i in r.json()["items"] if i["code"] == "rev-list")
    assert item["can_review"] is True, item


async def test_normal_user_cannot_see_others_pending(
    client, auth, ws, restore_git_config, publisher_user, stranger_user,  # noqa: ARG001
):
    """普通用户按状态过滤时只看得到自己的 —— 别人的待审内容不该被列出来."""
    from tests.conftest import set_setting

    await set_setting("marketplace.review.enabled", "true")
    await _enable_publisher(publisher_user)
    pauth = {"Authorization": f"Bearer {publisher_user['token']}"}
    await _publish_asset(client, auth, pauth, "rev-hidden")

    sauth = {"Authorization": f"Bearer {stranger_user['token']}"}
    r = await client.get(f"{API}?status=pending&limit=100", headers=sauth)
    codes = [i["code"] for i in r.json()["items"]]
    assert "rev-hidden" not in codes, f"不该看到别人的待审资产: {codes}"
