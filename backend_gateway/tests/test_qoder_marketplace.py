"""Qoder 原生 marketplace.json 单元测试."""
from __future__ import annotations

import json

import pytest

from app.core import pkg, qoder_marketplace as qm


async def _mk_asset(session, code: str, kind: str = "plugin",
                    publish_status: str = "published", version: str = "1.0.0"):
    """建一个资产, 并在工作区里放上它的内容文件 (否则 marketplace 会因无包而跳过)."""
    from app.models.asset import Asset

    git_path = f"assets/plugins/auto-code/{code}"
    files = _WS / git_path / "files"
    files.mkdir(parents=True, exist_ok=True)
    (files / "README.md").write_text(f"# {code}\n", encoding="utf-8")

    a = Asset(
        code=code, name=f"资产-{code}", kind=kind, version=version,
        summary="摘要", publish_status=publish_status, git_path=git_path,
    )
    session.add(a)
    await session.commit()
    await session.refresh(a)
    return a


@pytest.fixture
def ws_files(ws):
    """把工作区路径给 _mk_asset 用 (造出真实的包内容)."""
    global _WS
    _WS = ws
    return ws


_WS = None


async def test_marketplace_only_contains_published_plugins(ws_files, restore_git_config):  # noqa: ARG001
    from app.db.session import AsyncSessionLocal

    async with AsyncSessionLocal() as s:
        await _mk_asset(s, "pub-plugin")
        await _mk_asset(s, "pending-plugin", publish_status="pending")
        await _mk_asset(s, "unpub-plugin", publish_status="unpublished")
        await _mk_asset(s, "a-skill", kind="skill")
        await _mk_asset(s, "a-conn", kind="mcp")

    m = await qm.build_marketplace("http://test", name="testmate")
    codes = [p["name"] for p in m["plugins"]]
    assert codes == ["pub-plugin"], f"只应收 published 的 plugin, 实际 {codes}"


async def test_marketplace_structure_and_sha(ws_files, restore_git_config):  # noqa: ARG001
    """sha256 必须与实际下载到的字节一致 —— Qoder 会拿它校验包."""
    from app.db.session import AsyncSessionLocal

    base = ws_files / "assets/plugins/auto-code/sha-demo"
    (base / "files").mkdir(parents=True, exist_ok=True)
    (base / "files" / "README.md").write_text("# 插件\n", encoding="utf-8")

    async with AsyncSessionLocal() as s:
        await _mk_asset(s, "sha-demo")

    m = await qm.build_marketplace("http://test", name="testmate")
    assert m["name"] == "testmate"
    assert m["owner"]["name"]
    p = m["plugins"][0]
    assert set(p) >= {"name", "description", "version", "author", "source"}
    assert p["source"]["source"] == "archive"
    assert p["source"]["url"].endswith(
        "/api/v1/assets/sha-demo/versions/1.0.0/download"
    )
    # 现算一次包字节, sha 必须一致
    data = pkg.build_zip(base / "files")
    assert p["source"]["sha256"] == pkg.sha256_bytes(data)


async def test_marketplace_skips_asset_without_package(ws_files, restore_git_config):  # noqa: ARG001
    """没有内容文件的资产 → 跳过, 不能生成指向 404 的下载链接."""
    from app.db.session import AsyncSessionLocal

    from app.models.asset import Asset

    async with AsyncSessionLocal() as s:
        a = Asset(
            code="no-files", name="无包", kind="plugin", version="1.0.0",
            publish_status="published", git_path="assets/plugins/auto-code/no-files",
        )
        s.add(a)
        await s.commit()

    m = await qm.build_marketplace("http://test", name="testmate")
    assert m["plugins"] == []


def test_render_is_valid_json():
    m = {"name": "x", "owner": {"name": "y"}, "plugins": []}
    out = qm.render(m)
    assert json.loads(out) == m
    assert "插件" not in out  # 中文不该出现在 key 里 (只是确保能正常序列化)
