"""第二十一轮: 下载到本地的安装包名**不带版本号** (dml-xxx.zip).

⚠️ 背景: 仓库里存的原始安装包叫 "{version}.zip" (1.0.0.zip / 1.1.0.zip …),
   以前直接把这个名字发给浏览器 → 用户存到本地全是 "1.0.0.zip",
   一屏下三四个扩展就互相覆盖, 还根本认不出谁是谁.
   现在统一成 "{code}.zip" —— code 才是这个扩展的**身份**.

覆盖:
  · 纯函数 market_naming.download_filename / package_media_type 的规则
  · 真 HTTP 下载端点的 Content-Disposition / Content-Type
  · 无原始包时"即时打包"那条路也走同一套命名
"""
from __future__ import annotations

import io
import zipfile

import pytest

from app.core import market_naming

API = "/api/v1/extensions"


# ---------- 纯函数: 命名规则 ----------

def test_download_filename_is_code_without_version():
    """核心断言: 文件名 = code + 真实后缀, **不含版本号**."""
    assert market_naming.download_filename("dml-ssd-log-doctor", "1.0.0.zip") == (
        "dml-ssd-log-doctor.zip"
    )
    assert market_naming.download_filename("dml-ssd-log-doctor", "1.1.0.zip") == (
        "dml-ssd-log-doctor.zip"
    )
    # 同一个 code 的不同版本 → 文件名一样 (升级不会在本地堆出一堆同名不同版)
    assert market_naming.download_filename("dml-a", "1.0.0.zip") == market_naming.download_filename(
        "dml-a", "9.9.9.zip"
    )


@pytest.mark.parametrize(
    ("source_name", "expected"),
    [
        ("1.0.0.zip", "dml-a.zip"),
        ("1.0.0.tar.gz", "dml-a.tar.gz"),
        ("1.0.0.tgz", "dml-a.tgz"),
        ("1.0.0.ZIP", "dml-a.zip"),          # 大写后缀也认
        ("1.0.0.TAR.GZ", "dml-a.tar.gz"),
        ("", "dml-a.zip"),                    # 没有源名 → 默认 zip
        ("whatever", "dml-a.zip"),
    ],
)
def test_download_filename_suffix_follows_real_content(source_name, expected):
    """后缀跟着**真实内容**走 —— tar.gz 的包不能硬给个 .zip 的名字."""
    assert market_naming.download_filename("dml-a", source_name) == expected


def test_download_filename_sanitizes_code_for_header_safety():
    """code 会进 Content-Disposition 头 —— 引号/换行就是头注入."""
    assert market_naming.download_filename('dml-a"b', "1.0.0.zip") == "dml-a_b.zip"
    assert market_naming.download_filename("dml-a\r\nX-Evil", "1.0.0.zip") == (
        "dml-a__X-Evil.zip"
    )
    assert market_naming.download_filename("", "1.0.0.zip") == "package.zip"
    assert market_naming.download_filename("   ", "1.0.0.zip") == "package.zip"


def test_package_media_type_matches_suffix():
    assert market_naming.package_media_type("dml-a.zip") == "application/zip"
    assert market_naming.package_media_type("dml-a.tar.gz") == "application/gzip"
    assert market_naming.package_media_type("dml-a.tgz") == "application/gzip"
    assert market_naming.package_media_type("") == "application/zip"


# ---------- 真 HTTP: 下载端点 ----------

def _zip_bytes(files: dict[str, str], filename: str = "pkg.zip") -> tuple[str, bytes, str]:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        for name, content in files.items():
            z.writestr(name, content)
    return (filename, buf.getvalue(), "application/zip")


async def _upload(client, auth, code="demo", kind="skill", version="1.0.0", pkg_bytes=None):
    if pkg_bytes is None:
        pkg_bytes = _zip_bytes(
            {"SKILL.md": f"---\nname: {code}\ndescription: d\n---\n\n# {code}\n"},
            filename=f"{code}.zip",
        )
    data = {
        "code": code, "kind": kind, "name": f"资产-{code}", "version": version,
        "summary": "摘要", "description": "说明", "use_when": "何时", "not_for": "何时不",
        "category": "misc", "icon": "🧩", "tags": "[]", "keywords": "[]",
        "featured": "false", "permissions": "{}", "install_steps": "[]", "bindings": "{}",
    }
    return await client.post(
        f"{API}/upload", data=data,
        files={"package": (pkg_bytes[0], pkg_bytes[1], pkg_bytes[2])},
        headers=auth,
    )


async def _publish_direct(client, auth, **kw):
    """关掉审核 + 把发布者加白名单 → 上传即上架."""
    from tests.conftest import set_setting

    await set_setting("extensions.review.enabled", "false")
    await set_setting("extensions.publisher_usernames", "r21-publisher")
    return await _upload(client, auth, **kw)


async def test_download_endpoint_serves_code_filename_without_version(
    client, auth, ws, restore_git_config, publisher_user  # noqa: ARG001
):
    """下载端点: Content-Disposition 里的文件名是 {code}.zip, **不带版本号**."""
    pauth = {"Authorization": f"Bearer {publisher_user['token']}"}
    r = await _publish_direct(client, pauth, code="dml-round21-demo")
    assert r.status_code == 202, r.text

    resp = await client.get(f"{API}/dml-round21-demo/versions/1.0.0/download", headers=auth)
    assert resp.status_code == 200, resp.text
    disposition = resp.headers["content-disposition"]
    assert disposition == 'attachment; filename="dml-round21-demo.zip"'
    # 明确不该出现的形态
    assert "1.0.0.zip" not in disposition
    assert "dml-round21-demo-1.0.0.zip" not in disposition
    assert resp.headers["content-type"] == "application/zip"


async def test_download_endpoint_uses_code_for_later_versions_too(
    client, auth, ws, restore_git_config, publisher_user  # noqa: ARG001
):
    """同一资产换版本 → 文件名不变 (还是 dml-xxx.zip)."""
    pauth = {"Authorization": f"Bearer {publisher_user['token']}"}
    r = await _publish_direct(client, pauth, code="dml-round21-ver")
    assert r.status_code == 202, r.text

    resp = await client.get(f"{API}/dml-round21-ver/versions/1.0.0/download", headers=auth)
    assert resp.status_code == 200, resp.text
    assert resp.headers["content-disposition"] == 'attachment; filename="dml-round21-ver.zip"'


async def test_download_endpoint_content_type_matches_tar_gz_package(
    client, auth, ws, restore_git_config, publisher_user  # noqa: ARG001
):
    """tar.gz 的包: 文件名后缀 + Content-Type 都得是 tar.gz 那套, 不能硬标成 zip."""
    import tarfile

    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w:gz") as tf:
        payload = b"---\nname: dml-round21-tgz\ndescription: d\n---\n\n# x\n"
        info = tarfile.TarInfo("SKILL.md")
        info.size = len(payload)
        tf.addfile(info, io.BytesIO(payload))

    pauth = {"Authorization": f"Bearer {publisher_user['token']}"}
    r = await _publish_direct(
        client, pauth, code="dml-round21-tgz",
        pkg_bytes=("dml-round21-tgz.tar.gz", buf.getvalue(), "application/gzip"),
    )
    assert r.status_code == 202, r.text

    resp = await client.get(f"{API}/dml-round21-tgz/versions/1.0.0/download", headers=auth)
    assert resp.status_code == 200, resp.text
    assert resp.headers["content-disposition"] == (
        'attachment; filename="dml-round21-tgz.tar.gz"'
    )
    assert resp.headers["content-type"] == "application/gzip"


async def test_download_endpoint_names_code_when_no_stored_package(
    client, auth, ws, restore_git_config, publisher_user  # noqa: ARG001
):
    """老资产没有存原始包 → 即时打包那条路, 文件名照样是 {code}.zip."""
    from app.core import git_sync
    from sqlalchemy import select as _sel

    from app.db.session import AsyncSessionLocal
    from app.models.asset import Asset

    pauth = {"Authorization": f"Bearer {publisher_user['token']}"}
    r = await _publish_direct(client, pauth, code="dml-round21-nopkg")
    assert r.status_code == 202, r.text

    # 把存的原始包删掉 (模拟"只有文件、没有包"的老资产)
    async with AsyncSessionLocal() as s:
        asset = (await s.execute(
            _sel(Asset).where(Asset.code == "dml-round21-nopkg")
        )).scalar_one()
        base = git_sync.resolve_in_workspace(asset.git_path)
        pkg_dir = base / "package"
        for f in pkg_dir.iterdir():
            f.unlink()

    resp = await client.get(f"{API}/dml-round21-nopkg/versions/1.0.0/download", headers=auth)
    assert resp.status_code == 200, resp.text
    assert resp.headers["content-disposition"] == 'attachment; filename="dml-round21-nopkg.zip"'
    assert resp.content[:2] == b"PK"
