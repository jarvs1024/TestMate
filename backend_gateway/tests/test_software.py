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


async def test_create_duplicate_code_conflicts(client, sw_auth, sw_root):
    """同一个 code 只能有一个条目."""
    await _create(client, sw_auth)
    r = await client.post(
        "/api/v1/software",
        json={"code": "demo-sw", "name": "再来一个", "version": "1.0.0", "summary": "x"},
        headers=sw_auth,
    )
    assert r.status_code == 409, r.text


# ---------- 文件名清洗 ----------


async def test_upload_sanitizes_file_name(client, sw_auth, sw_root):
    """``../../etc/passwd`` → 落成 ``passwd`` (不能写到根目录外面去)."""
    await _create(client, sw_auth)
    r = await _upload(client, sw_auth, "demo-sw", b"x", filename="../../etc/passwd")
    assert r.status_code == 200, r.text
    assert (sw_root / "demo-sw" / "1.0.0" / "passwd").is_file()
    # 不该有任何文件跑到根目录外面
    assert not (sw_root.parent / "etc").exists()


async def test_upload_strips_leading_dots(client, sw_auth, sw_root):
    """前导点被剥掉 (``..`` 挡掉)."""
    await _create(client, sw_auth)
    r = await _upload(client, sw_auth, "demo-sw", b"x", filename="..hidden.bin")
    assert r.status_code == 200, r.text
    assert (sw_root / "demo-sw" / "1.0.0" / "hidden.bin").is_file()


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
    """超过保留数时, 最老的版本被清掉 (行 + 磁盘文件)."""
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
    assert len(versions) == 2, versions
    assert "1.0.0" not in versions
    # 老版本的目录也被清掉了
    assert not (sw_root / "demo-sw" / "1.0.0").exists()


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
        json={"code": "draft-sw", "name": "没传完的", "version": "0.1.0", "summary": "x"},
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


async def test_purge_requires_admin(client, sw_auth, sw_root, publisher_user):
    """彻底清理只有管理员能做."""
    await _create(client, sw_auth)
    auth2 = {"Authorization": f"Bearer {publisher_user['token']}"}
    r = await client.delete("/api/v1/software/demo-sw/purge", headers=auth2)
    assert r.status_code == 403, r.text


async def test_purge_removes_files(client, sw_auth, sw_root):
    """彻底清理: 记录与磁盘文件一起删."""
    await _create(client, sw_auth)
    await _upload(client, sw_auth, "demo-sw", b"hello")
    assert (sw_root / "demo-sw").is_dir()
    r = await client.delete("/api/v1/software/demo-sw/purge", headers=sw_auth)
    assert r.status_code == 200, r.text
    assert not (sw_root / "demo-sw").exists()
    assert (await client.get("/api/v1/software/demo-sw", headers=sw_auth)).status_code == 404


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
    """换根目录后, 「检查路径」要能说出缺哪些文件."""
    await _create(client, sw_auth)
    await _upload(client, sw_auth, "demo-sw", b"hello")

    # 换到一个空根目录 (模拟"改了设置但文件没搬")
    await set_setting("software.storage_path", str(sw_root.parent / "elsewhere"))
    r = await client.get("/api/v1/software/path-check", headers=sw_auth)
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["missing_count"] == 1
    assert body["missing"][0]["code"] == "demo-sw"


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
