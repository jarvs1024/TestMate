"""publish_status 在「上传 → 远端 → 同步器」这条链路上的正确性.

⚠️ 这里防的是一个真 bug:
  上传时写的 manifest.json **不带** publish_status (它由 build_manifest 生成,
  只有上传表单里的字段), 而同步器读到 None 时曾**猜成 published** ——
  于是**待审核的资产会被自动改成已上架**, 审核形同虚设.
  而且只在冲突判定触发时发作 → 表现为"端到端偶发失败", 极难复现.
"""
from __future__ import annotations

import json

# 复用市场 API 测试里的上传/白名单助手 (同一批夹具)
from tests.test_market_api import _enable_publisher, _upload


# ---------- 同步器: 缺字段不猜 ----------

def test_remote_publish_status_reads_field():
    from app.core.sync_puller import _remote_publish_status

    assert _remote_publish_status({"publish_status": "pending"}) == "pending"
    assert _remote_publish_status({"publish_status": "unpublished"}) == "unpublished"


def test_remote_publish_status_returns_none_when_missing():
    """缺字段 → None (**不是** "published")."""
    from app.core.sync_puller import _remote_publish_status

    assert _remote_publish_status({}) is None
    assert _remote_publish_status({"code": "x", "version": "1.0.0"}) is None
    assert _remote_publish_status(None) is None


def test_remote_publish_status_ignores_empty_value():
    from app.core.sync_puller import _remote_publish_status

    assert _remote_publish_status({"publish_status": ""}) is None


# ---------- 上传: manifest.json 必须带 publish_status ----------

async def test_upload_writes_publish_status_into_manifest(
    client, auth, ws, restore_git_config, publisher_user,  # noqa: ARG001
):
    """上传的 manifest.json 必须带 publish_status.

    少了它, 同步器会把它猜成 published → 待审核资产自动上架.
    """
    from tests.conftest import set_setting

    await set_setting("marketplace.review.enabled", "true")
    await _enable_publisher(publisher_user)
    pauth = {"Authorization": f"Bearer {publisher_user['token']}"}
    await _upload(client, pauth, code="man-demo")

    p = ws / "assets/skills/misc/man-demo/manifest.json"
    assert p.exists(), f"manifest.json 没落盘: {p}"
    m = json.loads(p.read_text(encoding="utf-8"))
    assert m.get("publish_status") == "pending", f"manifest 缺 publish_status: {m}"


async def test_upload_manifest_publish_status_matches_db(
    client, auth, ws, restore_git_config, publisher_user,  # noqa: ARG001
):
    """manifest 里的状态必须和 DB 里的**一致** (免审时都是 published)."""
    from app.db.session import AsyncSessionLocal
    from app.models.asset import Asset
    from sqlalchemy import select as _sel
    from tests.conftest import set_setting

    await set_setting("marketplace.review.enabled", "false")
    await _enable_publisher(publisher_user)
    pauth = {"Authorization": f"Bearer {publisher_user['token']}"}
    await _upload(client, pauth, code="man-ok")

    p = ws / "assets/skills/misc/man-ok/manifest.json"
    m = json.loads(p.read_text(encoding="utf-8"))
    async with AsyncSessionLocal() as s:
        a = (await s.execute(
            _sel(Asset).where(Asset.code == "man-ok")
        )).scalar_one()
        db_status = a.publish_status
    assert m.get("publish_status") == db_status, f"manifest={m.get('publish_status')} db={db_status}"
