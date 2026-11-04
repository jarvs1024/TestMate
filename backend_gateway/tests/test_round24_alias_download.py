"""第二十四轮: 永久下载别名 + 剪贴板降级 (2026-11-04).

⚠️ 用户报的两件事:

  ① 「生产环境部署后 http://10.20.65.25:8090/api/v1/software/aitestx-v2.1/download
      这个地址要是更新了版本变成了 V2.1 这个地址会变么? 变了就不是固定地址了」

     —— 用户担心 URL 里的版本号. 真相:
        · code 是从**上传文件名**派生的 → `aitestx-v2.1.zip` → code `aitestx-v2.1`
        · 走「发新版本」时 code 不变 → 链接**不会**变
        · 但走「**重新上架一个新包**」(文件名 `aitestx-v2.2.zip`) 时会派生出
          **新 code** → 新条目 → 旧链接 404
        用户没法区分这两种操作 → 链接必须**从结构上**就不含版本号.

     ✅ 新增 `download_alias` (下载别名): 从 code 剥掉版本号后缀派生
        (`aitestx-v2.1` → `aitestx`), **创建后永不改变**、全局唯一.
     ✅ 新增 `GET /api/v1/software/alias/{alias}/download` —— URL 里没有版本号.
     ⚠️ 旧的 `/api/v1/software/{code}/download` **保留** —— 已经贴到别的软件里的
        地址不能因为加别名就断.

  ② 「部署后, 复制地址和复制命令, 提示复制失败 —— 请手动选中复制」

     —— 根因: 剪贴板 API **只在安全上下文可用** (HTTPS / localhost).
        现网是 `http://10.20.65.25:8090` (内网 IP + 明文 HTTP) →
        `window.isSecureContext === false` → `navigator.clipboard` 是
        **undefined** → `navigator.clipboard.writeText(...)` 抛 TypeError →
        页面一律提示"复制失败".
        ⚠️ 本地开发 (localhost) 是安全上下文 → **本地测不出来**, 一上生产就翻车.
     ✅ 前端加 `utils/clipboard.ts` —— 剪贴板 API 不可用时降级到
        `document.execCommand('copy')` (任何上下文都能用).
"""
from __future__ import annotations

import pytest

from app.core.software_store import alias_from_code
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


# ---------- 别名派生 ----------

class TestAliasDerivation:
    """别名 = 从 code 剥掉版本号后缀 —— 剥错了比不剥更糟."""

    @pytest.mark.parametrize(
        "code,expected",
        [
            # ⚠️ 用户报的那个真实例子
            ("aitestx-v2.1", "aitestx"),
            ("aitestx-v2.10", "aitestx"),
            ("aitestx-v2", "aitestx"),
            ("aitestx-v1.2.3", "aitestx"),
            # 本来就没有版本号 → 原样
            ("aitestx", "aitestx"),
            ("ssd-log-doctor", "ssd-log-doctor"),
            ("e2e-sw-mvto3fei", "e2e-sw-mvto3fei"),
            # ⚠️ 数字段**不是**版本号 (文件名 img_6659.png 的 6659 是图片序号)
            ("img_6659", "img_6659"),
            # 变体标签不是版本号
            ("foo-beta", "foo-beta"),
            ("tool-x64", "tool-x64"),
        ],
    )
    def test_alias_strips_version_suffix(self, code, expected):
        assert alias_from_code(code) == expected

    def test_alias_never_contains_a_version(self):
        """核心承诺: 别名里**没有版本号** → URL 里也不会有."""
        for code in ("aitestx-v2.1", "aitestx-v2.10", "aitestx-v3"):
            alias = alias_from_code(code)
            assert not alias.endswith(("-v2.1", "-v2.10", "-v3"))
            assert alias == "aitestx"


# ---------- 别名分配 ----------

async def test_new_item_gets_an_alias(client, sw_auth, sw_root):
    """新建条目 → 自动分配别名."""
    await _create(client, sw_auth)
    d = (await client.get("/api/v1/software/demo-sw", headers=sw_auth)).json()
    assert d["download_alias"] == "demo-sw"


async def test_alias_strips_version_from_filename_derived_code(client, sw_auth, sw_root):
    """⚠️ 用户的真实场景: 文件名 `aitestx-v2.1.zip` → code 带版本号, 但别名不带."""
    await _create(client, sw_auth, code="", file_name="aitestx-v2.1.zip")
    d = (await client.get("/api/v1/software/aitestx-v2.1", headers=sw_auth)).json()
    assert d["code"] == "aitestx-v2.1"
    assert d["download_alias"] == "aitestx"


async def test_alias_is_unique(client, sw_auth, sw_root):
    """别名撞名 → 自动加序号 (不能两个软件抢同一个别名)."""
    # ⚠️ 图标也不能重复 (后端既有规则) —— 第二个换个图标
    await _create(client, sw_auth, code="", file_name="tool-v1.0.zip", icon="🔧")
    await _create(client, sw_auth, code="", file_name="tool-v2.0.zip", icon="🛠")
    a = (await client.get("/api/v1/software/tool-v1.0", headers=sw_auth)).json()
    b = (await client.get("/api/v1/software/tool-v2.0", headers=sw_auth)).json()
    assert a["download_alias"] == "tool"
    assert b["download_alias"] == "tool2"
    assert a["download_alias"] != b["download_alias"]


# ---------- 别名下载端点 ----------

async def test_alias_download_needs_no_login(client, sw_auth, sw_root):
    """**免登录** —— wget 不带 Authorization 头."""
    await _create(client, sw_auth, code="", file_name="aitestx-v2.1.zip")
    await _upload(client, sw_auth, "aitestx-v2.1", b"hello world", filename="aitestx-v2.1.zip")

    r = await client.get("/api/v1/software/alias/aitestx/download")   # ⚠️ 不带 auth
    assert r.status_code == 200, r.text
    assert r.content == b"hello world"


async def test_alias_url_has_no_version_number(client, sw_auth, sw_root):
    """⚠️ 用户的核心诉求: 链接里**不带版本号**."""
    await _create(client, sw_auth, code="", file_name="aitestx-v2.1.zip")
    await _upload(client, sw_auth, "aitestx-v2.1", b"x", filename="aitestx-v2.1.zip")

    d = (await client.get("/api/v1/software/aitestx-v2.1", headers=sw_auth)).json()
    url = d["fixed_download_url"]
    assert "/api/v1/software/alias/aitestx/download" in url
    assert "v2.1" not in url
    assert "2.1" not in url


async def test_alias_url_never_changes_after_new_version(client, sw_auth, sw_root):
    """⚠️ 发新版本 → **URL 一个字都没变**, 但内容跟着推荐版本走."""
    await _create(client, sw_auth, code="", file_name="aitestx-v2.1.zip")
    await _upload(client, sw_auth, "aitestx-v2.1", b"v21", filename="aitestx-v2.1.zip")

    d1 = (await client.get("/api/v1/software/aitestx-v2.1", headers=sw_auth)).json()
    url1 = d1["fixed_download_url"]
    assert d1["download_alias"] == "aitestx"

    # 发新版本 2.2 —— code 和别名都不动
    await _new_version(client, sw_auth, "aitestx-v2.1", "2.2", "aitestx-v2.2.zip",
                       is_default=True)
    await _upload(client, sw_auth, "aitestx-v2.1", b"v22", filename="aitestx-v2.2.zip")

    d2 = (await client.get("/api/v1/software/aitestx-v2.1", headers=sw_auth)).json()
    assert d2["fixed_download_url"] == url1, "链接变了 —— 这就不是固定地址了"
    assert d2["download_alias"] == "aitestx"

    # 内容跟着推荐版本走
    r = await client.get("/api/v1/software/alias/aitestx/download")
    assert r.status_code == 200, r.text
    assert r.content == b"v22"
    assert r.headers.get("x-software-version") == "2.2"


async def test_alias_and_code_endpoints_give_the_same_version(client, sw_auth, sw_root):
    """⚠️ 两个端点必须**逐字一致** —— 不然用户会以为有一个坏了."""
    await _create(client, sw_auth, version="1.0.0")
    await _upload(client, sw_auth, "demo-sw", b"v1")
    await _new_version(client, sw_auth, "demo-sw", "2.0.0", "v2.bin", is_default=False)
    await _upload(client, sw_auth, "demo-sw", b"v2-bytes", filename="v2.bin")

    by_code = await client.get("/api/v1/software/demo-sw/download")
    by_alias = await client.get("/api/v1/software/alias/demo-sw/download")
    assert by_code.status_code == by_alias.status_code == 200
    assert by_code.content == by_alias.content
    assert by_code.headers.get("x-software-version") == by_alias.headers.get("x-software-version")


async def test_alias_endpoint_multi_version_gives_recommended(client, sw_auth, sw_root):
    """⚠️ 多版本时 → 给**推荐版本**, 不是最新的那个.

    排序跟页面上「⬇ 下载」按钮用的 _latest_ready_versions 完全一致:
    is_default DESC, created_at DESC, id DESC.
    """
    await _create(client, sw_auth, version="1.0.0")
    await _upload(client, sw_auth, "demo-sw", b"v1")
    await _new_version(client, sw_auth, "demo-sw", "2.0.0", "v2.bin", is_default=False)
    await _upload(client, sw_auth, "demo-sw", b"v2-bytes", filename="v2.bin")

    # 1.0.0 是推荐 → 给它
    d = (await client.get("/api/v1/software/demo-sw", headers=sw_auth)).json()
    assert d["download_version"] == "1.0.0", "页面按钮给哪个"

    r = await client.get("/api/v1/software/alias/demo-sw/download")
    assert r.content == b"v1", "固定链接必须跟页面按钮给同一个版本"
    assert r.headers.get("x-software-version") == "1.0.0"


async def test_alias_endpoint_falls_back_to_latest_ready(client, sw_auth, sw_root):
    """一个都没标推荐 → 退回时间上最新的 ready 版本."""
    await _create(client, sw_auth, version="1.0.0")
    await _upload(client, sw_auth, "demo-sw", b"v1")
    await _new_version(client, sw_auth, "demo-sw", "2.0.0", "v2.bin", is_default=False)
    await _upload(client, sw_auth, "demo-sw", b"v2-bytes", filename="v2.bin")

    # 把唯一的推荐摘掉
    r = await client.patch(
        "/api/v1/software/demo-sw/versions/1.0.0", json={"is_default": False}, headers=sw_auth
    )
    assert r.status_code == 200, r.text

    res = await client.get("/api/v1/software/alias/demo-sw/download")
    assert res.status_code == 200, res.text
    assert res.content == b"v2-bytes"


async def test_alias_endpoint_404_for_unpublished(client, sw_auth, sw_root):
    """未上架 → 404 (跟按 code 的端点同口径)."""
    await _create(client, sw_auth)
    r = await client.get("/api/v1/software/alias/demo-sw/download")
    assert r.status_code == 404, r.text


async def test_alias_endpoint_404_for_unknown_alias(client, sw_auth, sw_root):
    """不存在的别名 → 404."""
    r = await client.get("/api/v1/software/alias/nope-nope/download")
    assert r.status_code == 404, r.text


async def test_old_code_url_still_works(client, sw_auth, sw_root):
    """⚠️ **旧链接不能废** —— 已经贴到别的软件里的地址不能因为加别名就断."""
    await _create(client, sw_auth, code="", file_name="aitestx-v2.1.zip")
    await _upload(client, sw_auth, "aitestx-v2.1", b"old-url", filename="aitestx-v2.1.zip")

    old = await client.get("/api/v1/software/aitestx-v2.1/download")
    assert old.status_code == 200, old.text
    assert old.content == b"old-url"

    new = await client.get("/api/v1/software/alias/aitestx/download")
    assert new.status_code == 200, new.text
    assert new.content == b"old-url"


async def test_alias_download_increments_count(client, sw_auth, sw_root):
    """下载计数照常 +1 (别名端点不能漏记)."""
    await _create(client, sw_auth)
    await _upload(client, sw_auth, "demo-sw", b"x")

    before = (await client.get("/api/v1/software/demo-sw", headers=sw_auth)).json()
    await client.get("/api/v1/software/alias/demo-sw/download")
    after = (await client.get("/api/v1/software/demo-sw", headers=sw_auth)).json()
    assert after["download_count"] == before["download_count"] + 1
