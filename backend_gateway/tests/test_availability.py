"""高可用专项测试 —— 并发 / 重试 / 崩溃恢复 / 降级.

这些是"出问题时系统还能不能自己好起来"的保证.
"""
from __future__ import annotations

import asyncio
from pathlib import Path

import pytest

from app.core import asset_jobs, git_sync, pkg
from tests.conftest import make_skill_zip

API = "/api/v1/extensions"


# ---------- 并发: 同一个 code 并发上传 ----------

async def test_concurrent_upload_same_code_does_not_mix_files(client, auth, ws,
                                                                restore_git_config,  # noqa: ARG001
                                                                publisher_user):
    """两个包并发上传同一个 code → 落盘的必须是**某一个完整的包**, 不能是交错体.

    交错体 = A 的 SKILL.md + B 的 extra.md, 谁都没上传过的东西.
    """
    from tests.conftest import set_setting

    await set_setting("extensions.review.enabled", "false")
    await set_setting("extensions.publisher_usernames", publisher_user["username"])
    pauth = {"Authorization": f"Bearer {publisher_user['token']}"}

    def _pkg(marker: str):
        import io
        import zipfile

        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w") as z:
            z.writestr("SKILL.md", f"---\nname: conc\ndescription: {marker}\n---\n\nMARKER-{marker}\n")
            z.writestr(f"only-{marker}.md", marker)
        # ⚠️ 包名必须与资产 code 一致 (命名契约) —— code 是 conc-same
        return ("conc-same.zip", buf.getvalue(), "application/zip")

    async def upload(marker: str):
        data = {
            "code": "conc-same", "kind": "skill", "name": f"并发-{marker}",
            "version": "1.0.0", "summary": "s", "description": "d", "use_when": "w",
            "not_for": "n", "category": "misc", "icon": "x", "tags": "[]",
            "keywords": "[]", "featured": "false", "permissions": "{}",
            "install_steps": "[]", "bindings": "{}",
        }
        p = _pkg(marker)
        return await client.post(
            f"{API}/upload", data=data,
            files={"package": (p[0], p[1], p[2])}, headers=pauth,
        )

    results = await asyncio.gather(upload("A"), upload("B"))
    assert any(r.status_code in (202, 409) for r in results)

    # 落盘结果必须是某一个完整的包
    files = pkg.content_files(ws / "assets/skills/misc/conc-same")
    names = {f.name for f in files}
    assert len(names) in (1, 2), f"落盘文件数异常: {names}"
    body = (ws / "assets/skills/misc/conc-same/files/SKILL.md").read_text()
    marker = "A" if "MARKER-A" in body else "B"
    assert f"only-{marker}.md" in names, f"SKILL.md 与 extra 文件来自不同的包: {names}"# ---------- 崩溃恢复 ----------

async def test_recover_pending_jobs_picks_up_staged(ws, restore_git_config):  # noqa: ARG001
    """进程重启后, 卡在 staged/syncing 的任务要重新入队, 不能丢."""
    from app.db.session import AsyncSessionLocal
    from app.models.asset import AssetJob

    async with AsyncSessionLocal() as s:
        s.add(AssetJob(
            action="create", status="staged", code="recover-me", asset_name="恢复用例",
            kind="skill", payload={}, git_path="assets/skills/misc/recover-me",
        ))
        await s.commit()

    n = await asset_jobs.recover_pending_jobs()
    assert n >= 1


async def test_recover_ignores_finished(ws, restore_git_config):  # noqa: ARG001
    """已完成的 job 不该被重新入队 (否则会重复提交)."""
    from app.db.session import AsyncSessionLocal
    from app.models.asset import AssetJob

    async with AsyncSessionLocal() as s:
        s.add(AssetJob(
            action="create", status="pushed", code="done-one", asset_name="已完成",
            kind="skill", payload={}, git_path="assets/skills/misc/done-one",
        ))
        await s.commit()

    n = await asset_jobs.recover_pending_jobs()
    assert n == 0


# ---------- 降级: 依赖不可用时的表现 ----------

async def test_list_survives_missing_workspace(client, auth, ws,  # noqa: ARG001
                                                 restore_git_config, monkeypatch):
    """工作区整个没了 → 列表接口仍要能用 (返回空列表而不是 500)."""
    from app.core import git_sync

    monkeypatch.setattr(git_sync, "WORKSPACE", Path("/tmp/tm-does-not-exist-xyz"))
    r = await client.get(f"{API}?limit=10", headers=auth)
    assert r.status_code == 200, r.text
    assert "items" in r.json()


async def test_doc_endpoint_404_for_unknown_code(client, auth):
    """不存在的资产 → 404, 不是 500."""
    r = await client.get(f"{API}/no-such-asset/doc", headers=auth)
    assert r.status_code == 404


async def test_unauthenticated_is_rejected(client):
    """没 token → 401, 不能拿到数据."""
    r = await client.get(f"{API}?limit=10")
    assert r.status_code == 401


# ---------- git 层的降级 ----------

def test_probe_remote_returns_error_not_raise(ws, monkeypatch):
    """远端不可达 → 返回 (False, 原因), 不能抛异常把调用方带崩."""
    git_sync.set_git_config(remote="ssh://git@127.0.0.1:1/none.git", branch="main")
    ok, msg = git_sync.probe_remote()
    assert ok is False
    assert isinstance(msg, str) and msg


def test_sync_paths_blocking_reports_push_failure(ws, monkeypatch):
    """推送失败 → 抛可重试的 SyncError, 而不是别的异常."""
    import subprocess

    # 得真的把 origin 指到坏地址 (只改内存配置不够, 仓库里的 origin 还在)
    subprocess.run(
        ["git", "remote", "set-url", "origin", "ssh://git@127.0.0.1:1/none.git"],
        cwd=str(ws), check=True, capture_output=True,
    )
    git_sync.set_git_config(remote="ssh://git@127.0.0.1:1/none.git", branch="main")
    git_sync.write_text("assets/x/SKILL.md", "x\n")
    with pytest.raises(git_sync.SyncError) as ei:
        git_sync.sync_paths_blocking(
            paths=["assets/x"], message="m", author=("t", "t@t"),
        )
    assert ei.value.category in ("network", "auth", "repo", "unknown")
    assert isinstance(ei.value.retryable, bool)


# ---------- 通知层降级 ----------

async def test_notification_failure_does_not_break_publish(monkeypatch):
    """钉钉挂了**不能**让上架失败 —— 通知是旁路, 不是主流程."""
    from app.core import dingtalk

    async def boom(*a, **kw):
        raise RuntimeError("钉钉不可达")

    monkeypatch.setattr(dingtalk, "send_markdown", boom)
    monkeypatch.setattr(
        dingtalk, "get",
        # 开关得打开 —— 不然压根不会走到"发不出去"这一步, 就测不到降级了
        _fake_get({"dingtalk.extensions_webhook": "http://x/hook", "dingtalk.notify_on_publish": "true"}),
    )
    # notify_extensions 内部已经吞掉了异常 → 返回 False 而不是抛出
    assert await dingtalk.notify_extensions("publish", name="x", code="y") is False


def _fake_get(values: dict[str, str]):
    async def _get(key: str, default: object = None) -> str:
        return values.get(key, default if default is not None else "")

    return _get


# ---------- 公告通知与 git 同步的时序 ----------

async def _seed_asset_with_job(ws: Path, code: str, notify: dict):
    """造一个已落盘、待同步的资产 + 带 notify 配置的 job (直接喂给 worker)."""
    from app.db.session import AsyncSessionLocal
    from app.models.asset import Asset, AssetJob

    base = f"assets/skills/misc/{code}"
    (ws / f"{base}/files").mkdir(parents=True)
    (ws / f"{base}/files/SKILL.md").write_text(
        "---\nname: x\ndescription: d\n---\n", encoding="utf-8",
    )
    (ws / "index.json").write_text("[]", encoding="utf-8")

    async with AsyncSessionLocal() as s:
        a = Asset(
            code=code, name=f"资产-{code}", kind="skill", version="1.0.0",
            summary="一句话简介", author="发布者甲", category="misc",
            publish_status="published", git_path=base, sync_status="staged",
        )
        s.add(a)
        await s.commit()
        await s.refresh(a)
        job = AssetJob(
            action="create", status="staged", code=code, asset_name=a.name,
            kind="skill", git_path=base,
            payload={
                "manifest": {"git_path": base, "version": "1.0.0"},
                "author": ["发布者甲", "a@local"],
                "notify": notify,
            },
        )
        s.add(job)
        await s.commit()
        await s.refresh(job)
    return job


async def test_worker_sends_deferred_notify_after_push(ws, restore_git_config, monkeypatch):  # noqa: ARG001
    """公告通知 (job.payload["notify"]) 只在 git 同步**成功**后发.

    ⚠️ 2026-11-05: 扩展群公告声称"资产已经变了" —— push 失败时不该发假公告.
    直接跑 worker 的 _process, 验证 pushed 之后 notify 才被调用.
    """
    sent: list[tuple[str, object, dict]] = []

    async def fake_notify(event, asset=None, **kw):
        sent.append((event, asset, kw))
        return True

    monkeypatch.setattr(asset_jobs.ext_notify, "notify_asset", fake_notify)

    job = await _seed_asset_with_job(
        ws, "defer-notify",
        {"event": "publish", "actor": "admin_t", "detail": "已上架"},
    )

    await asset_jobs._process(job.id)

    assert [e for e, _, _ in sent] == ["publish"], sent
    _, asset, kw = sent[0]
    # 简介与作者从**资产行**现取 —— 审核人是 admin_t, 通知要展示作者与简介
    assert asset.summary == "一句话简介"
    assert asset.author == "发布者甲"
    assert kw["actor"] == "admin_t"
    assert kw["detail"] == "已上架"


async def test_worker_skips_deferred_notify_on_push_failure(ws, restore_git_config, monkeypatch):  # noqa: ARG001
    """push 失败 → 扩展群**不**收到公告, job 停在 failed."""
    sent: list[tuple[str, object, dict]] = []

    async def fake_notify(event, asset=None, **kw):
        sent.append((event, asset, kw))
        return True

    monkeypatch.setattr(asset_jobs.ext_notify, "notify_asset", fake_notify)

    async def boom(*a, **kw):
        raise git_sync.SyncError("push 被拒", "internal", hint="服务端 bug")

    monkeypatch.setattr(git_sync, "sync_paths", boom)

    job = await _seed_asset_with_job(
        ws, "fail-notify",
        {"event": "publish", "actor": "admin_t", "detail": "已上架"},
    )

    await asset_jobs._process(job.id)

    assert sent == [], f"push 失败不该发公告: {sent}"
    from app.db.session import AsyncSessionLocal
    from app.models.asset import AssetJob

    async with AsyncSessionLocal() as s:
        j2 = await s.get(AssetJob, job.id)
        assert j2.status == "failed", j2.status
