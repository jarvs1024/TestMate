"""扩展库 —— 资产用户评论.

覆盖:
  · 发表 / 列表 / 删除 (本人、管理员)
  · 未登录 401、空白与超长 422
  · 当前用户看不到的资产 (待审核) 不能评论 → 404
  · 资产彻底删除时评论一并清理
"""
from __future__ import annotations

import io
import zipfile

from sqlalchemy import func, select

from app.db.session import AsyncSessionLocal
from app.models.asset import AssetComment
from tests.conftest import set_setting

API = "/api/v1/extensions"


def _zip_bytes(code: str) -> tuple[str, bytes, str]:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        z.writestr("SKILL.md", f"---\nname: {code}\ndescription: d\n---\n\n# {code}\n")
    return (f"{code}.zip", buf.getvalue(), "application/zip")


async def _upload(client, publisher_user, code: str) -> None:
    """以发布者身份上传一个资产 (审核关闭 → 直接 published)."""
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
        headers={"Authorization": f"Bearer {publisher_user['token']}"},
    )
    assert r.status_code == 202, r.text


def _auth(user: dict) -> dict[str, str]:
    return {"Authorization": f"Bearer {user['token']}"}


async def test_comment_create_and_list(
    client, ws, restore_git_config, publisher_user, stranger_user,  # noqa: ARG001
):
    await _upload(client, publisher_user, "cm-demo")

    r = await client.post(
        f"{API}/cm-demo/comments", json={"content": "这个技能很好用"}, headers=_auth(stranger_user),
    )
    assert r.status_code == 201, r.text
    body = r.json()
    assert body["content"] == "这个技能很好用"
    assert body["username"] == stranger_user["username"]
    # 删除只给管理员; 作者本人能编辑自己写的
    assert body["can_delete"] is False
    assert body["can_edit"] is True

    r = await client.get(f"{API}/cm-demo/comments", headers=_auth(stranger_user))
    assert r.status_code == 200, r.text
    data = r.json()
    assert data["total"] == 1
    assert data["items"][0]["content"] == "这个技能很好用"


async def test_comment_requires_login(client, ws, restore_git_config, publisher_user):  # noqa: ARG001
    await _upload(client, publisher_user, "cm-auth")
    r = await client.post(f"{API}/cm-auth/comments", json={"content": "匿名评论"})
    assert r.status_code == 401, r.text


async def test_comment_rejects_blank_and_too_long(
    client, ws, restore_git_config, publisher_user, stranger_user,  # noqa: ARG001
):
    await _upload(client, publisher_user, "cm-valid")
    headers = _auth(stranger_user)

    r = await client.post(f"{API}/cm-valid/comments", json={"content": "   "}, headers=headers)
    assert r.status_code == 422, r.text

    r = await client.post(f"{API}/cm-valid/comments", json={"content": "x" * 1001}, headers=headers)
    assert r.status_code == 422, r.text


async def test_only_admin_can_delete(
    client, ws, restore_git_config, publisher_user, stranger_user, admin_user,  # noqa: ARG001
):
    await _upload(client, publisher_user, "cm-del")
    created = (
        await client.post(
            f"{API}/cm-del/comments", json={"content": "待删除"}, headers=_auth(stranger_user),
        )
    ).json()
    cid = created["id"]

    # 别人的评论删不了
    r = await client.delete(f"{API}/cm-del/comments/{cid}", headers=_auth(publisher_user))
    assert r.status_code == 403, r.text

    # 本人也删不了 —— 删除只给管理员
    r = await client.delete(f"{API}/cm-del/comments/{cid}", headers=_auth(stranger_user))
    assert r.status_code == 403, r.text

    # 管理员可以删
    r = await client.delete(f"{API}/cm-del/comments/{cid}", headers=_auth(admin_user))
    assert r.status_code == 200, r.text

    r = await client.get(f"{API}/cm-del/comments", headers=_auth(stranger_user))
    assert r.json()["total"] == 0


async def test_author_can_edit_own_comment(
    client, ws, restore_git_config, publisher_user, stranger_user,  # noqa: ARG001
):
    """编辑: 谁写的谁改; 列表立刻看到新正文."""
    await _upload(client, publisher_user, "cm-edit")
    created = (
        await client.post(
            f"{API}/cm-edit/comments", json={"content": "原文"}, headers=_auth(stranger_user),
        )
    ).json()

    r = await client.put(
        f"{API}/cm-edit/comments/{created['id']}", json={"content": "改过的正文"},
        headers=_auth(stranger_user),
    )
    assert r.status_code == 200, r.text
    assert r.json()["content"] == "改过的正文"
    assert r.json()["can_edit"] is True

    data = (await client.get(f"{API}/cm-edit/comments", headers=_auth(stranger_user))).json()
    assert data["items"][0]["content"] == "改过的正文"


async def test_only_author_can_edit_comment(
    client, ws, restore_git_config, publisher_user, stranger_user, admin_user,  # noqa: ARG001
):
    """别人不能改; 管理员也不能改别人写的 (管理员只保留删除权)."""
    await _upload(client, publisher_user, "cm-edit-perm")
    created = (
        await client.post(
            f"{API}/cm-edit-perm/comments", json={"content": "原文"}, headers=_auth(stranger_user),
        )
    ).json()
    cid = created["id"]

    for who in (publisher_user, admin_user):
        r = await client.put(
            f"{API}/cm-edit-perm/comments/{cid}", json={"content": "越权修改"},
            headers=_auth(who),
        )
        assert r.status_code == 403, r.text

    data = (await client.get(f"{API}/cm-edit-perm/comments", headers=_auth(stranger_user))).json()
    assert data["items"][0]["content"] == "原文"


async def test_edit_rejects_blank_and_too_long(
    client, ws, restore_git_config, publisher_user, stranger_user,  # noqa: ARG001
):
    await _upload(client, publisher_user, "cm-edit-valid")
    created = (
        await client.post(
            f"{API}/cm-edit-valid/comments", json={"content": "原文"}, headers=_auth(stranger_user),
        )
    ).json()
    url = f"{API}/cm-edit-valid/comments/{created['id']}"

    r = await client.put(url, json={"content": "   "}, headers=_auth(stranger_user))
    assert r.status_code == 422, r.text

    r = await client.put(url, json={"content": "x" * 1001}, headers=_auth(stranger_user))
    assert r.status_code == 422, r.text


async def test_edit_reply_keeps_parent(
    client, ws, restore_git_config, publisher_user, stranger_user,  # noqa: ARG001
):
    """回复也能编辑; 编辑后仍挂在原主评论下."""
    await _upload(client, publisher_user, "cm-edit-reply")
    root = (
        await client.post(
            f"{API}/cm-edit-reply/comments", json={"content": "主评论"}, headers=_auth(stranger_user),
        )
    ).json()
    reply = (
        await client.post(
            f"{API}/cm-edit-reply/comments", json={"content": "旧回复", "parent_id": root["id"]},
            headers=_auth(publisher_user),
        )
    ).json()

    r = await client.put(
        f"{API}/cm-edit-reply/comments/{reply['id']}", json={"content": "新回复"},
        headers=_auth(publisher_user),
    )
    assert r.status_code == 200, r.text
    assert r.json()["parent_id"] == root["id"]

    data = (await client.get(f"{API}/cm-edit-reply/comments", headers=_auth(stranger_user))).json()
    assert data["items"][0]["replies"][0]["content"] == "新回复"


async def test_cannot_edit_deleted_comment(
    client, ws, restore_git_config, publisher_user, stranger_user, admin_user,  # noqa: ARG001
):
    await _upload(client, publisher_user, "cm-edit-gone")
    created = (
        await client.post(
            f"{API}/cm-edit-gone/comments", json={"content": "原文"}, headers=_auth(stranger_user),
        )
    ).json()
    r = await client.delete(
        f"{API}/cm-edit-gone/comments/{created['id']}", headers=_auth(admin_user),
    )
    assert r.status_code == 200, r.text

    r = await client.put(
        f"{API}/cm-edit-gone/comments/{created['id']}", json={"content": "还想改"},
        headers=_auth(stranger_user),
    )
    assert r.status_code == 404, r.text


async def test_hidden_asset_cannot_be_commented(
    client, ws, restore_git_config, publisher_user, stranger_user,  # noqa: ARG001
):
    """待审核资产对非作者不可见 —— 评论接口也必须是 404 (不泄露存在性)."""
    await set_setting("extensions.review.enabled", "true")
    await set_setting("extensions.publisher_usernames", publisher_user["username"])
    pkg = _zip_bytes("cm-hidden")
    data = {
        "code": "cm-hidden", "kind": "skill", "name": "隐藏资产", "version": "1.0.0",
        "summary": "摘要", "description": "", "use_when": "", "not_for": "",
        "category": "misc", "icon": "🧩", "tags": "[]", "keywords": "[]",
        "featured": "false", "permissions": "{}", "install_steps": "[]", "bindings": "{}",
    }
    r = await client.post(
        f"{API}/upload", data=data,
        files={"package": (pkg[0], pkg[1], pkg[2])},
        headers=_auth(publisher_user),
    )
    assert r.status_code == 202, r.text

    r = await client.post(
        f"{API}/cm-hidden/comments", json={"content": "看不见的资产"}, headers=_auth(stranger_user),
    )
    assert r.status_code == 404, r.text

    r = await client.get(f"{API}/cm-hidden/comments", headers=_auth(stranger_user))
    assert r.status_code == 404, r.text


async def test_comments_removed_when_asset_deleted(
    client, ws, restore_git_config, publisher_user, stranger_user, admin_user,  # noqa: ARG001
):
    await _upload(client, publisher_user, "cm-gone")
    await client.post(
        f"{API}/cm-gone/comments", json={"content": "随资产一起走"}, headers=_auth(stranger_user),
    )

    r = await client.delete(f"{API}/cm-gone", params={"comment": "清理测试"}, headers=_auth(admin_user))
    assert r.status_code == 200, r.text

    async with AsyncSessionLocal() as s:
        n = (
            await s.execute(
                select(func.count()).select_from(AssetComment).where(AssetComment.code == "cm-gone")
            )
        ).scalar_one()
    assert n == 0


async def test_only_asset_author_or_admin_can_reply(
    client, ws, restore_git_config, publisher_user, stranger_user, admin_user,  # noqa: ARG001
):
    """回复权限: 资产作者 + 管理员; 普通用户 403."""
    await _upload(client, publisher_user, "cm-reply")
    root = (
        await client.post(
            f"{API}/cm-reply/comments", json={"content": "主评论"}, headers=_auth(stranger_user),
        )
    ).json()

    r = await client.post(
        f"{API}/cm-reply/comments", json={"content": "路过回复", "parent_id": root["id"]},
        headers=_auth(stranger_user),
    )
    assert r.status_code == 403, r.text

    r = await client.post(
        f"{API}/cm-reply/comments", json={"content": "作者回复", "parent_id": root["id"]},
        headers=_auth(publisher_user),
    )
    assert r.status_code == 201, r.text
    assert r.json()["parent_id"] == root["id"]

    r = await client.post(
        f"{API}/cm-reply/comments", json={"content": "管理员回复", "parent_id": root["id"]},
        headers=_auth(admin_user),
    )
    assert r.status_code == 201, r.text


async def test_list_nests_replies_under_root(
    client, ws, restore_git_config, publisher_user, stranger_user, admin_user,  # noqa: ARG001
):
    """列表: 主评论按最新在前; 回复挂在父评论下, 按时间正序; total 只数主评论."""
    await _upload(client, publisher_user, "cm-nest")
    root = (
        await client.post(
            f"{API}/cm-nest/comments", json={"content": "主评论"}, headers=_auth(stranger_user),
        )
    ).json()
    for text, who in (("作者回复", publisher_user), ("管理员回复", admin_user)):
        r = await client.post(
            f"{API}/cm-nest/comments", json={"content": text, "parent_id": root["id"]},
            headers=_auth(who),
        )
        assert r.status_code == 201, r.text

    data = (
        await client.get(f"{API}/cm-nest/comments", headers=_auth(stranger_user))
    ).json()
    assert data["total"] == 1
    item = data["items"][0]
    names = [r["username"] for r in item["replies"]]
    assert names == [publisher_user["username"], admin_user["username"]]
    # 普通用户看 → 不能回复
    assert item["can_reply"] is False

    mine = (
        await client.get(f"{API}/cm-nest/comments", headers=_auth(publisher_user))
    ).json()
    # 作者看 → 能回复
    assert mine["items"][0]["can_reply"] is True


async def test_reply_to_reply_is_rejected(
    client, ws, restore_git_config, publisher_user, stranger_user,  # noqa: ARG001
):
    """只支持一级回复 —— 回复一条回复 → 422 且提示说人话."""
    await _upload(client, publisher_user, "cm-flat")
    root = (
        await client.post(
            f"{API}/cm-flat/comments", json={"content": "主评论"}, headers=_auth(stranger_user),
        )
    ).json()
    reply = (
        await client.post(
            f"{API}/cm-flat/comments", json={"content": "作者回复", "parent_id": root["id"]},
            headers=_auth(publisher_user),
        )
    ).json()

    r = await client.post(
        f"{API}/cm-flat/comments", json={"content": "套娃回复", "parent_id": reply["id"]},
        headers=_auth(publisher_user),
    )
    assert r.status_code == 422, r.text
    assert "只能回复主评论" in r.text


async def test_delete_root_also_hides_replies(
    client, ws, restore_git_config, publisher_user, stranger_user, admin_user,  # noqa: ARG001
):
    await _upload(client, publisher_user, "cm-cascade")
    root = (
        await client.post(
            f"{API}/cm-cascade/comments", json={"content": "主评论"}, headers=_auth(stranger_user),
        )
    ).json()
    r = await client.post(
        f"{API}/cm-cascade/comments", json={"content": "作者回复", "parent_id": root["id"]},
        headers=_auth(publisher_user),
    )
    assert r.status_code == 201, r.text

    r = await client.delete(f"{API}/cm-cascade/comments/{root['id']}", headers=_auth(admin_user))
    assert r.status_code == 200, r.text

    data = (
        await client.get(f"{API}/cm-cascade/comments", headers=_auth(stranger_user))
    ).json()
    assert data["total"] == 0
    assert data["items"] == []


async def test_reply_delete_also_admin_only(
    client, ws, restore_git_config, publisher_user, stranger_user, admin_user,  # noqa: ARG001
):
    """回复同理: 回复作者本人也删不了, 只有管理员能删."""
    await _upload(client, publisher_user, "cm-reply-del")
    root = (
        await client.post(
            f"{API}/cm-reply-del/comments", json={"content": "主评论"}, headers=_auth(stranger_user),
        )
    ).json()
    reply = (
        await client.post(
            f"{API}/cm-reply-del/comments", json={"content": "作者回复", "parent_id": root["id"]},
            headers=_auth(publisher_user),
        )
    ).json()

    r = await client.delete(
        f"{API}/cm-reply-del/comments/{reply['id']}", headers=_auth(publisher_user),
    )
    assert r.status_code == 403, r.text

    r = await client.delete(
        f"{API}/cm-reply-del/comments/{reply['id']}", headers=_auth(admin_user),
    )
    assert r.status_code == 200, r.text

    data = (
        await client.get(f"{API}/cm-reply-del/comments", headers=_auth(stranger_user))
    ).json()
    assert data["total"] == 1
    assert data["items"][0]["replies"] == []
