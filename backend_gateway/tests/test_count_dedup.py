"""第二十五轮: 下载/复制计数冷却窗口去重 (2026-11-05).

背景: 同一个人反复下载/复制 (误触、重试或恶意连点) 会把 download_count 刷虚高.
方案 (用户拍板):
  · **冷却窗口去重** —— 同一 dedup_key (u:{用户id} 或 ip:{客户端IP}) 在
    1 小时 (DEDUP_WINDOW_SECONDS) 内对同一目标只计 1 次, 之后照常计数.
  · **匿名下载按 IP 去重** (X-Forwarded-For 第一跳; 裸机 nginx 反代下
    request.client 恒为 127.0.0.1, 必须看转发头).
  · 软件库**条目计数**按 (key, code) 去重, **版本计数**按 (key, code@版本)
    各自独立 —— 同一人一小时内下同一软件的两个版本, 条目只计 1 次,
    两个版本各计 1 次.
  · 去重表 count_marks: (code, dedup_key) 唯一, 只存 last_counted_at,
    一行一对, 表永不膨胀.
"""
from __future__ import annotations

import asyncio
import time
from datetime import datetime, timedelta

import pytest
from jose import jwt
from sqlalchemy import select, update

from app.core.config import settings
from app.core.count_dedup import bump_count, user_key
from app.db.session import AsyncSessionLocal
from tests.conftest import set_setting

API = "/api/v1/extensions"
SW = "/api/v1/software"


async def _backdate_mark(code: str, dedup_key: str, seconds: int) -> None:
    """把去重标记拨回过去 —— 模拟冷却窗口已过."""
    from app.models.count import CountMark

    async with AsyncSessionLocal() as s:
        await s.execute(
            update(CountMark)
            .where(CountMark.code == code, CountMark.dedup_key == dedup_key)
            .values(last_counted_at=datetime.utcnow() - timedelta(seconds=seconds))
        )
        await s.commit()


# ---------- bump_count 核心 ----------

async def test_bump_first_counts_then_window_repeat_skips():
    """第一次 True, 窗口内重复 False."""
    async with AsyncSessionLocal() as s:
        assert await bump_count(s, "unit-demo", "u:1") is True
        await s.commit()
        assert await bump_count(s, "unit-demo", "u:1") is False


async def test_bump_counts_again_after_window():
    """窗口过了再计 —— 冷却窗口是"窗口", 不是"永不再计"."""
    async with AsyncSessionLocal() as s:
        assert await bump_count(s, "unit-demo", "u:1") is True
        await s.commit()
    await _backdate_mark("unit-demo", "u:1", 7200)
    async with AsyncSessionLocal() as s:
        assert await bump_count(s, "unit-demo", "u:1") is True
        await s.commit()


async def test_bump_different_keys_do_not_dedupe_each_other():
    """不同的人/不同目标互不去重."""
    async with AsyncSessionLocal() as s:
        assert await bump_count(s, "unit-demo", "u:1") is True
        assert await bump_count(s, "unit-demo", "u:2") is True
        assert await bump_count(s, "unit-other", "u:1") is True
        await s.commit()


async def test_bump_concurrent_calls_only_one_counts():
    """两个并发请求同一 key —— 唯一索引兜底, 恰好一个 True."""

    async def one() -> bool:
        async with AsyncSessionLocal() as s:
            ok = await bump_count(s, "unit-race", "u:9")
            await s.commit()
            return ok

    a, b = await asyncio.gather(one(), one())
    assert sorted([a, b]) == [False, True]


# ---------- 市场: 复制计数 ----------

@pytest.fixture
async def mcp_conn(ws, restore_git_config, client, auth):  # noqa: ARG001
    from tests.test_market_builtin import _make_mcp

    await set_setting("extensions.review.enabled", "false")
    await _make_mcp(client, auth, code="conn-x")


async def test_copy_same_user_repeat_within_window_counts_once(client, auth, mcp_conn):  # noqa: ARG001
    """同一人窗口内复制两次 → 只 +1 (第二下是误触/重试, 不该涨)."""
    r1 = await client.post(f"{API}/conn-x/copy", headers=auth)
    assert r1.status_code == 200, r1.text
    assert r1.json() == {"code": "conn-x", "copy_count": 1}

    r2 = await client.post(f"{API}/conn-x/copy", headers=auth)
    assert r2.status_code == 200, r2.text
    assert r2.json()["copy_count"] == 1


async def test_copy_counts_again_after_window(client, auth, mcp_conn, admin_user):  # noqa: ARG001
    """窗口过了再复制 → 照常 +1."""
    r1 = await client.post(f"{API}/conn-x/copy", headers=auth)
    assert r1.json()["copy_count"] == 1

    await _backdate_mark("conn-x", user_key(admin_user["id"]), 7200)

    r2 = await client.post(f"{API}/conn-x/copy", headers=auth)
    assert r2.json()["copy_count"] == 2


async def test_copy_different_users_each_count(
    client, auth, mcp_conn, stranger_user,  # noqa: ARG001
):
    """不同的人各复制一次 → 各计一次."""
    r1 = await client.post(f"{API}/conn-x/copy", headers=auth)
    assert r1.json()["copy_count"] == 1

    sauth = {"Authorization": f"Bearer {stranger_user['token']}"}
    r2 = await client.post(f"{API}/conn-x/copy", headers=sauth)
    assert r2.json()["copy_count"] == 2


# ---------- 市场: 下载 ----------

async def test_market_download_same_user_repeat_counts_once_and_still_serves(
    client, auth, ws, restore_git_config,  # noqa: ARG001
):
    """同一人窗口内下两次 → 计数只 +1, 但**每次都照常出包**."""
    from tests.test_market_api import _upload

    await set_setting("extensions.review.enabled", "false")
    await _upload(client, auth, code="dl-demo")

    url = f"{API}/dl-demo/versions/1.0.0/download"
    r1 = await client.get(url, headers=auth)
    assert r1.status_code == 200, r1.text
    assert r1.content[:2] == b"PK"

    r2 = await client.get(url, headers=auth)
    assert r2.status_code == 200, r2.text
    assert r2.content[:2] == b"PK"

    async with AsyncSessionLocal() as s:
        from app.models.asset import Asset

        a = (await s.execute(select(Asset).where(Asset.code == "dl-demo"))).scalar_one()
        assert a.download_count == 1, a.download_count


async def test_market_anon_download_dedup_by_ip(client, auth, ws, restore_git_config):  # noqa: ARG001
    """匿名下载按 IP 去重: 同 IP 窗口内只 +1, 换 IP 照计."""
    from tests.test_market_api import _upload

    await set_setting("extensions.review.enabled", "false")
    await set_setting("extensions.public_download", "true")
    await _upload(client, auth, code="dl-anon")

    url = f"{API}/dl-anon/versions/1.0.0/download"
    h1 = {"X-Forwarded-For": "10.1.2.3"}
    h2 = {"X-Forwarded-For": "10.1.2.4"}

    r1 = await client.get(url, headers=h1)
    assert r1.status_code == 200, r1.text
    r2 = await client.get(url, headers=h1)
    assert r2.status_code == 200, r2.text
    r3 = await client.get(url, headers=h2)
    assert r3.status_code == 200, r3.text

    async with AsyncSessionLocal() as s:
        from app.models.asset import Asset

        a = (await s.execute(select(Asset).where(Asset.code == "dl-anon"))).scalar_one()
        assert a.download_count == 2, a.download_count


def _asset_ticket(*, uid: int, code: str, version: str, ttl_seconds: int = 600) -> str:
    claims = {
        "typ": "asset-dl",
        "uid": uid,
        "code": code,
        "ver": version,
        "exp": datetime.utcnow() + timedelta(seconds=ttl_seconds),
    }
    return jwt.encode(claims, settings.JWT_SECRET, algorithm=settings.JWT_ALGORITHM)


async def test_market_ticket_download_dedup_by_uid(
    client, auth, ws, restore_git_config, admin_user,  # noqa: ARG001
):
    """票下载按票里的 uid 去重 (同一人窗口内只计一次)."""
    from tests.test_market_api import _upload

    await set_setting("extensions.review.enabled", "false")
    await _upload(client, auth, code="dl-ticket")

    ticket = _asset_ticket(uid=admin_user["id"], code="dl-ticket", version="1.0.0")
    url = f"{API}/dl-ticket/versions/1.0.0/ticket-download"
    r1 = await client.get(url, params={"ticket": ticket})
    assert r1.status_code == 200, r1.text
    r2 = await client.get(url, params={"ticket": ticket})
    assert r2.status_code == 200, r2.text

    async with AsyncSessionLocal() as s:
        from app.models.asset import Asset

        a = (await s.execute(select(Asset).where(Asset.code == "dl-ticket"))).scalar_one()
        assert a.download_count == 1, a.download_count


# ---------- 软件库: 下载 ----------

@pytest.fixture
async def sw_root(tmp_path):
    root = tmp_path / "software"
    root.mkdir(parents=True, exist_ok=True)
    await set_setting("software.storage_path", str(root))
    return root


@pytest.fixture
async def sw_auth(admin_user):
    return {"Authorization": f"Bearer {admin_user['token']}"}


async def _sw_create(client, auth, code="demo-sw", **over):
    payload = {
        "code": code, "name": "演示软件", "version": "1.0.0",
        "summary": "一句话说明", "features": ["功能一"],
        "use_when": "该用它的时候", "not_for": "不该用它的时候",
        "platform": "linux", "category": "工具", "tags": ["演示"],
        "keywords": ["demo"], "file_name": "demo.bin", "file_size": 0,
        "release_notes": "首个版本",
    }
    payload.update(over)
    r = await client.post(SW, json=payload, headers=auth)
    assert r.status_code == 201, r.text
    return r.json()


async def _sw_upload(client, auth, code, content=b"hello", filename="demo.bin"):
    headers = {**auth, "Content-Type": "application/octet-stream", "X-File-Name": filename}
    r = await client.put(f"{SW}/{code}/file", content=content, headers=headers)
    assert r.status_code == 200, r.text


async def _sw_new_version(client, auth, code, version, filename, *, is_default=None):
    body = {"version": version, "release_notes": "", "file_name": filename}
    if is_default is not None:
        body["is_default"] = is_default
    r = await client.post(f"{SW}/{code}/versions", json=body, headers=auth)
    assert r.status_code == 201, r.text


async def _sw_detail(client, auth, code) -> dict:
    r = await client.get(f"{SW}/{code}", headers=auth)
    assert r.status_code == 200, r.text
    return r.json()


async def test_sw_ticket_download_same_user_repeat_counts_once(client, sw_auth, sw_root):  # noqa: ARG001
    """同一人窗口内凭票下两次 → 条目和版本都只 +1."""
    await _sw_create(client, sw_auth)
    await _sw_upload(client, sw_auth, "demo-sw", b"v1")

    t = await client.post(f"{SW}/demo-sw/download-ticket", headers=sw_auth)
    url = t.json()["url"]
    r1 = await client.get(url)
    assert r1.status_code == 200, r1.text
    r2 = await client.get(url)
    assert r2.status_code == 200, r2.text

    d = await _sw_detail(client, sw_auth, "demo-sw")
    assert d["download_count"] == 1, d["download_count"]
    assert d["versions"][0]["download_count"] == 1, d["versions"]


async def test_sw_two_versions_same_user_item_once_versions_each(client, sw_auth, sw_root):  # noqa: ARG001
    """同一人窗口内下两个版本 → 条目只 +1, 两个版本各 +1."""
    await _sw_create(client, sw_auth)
    await _sw_upload(client, sw_auth, "demo-sw", b"v1")
    await _sw_new_version(client, sw_auth, "demo-sw", "2.0.0", "v2.bin", is_default=False)
    await _sw_upload(client, sw_auth, "demo-sw", b"v2-bytes", filename="v2.bin")

    t1 = await client.post(
        f"{SW}/demo-sw/download-ticket", params={"version": "1.0.0"}, headers=sw_auth
    )
    t2 = await client.post(
        f"{SW}/demo-sw/download-ticket", params={"version": "2.0.0"}, headers=sw_auth
    )
    assert (await client.get(t1.json()["url"])).status_code == 200
    assert (await client.get(t2.json()["url"])).status_code == 200

    d = await _sw_detail(client, sw_auth, "demo-sw")
    by_version = {v["version"]: v["download_count"] for v in d["versions"]}
    assert d["download_count"] == 1, d["download_count"]
    assert by_version["1.0.0"] == 1, by_version
    assert by_version["2.0.0"] == 1, by_version


async def test_sw_fixed_links_dedup_by_ip(client, sw_auth, sw_root):  # noqa: ARG001
    """固定链接 (纯匿名) 按 IP 去重: 同 IP 窗口内只 +1, 换 IP 照计;
    code 链接和别名链接指向同一软件 → 共用一个去重窗口."""
    await _sw_create(client, sw_auth)
    await _sw_upload(client, sw_auth, "demo-sw", b"v1")

    h1 = {"X-Forwarded-For": "10.9.9.1"}
    h2 = {"X-Forwarded-For": "10.9.9.2"}

    r1 = await client.get(f"{SW}/demo-sw/download", headers=h1)
    assert r1.status_code == 200, r1.text
    r2 = await client.get(f"{SW}/demo-sw/download", headers=h1)
    assert r2.status_code == 200, r2.text
    # 别名链接 + 同 IP → 同一个软件, 窗口内不再计
    r3 = await client.get(f"{SW}/alias/demo-sw/download", headers=h1)
    assert r3.status_code == 200, r3.text
    # 换 IP → 照计
    r4 = await client.get(f"{SW}/alias/demo-sw/download", headers=h2)
    assert r4.status_code == 200, r4.text

    d = await _sw_detail(client, sw_auth, "demo-sw")
    assert d["download_count"] == 2, d["download_count"]
    assert d["versions"][0]["download_count"] == 2, d["versions"]


async def test_sw_anon_ticket_download_dedup_by_ip(client, sw_auth, sw_root):  # noqa: ARG001
    """匿名票下载 (software.public_download) 按 IP 去重."""
    await _sw_create(client, sw_auth)
    await _sw_upload(client, sw_auth, "demo-sw", b"v1")
    await set_setting("software.public_download", "true")

    h1 = {"X-Forwarded-For": "10.9.8.1"}
    h2 = {"X-Forwarded-For": "10.9.8.2"}
    t = await client.post(f"{SW}/demo-sw/download-ticket", headers=h1)
    assert t.status_code == 200, t.text
    url = t.json()["url"]

    assert (await client.get(url, headers=h1)).status_code == 200
    assert (await client.get(url, headers=h1)).status_code == 200
    assert (await client.get(url, headers=h2)).status_code == 200

    d = await _sw_detail(client, sw_auth, "demo-sw")
    assert d["download_count"] == 2, d["download_count"]
