"""包处理单元测试 —— 解包安全是市场的第一道防线.

覆盖: zip-slip / 绝对路径 / 符号链接 / 敏感路径 / 体积与数量预算 /
      公共顶层目录剥离 / 确定性打包 / frontmatter 解析.
"""
from __future__ import annotations

import io
import json
import tarfile
import zipfile
from pathlib import Path

import pytest

from app.core import pkg


# ---------- 正常解包 ----------

def test_extract_zip_basic(tmp_path: Path):
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        z.writestr("SKILL.md", "---\nname: a\n---\n\n正文\n")
        z.writestr("docs/readme.md", "说明\n")
    dest = tmp_path / "out"
    res = pkg.extract_package(buf.getvalue(), "a.zip", dest)
    assert set(res.files) == {"SKILL.md", "docs/readme.md"}
    assert (dest / "SKILL.md").read_text().startswith("---")
    assert res.total_bytes > 0
    assert len(res.package_sha256) == 64


def test_extract_strips_common_top_dir(tmp_path: Path):
    """压缩包里多套一层同名目录 → 应被剥掉, 否则 files/ 下会多一层壳."""
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        z.writestr("my-skill/SKILL.md", "内容\n")
        z.writestr("my-skill/ref/a.md", "参考\n")
    dest = tmp_path / "out"
    res = pkg.extract_package(buf.getvalue(), "my-skill.zip", dest)
    assert set(res.files) == {"SKILL.md", "ref/a.md"}


def test_extract_tar_gz(tmp_path: Path):
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w:gz") as t:
        data = b"tar content\n"
        info = tarfile.TarInfo("SKILL.md")
        info.size = len(data)
        t.addfile(info, io.BytesIO(data))
    dest = tmp_path / "out"
    res = pkg.extract_package(buf.getvalue(), "a.tar.gz", dest)
    assert res.files == ["SKILL.md"]
    assert res.suffix == ".tar.gz"


def test_extract_rejects_unknown_format(tmp_path: Path):
    with pytest.raises(pkg.PackageError, match="不支持的包格式"):
        pkg.extract_package(b"x", "a.rar", tmp_path / "o")


def test_extract_rejects_empty_package(tmp_path: Path):
    with pytest.raises(pkg.PackageError):
        pkg.extract_package(b"", "a.zip", tmp_path / "o")


# ---------- 攻击面: 路径逃逸 ----------

def test_rejects_zip_slip(tmp_path: Path):
    """zip-slip: 条目名带 ../ → 必须拒绝, 绝不能写到 dest 外面."""
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        z.writestr("../../evil.txt", "pwned")
    dest = tmp_path / "out"
    with pytest.raises(pkg.PackageError):
        pkg.extract_package(buf.getvalue(), "evil.zip", dest)
    assert not (tmp_path / "evil.txt").exists()
    assert not (dest.parent / "evil.txt").exists()


def test_rejects_absolute_path(tmp_path: Path):
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        z.writestr("/etc/passwd", "pwned")
    with pytest.raises(pkg.PackageError):
        pkg.extract_package(buf.getvalue(), "abs.zip", tmp_path / "out")


def test_rejects_windows_drive_path(tmp_path: Path):
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        z.writestr("C:\\Windows\\evil.txt", "pwned")
    with pytest.raises(pkg.PackageError):
        pkg.extract_package(buf.getvalue(), "win.zip", tmp_path / "out")


def test_rejects_tar_zip_slip(tmp_path: Path):
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w:gz") as t:
        data = b"pwned"
        info = tarfile.TarInfo("../evil.txt")
        info.size = len(data)
        t.addfile(info, io.BytesIO(data))
    with pytest.raises(pkg.PackageError):
        pkg.extract_package(buf.getvalue(), "evil.tar.gz", tmp_path / "out")
    assert not (tmp_path / "evil.txt").exists()


# ---------- 攻击面: 符号链接 ----------

def test_rejects_zip_symlink(tmp_path: Path):
    """符号链接指向工作区外 → 必须拒绝 (否则等于任意文件写)."""
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        info = zipfile.ZipInfo("link")
        info.external_attr = (0o120777 << 16)  # 符号链接
        z.writestr(info, "/etc/passwd")
    with pytest.raises(pkg.PackageError, match="符号链接"):
        pkg.extract_package(buf.getvalue(), "link.zip", tmp_path / "out")


def test_rejects_tar_symlink(tmp_path: Path):
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w:gz") as t:
        info = tarfile.TarInfo("link")
        info.type = tarfile.SYMTYPE
        info.linkname = "/etc/passwd"
        t.addfile(info)
    with pytest.raises(pkg.PackageError, match="符号链接|硬链接"):
        pkg.extract_package(buf.getvalue(), "link.tar.gz", tmp_path / "out")


# ---------- 攻击面: 敏感路径 ----------

@pytest.mark.parametrize(
    "bad_path",
    [
        ".env",
        "sub/.env",
        ".ssh/id_rsa",
        "sub/.ssh/id_rsa",
        "id_rsa",
        ".npmrc",
        ".git/config",
    ],
)
def test_rejects_sensitive_paths(tmp_path: Path, bad_path: str):
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        z.writestr(bad_path, "secret")
    with pytest.raises(pkg.PackageError):
        pkg.extract_package(buf.getvalue(), "s.zip", tmp_path / "out")


# ---------- 攻击面: 预算 ----------

def test_rejects_too_many_entries(tmp_path: Path):
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        for i in range(12):
            z.writestr(f"f{i}.md", "x")
    with pytest.raises(pkg.PackageError, match="超限"):
        pkg.extract_package(buf.getvalue(), "many.zip", tmp_path / "o", max_entries=5)


def test_rejects_oversized_total(tmp_path: Path):
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        z.writestr("big.md", "A" * 5000)
    with pytest.raises(pkg.PackageError, match="超限"):
        pkg.extract_package(buf.getvalue(), "big.zip", tmp_path / "o", max_total_bytes=1000)


def test_rejects_oversized_single_file(tmp_path: Path):
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        z.writestr("big.md", "A" * 5000)
    with pytest.raises(pkg.PackageError, match="单个文件过大"):
        pkg.extract_package(buf.getvalue(), "big.zip", tmp_path / "o", max_file_bytes=100)


def test_rejects_oversized_package_bytes(tmp_path: Path):
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        z.writestr("a.md", "A" * 5000)
    with pytest.raises(pkg.PackageError, match="过大|超限"):
        pkg.extract_package(buf.getvalue(), "big.zip", tmp_path / "o", max_package_bytes=100)


# ---------- 确定性打包 ----------

def test_build_zip_is_deterministic(tmp_path: Path):
    """同一份内容打包两次, 字节必须一致 —— marketplace.json 的 sha256 依赖这个."""
    src = tmp_path / "src"
    (src / "sub").mkdir(parents=True)
    (src / "a.md").write_text("A\n")
    (src / "sub" / "b.md").write_text("B\n")
    one = pkg.build_zip(src)
    two = pkg.build_zip(src)
    assert one == two
    assert pkg.sha256_bytes(one) == pkg.sha256_bytes(two)


def test_build_zip_roundtrip(tmp_path: Path):
    src = tmp_path / "src"
    src.mkdir()
    (src / "SKILL.md").write_text("内容\n")
    data = pkg.build_zip(src)
    dest = tmp_path / "back"
    res = pkg.extract_package(data, "a.zip", dest)
    assert res.files == ["SKILL.md"]
    assert (dest / "SKILL.md").read_text() == "内容\n"


# ---------- frontmatter ----------

def test_parse_frontmatter():
    meta, body = pkg.parse_frontmatter(
        "---\nname: demo\ndescription: 描述\ntags: [a, b]\n---\n\n# 标题\n正文\n"
    )
    assert meta["name"] == "demo"
    assert meta["description"] == "描述"
    assert "# 标题" in body
    assert "name: demo" not in body


def test_parse_frontmatter_absent():
    meta, body = pkg.parse_frontmatter("没有 frontmatter 的正文\n")
    assert meta == {}
    assert "没有 frontmatter" in body


def test_parse_frontmatter_malformed():
    """frontmatter 坏掉时不能抛异常 —— 顶多当普通文本."""
    meta, body = pkg.parse_frontmatter("---\nname: 未闭合\n正文\n")
    assert isinstance(meta, dict)
    assert isinstance(body, str)


# ---------- 文档文件定位 ----------

def test_find_doc_file():
    assert pkg.find_doc_file(["SKILL.md", "a.md"], "skill") == "SKILL.md"
    assert pkg.find_doc_file(["README.md"], "plugin") == "README.md"
    assert pkg.find_doc_file(["docs/SKILL.md"], "skill") == "docs/SKILL.md"
    assert pkg.find_doc_file(["a.md"], "skill") is None


# ---------- 工作区布局 ----------

def test_files_root_prefers_files_dir(tmp_path: Path):
    (tmp_path / "files").mkdir()
    (tmp_path / "README.md").write_text("外层")
    (tmp_path / "files" / "SKILL.md").write_text("内层")
    assert pkg.files_root(tmp_path) == tmp_path / "files"


def test_files_root_falls_back_to_base(tmp_path: Path):
    (tmp_path / "README.md").write_text("x")
    assert pkg.files_root(tmp_path) == tmp_path


def test_content_files_excludes_reserved(tmp_path: Path):
    """manifest.json 与 package/ 是仓库侧的东西, 不能进用户安装目录."""
    (tmp_path / "files").mkdir()
    (tmp_path / "files" / "SKILL.md").write_text("x")
    (tmp_path / "files" / "manifest.json").write_text("{}")
    (tmp_path / "files" / "package").mkdir()
    (tmp_path / "files" / "package" / "1.0.0.zip").write_bytes(b"zip")
    names = {p.name for p in pkg.content_files(tmp_path)}
    assert names == {"SKILL.md"}


def test_sha256_helpers(tmp_path: Path):
    f = tmp_path / "a.bin"
    f.write_bytes(b"hello")
    assert pkg.sha256_bytes(b"hello") == pkg.sha256_file(f)
    assert len(pkg.sha256_bytes(b"x")) == 64
