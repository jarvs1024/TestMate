"""第二十二轮: 软件的**固定**下载链接 (2026-11-03).

⚠️ 用户要求:
   「增加一个下载链接, 比如可以用wget命令就能下载的, 但是软件上架后链接要固定不变,
     不能随着版本变化, 多个版本, 默认设置为推荐的链接, 目的是使用者用wget能根据固定
     连接下载最新的版本(推荐的版本), 以后版本更新后链接也不变」

⚠️ 为什么以前做不到: 下载走 `GET /software/dl?t=<10 分钟短时票>&v=<版本>` ——
   票会过期、URL 里带版本号 → 贴到别的软件里过一阵就失效.

✅ 新增 `GET /api/v1/software/{code}/download`:
   · **免登录** (wget 默认不带 Authorization 头) —— 用户拍板的取舍
   · **只对已上架**的软件开放 (未上架/已下架 → 404)
   · 永远返回**推荐版本** (is_default), 没有推荐才取时间上最新的 ready 版本
   · URL **永不变** —— 发新版本、换推荐版本都还是它
"""
from __future__ import annotations

import hashlib

import pytest

from tests.conftest import set_setting


# ---------- 夹具 ----------

@pytest.fixture
async def sw_root(tmp_path):
    root = tmp_path / "software"
    root.mkdir(parents=True, exist_ok=True)
    await set_setting("software.storage_path", str(root))
    return root


@pytest.fixture
async def sw_auth(admin_user):
    return {"Authorization": f"Bearer {admin_user['token']}"}


async def _create(client, auth, **over):
    payload = {
        "code": "demo-sw",
        "name": "演示软件",
        "version": "1.0.0",
        "summary": "一句话说明",
        "features": ["功能一"],
        "use_when": "该用它的时候",
        "not_for": "不该用它的时候",
        "platform": "linux",
        "category": "工具",
        "tags": ["演示"],
        "keywords": ["demo"],
        "file_name": "demo.bin",
        "file_size": 0,
        "release_notes": "首个版本",
    }
    payload.update(over)
    r = await client.post("/api/v1/software", json=payload, headers=auth)
    assert r.status_code == 201, r.text
    return r.json()


async def _upload(client, auth, code, content=b"hello", filename="demo.bin"):
    headers = {
        **auth,
        "Content-Type": "application/octet-stream",
        "X-File-Name": filename,
    }
    return await client.put(f"/api/v1/software/{code}/file", content=content, headers=headers)


async def _new_version(client, auth, code, version, filename, *, is_default=None, notes=""):
    body = {"version": version, "release_notes": notes, "file_name": filename}
    if is_default is not None:
        body["is_default"] = is_default
    r = await client.post(f"/api/v1/software/{code}/versions", json=body, headers=auth)
    assert r.status_code == 201, r.text


# ⚠️ 2026-11-04 (第二十四轮): 固定链接改用**下载别名** (与版本号无关).
#    按 code 的那个端点**仍然保留** —— 已经贴到别的软件里的地址不能废.
FIXED_URL = "/api/v1/software/alias/demo-sw/download"
LEGACY_CODE_URL = "/api/v1/software/demo-sw/download"


# ---------- 核心: 免登录 + 固定 ----------

async def test_fixed_download_url_needs_no_login(client, sw_auth, sw_root):
    """**免登录** —— wget 不带 Authorization 头, 所以这条链接必须能直接下."""
    await _create(client, sw_auth)
    await _upload(client, sw_auth, "demo-sw", b"hello world")

    r = await client.get(FIXED_URL)          # ⚠️ 故意**不带** auth 头
    assert r.status_code == 200, r.text
    assert r.content == b"hello world"


async def test_legacy_code_url_still_works(client, sw_auth, sw_root):
    """⚠️ 2026-11-04 (第二十四轮): 旧的按 code 的链接**不能废**.

    已经贴到别的软件/脚本里的地址还在用 —— 加别名是**新增**, 不是替换.
    """
    await _create(client, sw_auth)
    await _upload(client, sw_auth, "demo-sw", b"hello world")

    r = await client.get(LEGACY_CODE_URL)    # ⚠️ 不带 auth 头
    assert r.status_code == 200, r.text
    assert r.content == b"hello world"


async def test_fixed_download_returns_recommended_version(client, sw_auth, sw_root):
    """给的是**推荐版本** —— 跟页面上「⬇ 下载」按钮下的那个一致."""
    await _create(client, sw_auth, version="1.0.0")
    await _upload(client, sw_auth, "demo-sw", b"v1")
    await _new_version(client, sw_auth, "demo-sw", "2.0.0", "v2.bin", is_default=False)
    await _upload(client, sw_auth, "demo-sw", b"v2-bytes", filename="v2.bin")

    # 1.0.0 是推荐 (建条目时它默认就是推荐)
    d = (await client.get("/api/v1/software/demo-sw", headers=sw_auth)).json()
    assert d["download_version"] == "1.0.0"

    r = await client.get(FIXED_URL)
    assert r.status_code == 200, r.text
    assert r.content == b"v1"
    assert r.headers.get("x-software-version") == "1.0.0"


async def test_fixed_download_falls_back_to_latest_ready(client, sw_auth, sw_root):
    """没有推荐版本时 → 退回时间上最新的 ready 版本."""
    await _create(client, sw_auth, version="1.0.0")
    await _upload(client, sw_auth, "demo-sw", b"v1")
    await _new_version(client, sw_auth, "demo-sw", "2.0.0", "v2.bin", is_default=False)
    await _upload(client, sw_auth, "demo-sw", b"v2-bytes", filename="v2.bin")

    # 把唯一的推荐摘掉 (PATCH is_default=false)
    r = await client.patch(
        "/api/v1/software/demo-sw/versions/1.0.0", json={"is_default": False}, headers=sw_auth
    )
    assert r.status_code == 200, r.text

    d = (await client.get("/api/v1/software/demo-sw", headers=sw_auth)).json()
    assert d["download_version"] == "2.0.0"

    r2 = await client.get(FIXED_URL)
    assert r2.status_code == 200, r2.text
    assert r2.content == b"v2-bytes"


async def test_fixed_url_never_changes_but_content_follows_recommended(
    client, sw_auth, sw_root
):
    """⚠️ **链接永不变**, 但内容跟着推荐版本走 —— 这正是用户要的语义."""
    await _create(client, sw_auth, version="1.0.0")
    await _upload(client, sw_auth, "demo-sw", b"v1")

    url_before = (await client.get("/api/v1/software/demo-sw", headers=sw_auth)).json()[
        "fixed_download_url"
    ]

    # 发新版本 (默认接管推荐位)
    await _new_version(client, sw_auth, "demo-sw", "2.0.0", "v2.bin")
    await _upload(client, sw_auth, "demo-sw", b"v2-bytes", filename="v2.bin")

    d = (await client.get("/api/v1/software/demo-sw", headers=sw_auth)).json()
    url_after = d["fixed_download_url"]
    # ⚠️ URL 一个字都没变
    assert url_after == url_before == FIXED_URL
    # 但内容跟着推荐版本走了
    assert d["download_version"] == "2.0.0"
    r = await client.get(FIXED_URL)
    assert r.content == b"v2-bytes"

    # 手动把推荐切回 1.0.0 → 内容跟着切回去, URL 还是那个
    await client.patch(
        "/api/v1/software/demo-sw/versions/1.0.0", json={"is_default": True}, headers=sw_auth
    )
    d2 = (await client.get("/api/v1/software/demo-sw", headers=sw_auth)).json()
    assert d2["fixed_download_url"] == FIXED_URL
    assert (await client.get(FIXED_URL)).content == b"v1"


async def test_fixed_url_has_no_version_in_it(client, sw_auth, sw_root):
    """URL 里**不能有版本号** —— 版本会变, 链接不能变."""
    await _create(client, sw_auth, version="1.2.3")
    await _upload(client, sw_auth, "demo-sw", b"hello")
    d = (await client.get("/api/v1/software/demo-sw", headers=sw_auth)).json()
    assert "1.2.3" not in d["fixed_download_url"]
    # ⚠️ 2026-11-04: 链接走**下载别名** → URL 里没有版本号, 也没有 code
    assert d["fixed_download_url"].endswith("/api/v1/software/alias/demo-sw/download")


async def test_fixed_download_increments_counter(client, sw_auth, sw_root):
    """下载次数照常 +1 (固定链接也是下载)."""
    await _create(client, sw_auth)
    await _upload(client, sw_auth, "demo-sw", b"hello")
    before = (await client.get("/api/v1/software/demo-sw", headers=sw_auth)).json()
    assert before["download_count"] == 0

    await client.get(FIXED_URL)
    after = (await client.get("/api/v1/software/demo-sw", headers=sw_auth)).json()
    assert after["download_count"] == 1


async def test_fixed_download_filename_is_code_plus_real_suffix(client, sw_auth, sw_root):
    """文件名 = {code}{真实后缀} —— 不带版本号, 后缀跟内容走."""
    await _create(client, sw_auth, file_name="demo-sw-1.2.3.tar.gz")
    await _upload(client, sw_auth, "demo-sw", b"tgz-bytes", filename="demo-sw-1.2.3.tar.gz")

    r = await client.get(FIXED_URL)
    assert r.status_code == 200, r.text
    cd = r.headers.get("content-disposition", "")
    assert "demo-sw.tar.gz" in cd, cd
    assert "1.2.3" not in cd


async def test_fixed_download_rejects_unpublished(client, sw_auth, sw_root):
    """⚠️ **只对已上架**的软件开放 —— 内部工具不该被一条裸链接带出去."""
    await _create(client, sw_auth)
    await _upload(client, sw_auth, "demo-sw", b"hello")
    # 下架 (DELETE 条目 → publish_status=hidden, 文件还在)
    r = await client.delete("/api/v1/software/demo-sw", headers=sw_auth)
    assert r.status_code == 200, r.text

    d = await client.get(FIXED_URL)
    assert d.status_code == 404, d.text


async def test_fixed_download_404_for_unknown_code(client, sw_auth, sw_root):
    """没有这个软件 → 404."""
    r = await client.get("/api/v1/software/no-such-sw/download")
    assert r.status_code == 404, r.text


async def test_fixed_download_404_when_no_file(client, sw_auth, sw_root):
    """条目建了但文件还没传 → 没有可下的东西."""
    await _create(client, sw_auth)
    r = await client.get(FIXED_URL)
    assert r.status_code == 404, r.text


async def test_fixed_download_url_absent_for_unpublished(client, sw_auth, sw_root):
    """未上架的软件, 详情里**不返回**固定链接."""
    await _create(client, sw_auth)
    d = (await client.get("/api/v1/software/demo-sw", headers=sw_auth)).json()
    # 还没传文件 → 没有可下载的版本 → 没有固定链接
    assert d["fixed_download_url"] == ""


async def test_fixed_download_url_uses_public_base_url_setting(client, sw_auth, sw_root):
    """配了 `software.public_base_url` → 给绝对地址 (别的机器 wget 要用)."""
    await set_setting("software.public_base_url", "https://tm.internal")
    await _create(client, sw_auth)
    await _upload(client, sw_auth, "demo-sw", b"hello")
    d = (await client.get("/api/v1/software/demo-sw", headers=sw_auth)).json()
    assert d["fixed_download_url"] == "https://tm.internal/api/v1/software/alias/demo-sw/download"
    assert d["fixed_download_name"] == "demo-sw.bin"
