"""目录穿越防护 —— 远端 index.json 里的 git_path 不能越界 (2026-10-26).

⚠️ 为什么这条要单独测:
    index.json 是**远端**内容 (GitLab 仓库里的文件), 谁有仓库写权限谁就能改它.
    里面的 ``git_path`` 会被拼成 ``WORKSPACE / git_path`` 去**读文件**
    (下载 / 文件列表 / 打包) —— 不挡的话, 一个 ``../../../app/.env``
    就能把容器里的 JWT_SECRET 读出来.

    **仓库写权限 ≠ 服务器文件读权限** —— 中间不能有这一步跳跃.

两道闸:
    ① 落库侧: market_catalog.apply_index_to_db 校验, 不安全的条目直接跳过
    ② 读侧:   git_sync.resolve_in_workspace 校验, 越界当"没落盘" (404)
"""
from __future__ import annotations

import pytest


# ---------- ① 路径归一化 ----------

@pytest.mark.parametrize("bad", [
    "../../../app/.env",
    "..",
    "../etc/passwd",
    "skills/../../etc/passwd",
    "/etc/passwd",
    "/",
    "",
    "   ",
    "..\\..\\windows\\system32",
    "a/../../b",
])
def test_safe_rel_path_rejects_unsafe(bad):
    """危险路径一律判 None (调用方当"没落盘"处理)."""
    from app.core.git_sync import safe_rel_path

    assert safe_rel_path(bad) is None, bad


@pytest.mark.parametrize("good,want", [
    ("skills/dml-ssd", "skills/dml-ssd"),
    ("connectors/dml-log", "connectors/dml-log"),
    ("plugins/a/b/c", "plugins/a/b/c"),
    ("skills//dml-x", "skills/dml-x"),
    ("./skills/dml-x", "skills/dml-x"),
    ("skills/dml-x/", "skills/dml-x"),
])
def test_safe_rel_path_keeps_legal(good, want):
    """合法路径原样通过 (只做归一化, 不改语义)."""
    from app.core.git_sync import safe_rel_path

    assert safe_rel_path(good) == want


def test_resolve_in_workspace_blocks_escape(monkeypatch, tmp_path):
    """解析结果必须落在工作区里 —— 符号链接逃逸也挡住."""
    from app.core import git_sync

    ws = tmp_path / "ws"
    ws.mkdir()
    monkeypatch.setattr(git_sync, "WORKSPACE", ws)

    ok = git_sync.resolve_in_workspace("skills/dml-x")
    assert ok is not None
    assert ok == (ws / "skills" / "dml-x").resolve()

    assert git_sync.resolve_in_workspace("../outside") is None
    assert git_sync.resolve_in_workspace("/etc/passwd") is None


def test_resolve_in_workspace_blocks_symlink_escape(monkeypatch, tmp_path):
    """工作区里的符号链接指向外部 → 也算越界."""
    from app.core import git_sync

    ws = tmp_path / "ws"
    outside = tmp_path / "outside"
    ws.mkdir()
    outside.mkdir()
    (outside / "secret.txt").write_text("s3cret", encoding="utf-8")
    (ws / "link").symlink_to(outside)
    monkeypatch.setattr(git_sync, "WORKSPACE", ws)

    assert git_sync.resolve_in_workspace("link/secret.txt") is None


# ---------- ② 落库侧校验 ----------

async def test_apply_index_skips_unsafe_git_path(monkeypatch):
    """index.json 里带穿越路径的资产 → 不入库."""
    from app.core import market_catalog

    index = {
        "assets": [
            {"code": "dml-good", "kind": "skill", "name": "好的", "git_path": "skills/dml-good"},
            {"code": "dml-evil", "kind": "skill", "name": "坏的", "git_path": "../../../app/.env"},
        ]
    }

    async def _fake_read_index():
        return index

    monkeypatch.setattr(market_catalog, "read_index", _fake_read_index)

    from app.db.session import AsyncSessionLocal
    from app.models.asset import Asset
    from sqlalchemy import select

    async with AsyncSessionLocal() as s:
        added, updated = await market_catalog.apply_index_to_db(s)

    assert added == 1, added
    async with AsyncSessionLocal() as s:
        rows = (await s.execute(select(Asset).where(Asset.code.in_(["dml-good", "dml-evil"])))).scalars().all()
    codes = {a.code for a in rows}
    assert codes == {"dml-good"}, codes
    good = next(a for a in rows if a.code == "dml-good")
    assert good.git_path == "skills/dml-good"


# ---------- ③ 读侧: 越界的资产取不到文件 ----------

async def test_asset_files_404_when_git_path_escapes(client, admin_user):
    """DB 里已经有脏 git_path → 下载/文件列表一律 404, 不去读工作区外的文件."""
    from sqlalchemy import select

    from app.db.session import AsyncSessionLocal
    from app.models.asset import Asset

    async with AsyncSessionLocal() as s:
        a = Asset(
            code="dml-traversal",
            name="穿越探针",
            kind="skill",
            git_path="../../../app/.env",
            publish_status="published",
        )
        s.add(a)
        await s.commit()

    h = {"Authorization": f"Bearer {admin_user['token']}"}
    r1 = await client.get(f"/api/v1/assets/dml-traversal/files", headers=h)
    assert r1.status_code == 404, r1.text

    r2 = await client.get(f"/api/v1/assets/dml-traversal/bundle", headers=h)
    assert r2.status_code == 404, r2.text
