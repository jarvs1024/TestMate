"""资产市场 API 单元测试 —— 走真实的 HTTP 接口 + 真实的 git 提交流程.

覆盖: 上传落库 / 审核状态机 / 可见性 / 权限边界 / 包预检 / 安装与卸载 /
      上下架 / 删除 / 审计 / 回执 / 同步状态计数.
"""
from __future__ import annotations

import io
import json
import zipfile
from pathlib import Path

import pytest

from tests.conftest import make_plugin_zip, make_skill_zip

API = "/api/v1/assets"


def _zip_bytes(files: dict[str, str]) -> tuple[str, bytes, str]:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        for name, content in files.items():
            z.writestr(name, content)
    return ("pkg.zip", buf.getvalue(), "application/zip")


async def _upload(client, auth, code="demo", kind="skill", pkg_bytes=None, **over):
    """上传一个资产, 返回响应."""
    if pkg_bytes is None:
        pkg_bytes = _zip_bytes({"SKILL.md": f"---\nname: {code}\ndescription: d\n---\n\n# {code}\n"})
    data = {
        "code": code, "kind": kind, "name": f"资产-{code}", "version": "1.0.0",
        "summary": "摘要", "description": "说明", "use_when": "何时", "not_for": "何时不",
        "category": "misc", "icon": "🧩", "tags": "[]", "keywords": "[]",
        "featured": "false", "permissions": "{}", "install_steps": "[]", "bindings": "{}",
    }
    data.update(over)
    return await client.post(
        f"{API}/upload", data=data,
        files={"package": (pkg_bytes[0], pkg_bytes[1], pkg_bytes[2])},
        headers=auth,
    )


async def _enable_publisher(publisher_user):
    """把发布者加进白名单 (用户名口径)."""
    from tests.conftest import set_setting

    await set_setting("marketplace.publisher_usernames", publisher_user["username"])


# ---------- 上传 ----------

async def test_upload_creates_asset_as_pending(client, auth, ws, restore_git_config,
                                               publisher_user):  # noqa: ARG001
    """开了审核 → 发布者上传后进「待审核」, 不是直接上架."""
    from tests.conftest import set_setting

    await set_setting("marketplace.review.enabled", "true")
    await _enable_publisher(publisher_user)
    pauth = {"Authorization": f"Bearer {publisher_user['token']}"}

    r = await _upload(client, pauth, code="pend-demo")
    assert r.status_code == 202, r.text
    job = r.json()
    assert job["status"] == "staged"
    assert job["code"] == "pend-demo"

    r2 = await client.get(f"{API}/pend-demo", headers=auth)
    assert r2.status_code == 200
    assert r2.json()["publish_status"] == "pending"


async def test_upload_without_review_publishes_directly(client, auth, ws,
                                                        restore_git_config,  # noqa: ARG001
                                                        publisher_user):
    """关掉审核 → 直接上架 (旧行为)."""
    from tests.conftest import set_setting

    await set_setting("marketplace.review.enabled", "false")
    await _enable_publisher(publisher_user)
    pauth = {"Authorization": f"Bearer {publisher_user['token']}"}

    r = await _upload(client, pauth, code="direct-demo")
    assert r.status_code == 202, r.text
    r2 = await client.get(f"{API}/direct-demo", headers=auth)
    assert r2.json()["publish_status"] == "published"


async def test_upload_requires_publisher_whitelist(client, auth, ws,
                                                   restore_git_config,  # noqa: ARG001
                                                   stranger_user):
    """不在白名单 → 403."""
    from tests.conftest import set_setting

    await set_setting("marketplace.publisher_usernames", "")
    sauth = {"Authorization": f"Bearer {stranger_user['token']}"}
    r = await _upload(client, sauth, code="denied-demo")
    assert r.status_code == 403
    assert "白名单" in r.json()["detail"]


async def test_upload_rejects_missing_doc_file(client, auth, ws,  # noqa: ARG001
                                               restore_git_config, publisher_user):
    """包里没有 SKILL.md → 422 (技能包必须有)."""
    from tests.conftest import set_setting

    await set_setting("marketplace.review.enabled", "false")
    await _enable_publisher(publisher_user)
    pauth = {"Authorization": f"Bearer {publisher_user['token']}"}
    r = await _upload(client, pauth, code="nodoc-demo",
                      pkg_bytes=_zip_bytes({"README.md": "# 没有 SKILL.md\n"}))
    assert r.status_code == 422
    assert "SKILL.md" in r.json()["detail"]


# ---------- 可见性 ----------

async def test_visibility_stranger_cannot_see_pending(client, auth, ws,
                                                      restore_git_config,  # noqa: ARG001
                                                      publisher_user, stranger_user):
    """待审资产对陌生人不可见, 但对提交者和管理员可见."""
    from tests.conftest import set_setting

    await set_setting("marketplace.review.enabled", "true")
    await _enable_publisher(publisher_user)
    pauth = {"Authorization": f"Bearer {publisher_user['token']}"}
    sauth = {"Authorization": f"Bearer {stranger_user['token']}"}

    await _upload(client, pauth, code="vis-demo")

    r_stranger = await client.get(f"{API}?limit=100&client_id=s1", headers=sauth)
    codes = [i["code"] for i in r_stranger.json()["items"]]
    assert "vis-demo" not in codes

    r_owner = await client.get(f"{API}?limit=100&client_id=o1", headers=pauth)
    assert "vis-demo" in [i["code"] for i in r_owner.json()["items"]]

    r_admin = await client.get(f"{API}?limit=100&client_id=a1", headers=auth)
    assert "vis-demo" in [i["code"] for i in r_admin.json()["items"]]


async def test_visibility_non_admin_cannot_filter_others_pending(client, auth, ws,
                                                                 restore_git_config,  # noqa: ARG001
                                                                 publisher_user, stranger_user):
    """非管理员按状态过滤时只能看到自己的 —— 别人的待审内容不该被列出来."""
    from tests.conftest import set_setting

    await set_setting("marketplace.review.enabled", "true")
    await _enable_publisher(publisher_user)
    pauth = {"Authorization": f"Bearer {publisher_user['token']}"}
    sauth = {"Authorization": f"Bearer {stranger_user['token']}"}
    await _upload(client, pauth, code="leak-demo")

    r = await client.get(f"{API}?status=pending&limit=100&client_id=s2", headers=sauth)
    assert "leak-demo" not in [i["code"] for i in r.json()["items"]]

    r_admin = await client.get(f"{API}?status=pending&limit=100&client_id=a2", headers=auth)
    assert "leak-demo" in [i["code"] for i in r_admin.json()["items"]]


async def test_visibility_installed_unpublished_still_visible(client, auth, ws,
                                                              restore_git_config,  # noqa: ARG001
                                                              publisher_user):
    """已下架但本机装着的资产 → 仍然可见 (否则「已下架」提示没机会显示)."""
    from tests.conftest import set_setting

    await set_setting("marketplace.review.enabled", "false")
    await _enable_publisher(publisher_user)
    pauth = {"Authorization": f"Bearer {publisher_user['token']}"}
    await _upload(client, pauth, code="unpub-demo")

    cid = "client-installed"
    r = await client.post(
        f"{API}/unpub-demo/install",
        data={"version": "1.0.0", "channel": "frontend", "client_id": cid,
              "client_kind": "web"},
        headers=pauth,
    )
    assert r.status_code == 200, r.text

    await client.post(f"{API}/unpub-demo/unpublish", data={"comment": "下架"}, headers=auth)
    r_list = await client.get(f"{API}?limit=100&client_id={cid}", headers=pauth)
    item = next(i for i in r_list.json()["items"] if i["code"] == "unpub-demo")
    assert item["publish_status"] == "unpublished"
    assert item["installed"] is True


# ---------- 审核 ----------

async def test_review_flow_approve(client, auth, ws, restore_git_config,  # noqa: ARG001
                                   publisher_user):
    """发布者上传 → 管理员通过 → 上架, 全过程状态正确."""
    from tests.conftest import set_setting

    await set_setting("marketplace.review.enabled", "true")
    await _enable_publisher(publisher_user)
    pauth = {"Authorization": f"Bearer {publisher_user['token']}"}
    await _upload(client, pauth, code="approve-demo")

    r = await client.post(f"{API}/approve-demo/review",
                          data={"decision": "approve", "comment": "ok"},
                          headers=auth)
    assert r.status_code == 200, r.text
    assert r.json()["publish_status"] == "published"

    r2 = await client.get(f"{API}/approve-demo", headers=auth)
    assert r2.json()["publish_status"] == "published"


async def test_review_flow_reject_then_resubmit(client, auth, ws,  # noqa: ARG001
                                                 restore_git_config, publisher_user):
    """驳回 → rejected + 理由写进资产 → 重新提交 → pending → 通过 → published."""
    from tests.conftest import set_setting

    await set_setting("marketplace.review.enabled", "true")
    await _enable_publisher(publisher_user)
    pauth = {"Authorization": f"Bearer {publisher_user['token']}"}
    await _upload(client, pauth, code="cycle-demo")

    r = await client.post(f"{API}/cycle-demo/review",
                          data={"decision": "reject", "comment": "权限声明不完整"},
                          headers=auth)
    assert r.status_code == 200, r.text
    assert r.json()["publish_status"] == "rejected"

    r2 = await client.get(f"{API}/cycle-demo", headers=auth)
    assert r2.json()["review_note"] == "权限声明不完整"

    r3 = await client.post(f"{API}/cycle-demo/submit", data={"comment": "补了"},
                           headers=pauth)
    assert r3.status_code == 200, r3.text
    assert r3.json()["publish_status"] == "pending"


async def test_review_requires_admin(client, auth, ws, restore_git_config,  # noqa: ARG001
                                     publisher_user):
    """发布者不能自己审自己的资产."""
    from tests.conftest import set_setting

    await set_setting("marketplace.review.enabled", "true")
    await _enable_publisher(publisher_user)
    pauth = {"Authorization": f"Bearer {publisher_user['token']}"}
    await _upload(client, pauth, code="self-review-demo")

    r = await client.post(f"{API}/self-review-demo/review",
                          data={"decision": "approve"}, headers=pauth)
    assert r.status_code == 403


async def test_submit_requires_author(client, auth, ws, restore_git_config,  # noqa: ARG001
                                      publisher_user, stranger_user):
    """别人不能替别人的资产提交审核."""
    from tests.conftest import set_setting

    await set_setting("marketplace.review.enabled", "true")
    await _enable_publisher(publisher_user)
    pauth = {"Authorization": f"Bearer {publisher_user['token']}"}
    sauth = {"Authorization": f"Bearer {stranger_user['token']}"}
    await _upload(client, pauth, code="submit-demo")

    r = await client.post(f"{API}/submit-demo/submit", data={}, headers=sauth)
    assert r.status_code == 403


async def test_review_rejects_bad_decision(client, auth, ws,  # noqa: ARG001
                                           restore_git_config, publisher_user):
    from tests.conftest import set_setting

    await set_setting("marketplace.review.enabled", "true")
    await _enable_publisher(publisher_user)
    pauth = {"Authorization": f"Bearer {publisher_user['token']}"}
    await _upload(client, pauth, code="bad-dec-demo")
    r = await client.post(f"{API}/bad-dec-demo/review",
                          data={"decision": "wat"}, headers=auth)
    assert r.status_code == 400


# ---------- 包预检 ----------

async def test_preview_package_ok(client, auth, publisher_user):
    """合规包 → 可安装."""
    data = _zip_bytes({"SKILL.md": "---\nname: p\ndescription: d\n---\n\n# p\n"})
    r = await client.post(
        f"{API}/preview-package",
        data={"kind": "skill"},
        files={"package": (data[0], data[1], data[2])},
        headers=auth,
    )
    assert r.status_code == 200, r.text
    j = r.json()
    assert j["ok"] is True
    assert j["installable"] is True
    assert j["has_skill_md"] is True
    assert j["doc_file"] == "SKILL.md"
    assert j["issues"] == []


async def test_preview_package_missing_skill_md(client, auth, publisher_user):
    """缺 SKILL.md → 不可装, 给出原因."""
    data = _zip_bytes({"README.md": "# nope\n"})
    r = await client.post(
        f"{API}/preview-package",
        data={"kind": "skill"},
        files={"package": (data[0], data[1], data[2])},
        headers=auth,
    )
    j = r.json()
    assert j["installable"] is False
    assert "SKILL.md" in j["block_reason"]
    assert j["issues"]


async def test_preview_package_plugin_needs_manifest(client, auth, publisher_user):
    """插件包缺 .qoder-plugin/plugin.json → 不可装."""
    data = _zip_bytes({"README.md": "# 只有 README\n"})
    r = await client.post(
        f"{API}/preview-package",
        data={"kind": "plugin"},
        files={"package": (data[0], data[1], data[2])},
        headers=auth,
    )
    j = r.json()
    assert j["installable"] is False
    assert "plugin.json" in j["block_reason"]


async def test_preview_package_rejects_garbage(client, auth, publisher_user):
    """不是 zip → ok=False + 原因, 不能 500."""
    r = await client.post(
        f"{API}/preview-package",
        data={"kind": "skill"},
        files={"package": ("x.zip", b"not a zip at all", "application/zip")},
        headers=auth,
    )
    assert r.status_code == 200, r.text
    assert r.json()["ok"] is False
    assert r.json()["issues"]


# ---------- 安装 ----------
#
# ⚠️ 服务端写盘通道已下线 —— 安装统一在**用户本机**完成:
#   ① 「选择目录安装」浏览器 File System Access 写盘 (前端拿 /bundle 的明文文件)
#   ② 「下载安装包」自行解压
# 后端只负责**记录**安装状态 (哪个客户端、什么版本、装没装).

async def test_install_records_frontend_install(client, auth, ws, restore_git_config,  # noqa: ARG001
                                                publisher_user):
    """前端通道安装 → 只留记录, 文件由浏览器写在用户自己电脑上."""
    from tests.conftest import set_setting

    await set_setting("marketplace.review.enabled", "false")
    await _enable_publisher(publisher_user)
    pauth = {"Authorization": f"Bearer {publisher_user['token']}"}
    await _upload(client, pauth, code="inst-demo")

    cid = "c-inst"
    r = await client.post(
        f"{API}/inst-demo/install",
        data={"version": "1.0.0", "channel": "frontend", "client_id": cid,
              "client_kind": "web", "install_path": "skills"},
        headers=pauth,
    )
    assert r.status_code == 200, r.text
    j = r.json()
    assert j["ok"] is True
    assert j["channel"] == "frontend"

    # 列表标记为已安装
    r_list = await client.get(f"{API}?limit=100&client_id={cid}", headers=pauth)
    item = next(i for i in r_list.json()["items"] if i["code"] == "inst-demo")
    assert item["installed"] is True

    # 卸载 → 记录标记为已卸载, 列表不再标记已安装
    r2 = await client.request("DELETE", f"{API}/inst-demo/install",
                              params={"client_id": cid}, headers=pauth)
    assert r2.status_code == 200, r2.text
    r_list2 = await client.get(f"{API}?limit=100&client_id={cid}", headers=pauth)
    item2 = next(i for i in r_list2.json()["items"] if i["code"] == "inst-demo")
    assert item2["installed"] is False


async def test_install_rejects_server_channel(client, auth, ws, restore_git_config,  # noqa: ARG001
                                               publisher_user):
    """服务端写盘通道已下线 → 400, 且说清该改用哪条路."""
    from tests.conftest import set_setting

    await set_setting("marketplace.review.enabled", "false")
    await _enable_publisher(publisher_user)
    pauth = {"Authorization": f"Bearer {publisher_user['token']}"}
    await _upload(client, pauth, code="srv-demo")

    r = await client.post(
        f"{API}/srv-demo/install",
        data={"version": "1.0.0", "channel": "server", "client_id": "c-srv",
              "client_kind": "web"},
        headers=pauth,
    )
    assert r.status_code == 400, r.text
    assert "下载安装包" in r.json()["detail"]
    # 也不该留下安装记录
    r_list = await client.get(f"{API}/me/installed?client_id=c-srv", headers=pauth)
    assert not any(i["code"] == "srv-demo" for i in r_list.json()["items"])


async def test_install_rejects_version_mismatch(client, auth, ws, restore_git_config,  # noqa: ARG001
                                                publisher_user):
    """请求的版本与资产当前版本不一致 → 409, 且**不留安装记录**.

    以前会静默装成当前版本, 却把安装记录写成请求的版本 →
    「可更新」不再提示, 用户永远装不到新版, 而且全程没有任何报错.
    """
    from tests.conftest import set_setting

    await set_setting("marketplace.review.enabled", "false")
    await _enable_publisher(publisher_user)
    pauth = {"Authorization": f"Bearer {publisher_user['token']}"}
    await _upload(client, pauth, code="ver-demo")

    r = await client.post(
        f"{API}/ver-demo/install",
        data={"version": "9.9.9", "channel": "frontend", "client_id": "c-ver",
              "client_kind": "web"},
        headers=pauth,
    )
    assert r.status_code == 409, r.text
    assert "9.9.9" in r.json()["detail"]
    r_list = await client.get(f"{API}/me/installed?client_id=c-ver", headers=pauth)
    assert not any(i["code"] == "ver-demo" for i in r_list.json()["items"])


async def test_install_accepts_matching_version(client, auth, ws, restore_git_config,  # noqa: ARG001
                                                publisher_user):
    """版本一致时正常安装 —— 别让上一条的校验误伤正常流程."""
    from tests.conftest import set_setting

    await set_setting("marketplace.review.enabled", "false")
    await _enable_publisher(publisher_user)
    pauth = {"Authorization": f"Bearer {publisher_user['token']}"}
    await _upload(client, pauth, code="ver-ok")

    r = await client.post(
        f"{API}/ver-ok/install",
        data={"version": "1.0.0", "channel": "frontend", "client_id": "c-ver-ok",
              "client_kind": "web"},
        headers=pauth,
    )
    assert r.status_code == 200, r.text
    r_list = await client.get(f"{API}/me/installed?client_id=c-ver-ok", headers=pauth)
    assert any(i["code"] == "ver-ok" for i in r_list.json()["items"])


async def test_install_target_suggests_dir(client, auth, ws,  # noqa: ARG001
                                            restore_git_config, publisher_user):
    """install-target 给出建议的安装目录 (Qoder 标准布局) —— 下载安装包时告诉用户解压到哪."""
    from tests.conftest import set_setting

    await set_setting("marketplace.review.enabled", "false")
    await _enable_publisher(publisher_user)
    pauth = {"Authorization": f"Bearer {publisher_user['token']}"}
    await _upload(client, pauth, code="home-demo")

    r = await client.get(f"{API}/home-demo/install-target", headers=auth)
    assert r.status_code == 200, r.text
    j = r.json()
    assert j["target"] == "~/.qoder-cn/skills/home-demo", j
    assert j["skill_dir_host"] == "~/.qoder-cn/skills", j
    # 服务端通道相关的字段**不该再出现**
    assert "server_channel_available" not in j, j
    assert "install_root_rel_path" not in j, j


async def test_install_target_plugin_suggests_versioned_dir(client, auth, ws,  # noqa: ARG001
                                                            restore_git_config, publisher_user):
    """plugin 的建议目录带版本段 (对齐 Qoder 的 cache/<market>/<plugin>/<version>)."""
    import io
    import json as _json
    import zipfile

    from tests.conftest import set_setting

    await set_setting("marketplace.review.enabled", "false")
    await _enable_publisher(publisher_user)
    pauth = {"Authorization": f"Bearer {publisher_user['token']}"}

    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        z.writestr(".qoder-plugin/plugin.json", _json.dumps({"name": "p", "version": "1.0.0"}))
        z.writestr("README.md", "# p\n")
    pkg = ("p.zip", buf.getvalue(), "application/zip")
    await _upload(client, pauth, code="plug-demo", kind="plugin", pkg_bytes=pkg)

    j = (await client.get(f"{API}/plug-demo/install-target", headers=auth)).json()
    assert j["target"] == (
        "~/.qoder-cn/plugins/cache/qoder-marketplace/plug-demo/1.0.0"
    ), j
    assert j["plugin_dir_host"] == "~/.qoder-cn/plugins/cache/qoder-marketplace", j


async def test_uninstall_does_not_delete_user_files(client, auth, ws,  # noqa: ARG001
                                                     restore_git_config, tmp_path):
    """卸载**不碰用户文件** —— 文件在用户本机, 后端够不着, 也不该替用户删."""
    from tests.conftest import set_setting

    await set_setting("marketplace.review.enabled", "false")
    pauth = auth
    await _upload(client, pauth, code="keep-demo")

    # 假装用户本机装过 (后端只存路径字符串)
    await client.post(
        f"{API}/keep-demo/install",
        data={"version": "1.0.0", "channel": "frontend", "client_id": "c-keep",
              "client_kind": "web", "install_path": "/home/u/.qoder-cn/skills/keep-demo"},
        headers=pauth,
    )
    user_dir = tmp_path / "user-skills" / "keep-demo"
    user_dir.mkdir(parents=True)
    (user_dir / "SKILL.md").write_text("# 用户自己的文件\n")

    r = await client.request("DELETE", f"{API}/keep-demo/install",
                              params={"client_id": "c-keep"}, headers=pauth)
    assert r.status_code == 200, r.text
    # 文件还在 —— 卸载只改记录
    assert (user_dir / "SKILL.md").exists(), "卸载不该删用户自己的文件"


async def test_delete_asset_removes_install_records(client, auth, ws,  # noqa: ARG001
                                                     restore_git_config, publisher_user):
    """彻底删除资产 → 安装记录一并清掉."""
    from tests.conftest import set_setting

    await set_setting("marketplace.review.enabled", "false")
    await _enable_publisher(publisher_user)
    pauth = {"Authorization": f"Bearer {publisher_user['token']}"}
    await _upload(client, pauth, code="del-demo")

    await client.post(
        f"{API}/del-demo/install",
        data={"version": "1.0.0", "channel": "frontend", "client_id": "c-del",
              "client_kind": "web"},
        headers=pauth,
    )
    d = await client.delete(f"{API}/del-demo", headers=auth)
    assert d.status_code == 200, d.text

    from app.db.session import AsyncSessionLocal
    from app.models.asset import AssetInstall
    from sqlalchemy import select as _sel
    async with AsyncSessionLocal() as s:
        rows = (await s.execute(
            _sel(AssetInstall).where(AssetInstall.code == "del-demo")
        )).scalars().all()
        assert not rows, f"删资产后安装记录应清空, 实际还有 {len(rows)} 条"


async def test_install_two_versions_keeps_both_records(client, auth, ws,  # noqa: ARG001
                                                       restore_git_config, publisher_user):
    """装两个版本 → 两条安装记录, 旧版本的记录不能被覆盖.

    安装记录按 (code, version, client_id) 定位 —— 只按 (code, client_id) 的话,
    装第二版会把第一版覆盖, 「可更新」就再也提示不出来.
    """
    from app.db.session import AsyncSessionLocal
    from app.models.asset import Asset, AssetInstall
    from sqlalchemy import select as _sel
    from tests.conftest import set_setting

    await set_setting("marketplace.review.enabled", "false")
    await _enable_publisher(publisher_user)
    pauth = {"Authorization": f"Bearer {publisher_user['token']}"}
    await _upload(client, pauth, code="two-ver")

    r1 = await client.post(
        f"{API}/two-ver/install",
        data={"version": "1.0.0", "channel": "frontend", "client_id": "c-tv",
              "client_kind": "web"},
        headers=pauth,
    )
    assert r1.status_code == 200, r1.text

    # 模拟"发布了新版本" —— 资产版本变成 1.1.0
    async with AsyncSessionLocal() as s:
        a = (await s.execute(
            _sel(Asset).where(Asset.code == "two-ver")
        )).scalar_one()
        a.version = "1.1.0"
        await s.commit()

    r2 = await client.post(
        f"{API}/two-ver/install",
        data={"version": "1.1.0", "channel": "frontend", "client_id": "c-tv",
              "client_kind": "web"},
        headers=pauth,
    )
    assert r2.status_code == 200, r2.text

    async with AsyncSessionLocal() as s:
        rows = (await s.execute(
            _sel(AssetInstall).where(AssetInstall.code == "two-ver")
        )).scalars().all()
        versions = {r.version for r in rows}
        assert versions == {"1.0.0", "1.1.0"}, f"应有两版记录, 实际 {versions}"

    # 安装次数按**客户端**算 —— 同一台机器装几个版本都只算一次
    async with AsyncSessionLocal() as s:
        a = (await s.execute(
            _sel(Asset).where(Asset.code == "two-ver")
        )).scalar_one()
        assert a.install_count == 1, f"安装次数应为 1, 实际 {a.install_count}"

    # 同秒装两版时也要取**后装**的那版 (DATETIME 秒级精度)
    from app.api.marketplace import _install_map
    m = await _install_map(["two-ver"], "c-tv")
    assert m["two-ver"][0] == "1.1.0", f"应取后装的 1.1.0, 实际 {m['two-ver'][0]}"


async def test_uninstalled_asset_hidden_after_unpublish(client, auth, ws,  # noqa: ARG001
                                                         restore_git_config, publisher_user):
    """卸载之后, 下架的资产不该再出现在普通用户列表里.

    可见性判断以前没过滤安装记录的 status —— 卸载过的也还算"我已安装的",
    于是下架后它继续赖在列表上, 用户明明已经卸了.
    """
    from tests.conftest import set_setting

    await set_setting("marketplace.review.enabled", "false")
    await _enable_publisher(publisher_user)
    pauth = {"Authorization": f"Bearer {publisher_user['token']}"}
    # ⚠️ 资产由 **admin** 上传 —— publisher 只是安装者.
    #    否则 publisher 既是作者又是安装者, 命中"我提交的"规则, 卸载后照样可见.
    await _upload(client, auth, code="gone-demo")

    r = await client.post(
        f"{API}/gone-demo/install",
        data={"version": "1.0.0", "channel": "frontend", "client_id": "c-gone",
              "client_kind": "web"},
        headers=pauth,
    )
    assert r.status_code == 200, r.text

    # 下架 → 还没卸载, 应该还能看到 (已装的用户要能看到"已下架"提示)
    u1 = await client.post(f"{API}/gone-demo/unpublish", data={"comment": "x"}, headers=auth)
    assert u1.status_code == 200, u1.text
    l1 = await client.get(f"{API}?limit=200&client_id=c-gone", headers=pauth)
    assert any(i["code"] == "gone-demo" for i in l1.json()["items"]), \
        "已安装的用户看不到已下架的资产"

    # 卸载 → 下架的资产就不该再出现了
    u2 = await client.request("DELETE", f"{API}/gone-demo/install",
                              params={"client_id": "c-gone"}, headers=pauth)
    assert u2.status_code == 200, u2.text
    l2 = await client.get(f"{API}?limit=200&client_id=c-gone", headers=pauth)
    assert not any(i["code"] == "gone-demo" for i in l2.json()["items"]), \
        "卸载后仍出现在列表里"


async def test_install_blocked_when_package_invalid(client, auth, ws,  # noqa: ARG001
                                                    restore_git_config, publisher_user):
    """包不合规 (缺 SKILL.md) → install-target 说不能装, 并说清原因."""
    from app.db.session import AsyncSessionLocal
    from app.models.asset import Asset
    from tests.conftest import set_setting

    await set_setting("marketplace.review.enabled", "false")
    async with AsyncSessionLocal() as s:
        s.add(Asset(code="badinst", name="坏包", kind="skill", version="1.0.0",
                    publish_status="published",
                    git_path="assets/skills/misc/badinst"))
        await s.commit()
    d = ws / "assets/skills/misc/badinst/files"
    d.mkdir(parents=True, exist_ok=True)
    (d / "README.md").write_text("# 没有 SKILL.md\n")

    j = (await client.get(f"{API}/badinst/install-target", headers=auth)).json()
    assert j["installable"] is False, j
    assert "SKILL.md" in j["install_block_reason"], j


async def test_install_target_reports_installability(client, auth, ws,  # noqa: ARG001
                                                    restore_git_config, publisher_user):
    """install-target 要说清"能不能装"和"为什么不能"."""
    from app.db.session import AsyncSessionLocal
    from app.models.asset import Asset
    from tests.conftest import set_setting

    await set_setting("marketplace.review.enabled", "false")
    async with AsyncSessionLocal() as s:
        s.add(Asset(code="ok-target", name="好包", kind="skill", version="1.0.0",
                    publish_status="published",
                    git_path="assets/skills/misc/ok-target"))
        await s.commit()
    (ws / "assets/skills/misc/ok-target/files").mkdir(parents=True, exist_ok=True)
    (ws / "assets/skills/misc/ok-target/files/SKILL.md").write_text("# x\n")

    r = await client.get(f"{API}/ok-target/install-target", headers=auth)
    j = r.json()
    assert j["installable"] is True
    assert j["install_block_reason"] == ""
    assert j["skill_dir_host"].startswith("~") or "/" in j["skill_dir_host"]


async def test_install_mcp_rejected(client, auth, ws,  # noqa: ARG001
                                    restore_git_config, publisher_user):
    """连接器不支持一键安装 → 409."""
    from app.db.session import AsyncSessionLocal
    from app.models.asset import Asset

    async with AsyncSessionLocal() as s:
        s.add(Asset(code="conn-demo", name="连接器", kind="mcp", version="1.0.0",
                    publish_status="published",
                    git_path="assets/connectors/ops/conn-demo"))
        await s.commit()

    r = await client.post(
        f"{API}/conn-demo/install",
        data={"version": "1.0.0", "channel": "frontend", "client_id": "x",
              "client_kind": "web"},
        headers=auth,
    )
    assert r.status_code == 409


# ---------- 上下架 / 删除 ----------

async def test_unpublish_and_publish(client, auth, ws, restore_git_config,  # noqa: ARG001
                                     publisher_user):
    from tests.conftest import set_setting

    await set_setting("marketplace.review.enabled", "false")
    await _enable_publisher(publisher_user)
    pauth = {"Authorization": f"Bearer {publisher_user['token']}"}
    await _upload(client, pauth, code="updown-demo")

    r = await client.post(f"{API}/updown-demo/unpublish", data={"comment": "下架"},
                           headers=auth)
    assert r.status_code == 200
    assert r.json()["publish_status"] == "unpublished"

    r2 = await client.post(f"{API}/updown-demo/publish", data={"comment": "回架"},
                           headers=auth)
    assert r2.status_code == 200
    assert r2.json()["publish_status"] == "published"


async def test_delete_removes_everything(client, auth, ws, restore_git_config,  # noqa: ARG001
                                          publisher_user):
    """删除 → 资产、安装记录、索引条目全没, 审计留痕."""
    from tests.conftest import set_setting

    await set_setting("marketplace.review.enabled", "false")
    await _enable_publisher(publisher_user)
    pauth = {"Authorization": f"Bearer {publisher_user['token']}"}
    await _upload(client, pauth, code="del-demo")

    cid = "c-del"
    await client.post(
        f"{API}/del-demo/install",
        data={"version": "1.0.0", "channel": "frontend", "client_id": cid,
              "client_kind": "web"},
        headers=pauth,
    )

    # 该资产从未被提交过 (单测里没有 job worker) —— 删除也必须能成,
    # 不能因为 "pathspec did not match" 而 502
    r = await client.request("DELETE", f"{API}/del-demo",
                             params={"comment": "删了"}, headers=auth)
    assert r.status_code == 200, r.text
    j = r.json()
    assert j["ok"] is True
    assert j["removed_installs"] == 1

    r2 = await client.get(f"{API}/del-demo", headers=auth)
    assert r2.status_code == 404

    r3 = await client.get(f"{API}?limit=100&client_id={cid}", headers=pauth)
    assert "del-demo" not in [i["code"] for i in r3.json()["items"]]

    r4 = await client.get(f"{API}/audits?code=del-demo", headers=auth)
    actions = [a["action"] for a in r4.json()["items"]]
    assert "delete" in actions


# ---------- 审计 / 状态 / 通知 ----------

async def test_audit_records_actions(client, auth, ws, restore_git_config,  # noqa: ARG001
                                     publisher_user):
    from tests.conftest import set_setting

    await set_setting("marketplace.review.enabled", "true")
    await _enable_publisher(publisher_user)
    pauth = {"Authorization": f"Bearer {publisher_user['token']}"}
    await _upload(client, pauth, code="audit-demo")
    await client.post(f"{API}/audit-demo/review",
                      data={"decision": "reject", "comment": "不行"}, headers=auth)

    r = await client.get(f"{API}/audits?code=audit-demo", headers=auth)
    actions = [a["action"] for a in r.json()["items"]]
    assert "create" in actions
    assert "reject" in actions


async def test_sync_status_counts(client, auth, ws, restore_git_config,  # noqa: ARG001
                                  publisher_user):
    from tests.conftest import set_setting

    await set_setting("marketplace.review.enabled", "true")
    await _enable_publisher(publisher_user)
    pauth = {"Authorization": f"Bearer {publisher_user['token']}"}
    await _upload(client, pauth, code="cnt-demo")

    r = await client.get(f"{API}/sync-status?client_id=admin-x", headers=auth)
    j = r.json()
    assert j["awaiting_review_count"] >= 1
    assert j["pending_count"] >= 0


async def test_notifications_list_is_queryable(client, auth, ws,  # noqa: ARG001
                                                restore_git_config, publisher_user):
    """回执端点可用 (没配 webhook 时是空列表, 但不能报错)."""
    r = await client.get(f"{API}/notifications?limit=10", headers=auth)
    assert r.status_code == 200
    assert "items" in r.json()


async def test_config_endpoint(client, auth, ws, restore_git_config):  # noqa: ARG001
    """当前生效配置可读."""
    r = await client.get(f"{API}/config", headers=auth)
    assert r.status_code == 200
    j = r.json()
    assert j["branch"] == "main"
    assert j["remote"]
    assert j["workspace"]


# ---------- 其它端点 ----------

async def test_doc_bundle_and_files(client, auth, ws,  # noqa: ARG001
                                    restore_git_config, publisher_user):
    """文档 / 文件树 / 包内容 三个只读端点."""
    from tests.conftest import set_setting

    await set_setting("marketplace.review.enabled", "false")
    await _enable_publisher(publisher_user)
    pauth = {"Authorization": f"Bearer {publisher_user['token']}"}
    await _upload(client, pauth, code="read-demo")

    r = await client.get(f"{API}/read-demo/doc", headers=auth)
    assert r.status_code == 200
    assert r.json()["filename"] == "SKILL.md"

    r2 = await client.get(f"{API}/read-demo/files", headers=auth)
    assert r2.status_code == 200
    assert any(f["name"] == "SKILL.md" for f in r2.json()["files"])

    r3 = await client.get(f"{API}/read-demo/bundle", headers=auth)
    assert r3.status_code == 200
    assert r3.json()["total"] >= 1


async def test_me_installed_and_updates(client, auth, ws,  # noqa: ARG001
                                        restore_git_config, publisher_user):
    """「我安装的」「可更新的」两个端点."""
    from tests.conftest import set_setting

    await set_setting("marketplace.review.enabled", "false")
    await _enable_publisher(publisher_user)
    pauth = {"Authorization": f"Bearer {publisher_user['token']}"}
    await _upload(client, pauth, code="mine-demo")
    cid = "c-mine"
    await client.post(
        f"{API}/mine-demo/install",
        data={"version": "1.0.0", "channel": "frontend", "client_id": cid,
              "client_kind": "web"},
        headers=pauth,
    )

    r = await client.get(f"{API}/me/installed?client_id={cid}", headers=pauth)
    assert "mine-demo" in [i["code"] for i in r.json()["items"]]

    r2 = await client.get(f"{API}/me/updates?client_id={cid}", headers=pauth)
    assert r2.status_code == 200
    assert isinstance(r2.json()["items"], list)
