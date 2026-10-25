"""下架申请 → 管理员审核 → 自动删除 (2026-10-24 新流程).

为什么改成申请制:
  · 下架是**不可逆的终态** —— 确认后资产连文件带索引带 DB 记录一起没
  · 市场是**共享**的 —— 资产下架了别人第二天就装不上, 得有人拍板

状态机:
    published ──申请下架──▶ unpublish_pending ──管理员通过──▶ 💀 彻底删除
                                  │  ▲
                       管理员驳回 │  │ 作者撤销
                                  ▼  │
                              published

这里锁住的边界:
  1. 申请下架必须**手打 code 确认** (后端校验, 绕不过去)
  2. 申请下架: 作者本人或管理员
  3. 审核下架: **仅管理员** —— 通过就等于删了别人的资产
  4. 待下架审核期间资产**仍在架可见** (管理员确认前它还在被用)
  5. DELETE 端点收成 admin 专用 (前端不再暴露「彻底删除」按钮)
"""
from __future__ import annotations

import subprocess

from tests.test_market_api import _enable_publisher, _upload

API = "/api/v1/assets"


async def _make_published(client, pauth, code):
    r = await _upload(client, pauth, code=code)
    assert r.status_code == 202, f"上传失败: {r.status_code} {r.text[:200]}"
    return code


async def _apply_unpublish(client, pauth, code, comment="不维护了"):
    return await client.post(
        f"{API}/{code}/unpublish",
        data={"confirm_code": code, "comment": comment},
        headers=pauth,
    )


# ---------- 申请 ----------

async def test_apply_unpublish_moves_to_pending(
    client, auth, ws, restore_git_config, publisher_user,  # noqa: ARG001
):
    """申请下架 → 状态变 unpublish_pending."""
    from tests.conftest import set_setting

    await set_setting("marketplace.review.enabled", "false")
    await _enable_publisher(publisher_user)
    pauth = {"Authorization": f"Bearer {publisher_user['token']}"}
    await _make_published(client, pauth, "unp-apply")

    r = await _apply_unpublish(client, pauth, "unp-apply", "这个技能不维护了")
    assert r.status_code == 200, r.text
    assert r.json()["publish_status"] == "unpublish_pending", r.text

    d = await client.get(f"{API}/unp-apply", headers=auth)
    assert d.json()["publish_status"] == "unpublish_pending", d.text
    # 申请理由要给管理员看
    assert d.json()["review_note"] == "这个技能不维护了", d.text


async def test_pending_unpublish_still_visible_in_market(
    client, auth, ws, restore_git_config, publisher_user, stranger_user,  # noqa: ARG001
):
    """⚠️ 待下架审核期间资产**仍在架** —— 管理员确认前它还在被用, 不能消失."""
    from tests.conftest import set_setting

    await set_setting("marketplace.review.enabled", "false")
    await _enable_publisher(publisher_user)
    pauth = {"Authorization": f"Bearer {publisher_user['token']}"}
    await _make_published(client, pauth, "unp-visible")

    await _apply_unpublish(client, pauth, "unp-visible")

    # 另一个普通用户看市场列表 → 资产还在
    sauth = {"Authorization": f"Bearer {stranger_user['token']}"}
    r = await client.get(f"{API}?limit=100", headers=sauth)
    assert r.status_code == 200, r.text
    codes = [i["code"] for i in r.json()["items"]]
    assert "unp-visible" in codes, f"待下架审核的资产不该从市场消失: {codes}"

    # 详情也还打得开
    d = await client.get(f"{API}/unp-visible", headers=sauth)
    assert d.status_code == 200, d.text


async def test_duplicate_apply_rejected(
    client, auth, ws, restore_git_config, publisher_user,  # noqa: ARG001
):
    """重复申请 → 409 (别把审核台刷爆)."""
    from tests.conftest import set_setting

    await set_setting("marketplace.review.enabled", "false")
    await _enable_publisher(publisher_user)
    pauth = {"Authorization": f"Bearer {publisher_user['token']}"}
    await _make_published(client, pauth, "unp-dup")

    r1 = await _apply_unpublish(client, pauth, "unp-dup")
    assert r1.status_code == 200, r1.text
    r2 = await _apply_unpublish(client, pauth, "unp-dup")
    assert r2.status_code == 409, r2.text


async def test_publish_blocked_while_unpublish_pending(
    client, auth, ws, restore_git_config, publisher_user,  # noqa: ARG001
):
    """有待审的下架申请时不能直接"重新上架" —— 两条路别打架."""
    from tests.conftest import set_setting

    await set_setting("marketplace.review.enabled", "false")
    await _enable_publisher(publisher_user)
    pauth = {"Authorization": f"Bearer {publisher_user['token']}"}
    await _make_published(client, pauth, "unp-conflict")

    await _apply_unpublish(client, pauth, "unp-conflict")

    r = await client.post(f"{API}/unp-conflict/publish", data={"comment": "x"}, headers=pauth)
    assert r.status_code == 409, r.text
    assert "撤销" in r.json()["detail"], r.text


# ---------- 撤销 ----------

async def test_author_can_cancel_request(
    client, auth, ws, restore_git_config, publisher_user,  # noqa: ARG001
):
    """作者可以撤销自己的下架申请 —— 不用等管理员驳回."""
    from tests.conftest import set_setting

    await set_setting("marketplace.review.enabled", "false")
    await _enable_publisher(publisher_user)
    pauth = {"Authorization": f"Bearer {publisher_user['token']}"}
    await _make_published(client, pauth, "unp-cancel")

    await _apply_unpublish(client, pauth, "unp-cancel")

    r = await client.post(f"{API}/unp-cancel/unpublish-cancel", data={"comment": "误操作"},
                          headers=pauth)
    assert r.status_code == 200, r.text
    d = await client.get(f"{API}/unp-cancel", headers=auth)
    assert d.json()["publish_status"] == "published", d.text


async def test_cancel_without_request_rejected(
    client, auth, ws, restore_git_config, publisher_user,  # noqa: ARG001
):
    """没有待审申请时撤销 → 409."""
    from tests.conftest import set_setting

    await set_setting("marketplace.review.enabled", "false")
    await _enable_publisher(publisher_user)
    pauth = {"Authorization": f"Bearer {publisher_user['token']}"}
    await _make_published(client, pauth, "unp-nocancel")

    r = await client.post(f"{API}/unp-nocancel/unpublish-cancel", data={}, headers=pauth)
    assert r.status_code == 409, r.text


# ---------- 审核 ----------

async def test_reviewer_cannot_approve_unpublish(
    client, auth, ws, restore_git_config, publisher_user, stranger_user,  # noqa: ARG001
):
    """⚠️ 被授权的审核人**不能**审下架 —— 通过就等于删了别人的资产.

    边界跟之前定的一致: "能审" ≠ "能改别人上传的资产".
    """
    from tests.conftest import set_setting

    await set_setting("marketplace.review.enabled", "false")
    await set_setting("marketplace.review.reviewer_usernames", stranger_user["username"])
    await _enable_publisher(publisher_user)
    pauth = {"Authorization": f"Bearer {publisher_user['token']}"}
    await _make_published(client, pauth, "unp-rev")
    await _apply_unpublish(client, pauth, "unp-rev")

    sauth = {"Authorization": f"Bearer {stranger_user['token']}"}
    r = await client.post(f"{API}/unp-rev/unpublish-review",
                          data={"decision": "approve"}, headers=sauth)
    assert r.status_code == 403, r.text
    assert "管理员" in r.json()["detail"], r.text

    # 资产还在
    d = await client.get(f"{API}/unp-rev", headers=auth)
    assert d.status_code == 200, d.text


async def test_admin_approve_deletes_asset(
    client, auth, ws, restore_git_config, publisher_user,  # noqa: ARG001
):
    """管理员通过 → 资产被**彻底删除** (查不到了)."""
    from tests.conftest import set_setting

    await set_setting("marketplace.review.enabled", "false")
    await _enable_publisher(publisher_user)
    pauth = {"Authorization": f"Bearer {publisher_user['token']}"}
    await _make_published(client, pauth, "unp-ok")
    await _apply_unpublish(client, pauth, "unp-ok")

    r = await client.post(f"{API}/unp-ok/unpublish-review",
                          data={"decision": "approve", "comment": "同意下架"},
                          headers=auth)
    assert r.status_code == 200, r.text
    assert r.json()["deleted"] is True, r.text

    d = await client.get(f"{API}/unp-ok", headers=auth)
    assert d.status_code == 404, d.text


async def test_unpublish_review_has_no_reject(
    client, auth, ws, restore_git_config, publisher_user,  # noqa: ARG001
):
    """下架审核**没有"驳回"** —— 不通过就不处理, 作者可自行撤销.

    (2026-10-24 的流程调整: 下架审核只保留 approve.)
    """
    from tests.conftest import set_setting

    await set_setting("marketplace.review.enabled", "false")
    await _enable_publisher(publisher_user)
    pauth = {"Authorization": f"Bearer {publisher_user['token']}"}
    await _make_published(client, pauth, "unp-reject")
    await _apply_unpublish(client, pauth, "unp-reject")

    r = await client.post(f"{API}/unp-reject/unpublish-review",
                          data={"decision": "reject", "comment": "还有人用"},
                          headers=auth)
    assert r.status_code == 400, r.text
    assert "approve" in r.json()["detail"], r.text

    # 资产还在, 申请还挂着
    d = await client.get(f"{API}/unp-reject", headers=auth)
    assert d.status_code == 200, d.text
    assert d.json()["publish_status"] == "unpublish_pending", d.text


async def test_review_without_request_rejected(
    client, auth, ws, restore_git_config, publisher_user,  # noqa: ARG001
):
    """没有待审申请时审核 → 409 (别把已上架的资产误删了)."""
    from tests.conftest import set_setting

    await set_setting("marketplace.review.enabled", "false")
    await _enable_publisher(publisher_user)
    pauth = {"Authorization": f"Bearer {publisher_user['token']}"}
    await _make_published(client, pauth, "unp-noreview")

    r = await client.post(f"{API}/unp-noreview/unpublish-review",
                          data={"decision": "approve"}, headers=auth)
    assert r.status_code == 409, r.text
    d = await client.get(f"{API}/unp-noreview", headers=auth)
    assert d.status_code == 200, d.text


async def test_review_bad_decision_rejected(
    client, auth, ws, restore_git_config, publisher_user,  # noqa: ARG001
):
    from tests.conftest import set_setting

    await set_setting("marketplace.review.enabled", "false")
    await _enable_publisher(publisher_user)
    pauth = {"Authorization": f"Bearer {publisher_user['token']}"}
    await _make_published(client, pauth, "unp-baddec")
    await _apply_unpublish(client, pauth, "unp-baddec")

    r = await client.post(f"{API}/unp-baddec/unpublish-review",
                          data={"decision": "maybe"}, headers=auth)
    assert r.status_code == 400, r.text
    # 资产没被动过
    d = await client.get(f"{API}/unp-baddec", headers=auth)
    assert d.status_code == 200, d.text


# ---------- 审计留痕 ----------

async def test_audit_records_the_whole_flow(
    client, auth, ws, restore_git_config, publisher_user,  # noqa: ARG001
):
    """申请 / 审核 通过 都要留痕 —— 谁在什么时候动了什么."""
    from tests.conftest import set_setting

    await set_setting("marketplace.review.enabled", "false")
    await _enable_publisher(publisher_user)
    pauth = {"Authorization": f"Bearer {publisher_user['token']}"}
    await _make_published(client, pauth, "unp-audit")
    await _apply_unpublish(client, pauth, "unp-audit", "不维护了")
    await client.post(f"{API}/unp-audit/unpublish-review",
                      data={"decision": "approve"}, headers=auth)

    r = await client.get(f"{API}/audits?code=unp-audit", headers=auth)
    assert r.status_code == 200, r.text
    actions = [a["action"] for a in r.json()["items"]]
    assert "unpublish_request" in actions, actions
    assert "unpublish_approve" in actions, actions


# ---------- 通知时机 ----------

async def test_notification_only_after_full_removal(
    client, auth, ws, restore_git_config, publisher_user,  # noqa: ARG001
):
    """⚠️ 下架通知只在**彻底下架**之后发 —— 申请阶段不通知.

    申请只是内部流程 (管理员还要审), 提前往群里发等于剧透, 之后还得再发一次.
    """
    from app.db.session import AsyncSessionLocal
    from app.models.asset import AssetNotification
    from sqlalchemy import select
    from tests.conftest import set_setting

    # 配个连不上的 webhook —— 发送会失败, 但**回执照样落库** (我们要看的是"有没有发起")
    # 两个频道都要配: 申请下架通知走**审核群**, 彻底下架通知走**市场群**
    await set_setting("dingtalk.market_webhook", "http://127.0.0.1:1/nope")
    await set_setting("dingtalk.review_webhook", "http://127.0.0.1:1/nope")
    await set_setting("marketplace.review.enabled", "false")
    await _enable_publisher(publisher_user)
    pauth = {"Authorization": f"Bearer {publisher_user['token']}"}
    await _make_published(client, pauth, "unp-notify")

    async def events_of(code):
        async with AsyncSessionLocal() as s:
            rows = (await s.execute(
                select(AssetNotification).where(AssetNotification.code == code)
            )).scalars().all()
        return [r.event for r in rows]

    # 申请下架 → 通知**审核群** (unpublish_request 事件), 不是市场群的 unpublish
    await _apply_unpublish(client, pauth, "unp-notify")
    evs = await events_of("unp-notify")
    assert evs.count("unpublish_request") == 1, f"申请下架应通知审核群一次: {evs}"
    assert "unpublish" not in evs, f"申请阶段不该发彻底下架通知: {evs}"

    # 管理员通过 → 资产彻底下架 → 这时候才在市场群通知一次
    r = await client.post(f"{API}/unp-notify/unpublish-review",
                          data={"decision": "approve"}, headers=auth)
    assert r.status_code == 200, r.text
    evs = await events_of("unp-notify")
    assert evs.count("unpublish") == 1, f"彻底下架后应该有一条 unpublish 通知: {evs}"


async def test_cancel_request_sends_no_notification(
    client, auth, ws, restore_git_config, publisher_user,  # noqa: ARG001
):
    """撤销下架申请**不通知** —— 资产从头到尾没被移除过."""
    from app.db.session import AsyncSessionLocal
    from app.models.asset import AssetNotification
    from sqlalchemy import select
    from tests.conftest import set_setting

    await set_setting("dingtalk.market_webhook", "http://127.0.0.1:1/nope")
    await set_setting("dingtalk.review_webhook", "http://127.0.0.1:1/nope")
    await set_setting("marketplace.review.enabled", "false")
    await _enable_publisher(publisher_user)
    pauth = {"Authorization": f"Bearer {publisher_user['token']}"}
    await _make_published(client, pauth, "unp-cancel-notify")

    await _apply_unpublish(client, pauth, "unp-cancel-notify")
    r = await client.post(f"{API}/unp-cancel-notify/unpublish-cancel", data={}, headers=pauth)
    assert r.status_code == 200, r.text

    async with AsyncSessionLocal() as s:
        rows = (await s.execute(
            select(AssetNotification).where(AssetNotification.code == "unp-cancel-notify")
        )).scalars().all()
    evs = [x.event for x in rows]
    # 上架那条 publish 是上传时发的; 撤销**不能**再发任何一条
    assert evs.count("publish") == 1, f"撤销不该再发通知: {evs}"
    assert "unpublish" not in evs, f"撤销不该发下架通知: {evs}"


# ---------- 列表筛选 ----------

async def test_list_filter_by_unpublish_pending(
    client, auth, ws, restore_git_config, publisher_user,  # noqa: ARG001
):
    """管理员能按「待下架审核」筛选."""
    from tests.conftest import set_setting

    await set_setting("marketplace.review.enabled", "false")
    await _enable_publisher(publisher_user)
    pauth = {"Authorization": f"Bearer {publisher_user['token']}"}
    await _make_published(client, pauth, "unp-filter")
    await _apply_unpublish(client, pauth, "unp-filter")

    r = await client.get(f"{API}?status=unpublish_pending&limit=100", headers=auth)
    assert r.status_code == 200, r.text
    codes = [i["code"] for i in r.json()["items"]]
    assert "unp-filter" in codes, codes


# ---------- DELETE 端点: 在架的只有管理员能删, 未上架的作者能撤 ----------

async def test_delete_endpoint_is_admin_only(
    client, auth, ws, restore_git_config, publisher_user,  # noqa: ARG001
):
    """在架的资产作者不能直接删 —— 删除必须走审核.

    ⚠️ 2026-10-25: DELETE 端点现在**多**开放了一条路 ——
       作者可以删自己**还没上架过**的资产 (待审核 / 被驳回).
       那种东西从来没对外可见过, 直接删是安全的.
       但**在架**的资产仍然只有管理员能删 (作者要走「申请下架」).
    """
    from tests.conftest import set_setting

    await set_setting("marketplace.review.enabled", "false")
    await _enable_publisher(publisher_user)
    pauth = {"Authorization": f"Bearer {publisher_user['token']}"}
    await _make_published(client, pauth, "unp-del")

    r = await client.delete(f"{API}/unp-del", headers=pauth)
    assert r.status_code == 409, r.text     # 在架 → 409 (提示走申请下架)
    d = await client.get(f"{API}/unp-del", headers=auth)
    assert d.status_code == 200, r.text


async def test_author_can_discard_own_pending_asset(
    client, auth, ws, restore_git_config, publisher_user,  # noqa: ARG001
):
    """作者可以删自己**待审核**的资产 —— 传错了能撤回, 不必干等.

    ⚠️ 2026-10-25 之前 pending/rejected 没有出口 → 作者只能干等,
       文件还永久躺在 GitLab 里.
    """
    from tests.conftest import set_setting

    await set_setting("marketplace.review.enabled", "true")   # 开审核 → 落 pending
    await _enable_publisher(publisher_user)
    pauth = {"Authorization": f"Bearer {publisher_user['token']}"}
    await _upload(client, pauth, code="discard-demo")

    st = await client.get(f"{API}/discard-demo", headers=pauth)
    assert st.status_code == 200, st.text
    assert st.json()["publish_status"] == "pending", st.text

    r = await client.delete(f"{API}/discard-demo", headers=pauth)
    assert r.status_code == 200, r.text
    # 资产没了 (DB + GitLab 都不该留)
    assert (await client.get(f"{API}/discard-demo", headers=auth)).status_code == 404
    out = subprocess.run(
        ["git", "ls-tree", "-r", "--name-only", "main"],
        cwd=str(ws.parent / "remote.git"), capture_output=True, text=True,
    )
    assert "discard-demo" not in out.stdout, out.stdout
