"""软件库单测 —— 流式上传 / 下载票 / 版本 / 权限 / 存储路径.

⚠️ 这些用例**真的落盘** —— 存储根目录被设成 pytest 的 tmp_path,
   跑完由 pytest 清理, 不会碰到生产目录.
"""
from __future__ import annotations

import hashlib
from pathlib import Path

import pytest

from tests.conftest import set_setting


# ---------- 夹具 ----------


@pytest.fixture
async def sw_root(tmp_path):
    """软件库的存储根目录 (临时目录) + 把设置项指过去."""
    root = tmp_path / "software"
    root.mkdir(parents=True, exist_ok=True)
    await set_setting("software.storage_path", str(root))
    return root


@pytest.fixture
async def sw_auth(admin_user):
    return {"Authorization": f"Bearer {admin_user['token']}"}


async def _create(client, auth, **over):
    """建条目 (第 ① 步) —— 返回响应 JSON."""
    payload = {
        "code": "demo-sw",
        "name": "演示软件",
        "version": "1.0.0",
        "summary": "一句话说明",
        "features": ["功能一", "功能二"],
        "use_when": "该用它的时候",
        "not_for": "不该用它的时候",
        "platform": "linux",
        "category": "工具",
        "tags": ["演示"],
        "keywords": ["demo"],
        "file_name": "demo.bin",
        # 默认**不声明**大小 (0 = 不校验) —— 需要校验的用例自己显式传.
        "file_size": 0,
        "release_notes": "首个版本",
    }
    payload.update(over)
    r = await client.post("/api/v1/software", json=payload, headers=auth)
    assert r.status_code == 201, r.text
    return r.json()


async def _upload(client, auth, code, content=b"hello", filename="demo.bin", extra=None):
    headers = {
        **auth,
        "Content-Type": "application/octet-stream",
        "X-File-Name": filename,
    }
    if extra:
        headers.update(extra)
    return await client.put(f"/api/v1/software/{code}/file", content=content, headers=headers)


# ---------- 创建与校验 ----------


async def test_create_item_and_upload_file(client, sw_auth, sw_root):
    """两步上传: 建条目 → 传文件 → 状态转 published, 文件真的落盘."""
    created = await _create(client, sw_auth, file_size=5)
    assert created["code"] == "demo-sw"
    assert created["upload_path"] == "/api/v1/software/demo-sw/file"

    r = await _upload(client, sw_auth, "demo-sw", b"hello")
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["size"] == 5
    assert body["sha256"] == hashlib.sha256(b"hello").hexdigest()

    # 文件真的在盘上 —— 路径是相对的 (换根目录后仍然有效)
    expect = sw_root / "demo-sw" / "1.0.0" / "demo.bin"
    assert expect.is_file()
    assert expect.read_bytes() == b"hello"

    # 条目状态 → published
    detail = await client.get("/api/v1/software/demo-sw", headers=sw_auth)
    assert detail.status_code == 200
    d = detail.json()
    assert d["publish_status"] == "published"
    assert d["download_version"] == "1.0.0"
    assert len(d["versions"]) == 1
    assert d["versions"][0]["status"] == "ready"
    assert d["versions"][0]["release_notes"] == "首个版本"


async def test_create_rejects_bad_code(client, sw_auth, sw_root):
    """code 含路径分隔符 → 422 (code 会变成目录名, 不能放过)."""
    r = await client.post("/api/v1/software", json={"code": "../etc", "name": "x"}, headers=sw_auth)
    assert r.status_code == 422, r.text


async def test_create_rejects_reserved_code(client, sw_auth, sw_root):
    """保留字 (跟固定路由撞车的) → 422."""
    r = await client.post("/api/v1/software", json={"code": "dl", "name": "x"}, headers=sw_auth)
    assert r.status_code == 422, r.text


async def test_create_duplicate_code_gets_suffix(client, sw_auth, sw_root):
    """同一个 code 再来一次 → **自动加序号**, 不再报 409.

    ⚠️ 2026-10-28 改: code 现在由**文件名自动派生**, 同名文件本来就很常见
       (同一套工具的不同构建). 撞名就让用户自己想一个太费劲, 自动变成
       ``demo-sw2`` / ``demo-sw3`` 更符合直觉.
    """
    await _create(client, sw_auth)
    r = await client.post(
        "/api/v1/software",
        json={
            "code": "demo-sw",
            "name": "再来一个",
            "version": "1.0.0",
            "summary": "x",
            # ⚠️ 图标全局唯一 (2026-10-28 另一条规则) —— 这里必须换图标, 否则先撞图标
            "icon": "📦",
        },
        headers=sw_auth,
    )
    assert r.status_code == 201, r.text
    assert r.json()["code"] == "demo-sw2"

    # 再来一次 → 3
    r2 = await client.post(
        "/api/v1/software",
        json={
            "code": "demo-sw",
            "name": "再来一个",
            "version": "1.0.0",
            "summary": "x",
            "icon": "🧩",
        },
        headers=sw_auth,
    )
    assert r2.status_code == 201, r2.text
    assert r2.json()["code"] == "demo-sw3"


async def test_create_derives_code_from_file_name(client, sw_auth, sw_root):
    """code **不用用户填** —— 由软件包文件名自动派生 (2026-10-28)."""
    r = await client.post(
        "/api/v1/software",
        json={"name": "自动生成标识", "version": "1.0.0", "file_name": "Dify-Web-Entrypoint.sh"},
        headers=sw_auth,
    )
    assert r.status_code == 201, r.text
    # 扩展名去掉 + 转小写 + 分隔符合规
    assert r.json()["code"] == "dify-web-entrypoint"


async def test_create_rejects_bad_file_name(client, sw_auth, sw_root):
    """文件名带中文/空格 → 422 (目录名在别的机器上会乱码)."""
    r = await client.post(
        "/api/v1/software",
        json={"name": "x", "file_name": "SSD 日志医生.exe"},
        headers=sw_auth,
    )
    assert r.status_code == 422, r.text
    assert "英文" in r.json()["detail"] or "字母" in r.json()["detail"]


# ---------- 文件名规范 (2026-10-28: 校验而不是静默改名) ----------


async def test_upload_rejects_unsafe_file_name(client, sw_auth, sw_root):
    """``../../etc/passwd`` → **422 拒绝**, 不是静默改名.

    ⚠️ 以前是"洗成 passwd" —— 静默改名用户根本不知道, 下载回来的名字对不上.
       现在不合规当场拒, 并说清楚规则.
    """
    await _create(client, sw_auth)
    r = await _upload(client, sw_auth, "demo-sw", b"x", filename="../../etc/passwd")
    assert r.status_code == 422, r.text
    # 不该有任何文件跑到根目录外面, 也不该落进版本目录
    assert not (sw_root.parent / "etc").exists()
    assert not (sw_root / "demo-sw" / "1.0.0" / "passwd").exists()


async def test_upload_rejects_leading_dot_file_name(client, sw_auth, sw_root):
    """前导点的文件名 → 422 (那会变成隐藏文件, 还可能是 ``..``)."""
    await _create(client, sw_auth)
    r = await _upload(client, sw_auth, "demo-sw", b"x", filename="..hidden.bin")
    assert r.status_code == 422, r.text
    assert not (sw_root / "demo-sw" / "1.0.0" / "hidden.bin").exists()


# ---------- 大小与完整性 ----------


async def test_upload_rejects_oversized_file(client, sw_auth, sw_root):
    """超过上限 → 413, 且**不留残留**."""
    await set_setting("software.max_size_mb", "1")
    await _create(client, sw_auth)
    payload = b"x" * (1024 * 1024 + 1024)   # 1MB + 1KB
    r = await _upload(client, sw_auth, "demo-sw", payload)
    assert r.status_code == 413, r.text

    # 不该有落地的文件, 也不该有 .part 残留
    final = sw_root / "demo-sw" / "1.0.0" / "demo.bin"
    assert not final.exists()
    tmp = sw_root / ".tmp"
    assert not tmp.exists() or list(tmp.glob("*.part")) == []


async def test_upload_rejects_size_mismatch(client, sw_auth, sw_root):
    """声明 100 字节, 实际收到 5 字节 → 409 (传输中断)."""
    await _create(client, sw_auth, file_size=100)
    r = await _upload(client, sw_auth, "demo-sw", b"hello")
    assert r.status_code == 409, r.text
    # 半截文件不能落到正式目录
    assert not (sw_root / "demo-sw" / "1.0.0" / "demo.bin").exists()


async def test_upload_empty_file_rejected(client, sw_auth, sw_root):
    """空文件 → 400 (不是"成功传了个空包")."""
    await _create(client, sw_auth, file_size=0)
    r = await _upload(client, sw_auth, "demo-sw", b"")
    assert r.status_code == 400, r.text


async def test_upload_twice_conflicts(client, sw_auth, sw_root):
    """同一个版本传完了再传 → 409 (要换文件请发新版本)."""
    await _create(client, sw_auth)
    assert (await _upload(client, sw_auth, "demo-sw", b"hello")).status_code == 200
    r = await _upload(client, sw_auth, "demo-sw", b"world")
    assert r.status_code == 409, r.text


# ---------- 下载票 ----------


async def test_download_ticket_then_download(client, sw_auth, sw_root):
    """正常流程: 签票 → 凭票下载, 拿到的字节与源文件一致."""
    await _create(client, sw_auth)
    await _upload(client, sw_auth, "demo-sw", b"hello")

    t = await client.post("/api/v1/software/demo-sw/download-ticket", headers=sw_auth)
    assert t.status_code == 200, t.text
    url = t.json()["url"]
    assert "/software/dl?t=" in url

    # ⚠️ 凭票下载**不需要** Authorization 头 (票本身就是凭证)
    d = await client.get(url)
    assert d.status_code == 200, d.text
    assert d.content == b"hello"
    assert "attachment" in d.headers.get("content-disposition", "")
    assert d.headers.get("x-content-sha256") == hashlib.sha256(b"hello").hexdigest()


async def test_download_ticket_rejects_tampered(client, sw_auth, sw_root):
    """票被改过 → 401."""
    await _create(client, sw_auth)
    await _upload(client, sw_auth, "demo-sw", b"hello")
    t = await client.post("/api/v1/software/demo-sw/download-ticket", headers=sw_auth)
    url = t.json()["url"]
    # ⚠️ 只改**票据本身** (别把后面的 v=1.0.0 改了 —— 那会变成"版本不匹配"的 403)
    token = url.split("t=")[1].split("&")[0]
    bad = url.replace(token, token[:-3] + "aaa")
    d = await client.get(bad)
    assert d.status_code == 401, d.text


async def test_download_ticket_rejects_expired(client, sw_auth, sw_root):
    """过期票 → 401 (TTL 由签发时决定, 这里直接造一张过去的)."""
    from datetime import datetime, timedelta

    from jose import jwt

    from app.core.config import settings
    from app.core.security import DOWNLOAD_TICKET_TYPE

    await _create(client, sw_auth)
    await _upload(client, sw_auth, "demo-sw", b"hello")
    expired = jwt.encode(
        {
            "typ": DOWNLOAD_TICKET_TYPE,
            "uid": 1,
            "code": "demo-sw",
            "ver": "1.0.0",
            "exp": datetime.utcnow() - timedelta(seconds=10),
        },
        settings.JWT_SECRET,
        algorithm=settings.JWT_ALGORITHM,
    )
    d = await client.get(f"/api/v1/software/dl?t={expired}&v=1.0.0")
    assert d.status_code == 401, d.text


async def test_download_ticket_rejects_deactivated_user(client, sw_auth, sw_root, admin_user):
    """账号被停用 → 票立刻失效 (票只有 10 分钟, 但这 10 分钟也得算数)."""
    from app.db.session import AsyncSessionLocal
    from app.models.user import User

    await _create(client, sw_auth)
    await _upload(client, sw_auth, "demo-sw", b"hello")
    t = await client.post("/api/v1/software/demo-sw/download-ticket", headers=sw_auth)
    url = t.json()["url"]

    async with AsyncSessionLocal() as s:
        u = await s.get(User, admin_user["id"])
        u.is_active = False
        await s.commit()

    d = await client.get(url)
    assert d.status_code == 401, d.text


async def test_download_requires_login_when_not_public(client, sw_auth, sw_root):
    """没开公开下载时, 匿名拿不到票."""
    await _create(client, sw_auth)
    await _upload(client, sw_auth, "demo-sw", b"hello")
    t = await client.post("/api/v1/software/demo-sw/download-ticket")
    assert t.status_code == 401, t.text


# ---------- 版本 ----------


async def test_new_version_keeps_old_downloadable(client, sw_auth, sw_root):
    """发新版本后, 旧版本仍然能下载."""
    await _create(client, sw_auth)
    await _upload(client, sw_auth, "demo-sw", b"v1")

    r = await client.post(
        "/api/v1/software/demo-sw/versions",
        json={"version": "2.0.0", "release_notes": "加了新功能", "file_name": "demo2.bin", "file_size": 2},
        headers=sw_auth,
    )
    assert r.status_code == 201, r.text
    u = await _upload(client, sw_auth, "demo-sw", b"v2", filename="demo2.bin")
    assert u.status_code == 200, u.text

    detail = await client.get("/api/v1/software/demo-sw", headers=sw_auth)
    versions = {v["version"]: v for v in detail.json()["versions"]}
    assert set(versions) == {"1.0.0", "2.0.0"}
    assert versions["2.0.0"]["release_notes"] == "加了新功能"
    assert versions["1.0.0"]["status"] == "ready"

    # 旧版本还能下
    t = await client.post(
        "/api/v1/software/demo-sw/download-ticket", params={"version": "1.0.0"}, headers=sw_auth
    )
    d = await client.get(t.json()["url"])
    assert d.status_code == 200
    assert d.content == b"v1"


async def test_keep_versions_prunes_oldest(client, sw_auth, sw_root):
    """超过保留数时, 最老的版本被清掉 (行 + 磁盘文件).

    ⚠️ 2026-10-28: **推荐版本永远不参与清理** —— 上传者特意把某个版本标成推荐,
       正是因为那个版本还在用. 所以 keep_versions=2 时, 最多留 3 个
       (最近 2 个 + 推荐的那 1 个).
    """
    await set_setting("software.keep_versions", "2")
    await _create(client, sw_auth)
    await _upload(client, sw_auth, "demo-sw", b"v1")
    for v in ("2.0.0", "3.0.0"):
        await client.post(
            "/api/v1/software/demo-sw/versions",
            json={"version": v, "release_notes": "", "file_name": f"{v}.bin", "file_size": 2},
            headers=sw_auth,
        )
        await _upload(client, sw_auth, "demo-sw", b"xx", filename=f"{v}.bin")

    detail = await client.get("/api/v1/software/demo-sw", headers=sw_auth)
    versions = [v["version"] for v in detail.json()["versions"]]
    # 最近 2 个 (2.0.0 / 3.0.0) + 推荐版本 (3.0.0 本身就是最新, 已算在内)
    # → 实际留下 2.0.0 和 3.0.0
    assert set(versions) == {"2.0.0", "3.0.0"}, versions
    # 老版本的目录也被清掉了
    assert not (sw_root / "demo-sw" / "1.0.0").exists()


async def test_keep_versions_never_prunes_default_version(client, sw_auth, sw_root):
    """推荐版本再老也不会被自动清掉 (2026-10-28).

    ⚠️ 场景: 软件挂两个版本, 一个是「LTS版」还在给老环境用, 一个是新版.
       自动清理把 LTS 版清掉 → 用户的"该下哪个"就悬空了.

    ⚠️ 注意顺序: 发新版本时选「不设为推荐」, 否则新版本会接管推荐标记,
       老版本就成了普通版本 (照常被清理) —— 那是用户自己的选择.
    """
    await set_setting("software.keep_versions", "1")
    await _create(client, sw_auth, version="1.0.0")
    await _upload(client, sw_auth, "demo-sw", b"v1")
    for v in ("2.0.0", "3.0.0"):
        await client.post(
            "/api/v1/software/demo-sw/versions",
            # is_default=False → 1.0.0 保持推荐, 新版本不抢
            json={"version": v, "is_default": False, "file_name": f"{v}.bin", "file_size": 2},
            headers=sw_auth,
        )
        await _upload(client, sw_auth, "demo-sw", b"xx", filename=f"{v}.bin")

    detail = await client.get("/api/v1/software/demo-sw", headers=sw_auth)
    versions = {v["version"] for v in detail.json()["versions"]}
    assert "1.0.0" in versions, versions
    assert (sw_root / "demo-sw" / "1.0.0").is_dir()
    # 普通的 2.0.0 该被清掉 (keep=1, 只留最近的 3.0.0 + 推荐的 1.0.0)
    assert "2.0.0" not in versions, versions


async def test_duplicate_version_conflicts(client, sw_auth, sw_root):
    """同一个版本号不能建两次."""
    await _create(client, sw_auth)
    r = await client.post(
        "/api/v1/software/demo-sw/versions",
        json={"version": "1.0.0", "file_name": "x.bin"},
        headers=sw_auth,
    )
    assert r.status_code == 409, r.text


# ---------- 列表与可见性 ----------


async def test_list_shows_published_and_own(client, sw_auth, sw_root, publisher_user):
    """已上架的谁都能看见; 待传文件的只有作者自己看得见."""
    await _create(client, sw_auth)          # admin 的, 已上架
    await _upload(client, sw_auth, "demo-sw", b"hello")

    auth2 = {"Authorization": f"Bearer {publisher_user['token']}"}
    # publisher 建一个没传文件的
    r = await client.post(
        "/api/v1/software",
        json={"code": "draft-sw", "name": "没传完的", "version": "0.1.0", "summary": "x",
              "icon": "📦"},
        headers=auth2,
    )
    assert r.status_code == 201, r.text

    # publisher 自己看得到两个
    mine = await client.get("/api/v1/software", headers=auth2)
    codes = {i["code"] for i in mine.json()["items"]}
    assert "draft-sw" in codes

    # admin 看得到 publisher 的待传条目 (管理员要能管)
    admin_view = await client.get("/api/v1/software", headers=sw_auth)
    assert "draft-sw" in {i["code"] for i in admin_view.json()["items"]}


async def test_list_search_by_name(client, sw_auth, sw_root):
    """搜索能按名字命中."""
    await _create(client, sw_auth)
    await _upload(client, sw_auth, "demo-sw", b"hello")
    r = await client.get("/api/v1/software", params={"q": "演示"}, headers=sw_auth)
    assert r.status_code == 200
    assert "demo-sw" in {i["code"] for i in r.json()["items"]}


async def test_categories_are_served_by_backend(client, sw_auth, sw_root):
    """分类由后端下发 (前端动态渲染 chip)."""
    await _create(client, sw_auth)
    await _upload(client, sw_auth, "demo-sw", b"hello")
    r = await client.get("/api/v1/software/categories", headers=sw_auth)
    assert r.status_code == 200
    names = {c["name"] for c in r.json()["items"]}
    assert "工具" in names


async def test_config_hides_storage_root_from_non_admin(client, sw_root, publisher_user):
    """存储路径只有管理员能看到."""
    auth = {"Authorization": f"Bearer {publisher_user['token']}"}
    r = await client.get("/api/v1/software/config", headers=auth)
    assert r.status_code == 200
    body = r.json()
    assert body["storage_root"] == ""
    assert body["is_admin"] is False


# ---------- 钉钉通知 (2026-10-30 · 第十一轮 · 问题3) ----------


async def test_software_upload_triggers_dingtalk_notification(client, sw_auth, sw_root, monkeypatch):
    """⚠️ 用户要求「软件库的**上架**和**发布新版本**需要通知到钉钉」.

    两条要点:
      · 通知**在文件传完之后**才发 —— 上架是两步 (建条目 → 传包),
        只建了条目还没传包, 别人下不了, 那时候通知等于"上架了个寂寞";
      · 首次上架 → `software_publish`, 发新版本 → `software_update`.
    """
    from app.api import software as sw_api

    calls: list[tuple[str, dict]] = []

    async def fake_notify(event, **kw):
        calls.append((event, kw))
        return True

    monkeypatch.setattr(sw_api, "notify_market", fake_notify)

    await _create(client, sw_auth)
    assert calls == [], "只建条目(还没传包)不该通知 —— 别人根本下不了"

    r = await _upload(client, sw_auth, "demo-sw", b"hello")
    assert r.status_code == 200, r.text

    assert len(calls) == 1, calls
    event, kw = calls[0]
    assert event == "software_publish", event
    assert kw["kind"] == "software", "通知里要说明这是**软件包**"
    assert kw["version"] == "1.0.0"
    assert kw["summary"], "上架要带上简介 (这软件是干嘛的)"
    assert kw["release_notes"], "要带上更新说明"
    assert kw["name"] == "演示软件"


async def test_software_new_version_notifies_update(client, sw_auth, sw_root, monkeypatch):
    """发了新版本 → 通知**第二个**事件 (`software_update`), 且带新的更新说明."""
    from app.api import software as sw_api

    calls: list[tuple[str, dict]] = []

    async def fake_notify(event, **kw):
        calls.append((event, kw))
        return True

    monkeypatch.setattr(sw_api, "notify_market", fake_notify)

    await _create(client, sw_auth)
    await _upload(client, sw_auth, "demo-sw", b"hello")
    assert [e for e, _ in calls] == ["software_publish"], calls

    # 发新版本 → 传文件
    r = await client.post(
        "/api/v1/software/demo-sw/versions",
        json={"version": "1.1.0", "release_notes": "修了日志解析的截断问题"},
        headers=sw_auth,
    )
    assert r.status_code == 201, r.text
    # ⚠️ 建了版本行还没传包 → 还不该通知
    assert [e for e, _ in calls] == ["software_publish"], calls

    r = await _upload(client, sw_auth, "demo-sw", b"world", filename="demo.bin")
    assert r.status_code == 200, r.text

    assert [e for e, _ in calls] == ["software_publish", "software_update"], calls
    event, kw = calls[-1]
    assert event == "software_update"
    assert kw["version"] == "1.1.0"
    assert kw["release_notes"] == "修了日志解析的截断问题", "要说明这次改了啥"


# ---------- 软件下架也要通知钉钉 (2026-10-31 · 第十三轮) ----------


async def test_software_unpublish_notifies_dingtalk(client, sw_auth, sw_root, monkeypatch):
    """⚠️ 用户原话「下架软件也要通知@所有人」.

    之前软件下架是**静默**的 —— 那个软件从库里没了, 谁都不知道.
    """
    from app.api import software as sw_api

    calls: list[tuple[str, dict]] = []

    async def fake_notify(event, asset=None, **kw):
        calls.append((event, kw))
        return True

    monkeypatch.setattr(sw_api, "notify_market", fake_notify)

    await _create(client, sw_auth)
    await _upload(client, sw_auth, "demo-sw", b"hello")
    assert [e for e, _ in calls] == ["software_publish"], calls

    # ⚠️ 前端「下架」按钮走的是 purge (删记录 + 删文件)
    r = await client.delete("/api/v1/software/demo-sw/purge", headers=sw_auth)
    assert r.status_code == 200, r.text

    assert [e for e, _ in calls] == ["software_publish", "software_unpublish"], calls
    event, kw = calls[-1]
    assert event == "software_unpublish"
    assert kw["kind"] == "software", "类型要说清楚是软件包"
    assert kw["name"] == "演示软件"
    assert kw["detail"], "要说清楚为什么下架"


async def test_software_soft_delete_also_notifies(client, sw_auth, sw_root, monkeypatch):
    """软删 (文件保留) 也是下架 —— 同样通知."""
    from app.api import software as sw_api

    calls: list[tuple[str, dict]] = []

    async def fake_notify(event, asset=None, **kw):
        calls.append((event, kw))
        return True

    monkeypatch.setattr(sw_api, "notify_market", fake_notify)

    await _create(client, sw_auth)
    await _upload(client, sw_auth, "demo-sw", b"hello")
    calls.clear()

    r = await client.delete("/api/v1/software/demo-sw", headers=sw_auth)
    assert r.status_code == 200, r.text
    assert [e for e, _ in calls] == ["software_unpublish"], calls


# ---------- 权限 ----------


async def test_non_publisher_cannot_upload(client, sw_root, stranger_user):
    """没有发布权 → 403."""
    auth = {"Authorization": f"Bearer {stranger_user['token']}"}
    r = await client.post(
        "/api/v1/software",
        json={"code": "x-sw", "name": "x", "version": "1.0.0", "summary": "s"},
        headers=auth,
    )
    assert r.status_code == 403, r.text


async def test_cannot_modify_others_item(client, sw_auth, sw_root, publisher_user):
    """改别人的条目 → 403."""
    await _create(client, sw_auth)
    auth2 = {"Authorization": f"Bearer {publisher_user['token']}"}
    r = await client.put(
        "/api/v1/software/demo-sw",
        json={"summary": "我来改"},
        headers=auth2,
    )
    assert r.status_code == 403, r.text


async def test_admin_can_modify_others_item(client, sw_auth, sw_root, publisher_user):
    """管理员可以改任何条目."""
    await _create(client, sw_auth)
    r = await client.put(
        "/api/v1/software/demo-sw", json={"summary": "管理员改的"}, headers=sw_auth
    )
    assert r.status_code == 200, r.text
    assert r.json()["summary"] == "管理员改的"


async def test_purge_denied_for_others(client, sw_auth, sw_root, publisher_user):
    """下架**别人的**软件 → 403.

    ⚠️ 2026-10-28 改: 下架不再"只有管理员能做" —— **谁上架的谁就能下架自己的**,
       不用管理员审批. 但下架**别人的**照样不行 (见下面两条).
    """
    await _create(client, sw_auth)
    auth2 = {"Authorization": f"Bearer {publisher_user['token']}"}
    r = await client.delete("/api/v1/software/demo-sw/purge", headers=auth2)
    assert r.status_code == 403, r.text


async def test_author_can_unpublish_own_software(client, sw_auth, sw_root, publisher_user):
    """**上传者本人**能下架自己的软件, 不用管理员审批 (2026-10-28)."""
    auth2 = {"Authorization": f"Bearer {publisher_user['token']}"}
    await _create(client, auth2, code="own-sw", name="我自己的", icon="📦")
    await _upload(client, auth2, "own-sw", b"hello")
    assert (sw_root / "own-sw").is_dir()

    r = await client.delete("/api/v1/software/own-sw/purge", headers=auth2)
    assert r.status_code == 200, r.text
    # 条目和文件一起没了
    assert not (sw_root / "own-sw").exists()
    assert (await client.get("/api/v1/software/own-sw", headers=auth2)).status_code == 404


async def test_admin_can_unpublish_others_software(client, sw_auth, sw_root, publisher_user):
    """管理员能下架**任何人**的软件."""
    auth2 = {"Authorization": f"Bearer {publisher_user['token']}"}
    await _create(client, auth2, code="p-sw", name="别人的", icon="💿")
    await _upload(client, auth2, "p-sw", b"hello")

    r = await client.delete("/api/v1/software/p-sw/purge", headers=sw_auth)
    assert r.status_code == 200, r.text
    assert not (sw_root / "p-sw").exists()


async def test_purge_removes_files(client, sw_auth, sw_root):
    """彻底清理: 记录与磁盘文件一起删."""
    await _create(client, sw_auth)
    await _upload(client, sw_auth, "demo-sw", b"hello")
    assert (sw_root / "demo-sw").is_dir()
    r = await client.delete("/api/v1/software/demo-sw/purge", headers=sw_auth)
    assert r.status_code == 200, r.text
    assert not (sw_root / "demo-sw").exists()
    assert (await client.get("/api/v1/software/demo-sw", headers=sw_auth)).status_code == 404


# ---------- 图标不许重复 (2026-10-28) ----------


async def test_icon_cannot_duplicate(client, sw_auth):
    """图标不能跟别的软件重复 —— 两张卡长得一样, 用户分不清谁是谁."""
    await _create(client, sw_auth, icon="🚀")
    r = await client.post(
        "/api/v1/software",
        json={"code": "other-sw", "name": "另一个", "version": "1.0.0", "summary": "x",
              "icon": "🚀"},
        headers=sw_auth,
    )
    assert r.status_code == 409, r.text
    assert "已经被" in r.json()["detail"]


async def test_update_icon_cannot_duplicate(client, sw_auth):
    """改图标也要查重 (不能改成别人的图标)."""
    await _create(client, sw_auth, code="a-sw", name="A", icon="🚀")
    await _create(client, sw_auth, code="b-sw", name="B", icon="💿")
    r = await client.put(
        "/api/v1/software/b-sw", json={"icon": "🚀"}, headers=sw_auth
    )
    assert r.status_code == 409, r.text


async def test_update_icon_to_same_is_allowed(client, sw_auth):
    """不改图标 (或改成自己的同一个) 不该被自己撞上."""
    await _create(client, sw_auth, code="a-sw", name="A", icon="🚀")
    r = await client.put(
        "/api/v1/software/a-sw", json={"icon": "🚀", "summary": "改个简介"}, headers=sw_auth
    )
    assert r.status_code == 200, r.text


async def test_config_lists_used_icons(client, sw_auth):
    """config 要告诉前端哪些图标被占了 —— 前端据此把它们禁掉."""
    await _create(client, sw_auth, icon="🧪")
    r = await client.get("/api/v1/software/config", headers=sw_auth)
    assert r.status_code == 200, r.text
    used = r.json()["used_icons"]
    assert used.get("🧪") == "演示软件"


async def test_soft_delete_keeps_files(client, sw_auth, sw_root):
    """软删: 条目不见了, 文件还在 (管理员可以彻底清理)."""
    await _create(client, sw_auth)
    await _upload(client, sw_auth, "demo-sw", b"hello")
    r = await client.delete("/api/v1/software/demo-sw", headers=sw_auth)
    assert r.status_code == 200, r.text
    assert (await client.get("/api/v1/software/demo-sw", headers=sw_auth)).status_code == 404
    assert (sw_root / "demo-sw" / "1.0.0" / "demo.bin").is_file()


# ---------- 存储路径健康 ----------


async def test_path_check_reports_missing_files(client, sw_auth, sw_root):
    """换根目录后, 「检查路径」要能说出文件**在哪个根目录里**.

    ⚠️ 2026-10-28 改: 以前只报"缺了" —— 管理员换完根目录一看"缺 1 个文件",
       以为软件凭空消失了. 实际文件还在**旧根**里, 平台会自动去那边找.
       所以现在分两种: 在别的根里找到了 (missing) / 所有根都没有 (lost).
    """
    await _create(client, sw_auth)
    await _upload(client, sw_auth, "demo-sw", b"hello")

    # 换到一个空根目录 (模拟"改了设置但文件没搬")
    await set_setting("software.storage_path", str(sw_root.parent / "elsewhere"))
    # 旧根进了历史 (设置页改根目录时后端会自动记)
    await set_setting("software.storage_path_history", str(sw_root))
    r = await client.get("/api/v1/software/path-check", headers=sw_auth)
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["missing_count"] == 1
    assert body["missing"][0]["code"] == "demo-sw"
    # 在旧根里找到了 → **没丢**
    assert body["lost_count"] == 0
    assert body["missing"][0]["found_in"] == str(sw_root)


async def test_path_check_reports_lost_when_no_root_has_it(client, sw_auth, sw_root):
    """所有候选根里都没有 → 报 **lost** (真丢了)."""
    await _create(client, sw_auth)
    await _upload(client, sw_auth, "demo-sw", b"hello")

    # 换根 + 把文件真删掉 —— 这次是真的找不到了
    await set_setting("software.storage_path", str(sw_root.parent / "elsewhere"))
    await set_setting("software.storage_path_history", str(sw_root))
    for p in (sw_root / "demo-sw").rglob("*"):
        if p.is_file():
            p.unlink()

    r = await client.get("/api/v1/software/path-check", headers=sw_auth)
    body = r.json()
    assert body["lost_count"] == 1
    assert body["lost"][0]["code"] == "demo-sw"


async def test_path_check_lists_orphan_dirs(client, sw_auth, sw_root):
    """根目录下有目录、DB 里却没有对应条目 → 报成**孤儿目录**.

    ⚠️ 这正是用户报的: 版本全下架了, ``<root>/<code>/`` 空壳还在.
    """
    await _create(client, sw_auth)
    await _upload(client, sw_auth, "demo-sw", b"hello")
    # 手工造一个 DB 里没有的目录
    (sw_root / "ghost-item").mkdir(parents=True, exist_ok=True)

    r = await client.get("/api/v1/software/path-check", headers=sw_auth)
    body = r.json()
    names = [o["name"] for o in body["orphan_dirs"]]
    assert "ghost-item" in names
    # 有条目的不算孤儿
    assert "demo-sw" not in names


async def test_config_reports_path_not_writable(client, sw_auth, tmp_path):
    """存储根不可用 → path_ok=false (设置页要显红字)."""
    bad = tmp_path / "nope"
    await set_setting("software.storage_path", str(bad))
    r = await client.get("/api/v1/software/config", headers=sw_auth)
    assert r.status_code == 200
    assert r.json()["path_ok"] is False


# ===== 两种部署模式的存储路径口径 =====


async def test_storage_source_tells_where_the_root_came_from(client, sw_auth, sw_root):
    """设置项填了 → source=setting.

    ⚠️ 为什么要有这个字段: "我改了设置项怎么没生效" 是最常见的问法 ——
       实际多半是**环境变量**把它盖住了 (容器模式就是 compose 注入的),
       光看路径猜不出来, 所以后端直接告诉前端.
    """
    r = await client.get("/api/v1/software/config", headers=sw_auth)
    assert r.status_code == 200
    assert r.json()["storage_source"] == "setting"


async def test_storage_source_env_when_setting_empty(client, sw_auth, tmp_path, monkeypatch):
    """设置项留空 → 看环境变量 → source=env."""
    monkeypatch.setenv("SOFTWARE_STORAGE_PATH", str(tmp_path / "sw-env"))
    await set_setting("software.storage_path", "")
    r = await client.get("/api/v1/software/config", headers=sw_auth)
    assert r.status_code == 200
    assert r.json()["storage_source"] == "env"


async def test_storage_source_default_when_nothing_configured(client, sw_auth, monkeypatch):
    """都没配 → source=default (兜底路径, 容器里落在 /data/software)."""
    monkeypatch.delenv("SOFTWARE_STORAGE_PATH", raising=False)
    await set_setting("software.storage_path", "")
    r = await client.get("/api/v1/software/config", headers=sw_auth)
    assert r.status_code == 200
    assert r.json()["storage_source"] == "default"


def test_probe_storage_reports_unwritable_dir(tmp_path):
    """存储根体检: 目录建不出来 → 报出原因 (启动时就会喊)."""
    from app.core import software_store

    blocker = tmp_path / "not-a-dir"
    blocker.write_text("我是文件, 不能当目录用", encoding="utf-8")
    info = software_store.probe_storage(blocker / "sub")
    assert info["exists"] is False
    assert info.get("error")


def test_repo_root_finds_the_real_repo():
    """仓库根要认标志目录 —— 容器里代码整份 COPY 进 /app, 不能只按"上三层"算."""
    from app.core import software_store

    root = software_store.repo_root()
    # 裸机: 上层有 backend_gateway; 容器: 没有 (退到 "/"), 两种都得能返回
    assert root.is_absolute()
    assert (root / "backend_gateway").is_dir() or root == Path("/")


# ---------- 审计 ----------

async def test_audit_is_recorded(client, sw_auth, sw_root):
    """动作进审计流水 (复用 asset_audits, 命名空间 sw:)."""
    from app.db.session import AsyncSessionLocal
    from app.models.asset import AssetAudit
    from sqlalchemy import select

    await _create(client, sw_auth)
    await _upload(client, sw_auth, "demo-sw", b"hello")

    async with AsyncSessionLocal() as s:
        rows = (
            await s.execute(select(AssetAudit).where(AssetAudit.code == "sw:demo-sw"))
        ).scalars().all()
    actions = {r.action for r in rows}
    assert "create" in actions
    assert "upload" in actions


# ---------- 安装说明 / 注意事项 (2026-10-28) ----------


async def test_create_keeps_install_steps_and_caveats(client, sw_auth, sw_root):
    """安装说明 / 注意事项是**选填**字段 —— 填了要存下来, 详情里能读出来."""
    await _create(
        client,
        sw_auth,
        install_steps="1. 解压到 /opt\n2. 运行 install.sh",
        caveats="需要管理员权限, 别在生产机上乱试",
    )
    d = (await client.get("/api/v1/software/demo-sw", headers=sw_auth)).json()
    assert d["install_steps"] == "1. 解压到 /opt\n2. 运行 install.sh"
    assert d["caveats"] == "需要管理员权限, 别在生产机上乱试"


async def test_install_steps_are_optional(client, sw_auth, sw_root):
    """不填 = 空串 (老条目没有这两栏, 详情页不该报错)."""
    await _create(client, sw_auth)
    d = (await client.get("/api/v1/software/demo-sw", headers=sw_auth)).json()
    assert d["install_steps"] == ""
    assert d["caveats"] == ""


async def test_update_can_change_install_steps(client, sw_auth, sw_root):
    """改元信息时能补上安装说明 (上架时忘了写, 后面再补)."""
    await _create(client, sw_auth)
    r = await client.put(
        "/api/v1/software/demo-sw",
        json={"install_steps": "解压即用", "caveats": "别在 32 位系统上跑"},
        headers=sw_auth,
    )
    assert r.status_code == 200, r.text
    d = (await client.get("/api/v1/software/demo-sw", headers=sw_auth)).json()
    assert d["install_steps"] == "解压即用"
    assert d["caveats"] == "别在 32 位系统上跑"


# ---------- 多版本: 变体标签 / 推荐版本 / 单版本下架 (2026-10-28) ----------


async def test_two_versions_both_downloadable(client, sw_auth, sw_root):
    """一个软件挂两个版本, **两个都能下** —— 「两个版本都有用」的基础."""
    await _create(client, sw_auth, version="1.0.0")
    await _upload(client, sw_auth, "demo-sw", b"v1")

    r = await client.post(
        "/api/v1/software/demo-sw/versions",
        json={"version": "2.0.0", "release_notes": "第二个版本", "file_name": "v2.bin"},
        headers=sw_auth,
    )
    assert r.status_code == 201, r.text
    await _upload(client, sw_auth, "demo-sw", b"v2-file", filename="v2.bin")

    d = (await client.get("/api/v1/software/demo-sw", headers=sw_auth)).json()
    assert len(d["versions"]) == 2
    ready = {v["version"] for v in d["versions"] if v["status"] == "ready"}
    assert ready == {"1.0.0", "2.0.0"}

    # 两个版本都能拿到下载票
    for ver in ("1.0.0", "2.0.0"):
        t = await client.post(
            "/api/v1/software/demo-sw/download-ticket",
            params={"version": ver},
            headers=sw_auth,
        )
        assert t.status_code == 200, t.text
        assert f"v={ver}" in t.json()["url"]


async def test_version_variant_label(client, sw_auth, sw_root):
    """变体标签 —— 两个版本光看版本号分不清, 标签就是那个「小名」."""
    await _create(client, sw_auth, version="1.0.0")
    r = await client.post(
        "/api/v1/software/demo-sw/versions",
        json={"version": "2.0.0", "variant": "Windows 版", "file_name": "v2.bin"},
        headers=sw_auth,
    )
    assert r.status_code == 201, r.text

    d = (await client.get("/api/v1/software/demo-sw", headers=sw_auth)).json()
    by_ver = {v["version"]: v for v in d["versions"]}
    assert by_ver["2.0.0"]["variant"] == "Windows 版"
    assert by_ver["1.0.0"]["variant"] == ""


async def test_set_default_version_changes_download_target(client, sw_auth, sw_root):
    """推荐下载版本 —— 手动指定后, 头部「⬇ 下载」跟着走, 不再永远是最新的."""
    await _create(client, sw_auth, version="1.0.0")
    await _upload(client, sw_auth, "demo-sw", b"v1")
    await client.post(
        "/api/v1/software/demo-sw/versions",
        json={"version": "2.0.0", "file_name": "v2.bin"},
        headers=sw_auth,
    )
    await _upload(client, sw_auth, "demo-sw", b"v2-file", filename="v2.bin")

    # 新版本默认成了推荐 —— 下载目标指向它
    d = (await client.get("/api/v1/software/demo-sw", headers=sw_auth)).json()
    assert d["download_version"] == "2.0.0"

    # 手动把 1.0.0 设成推荐 → 下载目标切回去
    r = await client.patch(
        "/api/v1/software/demo-sw/versions/1.0.0",
        json={"is_default": True},
        headers=sw_auth,
    )
    assert r.status_code == 200, r.text
    assert r.json()["is_default"] is True

    d = (await client.get("/api/v1/software/demo-sw", headers=sw_auth)).json()
    assert d["download_version"] == "1.0.0"
    # ⚠️ 推荐必须**唯一** —— 2.0.0 的标记要被摘掉
    by_ver = {v["version"]: v for v in d["versions"]}
    assert by_ver["2.0.0"]["is_default"] is False
    assert by_ver["1.0.0"]["is_default"] is True


async def test_new_version_takes_over_default(client, sw_auth, sw_root):
    """发新版本 (默认 is_default=true) → 旧的推荐标记自动摘掉."""
    await _create(client, sw_auth, version="1.0.0")
    await _upload(client, sw_auth, "demo-sw", b"v1")
    await client.post(
        "/api/v1/software/demo-sw/versions",
        json={"version": "2.0.0", "file_name": "v2.bin"},
        headers=sw_auth,
    )
    await _upload(client, sw_auth, "demo-sw", b"v2-file", filename="v2.bin")

    d = (await client.get("/api/v1/software/demo-sw", headers=sw_auth)).json()
    by_ver = {v["version"]: v for v in d["versions"]}
    assert by_ver["1.0.0"]["is_default"] is False
    assert by_ver["2.0.0"]["is_default"] is True


async def test_new_version_can_skip_default(client, sw_auth, sw_root):
    """发新版本时选「不设为推荐」 → 老的推荐版本保持不变."""
    await _create(client, sw_auth, version="1.0.0")
    await _upload(client, sw_auth, "demo-sw", b"v1")
    await client.post(
        "/api/v1/software/demo-sw/versions",
        json={"version": "2.0.0", "is_default": False, "file_name": "v2.bin"},
        headers=sw_auth,
    )
    await _upload(client, sw_auth, "demo-sw", b"v2-file", filename="v2.bin")

    d = (await client.get("/api/v1/software/demo-sw", headers=sw_auth)).json()
    assert d["download_version"] == "1.0.0"
    by_ver = {v["version"]: v for v in d["versions"]}
    assert by_ver["1.0.0"]["is_default"] is True
    assert by_ver["2.0.0"]["is_default"] is False


async def test_cannot_unset_last_downloadable_default(client, sw_auth, sw_root):
    """只有一个能下载的版本 → 不许取消推荐 (否则条目就没有「该下哪个」了)."""
    await _create(client, sw_auth, version="1.0.0")
    await _upload(client, sw_auth, "demo-sw", b"v1")
    r = await client.patch(
        "/api/v1/software/demo-sw/versions/1.0.0",
        json={"is_default": False},
        headers=sw_auth,
    )
    assert r.status_code == 409, r.text


async def test_delete_single_version_keeps_others(client, sw_auth, sw_root):
    """**单版本下架** —— 只删这一个版本的文件, 其他版本照旧能下."""
    await _create(client, sw_auth, version="1.0.0")
    await _upload(client, sw_auth, "demo-sw", b"v1")
    await client.post(
        "/api/v1/software/demo-sw/versions",
        json={"version": "2.0.0", "file_name": "v2.bin"},
        headers=sw_auth,
    )
    await _upload(client, sw_auth, "demo-sw", b"v2-file", filename="v2.bin")
    assert (sw_root / "demo-sw" / "1.0.0").is_dir()
    assert (sw_root / "demo-sw" / "2.0.0").is_dir()

    r = await client.delete("/api/v1/software/demo-sw/versions/1.0.0", headers=sw_auth)
    assert r.status_code == 200, r.text
    # 1.0.0 的文件没了, 2.0.0 的还在
    assert not (sw_root / "demo-sw" / "1.0.0").exists()
    assert (sw_root / "demo-sw" / "2.0.0").is_dir()

    d = (await client.get("/api/v1/software/demo-sw", headers=sw_auth)).json()
    assert [v["version"] for v in d["versions"]] == ["2.0.0"]
    # 条目还在, 还能下
    assert d["publish_status"] == "published"
    t = await client.post(
        "/api/v1/software/demo-sw/download-ticket",
        params={"version": "2.0.0"},
        headers=sw_auth,
    )
    assert t.status_code == 200, t.text


async def test_delete_last_version_unpublishes_item(client, sw_auth, sw_root):
    """删掉最后一个能下载的版本 → 条目一起下架 (不能空着上架)."""
    await _create(client, sw_auth, version="1.0.0")
    await _upload(client, sw_auth, "demo-sw", b"v1")
    r = await client.delete("/api/v1/software/demo-sw/versions/1.0.0", headers=sw_auth)
    assert r.status_code == 200, r.text
    assert (await client.get("/api/v1/software/demo-sw", headers=sw_auth)).status_code == 404
    # ⚠️ 返回体要**告诉前端条目被连带下架了** (2026-10-28 用户报的"成功却报错"):
    #    前端下架完再去查详情必然 404, 不知道这一条就会弹红字「软件 xxx 不存在」.
    body = r.json()
    assert body["item_unpublished"] is True
    assert body["remaining_versions"] == 0


async def test_delete_version_reports_remaining_versions(client, sw_auth, sw_root):
    """还有别的版本 → 条目**不下架**, 返回体说清还剩几个."""
    await _create(client, sw_auth, version="1.0.0")
    await _upload(client, sw_auth, "demo-sw", b"v1")
    await client.post(
        "/api/v1/software/demo-sw/versions",
        json={"version": "2.0.0", "file_name": "v2.bin"},
        headers=sw_auth,
    )
    await _upload(client, sw_auth, "demo-sw", b"v2-file", filename="v2.bin")
    r = await client.delete("/api/v1/software/demo-sw/versions/1.0.0", headers=sw_auth)
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["item_unpublished"] is False
    assert body["remaining_versions"] == 1
    # 条目还在 —— 前端这时可以正常刷新详情
    assert (await client.get("/api/v1/software/demo-sw", headers=sw_auth)).status_code == 200


async def test_delete_version_denied_for_others(client, sw_auth, sw_root, publisher_user):
    """下架**别人的**某个版本 → 403 (反过来: 管理员有权限, 普通发布者没有)."""
    auth2 = {"Authorization": f"Bearer {publisher_user['token']}"}
    await _create(client, sw_auth, code="a-sw", name="管理员的", icon="🖥")
    await _upload(client, sw_auth, "a-sw", b"v1")
    # publisher_user 不是作者 → 403
    r = await client.delete("/api/v1/software/a-sw/versions/1.0.0", headers=auth2)
    assert r.status_code == 403, r.text
    # 管理员自己当然可以
    r2 = await client.delete("/api/v1/software/a-sw/versions/1.0.0", headers=sw_auth)
    assert r2.status_code == 200, r2.text


async def test_update_version_variant_by_author(client, sw_auth, sw_root):
    """上传者本人能改自己版本的变体标签."""
    await _create(client, sw_auth, version="1.0.0")
    await _upload(client, sw_auth, "demo-sw", b"v1")
    r = await client.patch(
        "/api/v1/software/demo-sw/versions/1.0.0",
        json={"variant": "LTS 版"},
        headers=sw_auth,
    )
    assert r.status_code == 200, r.text
    assert r.json()["variant"] == "LTS 版"


# ---------- 存储目录体检 (设置页的「体检存储目录」按钮) ----------


async def test_storage_probe_reports_ok(client, sw_auth, sw_root):
    """存储根可写 + 文件都在 → 报 ok, 并且说清路径和占用."""
    await _create(client, sw_auth)
    await _upload(client, sw_auth, "demo-sw", b"hello")

    r = await client.post("/api/v1/settings/test/software_storage", headers=sw_auth)
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["ok"] is True
    assert body["status"] == "ok"
    d = body["detail"]
    assert d["root"] == str(sw_root)
    assert d["writable"] is True
    assert d["missing_count"] == 0
    # ⚠️ 占用是**软件库目录自己**的, 不是整块磁盘的
    #    (曾经用错成 disk_usage.used → 显示"占了 725GB", 那是整块盘)
    #    具体字节数不写死 —— 目录里还有 release.json 快照, 大小会变
    assert d["used_bytes"] >= 5
    assert d["used_bytes"] < 1024 * 1024
    assert d["free_bytes"] > 0
    # 路径是哪来的 —— 让管理员知道改了设置项到底生效没
    assert d["source"] == "setting"


async def test_storage_probe_lists_missing_files(client, sw_auth, sw_root, tmp_path):
    """换了存储根目录 → 老文件不在新目录里 → **报出来在旧根** (不是"丢了").

    ⚠️ 这是「改存储路径」最常见的坑: 改完配置, 老文件不会自动搬过去,
       用户以为软件没了. 体检接口要一次把"在哪儿"说清楚.
    """
    await _create(client, sw_auth)
    await _upload(client, sw_auth, "demo-sw", b"hello")

    # 把存储根指到一个**空的新目录** —— 模拟"换了根目录但没搬文件"
    other = tmp_path / "other"
    other.mkdir(parents=True, exist_ok=True)
    await set_setting("software.storage_path", str(other))
    await set_setting("software.storage_path_history", str(sw_root))

    r = await client.post("/api/v1/settings/test/software_storage", headers=sw_auth)
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["ok"] is False
    assert body["status"] == "warn"
    d = body["detail"]
    assert d["missing_count"] == 1
    assert d["missing"][0]["version"] == "1.0.0"
    # 在旧根里找到了 → 没丢
    assert d["lost_count"] == 0
    assert d["missing"][0]["found_in"] == str(sw_root)
    # 所有候选根都列出来 —— 管理员能看到文件实际在哪
    assert str(sw_root) in d["roots"]


async def test_changing_storage_root_remembers_old_root(client, sw_auth, sw_root, tmp_path):
    """改存储根目录 → **旧根自动记进历史** (2026-10-28).

    ⚠️ 这条是"换根后老文件变孤儿"的根因修复点:
       库里存的是**相对路径**, 换了根目录后"当前根 + 相对路径"就找不到老文件.
       所以改根目录时必须把旧根记下来, 让平台后续能在各个根里找文件.
    """
    new_root = tmp_path / "software-new"
    new_root.mkdir(parents=True, exist_ok=True)
    r = await client.put(
        "/api/v1/settings/software.storage_path",
        json={"value": str(new_root)},
        headers=sw_auth,
    )
    assert r.status_code == 200, r.text
    # 旧根进了历史
    from app.core.settings_store import get

    hist = (await get("software.storage_path_history", "")) or ""
    assert str(sw_root) in hist
    # 新值生效
    assert (await get("software.storage_path", "")) == str(new_root)


async def test_storage_probe_denied_for_non_admin(client, sw_root, publisher_user):
    """存储根是**服务端路径** —— 非管理员不该能探."""
    r = await client.post(
        "/api/v1/settings/test/software_storage",
        headers={"Authorization": f"Bearer {publisher_user['token']}"},
    )
    assert r.status_code == 403, r.text


async def test_storage_probe_reports_unwritable_root(client, sw_auth, sw_root, tmp_path):
    """目录不可写 → 报出来原因 (容器里没挂卷是最常见的)."""
    await set_setting("software.storage_path", str(tmp_path / "not-exist"))
    r = await client.post("/api/v1/settings/test/software_storage", headers=sw_auth)
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["ok"] is False
    assert "目录" in body["message"]


# ---------- 覆盖已有版本 (2026-10-30 · 第十一轮 · 问题3) ----------
#
# 用户的要求: "多版本功能也是需要……下次我又想只覆盖版本1或者版本2".
# → 发新版本时可选「新增一条」或「覆盖已有某一条」.
#
# ⚠️ 定稿语义: 覆盖 = **复用目标版本行** (不删行), 只重置字段 + 删旧文件目录.
#    删行的话, "文件没传成功" 就变成"版本凭空消失", 用户根本看不出来少了什么.


async def _create_two_versions(client, auth, root):
    """造一个有两个版本 (都传了文件) 的软件."""
    await _create(client, auth)
    await _upload(client, auth, "demo-sw", b"v1", filename="v1.bin")
    r = await client.post(
        "/api/v1/software/demo-sw/versions",
        json={"version": "2.0.0", "release_notes": "第二个版本",
              "file_name": "v2.bin", "file_size": 2, "is_default": False},
        headers=auth,
    )
    assert r.status_code == 201, r.text
    await _upload(client, auth, "demo-sw", b"v2", filename="v2.bin")
    return root


async def test_replace_version_reuses_row_and_keeps_count(client, sw_auth, sw_root):
    """覆盖 1.0.0 → 3.0.0: 版本**总条数不变** (还是两条), 目标那条被换掉."""
    await _create_two_versions(client, sw_auth, sw_root)

    r = await client.post(
        "/api/v1/software/demo-sw/versions",
        json={"version": "3.0.0", "release_notes": "覆盖后的说明",
              "file_name": "v3.bin", "file_size": 2,
              "replace_version": "1.0.0"},
        headers=sw_auth,
    )
    assert r.status_code == 201, r.text

    detail = await client.get("/api/v1/software/demo-sw", headers=sw_auth)
    versions = {v["version"]: v for v in detail.json()["versions"]}
    # ⚠️ 总条数不变 —— 覆盖不是新增
    assert len(versions) == 2, versions
    assert set(versions) == {"2.0.0", "3.0.0"}, versions
    assert "1.0.0" not in versions, "被覆盖的版本号应该消失 (行被复用了)"
    # 目标那条的内容换成了新的
    assert versions["3.0.0"]["release_notes"] == "覆盖后的说明"
    assert versions["3.0.0"]["status"] == "awaiting_file", "新文件还没传"
    # 其它版本不受影响
    assert versions["2.0.0"]["status"] == "ready"
    assert versions["2.0.0"]["release_notes"] == "第二个版本"


async def test_replace_version_deletes_old_file_dir(client, sw_auth, sw_root):
    """覆盖时旧版本的文件目录要清掉 (不然仓库里躺着两份包)."""
    await _create_two_versions(client, sw_auth, sw_root)
    assert (sw_root / "demo-sw" / "1.0.0").is_dir()

    r = await client.post(
        "/api/v1/software/demo-sw/versions",
        json={"version": "3.0.0", "file_name": "v3.bin", "file_size": 2,
              "replace_version": "1.0.0"},
        headers=sw_auth,
    )
    assert r.status_code == 201, r.text
    # 旧目录没了
    assert not (sw_root / "demo-sw" / "1.0.0").exists()
    # 别的版本的文件还在
    assert (sw_root / "demo-sw" / "2.0.0" / "v2.bin").is_file()


async def test_replace_version_same_number_is_allowed(client, sw_auth, sw_root):
    """同名覆盖 (1.0.0 → 1.0.0) 是合法的 —— 不算撞号."""
    await _create(client, sw_auth)
    await _upload(client, sw_auth, "demo-sw", b"v1", filename="v1.bin")

    r = await client.post(
        "/api/v1/software/demo-sw/versions",
        json={"version": "1.0.0", "release_notes": "重传的包",
              "file_name": "v1b.bin", "file_size": 3,
              "replace_version": "1.0.0"},
        headers=sw_auth,
    )
    assert r.status_code == 201, r.text
    detail = await client.get("/api/v1/software/demo-sw", headers=sw_auth)
    versions = detail.json()["versions"]
    assert len(versions) == 1
    assert versions[0]["version"] == "1.0.0"
    assert versions[0]["release_notes"] == "重传的包"
    assert versions[0]["status"] == "awaiting_file"


async def test_replace_version_onto_other_version_conflicts(client, sw_auth, sw_root):
    """覆盖成**别人已有的**版本号 → 409 (不能出现两个同号版本)."""
    await _create_two_versions(client, sw_auth, sw_root)
    r = await client.post(
        "/api/v1/software/demo-sw/versions",
        json={"version": "2.0.0", "file_name": "x.bin",
              "replace_version": "1.0.0"},
        headers=sw_auth,
    )
    assert r.status_code == 409, r.text


async def test_replace_version_keeps_default_unique(client, sw_auth, sw_root):
    """覆盖后**推荐版本仍然只有一个**."""
    await _create_two_versions(client, sw_auth, sw_root)
    r = await client.post(
        "/api/v1/software/demo-sw/versions",
        json={"version": "3.0.0", "file_name": "v3.bin", "file_size": 2,
              "is_default": True, "replace_version": "1.0.0"},
        headers=sw_auth,
    )
    assert r.status_code == 201, r.text
    detail = await client.get("/api/v1/software/demo-sw", headers=sw_auth)
    defaults = [v["version"] for v in detail.json()["versions"] if v["is_default"]]
    assert defaults == ["3.0.0"], defaults


async def test_replace_version_missing_target_404(client, sw_auth, sw_root):
    """要覆盖的版本不存在 → 404."""
    await _create(client, sw_auth)
    r = await client.post(
        "/api/v1/software/demo-sw/versions",
        json={"version": "2.0.0", "file_name": "x.bin", "replace_version": "9.9.9"},
        headers=sw_auth,
    )
    assert r.status_code == 404, r.text


async def test_replace_version_denied_for_others(client, sw_auth, sw_root, publisher_user):
    """覆盖别人上传的软件 → 403."""
    await _create(client, sw_auth)
    pauth = {"Authorization": f"Bearer {publisher_user['token']}"}
    r = await client.post(
        "/api/v1/software/demo-sw/versions",
        json={"version": "2.0.0", "file_name": "x.bin", "replace_version": "1.0.0"},
        headers=pauth,
    )
    assert r.status_code == 403, r.text


async def test_replace_version_by_author_allowed(client, sw_root, publisher_user):
    """作者本人可以覆盖自己的版本."""
    from tests.conftest import set_setting

    await set_setting("marketplace.publisher_usernames", publisher_user["username"])
    pauth = {"Authorization": f"Bearer {publisher_user['token']}"}
    r = await client.post(
        "/api/v1/software",
        json={"code": "own-sw", "name": "我的软件", "version": "1.0.0",
              "summary": "x", "icon": "📦", "file_name": "a.bin"},
        headers=pauth,
    )
    assert r.status_code == 201, r.text
    await _upload(client, pauth, "own-sw", b"v1", filename="a.bin")

    r2 = await client.post(
        "/api/v1/software/own-sw/versions",
        json={"version": "2.0.0", "file_name": "b.bin", "file_size": 2,
              "replace_version": "1.0.0"},
        headers=pauth,
    )
    assert r2.status_code == 201, r2.text
    detail = await client.get("/api/v1/software/own-sw", headers=pauth)
    assert len(detail.json()["versions"]) == 1
