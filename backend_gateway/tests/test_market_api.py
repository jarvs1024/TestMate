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


async def test_visibility_unpublished_hidden_from_others(client, auth, ws,
                                                          restore_git_config,  # noqa: ARG001
                                                          publisher_user,
                                                          stranger_user):
    """已下架 (unpublished) 的资产: **别人看不到, 作者自己看得到**.

    以前还有第三条规则「我已安装的也能看到」—— 现在安装只是下载,
    后端根本不知道用户装没装, 拿下载记录当"已安装"是虚假语义, 那条规则也去掉了.
    可见性因此简化成: 在架 ∪ 我提交的.

    ⚠️ 「已下架」这个状态现在**只能由管理员手动置** (用户下架走申请制,
    确认后直接删除), 所以这里直接改 DB 造这个状态来验可见性规则.
    """
    from tests.conftest import set_setting

    await set_setting("marketplace.review.enabled", "false")
    await _enable_publisher(publisher_user)
    pauth = {"Authorization": f"Bearer {publisher_user['token']}"}
    await _upload(client, pauth, code="unpub-demo")

    # 管理员手动置成「已下架」(历史数据 / 运维场景)
    from app.db.session import AsyncSessionLocal
    from app.models.asset import Asset
    from sqlalchemy import select

    async with AsyncSessionLocal() as s:
        a = (await s.execute(select(Asset).where(Asset.code == "unpub-demo"))).scalar_one()
        a.publish_status = "unpublished"
        await s.commit()

    # 作者自己看得到 (我提交的)
    r_own = await client.get(f"{API}?limit=100&client_id=c-own", headers=pauth)
    own = next((i for i in r_own.json()["items"] if i["code"] == "unpub-demo"), None)
    assert own is not None, "作者应能看到自己下架的资产"
    assert own["publish_status"] == "unpublished"

    # 别人看不到
    sauth = {"Authorization": f"Bearer {stranger_user['token']}"}
    r_other = await client.get(f"{API}?limit=100&client_id=c-other", headers=sauth)
    assert not any(i["code"] == "unpub-demo" for i in r_other.json()["items"]), \
        "下架的资产不该被别人看到"


async def test_download_increments_download_count(
    client, auth, ws, restore_git_config, publisher_user,  # noqa: ARG001
):
    """下载一次 → 下载计数 +1 (热门度指标, 不是"安装次数").

    下载次数是**准确**的: 下载端点自己知道有人下了.
    ("安装次数" 猜不出来 —— 后端不知道用户到底解压没有, 所以那个字段下线了)
    """
    from sqlalchemy import select as _sel

    from app.db.session import AsyncSessionLocal
    from app.models.asset import Asset
    from tests.conftest import set_setting

    await set_setting("marketplace.review.enabled", "false")
    await _enable_publisher(publisher_user)
    pauth = {"Authorization": f"Bearer {publisher_user['token']}"}
    await _upload(client, pauth, code="dl-demo")

    # 先确认 0
    async with AsyncSessionLocal() as s:
        a = (await s.execute(
            _sel(Asset).where(Asset.code == "dl-demo")
        )).scalar_one()
        assert a.download_count == 0, a.download_count

    r = await client.get(f"{API}/dl-demo/versions/1.0.0/download", headers=auth)
    assert r.status_code == 200, r.text
    assert r.headers["content-type"] == "application/zip"
    assert r.content[:2] == b"PK", "不是 zip"

    async with AsyncSessionLocal() as s:
        a = (await s.execute(
            _sel(Asset).where(Asset.code == "dl-demo")
        )).scalar_one()
        assert a.download_count == 1, a.download_count

    # 再下一次 → 2
    await client.get(f"{API}/dl-demo/versions/1.0.0/download", headers=auth)
    async with AsyncSessionLocal() as s:
        a = (await s.execute(
            _sel(Asset).where(Asset.code == "dl-demo")
        )).scalar_one()
        assert a.download_count == 2, a.download_count


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
# 后端只负责**记录**安装状态 (哪个客户端、什么版本、装没装).# ---------- 上下架 / 删除 ----------

async def test_unpublish_and_publish(client, auth, ws, restore_git_config,  # noqa: ARG001
                                     publisher_user):
    """申请下架 → 撤销申请 → 恢复在架.

    (下架现在是**申请制**: 提交后等管理员确认, 确认通过就彻底删除 ——
     完整流程见 test_unpublish_flow.py. 这里只验"能不能撤销回架".)
    """
    from tests.conftest import set_setting

    await set_setting("marketplace.review.enabled", "false")
    await _enable_publisher(publisher_user)
    pauth = {"Authorization": f"Bearer {publisher_user['token']}"}
    await _upload(client, pauth, code="updown-demo")

    r = await client.post(f"{API}/updown-demo/unpublish",
                          data={"confirm_code": "updown-demo", "comment": "下架"},
                          headers=auth)
    assert r.status_code == 200
    assert r.json()["publish_status"] == "unpublish_pending"

    r2 = await client.post(f"{API}/updown-demo/unpublish-cancel", data={"comment": "回架"},
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
        data={"version": "1.0.0", "channel": "download", "client_id": cid,
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