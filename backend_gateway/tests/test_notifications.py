"""扩展库评论站内通知.

覆盖:
  · 他人评论 → 通知资产作者; 自己评论自己的资产 → 不通知
  · 作者/管理员回复 → 通知被回复的主评论作者; 自己回自己 → 不通知
  · 未读通知按「资产评论 / 同一条主评论的回复」聚合, 已读后再来另起一条
  · 单条已读 / 全部已读 / 未读数; 通知只看得到自己的
  · 作者名短名 / 邮箱两种写法都能命中
  · focus_comment_id: 评论在分页后面也能直接定位到它所在的那一页
  · 评论 / 回复被删, 资产被删 → 对应通知同步删除 (不留 404 深链和虚高未读数)
  · 删除同步上线**之前**留下的孤儿通知 (评论已软删/不存在) → 不展示, 且打开消息时清掉
"""
from __future__ import annotations

import io
import zipfile
from datetime import datetime

from sqlalchemy import select

from app.core.identity import to_email
from app.db.session import AsyncSessionLocal
from app.models.asset import Asset, AssetComment
from app.models.notification import UserNotification
from tests.conftest import set_setting

API = "/api/v1/extensions"
NAPI = "/api/v1/notifications"


def _zip_bytes(code: str) -> tuple[str, bytes, str]:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        z.writestr("SKILL.md", f"---\nname: {code}\ndescription: d\n---\n\n# {code}\n")
    return (f"{code}.zip", buf.getvalue(), "application/zip")


async def _upload(client, publisher_user, code: str) -> None:
    await set_setting("extensions.review.enabled", "false")
    await set_setting("extensions.publisher_usernames", publisher_user["username"])
    pkg = _zip_bytes(code)
    data = {
        "code": code, "kind": "skill", "name": f"资产-{code}", "version": "1.0.0",
        "summary": "摘要", "description": "说明", "use_when": "", "not_for": "",
        "category": "misc", "icon": "🧩", "tags": "[]", "keywords": "[]",
        "featured": "false", "permissions": "{}", "install_steps": "[]", "bindings": "{}",
    }
    r = await client.post(
        f"{API}/upload", data=data,
        files={"package": (pkg[0], pkg[1], pkg[2])},
        headers=_auth(publisher_user),
    )
    assert r.status_code == 202, r.text


def _auth(user: dict) -> dict[str, str]:
    return {"Authorization": f"Bearer {user['token']}"}


async def _comment(client, code: str, user: dict, content: str, parent_id: int | None = None) -> dict:
    payload: dict = {"content": content}
    if parent_id is not None:
        payload["parent_id"] = parent_id
    r = await client.post(f"{API}/{code}/comments", json=payload, headers=_auth(user))
    assert r.status_code == 201, r.text
    return r.json()


async def _list(client, user: dict, **params) -> dict:
    r = await client.get(NAPI, headers=_auth(user), params=params)
    assert r.status_code == 200, r.text
    return r.json()


async def _unread(client, user: dict) -> int:
    r = await client.get(f"{NAPI}/unread-count", headers=_auth(user))
    assert r.status_code == 200, r.text
    return r.json()["count"]


async def test_other_comment_notifies_asset_author(
    client, ws, restore_git_config, publisher_user, stranger_user,  # noqa: ARG001
):
    await _upload(client, publisher_user, "nt-root")
    c = await _comment(client, "nt-root", stranger_user, "这个技能很好用")

    data = await _list(client, publisher_user)
    assert data["total"] == 1
    assert data["unread_count"] == 1
    n = data["items"][0]
    assert n["kind"] == "asset_comment"
    assert n["actor_name"] == stranger_user["username"]
    assert n["asset_code"] == "nt-root"
    assert n["asset_name"] == "资产-nt-root"
    assert n["comment_id"] == c["id"]
    assert n["parent_comment_id"] is None
    assert n["event_count"] == 1
    assert n["read_at"] is None
    assert "这个技能很好用" in n["body"]

    # 评论的人自己不会收到通知
    assert (await _list(client, stranger_user))["total"] == 0
    assert await _unread(client, stranger_user) == 0


async def test_self_comment_on_own_asset_is_silent(
    client, ws, restore_git_config, publisher_user,  # noqa: ARG001
):
    """自己评论自己的资产 —— 不通知 (评论者就是收件人)."""
    await _upload(client, publisher_user, "nt-self")
    await _comment(client, "nt-self", publisher_user, "作者自己补充两句")

    data = await _list(client, publisher_user)
    assert data["total"] == 0
    assert data["unread_count"] == 0


async def test_author_email_form_still_matches(
    client, ws, restore_git_config, publisher_user, stranger_user,  # noqa: ARG001
):
    """存量资产 author 可能是邮箱写法 —— 作者照样能收到通知, 自评也照样不通知."""
    await _upload(client, publisher_user, "nt-mail")
    email = to_email(publisher_user["username"])
    assert email
    async with AsyncSessionLocal() as s:
        a = (await s.execute(select(Asset).where(Asset.code == "nt-mail"))).scalar_one()
        a.author = email
        await s.commit()

    await _comment(client, "nt-mail", stranger_user, "邮箱写法的作者")
    data = await _list(client, publisher_user)
    assert data["total"] == 1
    assert data["items"][0]["event_count"] == 1

    # 自评同样不通知 —— 不能因为写法不同就多出一条
    await _comment(client, "nt-mail", publisher_user, "自评")
    data = await _list(client, publisher_user)
    assert data["total"] == 1
    assert data["items"][0]["event_count"] == 1


async def test_reply_notifies_commenter(
    client, ws, restore_git_config, publisher_user, stranger_user,  # noqa: ARG001
):
    await _upload(client, publisher_user, "nt-reply")
    root = await _comment(client, "nt-reply", stranger_user, "主评论")
    reply = await _comment(client, "nt-reply", publisher_user, "作者回复", parent_id=root["id"])

    data = await _list(client, stranger_user)
    assert data["total"] == 1
    assert data["unread_count"] == 1
    n = data["items"][0]
    assert n["kind"] == "comment_reply"
    assert n["actor_name"] == publisher_user["username"]
    assert n["comment_id"] == reply["id"]
    assert n["parent_comment_id"] == root["id"]
    assert "作者回复" in n["body"]


async def test_self_reply_is_silent(
    client, ws, restore_git_config, publisher_user,  # noqa: ARG001
):
    """作者在自己的评论区里自己回自己 —— 不通知."""
    await _upload(client, publisher_user, "nt-self-reply")
    root = await _comment(client, "nt-self-reply", publisher_user, "自评")
    await _comment(client, "nt-self-reply", publisher_user, "自己回复自己", parent_id=root["id"])

    assert (await _list(client, publisher_user))["total"] == 0


async def test_admin_reply_notifies_commenter(
    client, ws, restore_git_config, publisher_user, stranger_user, admin_user,  # noqa: ARG001
):
    await _upload(client, publisher_user, "nt-admin-reply")
    root = await _comment(client, "nt-admin-reply", stranger_user, "主评论")
    await _comment(client, "nt-admin-reply", admin_user, "管理员回复", parent_id=root["id"])

    data = await _list(client, stranger_user)
    assert data["total"] == 1
    n = data["items"][0]
    assert n["kind"] == "comment_reply"
    assert n["actor_name"] == admin_user["username"]


async def test_unread_comments_aggregate_until_read(
    client, ws, restore_git_config, publisher_user, stranger_user,  # noqa: ARG001
):
    """未读期间同一资产的评论合并一条; 已读后再来另起一条."""
    await _upload(client, publisher_user, "nt-agg")
    c1 = await _comment(client, "nt-agg", stranger_user, "第一条")
    c2 = await _comment(client, "nt-agg", stranger_user, "第二条")

    data = await _list(client, publisher_user)
    assert data["total"] == 1
    n = data["items"][0]
    assert n["event_count"] == 2
    assert n["comment_id"] == c2["id"]
    assert "第二条" in n["body"]
    assert n["title"].startswith(stranger_user["username"])

    r = await client.post(f"{NAPI}/{n['id']}/read", headers=_auth(publisher_user))
    assert r.status_code == 200, r.text
    assert await _unread(client, publisher_user) == 0

    c3 = await _comment(client, "nt-agg", stranger_user, "第三条")
    data = await _list(client, publisher_user)
    assert data["total"] == 2
    assert data["unread_count"] == 1
    newest = data["items"][0]
    assert newest["event_count"] == 1
    assert newest["comment_id"] == c3["id"]


async def test_aggregation_is_per_asset_and_per_thread(
    client, ws, restore_git_config, publisher_user, stranger_user,  # noqa: ARG001
):
    """不同资产不合并; 不同主评论下的回复也不合并."""
    await _upload(client, publisher_user, "nt-agg-a")
    await _upload(client, publisher_user, "nt-agg-b")
    await _comment(client, "nt-agg-a", stranger_user, "A 的第一条")
    await _comment(client, "nt-agg-b", stranger_user, "B 的第一条")

    data = await _list(client, publisher_user)
    assert data["total"] == 2
    assert {i["asset_code"] for i in data["items"]} == {"nt-agg-a", "nt-agg-b"}

    root1 = await _comment(client, "nt-agg-a", stranger_user, "线程一")
    root2 = await _comment(client, "nt-agg-a", stranger_user, "线程二")
    # 未读期间两个线程的回复各自一条 (此前两条主评论通知已合并成 1 条)
    before = (await _list(client, stranger_user))["total"]
    await _comment(client, "nt-agg-a", publisher_user, "回线程一", parent_id=root1["id"])
    await _comment(client, "nt-agg-a", publisher_user, "回线程二", parent_id=root2["id"])
    after = (await _list(client, stranger_user))["total"]
    assert after - before == 2


async def test_read_one_and_read_all(
    client, ws, restore_git_config, publisher_user, stranger_user,  # noqa: ARG001
):
    await _upload(client, publisher_user, "nt-read-a")
    await _upload(client, publisher_user, "nt-read-b")
    await _comment(client, "nt-read-a", stranger_user, "A")
    await _comment(client, "nt-read-b", stranger_user, "B")

    data = await _list(client, publisher_user)
    assert data["unread_count"] == 2
    target = data["items"][0]["id"]

    r = await client.post(f"{NAPI}/{target}/read", headers=_auth(publisher_user))
    assert r.status_code == 200, r.text
    assert await _unread(client, publisher_user) == 1
    data = await _list(client, publisher_user)
    read_ids = {i["id"] for i in data["items"] if i["read_at"]}
    assert target in read_ids

    r = await client.post(f"{NAPI}/read-all", headers=_auth(publisher_user))
    assert r.status_code == 200, r.text
    assert await _unread(client, publisher_user) == 0
    data = await _list(client, publisher_user)
    assert all(i["read_at"] for i in data["items"])

    # 幂等: 再点一次不报错
    r = await client.post(f"{NAPI}/read-all", headers=_auth(publisher_user))
    assert r.status_code == 200, r.text


async def test_notifications_are_private(
    client, ws, restore_git_config, publisher_user, stranger_user,  # noqa: ARG001
):
    await _upload(client, publisher_user, "nt-private")
    await _comment(client, "nt-private", stranger_user, "给作者的通知")
    nid = (await _list(client, publisher_user))["items"][0]["id"]

    # 别人看不到, 也不能代读
    assert (await _list(client, stranger_user))["total"] == 0
    r = await client.post(f"{NAPI}/{nid}/read", headers=_auth(stranger_user))
    assert r.status_code == 404, r.text
    assert await _unread(client, publisher_user) == 1

    # 未登录 401
    r = await client.get(NAPI)
    assert r.status_code == 401, r.text


async def test_focus_comment_id_loads_containing_page(
    client, ws, restore_git_config, publisher_user, stranger_user,  # noqa: ARG001
):
    """深链: 目标评论在第 2 页也能直接取到它所在的那一页."""
    await _upload(client, publisher_user, "nt-focus")
    roots = [await _comment(client, "nt-focus", stranger_user, f"评论 {i}") for i in range(15)]
    target = roots[2]           # 最新在前: 第 13 条, 落在第二页

    r = await client.get(
        f"{API}/nt-focus/comments",
        params={"limit": 10, "offset": 0, "focus_comment_id": target["id"]},
        headers=_auth(stranger_user),
    )
    assert r.status_code == 200, r.text
    data = r.json()
    assert len(data["items"]) == 10
    assert target["id"] in {i["id"] for i in data["items"]}

    # 回复的深链 → 定位到它所在主评论的那一页, 回复挂在父评论下
    reply = await _comment(
        client, "nt-focus", publisher_user, "作者的回复",
        parent_id=target["id"],
    )
    r = await client.get(
        f"{API}/nt-focus/comments",
        params={"limit": 10, "focus_comment_id": reply["id"]},
        headers=_auth(stranger_user),
    )
    assert r.status_code == 200, r.text
    page = r.json()["items"]
    parent = next(i for i in page if i["id"] == target["id"])
    assert reply["id"] in {x["id"] for x in parent["replies"]}

    # 目标不存在 (被删/传错) → 退回第一页, 不报错
    r = await client.get(
        f"{API}/nt-focus/comments",
        params={"limit": 10, "focus_comment_id": 999999},
        headers=_auth(stranger_user),
    )
    assert r.status_code == 200, r.text
    assert len(r.json()["items"]) == 10


# ---------- 评论被删 → 通知同步消失 ----------

async def test_deleting_comment_removes_its_notification(
    client, ws, restore_git_config, publisher_user, stranger_user, admin_user,  # noqa: ARG001
):
    """评论删了, 收件人那条通知也要删 —— 否则点进去 404, 未读数还挂着."""
    await _upload(client, publisher_user, "nt-del")
    c = await _comment(client, "nt-del", stranger_user, "这条评论会被管理员删掉")
    assert (await _list(client, publisher_user))["total"] == 1

    r = await client.delete(f"{API}/nt-del/comments/{c['id']}", headers=_auth(admin_user))
    assert r.status_code == 200, r.text

    data = await _list(client, publisher_user)
    assert data["total"] == 0
    assert data["unread_count"] == 0
    assert await _unread(client, publisher_user) == 0


async def test_deleting_root_comment_removes_reply_notifications(
    client, ws, restore_git_config, publisher_user, stranger_user, admin_user,  # noqa: ARG001
):
    """删主评论会连带软删回复 —— 主评论通知和整条回复线程的通知都该消失."""
    await _upload(client, publisher_user, "nt-del-root")
    root = await _comment(client, "nt-del-root", stranger_user, "主评论")
    await _comment(client, "nt-del-root", publisher_user, "作者回复", parent_id=root["id"])

    assert (await _list(client, publisher_user))["total"] == 1   # 收到陌生人的主评论
    assert (await _list(client, stranger_user))["total"] == 1    # 收到作者的回复

    r = await client.delete(
        f"{API}/nt-del-root/comments/{root['id']}", headers=_auth(admin_user),
    )
    assert r.status_code == 200, r.text

    assert (await _list(client, publisher_user))["total"] == 0
    assert (await _list(client, stranger_user))["total"] == 0
    assert await _unread(client, publisher_user) == 0
    assert await _unread(client, stranger_user) == 0


async def test_deleting_one_reply_keeps_other_threads(
    client, ws, restore_git_config, publisher_user, stranger_user, admin_user,  # noqa: ARG001
):
    """只删一条回复 —— 别的回复线程/资产评论通知不受影响."""
    await _upload(client, publisher_user, "nt-del-one")
    root1 = await _comment(client, "nt-del-one", stranger_user, "线程一")
    root2 = await _comment(client, "nt-del-one", stranger_user, "线程二")
    reply1 = await _comment(
        client, "nt-del-one", publisher_user, "回线程一", parent_id=root1["id"],
    )
    await _comment(client, "nt-del-one", publisher_user, "回线程二", parent_id=root2["id"])

    assert (await _list(client, stranger_user))["total"] == 2

    r = await client.delete(
        f"{API}/nt-del-one/comments/{reply1['id']}", headers=_auth(admin_user),
    )
    assert r.status_code == 200, r.text

    data = await _list(client, stranger_user)
    assert data["total"] == 1
    assert data["items"][0]["parent_comment_id"] == root2["id"]
    # 作者那边的「评论了你的资产」通知指向最新的主评论, 不该被回复删除带走
    assert (await _list(client, publisher_user))["total"] == 1


async def test_deleting_asset_removes_comment_notifications(
    client, ws, restore_git_config, publisher_user, stranger_user, admin_user,  # noqa: ARG001
):
    """资产整体删除时评论已随资产消失 —— 通知不能留下指向空资产的孤儿."""
    await _upload(client, publisher_user, "nt-del-asset")
    await _comment(client, "nt-del-asset", stranger_user, "评论")

    assert (await _list(client, publisher_user))["total"] == 1

    r = await client.delete(
        f"{API}/nt-del-asset", params={"comment": "清理测试"}, headers=_auth(admin_user),
    )
    assert r.status_code == 200, r.text

    assert (await _list(client, publisher_user))["total"] == 0
    assert await _unread(client, publisher_user) == 0


# ---------- 存量孤儿: 删除同步上线前留下的死链通知 ----------

async def _soft_delete_comment_directly(comment_id: int) -> None:
    """模拟老数据: 评论已软删, 但当时的删除接口还没同步删通知."""
    async with AsyncSessionLocal() as s:
        row = await s.get(AssetComment, comment_id)
        assert row is not None
        row.deleted_at = datetime.utcnow()
        await s.commit()


async def test_orphaned_notification_hidden_and_pruned(
    client, ws, restore_git_config, publisher_user, stranger_user,  # noqa: ARG001
):
    """评论被删 (通知没删掉) → 这条消息既不展示也不计数, 打开消息时清掉."""
    await _upload(client, publisher_user, "nt-orphan")
    c = await _comment(client, "nt-orphan", stranger_user, "这条评论后来被删了")
    assert (await _list(client, publisher_user))["total"] == 1

    await _soft_delete_comment_directly(c["id"])

    data = await _list(client, publisher_user)
    assert data["total"] == 0
    assert data["unread_count"] == 0
    assert await _unread(client, publisher_user) == 0

    # 打开一次消息就顺手清库 —— 不用每轮轮询都靠过滤兜着
    async with AsyncSessionLocal() as s:
        left = (
            await s.execute(
                select(UserNotification).where(UserNotification.asset_code == "nt-orphan")
            )
        ).scalars().all()
        assert left == []


async def test_orphan_pruning_keeps_live_notifications(
    client, ws, restore_git_config, publisher_user, stranger_user,  # noqa: ARG001
):
    """只清理死链, 还活着的通知一条都不能少."""
    await _upload(client, publisher_user, "nt-orphan-a")
    await _upload(client, publisher_user, "nt-orphan-b")
    dead = await _comment(client, "nt-orphan-a", stranger_user, "会被删")
    await _comment(client, "nt-orphan-b", stranger_user, "留着")

    await _soft_delete_comment_directly(dead["id"])

    data = await _list(client, publisher_user)
    assert data["total"] == 1
    assert data["items"][0]["asset_code"] == "nt-orphan-b"
    assert data["unread_count"] == 1
    assert await _unread(client, publisher_user) == 1
