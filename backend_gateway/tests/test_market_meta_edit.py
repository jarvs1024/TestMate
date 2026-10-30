"""资产市场 —— **只改元信息** (PATCH /assets/{code}) 的单元测试 (2026-10-30 · 第十一轮 · 问题6).

用户报的问题: "插件技能连接器支持编辑相关信息（同样是作者和管理才能编辑）".

⚠️ 这条路最要紧的一点: **不能把别人的安装包删掉**.
   原来的 `PUT /assets/{code}` (发新版本) 里, 多文件文本上传那条分支第一件事就是
   `shutil.rmtree(files_dir)` —— 纯元信息编辑如果走那条分支,
   用户的包就没了. 所以后端另写了一条 `meta_only` 落盘路径,
   这组用例盯的就是它.

覆盖:
  · 权限 (作者本人可改 / 他人 403 / 管理员可改)
  · **files/ 与 package/ 目录不被清空** (关键回归)
  · manifest 里 files / doc_file / package_sha256 / package_name 原样保留
  · 版本号不动 (改版本 = 发新版本, 不是这条路的活)
  · 工作区里找不到这个资产 → 409, 且工作区不脏
"""
from __future__ import annotations

import io
import json
import zipfile
from pathlib import Path

import pytest

from tests.conftest import set_setting

API = "/api/v1/assets"


def _zip_bytes(files: dict[str, str], filename: str = "pkg.zip") -> tuple[str, bytes, str]:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        for name, content in files.items():
            z.writestr(name, content)
    return (filename, buf.getvalue(), "application/zip")


async def _upload(client, auth, code="demo", kind="skill", **over):
    pkg = _zip_bytes(
        {"SKILL.md": f"---\nname: {code}\ndescription: d\n---\n\n# {code}\n"},
        filename=f"{code}.zip",
    )
    data = {
        "code": code, "kind": kind, "name": f"资产-{code}", "version": "1.0.0",
        "summary": "摘要", "description": "说明", "use_when": "何时", "not_for": "何时不",
        "category": "misc", "icon": "🧩", "tags": "[]", "keywords": "[]",
        "featured": "false", "permissions": "{}", "install_steps": "[]", "bindings": "{}",
    }
    data.update(over)
    return await client.post(
        f"{API}/upload", data=data,
        files={"package": (pkg[0], pkg[1], pkg[2])},
        headers=auth,
    )


async def _enable_publisher(publisher_user):
    await set_setting("marketplace.publisher_usernames", publisher_user["username"])


def _manifest_path(ws: Path, code: str) -> Path:
    """工作区里某个资产的 manifest.json 路径 (分类是 misc)."""
    return ws / "assets" / "skills" / "misc" / code / "manifest.json"


# ---------- 权限 ----------


async def test_meta_edit_by_author_allowed(client, auth, ws, restore_git_config,  # noqa: ARG001
                                           publisher_user):
    """作者本人可以改自己资产的元信息."""
    await set_setting("marketplace.review.enabled", "false")
    await _enable_publisher(publisher_user)
    pauth = {"Authorization": f"Bearer {publisher_user['token']}"}
    await _upload(client, pauth, code="meta-own")

    r = await client.patch(
        f"{API}/meta-own",
        json={"summary": "改过的简介", "description": "改过的说明"},
        headers=pauth,
    )
    assert r.status_code == 202, r.text
    assert r.json()["code"] == "meta-own"

    st = await client.get(f"{API}/meta-own", headers=pauth)
    body = st.json()
    assert body["summary"] == "改过的简介"
    assert body["description"] == "改过的说明"


async def test_meta_edit_denied_for_others(client, auth, ws, restore_git_config,  # noqa: ARG001
                                           publisher_user):
    """别人不能改你的资产 → 403 (有发布权也不行, 那只是"能往市场上放东西")."""
    await set_setting("marketplace.review.enabled", "false")
    await _enable_publisher(publisher_user)
    pauth = {"Authorization": f"Bearer {publisher_user['token']}"}
    await _upload(client, pauth, code="meta-guard")

    # 另一个白名单里的发布者 (有发布权, 但不是作者)
    from app.core.security import create_access_token
    from app.db.session import AsyncSessionLocal
    from app.models.user import User, UserRole

    async with AsyncSessionLocal() as s:
        u = User(username="other_pub_t", password_hash="x", role=UserRole.tester)
        s.add(u)
        await s.commit()
        await s.refresh(u)
        uid, uname = u.id, u.username
    token, _ = create_access_token(uid)
    await set_setting("marketplace.publisher_usernames",
                      f"{uname},{publisher_user['username']}")

    r = await client.patch(
        f"{API}/meta-guard",
        json={"summary": "我要改别人的"},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert r.status_code == 403, r.text


async def test_meta_edit_by_admin_allowed(client, auth, ws, restore_git_config,  # noqa: ARG001
                                          publisher_user):
    """管理员可以改任何人的资产."""
    await set_setting("marketplace.review.enabled", "false")
    await _enable_publisher(publisher_user)
    pauth = {"Authorization": f"Bearer {publisher_user['token']}"}
    await _upload(client, pauth, code="meta-admin")

    r = await client.patch(
        f"{API}/meta-admin",
        json={"summary": "管理员改的"},
        headers=auth,
    )
    assert r.status_code == 202, r.text
    st = await client.get(f"{API}/meta-admin", headers=auth)
    assert st.json()["summary"] == "管理员改的"


# ---------- 关键回归: 不能删掉安装包 ----------


async def test_meta_edit_keeps_files_and_package(client, auth, ws, restore_git_config,  # noqa: ARG001
                                                  publisher_user):
    """⚠️ **最要紧的一条**: 改完元信息, files/ 与 package/ 必须原封不动.

    走错分支 (多文件文本上传那条) 会 `rmtree(files_dir)` —— 用户的包直接没了.
    """
    await set_setting("marketplace.review.enabled", "false")
    await _enable_publisher(publisher_user)
    pauth = {"Authorization": f"Bearer {publisher_user['token']}"}
    await _upload(client, pauth, code="meta-keep")

    base = ws / "assets" / "skills" / "misc" / "meta-keep"
    skill_md = base / "files" / "SKILL.md"
    pkg_dir = base / "package"
    assert skill_md.is_file(), "上传后 files/SKILL.md 应该在"
    assert pkg_dir.is_dir(), "上传后 package/ 应该在"
    before = skill_md.read_bytes()

    r = await client.patch(
        f"{API}/meta-keep",
        json={"summary": "只改简介"},
        headers=pauth,
    )
    assert r.status_code == 202, r.text

    # ⚠️ 文件还在, 内容没变
    assert skill_md.is_file(), "files/SKILL.md 被删了 —— 元信息编辑不能碰安装包!"
    assert skill_md.read_bytes() == before
    # ⚠️ package/ 也没被清空
    assert pkg_dir.is_dir(), "package/ 被删了 —— 元信息编辑不能碰安装包!"
    assert list(pkg_dir.iterdir()), "package/ 里空了"


async def test_meta_edit_keeps_manifest_file_fields(client, auth, ws, restore_git_config,  # noqa: ARG001
                                                      publisher_user):
    """manifest 里的 files / doc_file / package_sha256 / package_name 原样保留."""
    await set_setting("marketplace.review.enabled", "false")
    await _enable_publisher(publisher_user)
    pauth = {"Authorization": f"Bearer {publisher_user['token']}"}
    await _upload(client, pauth, code="meta-fields")

    mpath = _manifest_path(ws, "meta-fields")
    old = json.loads(mpath.read_text(encoding="utf-8"))
    assert old["files"], "上传后 manifest 里应该有 files"

    r = await client.patch(
        f"{API}/meta-fields",
        json={"summary": "新的简介", "description": "新的说明"},
        headers=pauth,
    )
    assert r.status_code == 202, r.text

    new = json.loads(mpath.read_text(encoding="utf-8"))
    assert new["files"] == old["files"]
    assert new["doc_file"] == old["doc_file"]
    assert new["package_sha256"] == old["package_sha256"]
    assert new["package_name"] == old["package_name"]
    # ⚠️ 版本号不动 —— 改版本是「发新版本」的活
    assert new["version"] == old["version"]
    # 元信息改了
    assert new["summary"] == "新的简介"
    assert new["description"] == "新的说明"


async def test_meta_edit_keeps_author(client, auth, ws, restore_git_config,  # noqa: ARG001
                                      publisher_user):
    """管理员改别人的资产时, **不能把作者改成自己**."""
    await set_setting("marketplace.review.enabled", "false")
    await _enable_publisher(publisher_user)
    pauth = {"Authorization": f"Bearer {publisher_user['token']}"}
    await _upload(client, pauth, code="meta-author")
    before = json.loads(_manifest_path(ws, "meta-author").read_text(encoding="utf-8"))["author"]

    r = await client.patch(
        f"{API}/meta-author",
        json={"summary": "管理员改的"},
        headers=auth,
    )
    assert r.status_code == 202, r.text
    after = json.loads(_manifest_path(ws, "meta-author").read_text(encoding="utf-8"))["author"]
    assert after == before, "作者被改掉了 —— 管理员不该抢别人的署名"


# ---------- 失败与恢复 ----------


async def test_meta_edit_without_manifest_returns_409_and_keeps_workspace_clean(
    client, auth, ws, restore_git_config, publisher_user  # noqa: ARG001
):
    """工作区里找不到这个资产 → 409, **不能凭空造一个** (files/package 都不在)."""
    await set_setting("marketplace.review.enabled", "false")
    await _enable_publisher(publisher_user)
    pauth = {"Authorization": f"Bearer {publisher_user['token']}"}
    await _upload(client, pauth, code="meta-nomani")

    # 把 manifest 删掉 (模拟"工作区跟远端对不上")
    mpath = _manifest_path(ws, "meta-nomani")
    mpath.unlink()

    # ⚠️ 工作区本来就是"脏"的 (单测里没有 job worker, 上传的东西没提交) ——
    #    所以要比的是**前后有没有变脏**, 不是"干不干净".
    from app.core import git_sync
    dirty_before = sorted(git_sync.workspace_status().get("dirty_files") or [])

    r = await client.patch(
        f"{API}/meta-nomani",
        json={"summary": "改一下"},
        headers=pauth,
    )
    assert r.status_code == 409, r.text
    # ⚠️ 没有新造出 manifest
    assert not mpath.exists()
    # ⚠️ 工作区不能更脏 —— 否则反向同步的安全闸每轮跳过 → 永久卡死
    dirty_after = sorted(git_sync.workspace_status().get("dirty_files") or [])
    assert dirty_after == dirty_before, (dirty_before, dirty_after)


async def test_meta_edit_unknown_asset_404(client, auth, ws, restore_git_config):  # noqa: ARG001
    """资产不存在 → 404."""
    r = await client.patch(
        f"{API}/no-such-asset",
        json={"summary": "x"},
        headers=auth,
    )
    assert r.status_code == 404, r.text


async def test_meta_edit_rejects_empty_name(client, auth, ws, restore_git_config,  # noqa: ARG001
                                            publisher_user):
    """名字不能改成空 → 422."""
    await set_setting("marketplace.review.enabled", "false")
    await _enable_publisher(publisher_user)
    pauth = {"Authorization": f"Bearer {publisher_user['token']}"}
    await _upload(client, pauth, code="meta-bad")
    r = await client.patch(
        f"{API}/meta-bad",
        json={"name": ""},
        headers=pauth,
    )
    assert r.status_code == 422, r.text
