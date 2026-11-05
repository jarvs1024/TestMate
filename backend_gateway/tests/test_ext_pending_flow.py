"""扩展库 —— 待审流程「审核通过才进 git」的单元测试 (2026-11-05 · 第十三轮).

用户报的问题: "测试人员提交扩展资产, 不先审核通过再提交 git? 驳回了也只需要
站内通知, 不用钉钉通知; 打回再编辑再提交或直接删除? 中间态数据怎么处理?"

方案 (用户拍板):
  · 待审内容落**仓库外暂存区** (EXTENSIONS_STAGING), 绝不进 git ——
    上传只建一个 stage_only 的 job (worker 直接记完成, 不跑 git).
  · 审核**通过**才把暂存内容拷进工作区, 走正常 commit+push 上架.
  · 驳回 / 重新提交是**纯状态**流转: 不改 git、不发钉钉 (站内看状态即可).
  · 在架资产发新版本/改信息待审期间, git 里老版本原样不动 (货架隐藏) ——
    想放弃这次修改点「恢复在架」; 从没上架过的待审资产直接删除 (连暂存区清掉).
  · 待审改信息的读侧兜底: 暂存区只有 manifest → files/package 回落到工作区老内容.

覆盖:
  · 待审上传: 工作区无痕 / 暂存区有内容 / job 只标记不推 git / 索引不含它
  · 通过: 暂存区 → 工作区, 索引上架, 真同步 job (不带 stage_only)
  · 驳回/重新提交: 纯状态, 驳回零通知、零新 job, 工作区/暂存区都不动
  · 恢复在架: DB 行回到老版本, 暂存区清掉, 不动 git 不发通知
  · 删除: 从未上架过的待审资产可删且暂存区清干净; 有在架版本的待审改版 409
  · 待审改信息的读侧: files/package 从工作区老内容回落, 通过后 README 重生成
"""
from __future__ import annotations

import io
import json
import zipfile
from pathlib import Path

from sqlalchemy import func, select

from app.api import extensions as mk_api
from app.core import git_sync
from app.core.ext_catalog import read_index
from app.db.session import AsyncSessionLocal
from app.models.asset import AssetJob
from tests.conftest import set_setting

API = "/api/v1/extensions"


def _zip_bytes(files: dict[str, str], filename: str = "pkg.zip") -> tuple[str, bytes, str]:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        for name, content in files.items():
            z.writestr(name, content)
    return (filename, buf.getvalue(), "application/zip")


async def _upload(client, auth, code="demo", kind="skill", *, new_version=False, **over):
    """上架新资产 (POST /upload) 或给已有资产发新版本 (PUT /{code}).

    ⚠️ 这两个是**不同的端点**, 不能混:
      · POST /upload  = 上架**新**资产 (action=create) —— 同 code 再传一次是 409
      · PUT  /{code}  = 给**已有**资产发新版本 / 改信息 (action=update)
    """
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
    files = {"package": (pkg[0], pkg[1], pkg[2])}
    if new_version:
        # PUT 的 code 来自路径 —— 表单里那个 code 字段去掉 (免得两处打架)
        data.pop("code", None)
        return await client.put(
            f"{API}/{code}", data=data, files=files, headers=auth,
        )
    return await client.post(
        f"{API}/upload", data=data,
        files=files,
        headers=auth,
    )


async def _enable_publisher(publisher_user):
    await set_setting("extensions.publisher_usernames", publisher_user["username"])


def _ws_dir(ws: Path, code: str) -> Path:
    return ws / "assets" / "skills" / "misc" / code


def _staging_dir(code: str) -> Path:
    return git_sync.STAGING / "assets" / "skills" / "misc" / code


async def _index_codes() -> list[str]:
    idx = await read_index() or {}
    return [e.get("code") for e in idx.get("assets") or []]


async def _job_count() -> int:
    async with AsyncSessionLocal() as s:
        return int((await s.execute(select(func.count(AssetJob.id)))).scalar_one())


def _capture_notify(monkeypatch) -> list[tuple[str, dict, dict]]:
    """挂个假 notify_asset, 记下每一次调用 (上传待审资产本身会发一次审核群提醒)."""
    captured: list[tuple[str, dict, dict]] = []

    async def fake_notify(event, asset=None, **kw):
        captured.append((event, asset or {}, kw))
        return True

    monkeypatch.setattr(mk_api.ext_notify, "notify_asset", fake_notify)
    return captured


# ---------- 待审上传: 不进 git ----------


async def test_pending_upload_stays_out_of_git(client, auth, ws,  # noqa: ARG001
                                               restore_git_config, publisher_user):
    """待审上传: 工作区无痕, 暂存区有内容, job 只标记不推 git, 索引不含它."""
    await set_setting("extensions.review.enabled", "true")
    await _enable_publisher(publisher_user)
    pauth = {"Authorization": f"Bearer {publisher_user['token']}"}

    r = await _upload(client, pauth, code="pend-fresh")
    assert r.status_code == 202, r.text
    assert r.json()["status"] == "staged"

    # ⚠️ 核心断言: git 工作区里**没有**这个资产 —— 审核前不碰仓库
    assert not _ws_dir(ws, "pend-fresh").exists(), "待审内容绝对不能出现在 git 工作区"
    staging = _staging_dir("pend-fresh")
    assert (staging / "manifest.json").is_file(), "待审内容应完整落在仓库外暂存区"
    assert (staging / "files" / "SKILL.md").is_file()
    sm = json.loads((staging / "manifest.json").read_text(encoding="utf-8"))
    assert sm["publish_status"] == "pending"

    # 索引 (货架) 不含待审资产
    assert "pend-fresh" not in await _index_codes()

    # 同步 job: stage_only → worker 直接记完成, 不跑 git
    async with AsyncSessionLocal() as s:
        row = (
            await s.execute(select(AssetJob).where(AssetJob.code == "pend-fresh"))
        ).scalar_one()
        assert row.status == "staged"
        assert row.payload.get("stage_only") is True
        assert not row.commit_sha

    # 读侧: 作者能看到自己的待审资产 (含文件树, 从暂存区读)
    st = await client.get(f"{API}/pend-fresh", headers=pauth)
    assert st.json()["publish_status"] == "pending"
    r2 = await client.get(f"{API}/pend-fresh/files", headers=pauth)
    assert r2.status_code == 200, r2.text
    assert any(f["path"] == "SKILL.md" for f in r2.json()["files"])


# ---------- 审核通过: 暂存区 → 工作区 ----------


async def test_approve_promotes_staging_to_workspace(client, auth, ws,  # noqa: ARG001
                                                     restore_git_config, publisher_user):
    """通过: 暂存内容拷进工作区, 索引上架, 真同步 job (不带 stage_only)."""
    await set_setting("extensions.review.enabled", "true")
    await _enable_publisher(publisher_user)
    pauth = {"Authorization": f"Bearer {publisher_user['token']}"}
    await _upload(client, pauth, code="pend-ok")

    r = await client.post(f"{API}/pend-ok/review",
                          data={"decision": "approve", "comment": "通过"},
                          headers=auth)
    assert r.status_code == 200, r.text
    assert r.json()["ok"] is True
    assert r.json()["publish_status"] == "published"

    # 工作区里现在有了完整资产, 状态是 published
    wsdir = _ws_dir(ws, "pend-ok")
    assert (wsdir / "manifest.json").is_file(), "通过后内容应拷进工作区"
    assert (wsdir / "files" / "SKILL.md").is_file()
    wm = json.loads((wsdir / "manifest.json").read_text(encoding="utf-8"))
    assert wm["publish_status"] == "published"
    # 暂存区清干净 —— 别在仓库外留一份幽灵副本
    assert not _staging_dir("pend-ok").exists(), "通过后暂存区应清掉"

    # 索引上架
    assert "pend-ok" in await _index_codes()

    # approve 建的是**真**同步 job (要 commit+push), 不是 stage_only
    async with AsyncSessionLocal() as s:
        row = await s.get(AssetJob, r.json()["job_id"])
        assert row is not None
        assert row.action == "approve"
        assert not row.payload.get("stage_only")
        assert row.payload.get("notify") == {
            "event": "publish", "actor": "admin_t", "detail": "通过",
        }, row.payload


# ---------- 驳回 / 重新提交: 纯状态 ----------


async def test_reject_and_resubmit_are_pure_state(client, auth, ws,  # noqa: ARG001
                                                  restore_git_config, publisher_user,
                                                  monkeypatch):
    """驳回零钉钉通知、零新 job; 重新提交只发审核群提醒; 文件哪边都不动."""
    await set_setting("extensions.review.enabled", "true")
    await _enable_publisher(publisher_user)
    pauth = {"Authorization": f"Bearer {publisher_user['token']}"}
    captured = _capture_notify(monkeypatch)

    await _upload(client, pauth, code="pend-no")
    # 上传本身会发一条「有人提交了, 请审核」的审核群提醒 —— 这是要保留的
    assert [c[0] for c in captured] == ["review"]
    captured.clear()
    jobs_before = await _job_count()

    r = await client.post(f"{API}/pend-no/review",
                          data={"decision": "reject", "comment": "权限声明不完整"},
                          headers=auth)
    assert r.status_code == 200, r.text
    assert r.json()["publish_status"] == "rejected"
    # ⚠️ 驳回不发钉钉 (站内看状态即可), 也不建任何 git job
    assert captured == [], captured
    assert await _job_count() == jobs_before, "驳回是纯状态流转, 不能建 job"
    # 工作区 / 暂存区两边都不动
    assert not _ws_dir(ws, "pend-no").exists()
    assert (_staging_dir("pend-no") / "manifest.json").is_file()

    r2 = await client.post(f"{API}/pend-no/submit", data={"comment": "补了"}, headers=pauth)
    assert r2.status_code == 200, r2.text
    assert r2.json()["publish_status"] == "pending"
    # 重新提交: 审核群提醒照发 (事件 review), 但依然不建 job、不动文件
    assert [c[0] for c in captured] == ["review"], captured
    assert await _job_count() == jobs_before, "重新提交是纯状态流转, 不能建 job"
    assert not _ws_dir(ws, "pend-no").exists()
    assert (_staging_dir("pend-no") / "manifest.json").is_file()


# ---------- 恢复在架 ----------


async def test_revert_restores_shelved_version(client, auth, ws,  # noqa: ARG001
                                               restore_git_config, publisher_user,
                                               monkeypatch):
    """在架资产发新版本待审 → 「恢复在架」: DB 回到老版本, 暂存区清掉, 不动 git."""
    await set_setting("extensions.review.enabled", "false")
    await _enable_publisher(publisher_user)
    pauth = {"Authorization": f"Bearer {publisher_user['token']}"}
    await _upload(client, pauth, code="rev-demo")
    st = await client.get(f"{API}/rev-demo", headers=pauth)
    assert st.json()["publish_status"] == "published"
    assert st.json()["version"] == "1.0.0"
    ws_manifest = _ws_dir(ws, "rev-demo") / "manifest.json"
    old_manifest = ws_manifest.read_bytes()

    # 开审核 → 发新版本 2.0.0 → 待审 (内容落暂存区, 工作区老版本原样)
    await set_setting("extensions.review.enabled", "true")
    captured = _capture_notify(monkeypatch)
    jobs_before = await _job_count()
    r = await _upload(client, pauth, code="rev-demo", version="2.0.0", new_version=True)
    assert r.status_code == 202, r.text
    st2 = await client.get(f"{API}/rev-demo", headers=pauth)
    assert st2.json()["publish_status"] == "pending"
    assert st2.json()["version"] == "2.0.0"
    assert ws_manifest.read_bytes() == old_manifest, "待审期间工作区老版本不能动"

    # 恢复在架: 版本回到老 manifest
    r3 = await client.post(f"{API}/rev-demo/revert", headers=pauth)
    assert r3.status_code == 200, r3.text
    assert r3.json()["publish_status"] == "published"
    assert r3.json()["version"] == "1.0.0"

    st3 = await client.get(f"{API}/rev-demo", headers=pauth)
    assert st3.json()["publish_status"] == "published"
    assert st3.json()["version"] == "1.0.0"
    assert ws_manifest.read_bytes() == old_manifest
    # 待审内容作废: 暂存区清掉; 没有任何新通知 / 新 job (老版本本来就在货架上)
    assert not _staging_dir("rev-demo").exists(), "恢复后暂存区应清掉"
    assert [c[0] for c in captured] == ["review"], "恢复在架不发任何通知 (上传时那条除外)"
    assert await _job_count() == jobs_before + 1, "恢复在架不动 git, 不建 job"


# ---------- 删除语义 ----------


async def test_delete_blocked_for_pending_update(client, auth, ws,  # noqa: ARG001
                                                 restore_git_config, publisher_user):
    """有在架版本的资产, 待审改版期间不能直接删 —— 引导走「恢复在架」."""
    await set_setting("extensions.review.enabled", "false")
    await _enable_publisher(publisher_user)
    pauth = {"Authorization": f"Bearer {publisher_user['token']}"}
    await _upload(client, pauth, code="del-guard")

    await set_setting("extensions.review.enabled", "true")
    await _upload(client, pauth, code="del-guard", version="2.0.0", new_version=True)
    st = await client.get(f"{API}/del-guard", headers=pauth)
    assert st.json()["publish_status"] == "pending"

    r = await client.request("DELETE", f"{API}/del-guard",
                             params={"comment": "删了"}, headers=pauth)
    assert r.status_code == 409, r.text
    assert "恢复在架" in r.json()["detail"]
    # 资产还在 (没被误删)
    st2 = await client.get(f"{API}/del-guard", headers=pauth)
    assert st2.status_code == 200


async def test_delete_of_new_pending_asset(client, auth, ws,  # noqa: ARG001
                                           restore_git_config, publisher_user):
    """从没上架过的待审资产: 直接删除, 连仓库外暂存区一起清干净."""
    await set_setting("extensions.review.enabled", "true")
    await _enable_publisher(publisher_user)
    pauth = {"Authorization": f"Bearer {publisher_user['token']}"}
    await _upload(client, pauth, code="del-fresh")
    assert _staging_dir("del-fresh").is_dir()

    r = await client.request("DELETE", f"{API}/del-fresh",
                             params={"comment": "不要了"}, headers=pauth)
    assert r.status_code == 200, r.text
    assert r.json()["ok"] is True

    # 资产没了, 暂存区也清干净 —— 中间态数据不残留
    st = await client.get(f"{API}/del-fresh", headers=auth)
    assert st.status_code == 404
    assert not _staging_dir("del-fresh").exists(), "删除后暂存区应清干净"


# ---------- 待审改信息的读侧兜底 ----------


async def test_meta_edit_pending_reads_fall_back_to_workspace(client, auth, ws,  # noqa: ARG001
                                                              restore_git_config,
                                                              publisher_user):
    """改信息待审: 暂存区只有 manifest → files/package 回落到工作区老内容;
    通过后 manifest 带新元信息, README 重生成, 公告不发 (包没变)."""
    await set_setting("extensions.review.enabled", "false")
    await _enable_publisher(publisher_user)
    pauth = {"Authorization": f"Bearer {publisher_user['token']}"}
    await _upload(client, pauth, code="meta-pend")

    await set_setting("extensions.review.enabled", "true")
    r = await client.patch(f"{API}/meta-pend",
                           json={"summary": "待审的新简介"},
                           headers=pauth)
    assert r.status_code == 202, r.text
    st = await client.get(f"{API}/meta-pend", headers=pauth)
    assert st.json()["publish_status"] == "pending"
    assert st.json()["pending_action"] == "meta"

    # 暂存区只有 manifest (没有 files/) —— 安装包/文件树从工作区老内容读
    staging = _staging_dir("meta-pend")
    assert (staging / "manifest.json").is_file()
    assert not (staging / "files").exists(), "改信息不重传安装包, 暂存区不该有 files"
    r2 = await client.get(f"{API}/meta-pend/files", headers=pauth)
    assert r2.status_code == 200, r2.text
    assert any(f["path"] == "SKILL.md" for f in r2.json()["files"]), (
        "待审改信息的文件树应回落到工作区老内容"
    )

    # 通过: manifest 带新简介, publish_status 回到 published, 暂存区清掉
    r3 = await client.post(f"{API}/meta-pend/review",
                           data={"decision": "approve", "comment": "行"},
                           headers=auth)
    assert r3.status_code == 200, r3.text
    wm = json.loads(
        (_ws_dir(ws, "meta-pend") / "manifest.json").read_text(encoding="utf-8")
    )
    assert wm["summary"] == "待审的新简介"
    assert wm["publish_status"] == "published"
    assert not staging.exists(), "通过后暂存区应清掉"
    # 只改了信息的通过, 公告挂在 job 上但被跳过 (包没变, 发了是假消息)
    async with AsyncSessionLocal() as s:
        row = await s.get(AssetJob, r3.json()["job_id"])
        assert row is not None
        assert row.action == "approve"
        assert not row.payload.get("notify"), "只改信息的通过不发上架公告"
