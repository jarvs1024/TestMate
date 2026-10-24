"""高可用专项测试 —— 并发 / 重试 / 崩溃恢复 / 降级.

这些是"出问题时系统还能不能自己好起来"的保证.
"""
from __future__ import annotations

import asyncio
from pathlib import Path

import pytest

from app.core import asset_jobs, git_sync, pkg
from tests.conftest import make_skill_zip

API = "/api/v1/assets"


# ---------- 并发: 同一个 code 并发上传 ----------

async def test_concurrent_upload_same_code_does_not_mix_files(client, auth, ws,
                                                                restore_git_config,  # noqa: ARG001
                                                                publisher_user):
    """两个包并发上传同一个 code → 落盘的必须是**某一个完整的包**, 不能是交错体.

    交错体 = A 的 SKILL.md + B 的 extra.md, 谁都没上传过的东西.
    """
    from tests.conftest import set_setting

    await set_setting("marketplace.review.enabled", "false")
    await set_setting("marketplace.publisher_usernames", publisher_user["username"])
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
        _fake_get({"dingtalk.market_webhook": "http://x/hook", "dingtalk.notify_on_publish": "true"}),
    )
    # notify_market 内部已经吞掉了异常 → 返回 False 而不是抛出
    assert await dingtalk.notify_market("publish", name="x", code="y") is False


def _fake_get(values: dict[str, str]):
    async def _get(key: str, default: object = None) -> str:
        return values.get(key, default if default is not None else "")

    return _get
