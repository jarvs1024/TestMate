"""安装包解包 — zip / tar.gz, 带完整安全防护.

上传的是**压缩包**, 解压发生在服务端 (在推 git 之前), 因此:
  - git 里存的是解压后的明文文件树 (可 diff、可 review)
  - **安装端拿到的直接是明文文件, 全程无需解压** —— 前端因此不需要 zip 库
    (浏览器原生 DecompressionStream 不支持 zip)

安全防护 (缺一不可):
  1. zip-slip      —— 条目路径规范化后必须仍在解压根目录内 (拒绝 ../ 与绝对路径)
  2. zip bomb      —— 解压后总大小上限 + 条目数上限
  3. 符号链接逃逸   —— 拒绝指向根目录外的符号链接
  4. 敏感路径      —— 拒绝含 .git/ .ssh/ .env 等的包
  5. 单文件上限    —— 防止单个超大文件撑爆磁盘
"""
from __future__ import annotations

import hashlib
import os
import shutil
import tarfile
import zipfile
from dataclasses import dataclass
from pathlib import Path

# 包格式
ZIP_SUFFIXES = {".zip"}
TAR_SUFFIXES = {".tar.gz", ".tgz"}

# 解压后各项上限
DEFAULT_MAX_ENTRIES = 5000
DEFAULT_MAX_TOTAL_BYTES = 200 * 1024 * 1024      # 200MB
DEFAULT_MAX_FILE_BYTES = 50 * 1024 * 1024        # 单文件 50MB
DEFAULT_MAX_PACKAGE_BYTES = 50 * 1024 * 1024    # 压缩包本身 50MB

# 敏感路径片段 (相对路径里出现即拒绝)
FORBIDDEN_PARTS = {
    ".git", ".ssh", ".gnupg", ".aws", ".config/gcloud",
    ".env", ".env.local", ".npmrc", ".pypirc", "id_rsa", "id_ed25519",
}


class PackageError(ValueError):
    """包不合规 (可重试性由调用方决定, 这里只描述原因)."""


@dataclass
class ExtractedPackage:
    """解包结果."""

    files: list[str]           # 相对解压根目录的路径列表
    total_bytes: int
    package_sha256: str        # 原始压缩包的 sha256 (字节稳定, 用于 marketplace source.sha256)
    suffix: str                # 原始包扩展名


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def _is_forbidden(rel: str) -> bool:
    parts = [p for p in rel.replace("\\", "/").split("/") if p]
    for p in parts:
        if p in FORBIDDEN_PARTS:
            return True
    # 也拦 .env.* 这种
    for p in parts:
        if p.startswith(".env"):
            return True
    return False


def _safe_target(root: Path, rel: str) -> Path:
    """把条目路径解析成目标绝对路径, 并确保它仍在 root 内 (zip-slip 防护)."""
    norm = rel.replace("\\", "/").lstrip("/")
    if not norm or norm in (".", "/"):
        raise PackageError(f"非法条目路径: {rel!r}")
    if ".." in norm.split("/"):
        raise PackageError(f"条目路径含上级引用 (zip-slip): {rel!r}")
    if ":" in norm.split("/")[0] and os.name == "nt":
        raise PackageError(f"条目路径含盘符: {rel!r}")
    target = (root / norm).resolve()
    root_resolved = root.resolve()
    if target != root_resolved and root_resolved not in target.parents:
        raise PackageError(f"条目路径逃逸出解压根目录 (zip-slip): {rel!r}")
    return target


def _check_budget(rel: str, size: int, entries: int, total: int,
                  max_entries: int, max_total: int, max_file: int) -> tuple[int, int]:
    if entries > max_entries:
        raise PackageError(f"包内条目数超限 ({entries} > {max_entries})")
    if size > max_file:
        raise PackageError(f"单个文件过大: {rel} ({size} > {max_file} 字节)")
    total += size
    if total > max_total:
        raise PackageError(f"解压后总体积超限 ({total} > {max_total} 字节, 疑似 zip bomb)")
    return entries + 1, total


def _validate_original_path(rel: str) -> None:
    """对**原始**条目路径做安全校验.

    ⚠️ 必须在"剥公共顶层目录"**之前**执行. 否则 '../evil.txt' 会被当成
    公共顶层目录剥成 'evil.txt', 正好绕过 zip-slip 检查 —— 这是实测踩到的坑.
    """
    norm = rel.replace("\\", "/")
    if norm.startswith("/"):
        raise PackageError(f"条目路径为绝对路径: {rel!r}")
    parts = [p for p in norm.split("/") if p]
    if ".." in parts:
        raise PackageError(f"条目路径含上级引用 (zip-slip): {rel!r}")
    if len(parts) > 1 and ":" in parts[0]:
        raise PackageError(f"条目路径含盘符: {rel!r}")


def _common_root_prefix(paths: list[str]) -> str:
    """算出所有条目共用的顶层目录前缀 (没有则返回 "").

    包通常是 `skill-name/SKILL.md` 这种带一层顶层目录的. 不剥掉的话安装后会变成
    ~/.qoder-cn/skills/<code>/<code>/SKILL.md —— 多一层, Qoder 认不出来.
    只在**所有**条目都共享同一个顶层目录时才剥 (避免把本就在根目录的文件误伤).
    """
    tops = set()
    for p in paths:
        norm = p.replace("\\", "/").lstrip("/")
        if not norm or norm == ".":
            continue
        parts = norm.split("/")
        if len(parts) < 2:
            return ""   # 有条目直接在根 → 不剥
        tops.add(parts[0])
    if len(tops) != 1:
        return ""
    top = next(iter(tops))
    # 顶层名本身不安全 → 不剥 (交给 _validate_original_path 拦截)
    if top in (".", "..") or top.startswith("."):
        return ""
    return f"{top}/"


def _strip_prefix(rel: str, prefix: str) -> str:
    if prefix and rel.startswith(prefix):
        return rel[len(prefix):]
    return rel


def _extract_zip(data: bytes, dest: Path, *, max_entries: int,
                 max_total: int, max_file: int) -> tuple[list[str], int]:
    import io

    files: list[str] = []
    entries = 0
    total = 0
    with zipfile.ZipFile(io.BytesIO(data)) as zf:
        names = [i.filename for i in zf.infolist() if not i.is_dir()]
        # 先对原始路径做安全校验, 再算公共顶层目录 —— 顺序不能反
        for n in names:
            _validate_original_path(n)
        prefix = _common_root_prefix(names)
        for info in zf.infolist():
            if info.is_dir():
                continue
            rel = info.filename
            if _is_forbidden(rel):
                raise PackageError(f"包内含敏感路径: {rel}")
            # 0xA000 = 符号链接 (unix)
            if (info.external_attr >> 16) & 0o170000 == 0o120000:
                raise PackageError(f"包内含符号链接 (拒绝, 防逃逸): {rel}")
            target = _safe_target(dest, _strip_prefix(rel, prefix))
            entries, total = _check_budget(
                rel, info.file_size, entries, total, max_entries, max_total, max_file
            )
            target.parent.mkdir(parents=True, exist_ok=True)
            with zf.open(info) as src, target.open("wb") as out:
                shutil.copyfileobj(src, out, length=1024 * 1024)
            files.append(_strip_prefix(rel, prefix))
    return files, total


def _extract_tar(data: bytes, dest: Path, *, max_entries: int,
                 max_total: int, max_file: int) -> tuple[list[str], int]:
    import io

    files: list[str] = []
    entries = 0
    total = 0
    with tarfile.open(fileobj=io.BytesIO(data), mode="r:*") as tf:
        members = [m for m in tf.getmembers() if not m.isdir()]
        # 先对原始路径做安全校验, 再算公共顶层目录 —— 顺序不能反
        for m in members:
            _validate_original_path(m.name)
        prefix = _common_root_prefix([m.name for m in members])
        for member in members:
            if member.issym() or member.islnk():
                raise PackageError(f"包内含符号链接/硬链接 (拒绝, 防逃逸): {member.name}")
            if not member.isfile():
                raise PackageError(f"包内含特殊文件 (拒绝): {member.name}")
            rel = member.name
            if _is_forbidden(rel):
                raise PackageError(f"包内含敏感路径: {rel}")
            target = _safe_target(dest, _strip_prefix(rel, prefix))
            entries, total = _check_budget(
                rel, member.size, entries, total, max_entries, max_total, max_file
            )
            target.parent.mkdir(parents=True, exist_ok=True)
            src = tf.extractfile(member)
            if src is None:
                continue
            with src, target.open("wb") as out:
                shutil.copyfileobj(src, out, length=1024 * 1024)
            files.append(_strip_prefix(rel, prefix))
    return files, total


def extract_package(
    data: bytes,
    filename: str,
    dest: Path,
    *,
    max_entries: int = DEFAULT_MAX_ENTRIES,
    max_total_bytes: int = DEFAULT_MAX_TOTAL_BYTES,
    max_file_bytes: int = DEFAULT_MAX_FILE_BYTES,
    max_package_bytes: int = DEFAULT_MAX_PACKAGE_BYTES,
) -> ExtractedPackage:
    """把压缩包解到 dest. 返回文件清单与原始包 sha256.

    dest 必须**不存在或为空** —— 解包前会清空.
    """
    name = (filename or "").lower()
    if name.endswith(".zip"):
        suffix = ".zip"
    elif name.endswith(".tar.gz") or name.endswith(".tgz"):
        suffix = ".tar.gz"
    else:
        raise PackageError(
            f"不支持的包格式: {filename} (支持 .zip / .tar.gz / .tgz)"
        )

    if len(data) > max_package_bytes:
        raise PackageError(
            f"压缩包过大 ({len(data)} > {max_package_bytes} 字节)"
        )
    if not data:
        raise PackageError("压缩包为空")

    if dest.exists():
        shutil.rmtree(dest, ignore_errors=True)
    dest.mkdir(parents=True, exist_ok=True)

    try:
        if suffix == ".zip":
            files, total = _extract_zip(
                data, dest,
                max_entries=max_entries, max_total=max_total_bytes, max_file=max_file_bytes,
            )
        else:
            files, total = _extract_tar(
                data, dest,
                max_entries=max_entries, max_total=max_total_bytes, max_file=max_file_bytes,
            )
    except PackageError:
        shutil.rmtree(dest, ignore_errors=True)
        raise
    except zipfile.BadZipFile as e:
        shutil.rmtree(dest, ignore_errors=True)
        raise PackageError(f"zip 包损坏: {e}") from e
    except tarfile.TarError as e:
        shutil.rmtree(dest, ignore_errors=True)
        raise PackageError(f"tar 包损坏: {e}") from e

    if not files:
        shutil.rmtree(dest, ignore_errors=True)
        raise PackageError("包内没有任何文件")

    return ExtractedPackage(
        files=sorted(files),
        total_bytes=total,
        package_sha256=sha256_bytes(data),
        suffix=suffix,
    )


def find_doc_file(files: list[str], kind: str) -> str | None:
    """在文件清单里找展示用的文档: skill→SKILL.md, plugin→README.md."""
    wanted = "SKILL.md" if kind == "skill" else "README.md"
    # 优先根目录下的
    for f in files:
        if f == wanted:
            return f
    # 其次任意层级 (取最短路径)
    cands = [f for f in files if f.lower().endswith("/" + wanted.lower())]
    if cands:
        return min(cands, key=lambda p: (p.count("/"), len(p)))
    return None


def read_text_safe(path: Path, max_bytes: int = 512 * 1024) -> str | None:
    """读文本文件 (超过上限截断). 二进制返回 None."""
    try:
        if not path.is_file():
            return None
        raw = path.read_bytes()[:max_bytes]
        return raw.decode("utf-8", errors="replace")
    except OSError:
        return None


RESERVED_NAMES = {"manifest.json"}
RESERVED_DIRS = {"package"}


def files_root(base: Path) -> Path:
    """返回资产内容所在目录.

    兼容两种布局:
      新: <asset>/files/**        (压缩包解出来的内容)
      旧: <asset>/**             (早期文本上传, 文件直接在资产根下)
    """
    files_dir = base / "files"
    return files_dir if files_dir.is_dir() else base


def content_files(base: Path) -> list[Path]:
    """列出资产的内容文件 (排除 manifest.json 与 package/ 目录)."""
    root = files_root(base)
    out: list[Path] = []
    for p in sorted(root.rglob("*")):
        if not p.is_file():
            continue
        rel = p.relative_to(root)
        if rel.parts and rel.parts[0] in RESERVED_DIRS:
            continue
        if rel.name in RESERVED_NAMES:
            continue
        out.append(p)
    return out


def build_zip(src_dir: Path, prefix: str = "") -> bytes:
    """把目录打包成**确定性**的 zip (字节稳定).

    确定性来自三件事:
      - 文件按路径排序
      - 每个条目的时间戳固定为 1980-01-01 (zip 格式的最早时间)
      - 压缩方式与级别固定

    为什么要确定性: Qoder 原生 marketplace 的 source.sha256 必须与实际下载到的
    字节一致. 若每次请求都重新打包, sha256 会随实现细节漂移 → Qoder 校验失败.
    """
    import io
    import zipfile

    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        for path in sorted(src_dir.rglob("*")):
            if not path.is_file():
                continue
            rel = path.relative_to(src_dir).as_posix()
            arcname = f"{prefix}{rel}" if prefix else rel
            info = zipfile.ZipInfo(arcname, date_time=(1980, 1, 1, 0, 0, 0))
            info.compress_type = zipfile.ZIP_DEFLATED
            info.external_attr = 0o644 << 16
            zf.writestr(info, path.read_bytes())
    return buf.getvalue()


def parse_frontmatter(text: str) -> tuple[dict, str]:
    """解析 markdown frontmatter, 返回 (元信息 dict, 正文).

    只支持最简单的 `key: value` 形态 (YAML 的子集) —— 足够覆盖
    name / description / license 这几个常见字段, 且不引入 pyyaml 依赖.
    """
    if not text.startswith("---"):
        return {}, text
    lines = text.splitlines()
    if not lines or lines[0].strip() != "---":
        return {}, text
    end = None
    for i in range(1, len(lines)):
        if lines[i].strip() == "---":
            end = i
            break
    if end is None:
        return {}, text
    meta: dict = {}
    for line in lines[1:end]:
        if not line.strip() or line.lstrip().startswith("#"):
            continue
        if ":" not in line:
            continue
        k, v = line.split(":", 1)
        k = k.strip()
        v = v.strip()
        if len(v) >= 2 and v[0] == v[-1] and v[0] in "\"'":
            v = v[1:-1]
        if k:
            meta[k] = v
    body = "\n".join(lines[end + 1 :])
    return meta, body
