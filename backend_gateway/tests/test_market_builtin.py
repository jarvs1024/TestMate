"""内置 MCP 资产 + 连接器复制计数 (2026-11-04 第二十四轮).

用户要求:
  · 扩展库里有一张「内置 MCP」卡片 —— **不落 GitLab**, 静态展示,
    归类连接器 / 其他, 作者 admin, 带「内置」标签;
  · 它的 MCP 配置指向 **TestMate 自己的扩展库管理 MCP** (/mcp/skill),
    地址要**自适应生产环境** (public_base_url 优先, 否则按请求地址);
  · 连接器卡片显示「⬇ 复制次数」—— 两个复制按钮每复制成功一次 +1,
    复用 download_count (连接器的下载接口恒 400, 字段本来恒 0).
"""
from __future__ import annotations

import pytest

from tests.conftest import set_setting

API = "/api/v1/extensions"


@pytest.fixture
async def builtin_seeded():
    """种入内置资产 (lifespan 在 ASGITransport 下不跑, 手动种)."""
    from app.core.builtin_assets import ensure_builtin_asset
    from app.db.session import AsyncSessionLocal

    async with AsyncSessionLocal() as s:
        await ensure_builtin_asset(s)


@pytest.fixture
def clear_base_url_cache():
    """清掉进程内「最近一次推断的基地址」缓存 —— 别让用例互相污染."""
    from app.core.dingtalk import reset_base_url_cache

    reset_base_url_cache()
    yield
    reset_base_url_cache()


# ---------- 种子: 幂等 + 字段 ----------

async def test_ensure_builtin_creates_row(builtin_seeded):
    from sqlalchemy import select

    from app.db.session import AsyncSessionLocal
    from app.models.asset import Asset

    async with AsyncSessionLocal() as s:
        a = (
            await s.execute(select(Asset).where(Asset.code == "testmate-extensions"))
        ).scalar_one()
        assert a.kind == "mcp"
        assert a.category == "其他"
        assert a.author == "admin"
        assert a.publish_status == "published"
        assert "内置" in (a.tags or [])
        assert a.git_path == ""      # 不落 GitLab


async def test_ensure_builtin_idempotent_preserves_download_count(builtin_seeded):
    """第二次种子不重复建行, 且**保留**运行时指标 (download_count)."""
    from sqlalchemy import func, select

    from app.core.builtin_assets import ensure_builtin_asset
    from app.db.session import AsyncSessionLocal
    from app.models.asset import Asset

    async with AsyncSessionLocal() as s:
        a = (
            await s.execute(select(Asset).where(Asset.code == "testmate-extensions"))
        ).scalar_one()
        a.download_count = 42
        await s.commit()

    async with AsyncSessionLocal() as s:
        await ensure_builtin_asset(s)

    async with AsyncSessionLocal() as s:
        total = (
            await s.execute(
                select(func.count()).select_from(Asset)
                .where(Asset.code == "testmate-extensions")
            )
        ).scalar_one()
        a = (
            await s.execute(select(Asset).where(Asset.code == "testmate-extensions"))
        ).scalar_one()
        assert total == 1
        assert a.download_count == 42
        assert a.name == "TestMate 扩展库助手"   # 元信息刷回了常量


# ---------- 列表 / 详情: builtin 标记 + 自适应 MCP 配置 ----------

async def test_list_marks_builtin_and_adapts_to_public_base_url(
    client, auth, builtin_seeded,
):
    """配了 extensions.public_base_url → 配置用它的地址拼 (生产域名自适应)."""
    await set_setting("extensions.public_base_url", "https://tm.example.com/")

    r = await client.get(API, headers=auth, params={"kind": "mcp"})
    assert r.status_code == 200, r.text
    items = r.json()["items"]
    assert items, "列表里应有内置连接器"
    it = items[0]
    assert it["builtin"] is True
    assert it["author"] == "admin"
    assert it["category"] == "其他"
    assert "内置" in it["tags"]
    assert it["mcp_config"]["mcpServers"]["testmate-extensions"]["url"] == (
        "https://tm.example.com/mcp/skill"
    )


async def test_list_without_setting_falls_back_to_request_base(
    client, auth, builtin_seeded, clear_base_url_cache,
):
    """没配 public_base_url → 按「当前请求进来的地址」拼 (本机 8081 / 内网 IP 都对)."""
    r = await client.get(API, headers=auth, params={"kind": "mcp"})
    assert r.status_code == 200, r.text
    items = r.json()["items"]
    assert items
    url = items[0]["mcp_config"]["mcpServers"]["testmate-extensions"]["url"]
    assert url.startswith("http://test") and url.endswith("/mcp/skill")


async def test_get_builtin_detail(client, auth, builtin_seeded, clear_base_url_cache):
    r = await client.get(f"{API}/testmate-extensions", headers=auth)
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["builtin"] is True
    assert body["kind"] == "mcp"
    assert body["publish_status"] == "published"
    assert body["mcp_config"]["mcpServers"]["testmate-extensions"]["url"] == (
        "http://test/mcp/skill"
    )


# ---------- 复制计数 ----------

async def _make_mcp(client, auth, code="conn-x"):
    """种一个普通连接器 (走标准上传 + 免审直接上架, 不动 git).

    ⚠️ 命名契约: MCP 配置里的 server 名必须 == code.
    """
    r = await client.post(
        f"{API}/upload",
        data={
            "code": code, "kind": "mcp", "name": f"连接器-{code}", "version": "1.0.0",
            "summary": "摘要", "description": "说明", "use_when": "何时", "not_for": "何时不",
            "category": "其他", "icon": "🔌", "tags": "[]", "keywords": "[]",
            "featured": "false", "permissions": "{}", "install_steps": "[]", "bindings": "{}",
            "mcp_config": f'{{"mcpServers":{{"{code}":{{"url":"http://x/mcp"}}}}}}',
        },
        headers=auth,
    )
    assert r.status_code in (200, 202), r.text
    return r


async def test_copy_increments_download_count(client, auth, ws, restore_git_config):
    """复制一次 +1, 返回累计次数 (download_count 复用).

    ⚠️ 2026-11-05 起同一人**冷却窗口内**重复复制不再计数 (误触/刷量防护),
       详见 tests/test_count_dedup.py.
    """
    await set_setting("extensions.review.enabled", "false")
    await _make_mcp(client, auth)

    r1 = await client.post(f"{API}/conn-x/copy", headers=auth)
    assert r1.status_code == 200, r1.text
    assert r1.json() == {"code": "conn-x", "copy_count": 1}


async def test_copy_rejects_non_mcp(client, auth, ws, restore_git_config):
    await set_setting("extensions.review.enabled", "false")
    from tests.test_market_api import _upload

    r = await _upload(client, auth, code="skill-x")
    assert r.status_code in (200, 202), r.text

    rc = await client.post(f"{API}/skill-x/copy", headers=auth)
    assert rc.status_code == 400
    assert "连接器" in rc.json()["detail"]


async def test_copy_404_for_missing(client, auth):
    r = await client.post(f"{API}/nope-copy/copy", headers=auth)
    assert r.status_code == 404


# ---------- 内置资产的修改 / 删除保护 ----------

async def test_builtin_cannot_be_meta_edited(client, auth, builtin_seeded):
    r = await client.patch(
        f"{API}/testmate-extensions",
        json={"summary": "改掉它"},
        headers=auth,
    )
    assert r.status_code == 400
    assert "内置" in r.json()["detail"]


async def test_builtin_cannot_be_updated(client, auth, builtin_seeded):
    # PUT 的 Form(...) 必填项要带全 —— FastAPI 先校验表单, 再到 handler 里的内置保护
    r = await client.put(
        f"{API}/testmate-extensions",
        data={
            "kind": "mcp", "name": "改名", "summary": "摘要", "version": "2.0.0",
            "mcp_config": '{"mcpServers":{"x":{"url":"http://x"}}}',
        },
        headers=auth,
    )
    assert r.status_code == 400
    assert "内置" in r.json()["detail"]


async def test_builtin_cannot_be_deleted(client, auth, builtin_seeded):
    r = await client.delete(f"{API}/testmate-extensions", headers=auth)
    assert r.status_code == 400
    assert "内置" in r.json()["detail"]


# ---------- 同步器跳过内置 code ----------

async def test_sync_index_cannot_overwrite_builtin(builtin_seeded, ws):
    """远端 index.json 里**故意**带一条同 code 的脏数据 → 跳过, 不覆盖内置行."""
    from app.core import market_catalog

    entry = {
        "code": "testmate-extensions", "name": "冒名顶替", "kind": "mcp",
        "version": "9.9.9", "summary": "s", "description": "d",
        "use_when": "", "not_for": "", "category": "misc", "project": "",
        "tags": [], "keywords": [], "author": "hacker", "featured": False,
        "homepage": None, "permissions": {}, "install_steps": [],
        "bindings": {}, "git_path": "assets/mcp/misc/testmate-extensions",
        "git_commit_sha": "abc", "download_count": 0, "updated_at": None,
        "sync_status": "pushed", "publish_status": "published",
        "pending_action": "", "review_note": "", "mcp_config": {
            "mcpServers": {"evil": {"url": "http://evil.example/mcp"}},
        },
    }
    market_catalog.write_index([entry])

    from sqlalchemy import select

    from app.db.session import AsyncSessionLocal
    from app.models.asset import Asset

    async with AsyncSessionLocal() as s:
        await market_catalog.apply_index_to_db(s)

    async with AsyncSessionLocal() as s:
        a = (
            await s.execute(select(Asset).where(Asset.code == "testmate-extensions"))
        ).scalar_one()
        assert a.name == "TestMate 扩展库助手"     # 没被 index 覆盖
        assert a.author == "admin"
        assert a.mcp_config is None                 # 配置仍动态生成, 没被写入
        assert a.git_path == ""                     # 仍不落 GitLab
