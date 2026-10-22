"""资产目录层 — index.json 生成 / 校验 / DB 镜像同步.

index.json 是 GitLab 仓库根目录下的一份索引, 前端列表直接消费它。
它由 **数据库镜像** 渲染而成 (不是每次去 git 逐个读 manifest), 所以一次上传
只需要一次 commit, 不产生 N 次 API 调用; DB 被清空时从 index.json 回灌即可。

上传一次写入的内容 (一个 commit, 原子生效):
    assets/{kind}/{category_slug}/{code}/manifest.json
    assets/{kind}/{category_slug}/{code}/README.md
    assets/{kind}/{category_slug}/{code}/<用户上传的其他文本文件>
    index.json                                  ← 同一次 commit 里一并更新
"""
from __future__ import annotations

import json
import re
from typing import Any

from sqlalchemy import select

from app.core import git_sync
from app.models.asset import Asset

INDEX_PATH = "index.json"
INDEX_SCHEMA_VERSION = 1

KIND_DIRS = {"plugin": "plugins", "skill": "skills", "mcp": "connectors"}
VALID_KINDS = set(KIND_DIRS)

# 分类 → 目录 slug (git 路径要安全, 不能有中文/空格)
CATEGORY_SLUGS = {
    "Trace 诊断": "trace",
    "FW 比对": "fw",
    "老化任务": "burn",
    "Spec 问答": "spec",
    "机台运维": "ops",
    "自动化代码": "auto-code",
    "测试报告": "report",
}
DEFAULT_CATEGORY_SLUG = "misc"

CODE_RE = re.compile(r"^[a-z0-9][a-z0-9-]{1,62}[a-z0-9]$")
VERSION_RE = re.compile(r"^\d+\.\d+\.\d+(?:[-+][0-9A-Za-z.-]+)?$")
MAX_FILES = 200
MAX_TOTAL_BYTES = 2 * 1024 * 1024
ALLOWED_SUFFIXES = {
    ".md", ".txt", ".json", ".yaml", ".yml", ".toml", ".ini", ".cfg",
    ".py", ".js", ".ts", ".sh", ".sql", ".csv", ".env.example",
}


class ManifestError(ValueError):
    """manifest 校验失败 — 直接回给用户, 不入库。"""


def category_slug(category: str) -> str:
    if category in CATEGORY_SLUGS:
        return CATEGORY_SLUGS[category]
    # 未知分类: 生成一个安全的 slug
    slug = re.sub(r"[^a-z0-9-]+", "-", (category or "").lower()).strip("-")
    return slug or DEFAULT_CATEGORY_SLUG


def asset_git_path(kind: str, category: str, code: str) -> str:
    return f"assets/{KIND_DIRS[kind]}/{category_slug(category)}/{code}"


def validate_code(code: str) -> str:
    code = (code or "").strip().lower()
    if not CODE_RE.match(code):
        raise ManifestError(
            "code 只能用小写字母/数字/连字符, 长度 3-64, 且不能以连字符开头或结尾"
        )
    return code


def validate_version(version: str) -> str:
    version = (version or "").strip().lstrip("v")
    if not VERSION_RE.match(version):
        raise ManifestError("version 必须是 semver, 如 1.2.0 (可带 -beta 后缀)")
    return version


def validate_files(files: dict[str, str]) -> dict[str, str]:
    """校验上传的附加文件: 路径安全 + 后缀白名单 + 体积限制."""
    if len(files) > MAX_FILES:
        raise ManifestError(f"文件数超限 (最多 {MAX_FILES} 个)")
    total = 0
    out: dict[str, str] = {}
    for raw_path, content in files.items():
        p = raw_path.replace("\\", "/").lstrip("/")
        if not p or p.startswith("../") or "/../" in p or p.endswith("/.."):
            raise ManifestError(f"非法路径: {raw_path}")
        if ".." in p.split("/"):
            raise ManifestError(f"非法路径: {raw_path}")
        suffix = "." + p.rsplit(".", 1)[-1].lower() if "." in p else ""
        if suffix not in ALLOWED_SUFFIXES:
            raise ManifestError(f"不支持的文件类型: {suffix or '(无扩展名)'} (白名单: {sorted(ALLOWED_SUFFIXES)})")
        try:
            content.encode("utf-8")
        except UnicodeEncodeError as e:
            raise ManifestError(f"{p} 含非 UTF-8 内容: {e}") from e
        total += len(content.encode("utf-8"))
        out[p] = content
    if total > MAX_TOTAL_BYTES:
        raise ManifestError(f"总体积超限 ({total} > {MAX_TOTAL_BYTES} 字节)")
    return out


def build_manifest(
    *,
    code: str,
    kind: str,
    name: str,
    version: str,
    summary: str,
    description: str = "",
    use_when: str = "",
    not_for: str = "",
    category: str = "",
    tags: list[str] | None = None,
    keywords: list[str] | None = None,
    icon: str = "🧩",
    author: str = "",
    featured: bool = False,
    homepage: str | None = None,
    permissions: dict | None = None,
    install_steps: list[str] | None = None,
    bindings: dict | None = None,
) -> dict[str, Any]:
    code = validate_code(code)
    if kind not in VALID_KINDS:
        raise ManifestError(f"kind 必须是 {sorted(VALID_KINDS)} 之一")
    version = validate_version(version)
    if not name or len(name) > 128:
        raise ManifestError("name 必填且不超过 128 字符")
    if not summary or len(summary) > 500:
        raise ManifestError("summary 必填且不超过 500 字符")

    path = asset_git_path(kind, category, code)
    return {
        "schema_version": 1,
        "code": code,
        "name": name,
        "icon": icon,
        "kind": kind,
        "version": version,
        "summary": summary,
        "description": description,
        "use_when": use_when,
        "not_for": not_for,
        "category": category,
        "tags": tags or [],
        "keywords": keywords or [],
        "author": author,
        "featured": bool(featured),
        "homepage": homepage,
        "permissions": permissions or {},
        "install_steps": install_steps or [],
        "bindings": bindings or {},
        "git_path": path,
        "updated_at": "",
    }


def asset_to_index_entry(a: Asset) -> dict[str, Any]:
    return {
        "code": a.code,
        "name": a.name,
        "icon": a.icon,
        "kind": a.kind,
        "version": a.version,
        "summary": a.summary,
        "description": a.description,
        "use_when": a.use_when,
        "not_for": a.not_for,
        "category": a.category,
        "tags": list(a.tags or []),
        "keywords": list(a.keywords or []),
        "author": a.author,
        "featured": bool(a.featured),
        "homepage": a.homepage,
        "permissions": dict(a.permissions or {}),
        "install_steps": list(a.install_steps or []),
        "bindings": dict(a.bindings or {}),
        "git_path": a.git_path,
        "install_count": a.install_count,
        # 生命周期状态也在索引里 —— 上下架必须能被别的实例看到
        "publish_status": a.publish_status or "published",
        "updated_at": a.updated_at.isoformat() if a.updated_at else "",
    }


def render_index_entries(entries: list[dict[str, Any]]) -> str:
    payload = {
        "schema_version": INDEX_SCHEMA_VERSION,
        "generated_by": "testmate-marketplace",
        "assets": entries,
    }
    return json.dumps(payload, ensure_ascii=False, indent=2)


def render_index(assets: list[Asset]) -> str:
    return render_index_entries([asset_to_index_entry(a) for a in assets])


async def stage_index(session, override: dict[str, Any] | None = None,
                      exclude: set[str] | None = None) -> str:
    """渲染 index.json 并写入本地工作区, 返回写完的内容.

    override 是本次要新增/更新的资产条目 (以 code 为键合并进去).
    exclude 是本次要从索引里**剔除**的 code —— 硬删时用: DB 行还没删,
    但 index.json 必须先不含它, 否则会把资产又提交回去.
    DB 是索引的真相源, 工作区里的 index.json 是它的物化 —— 下一次 git commit 会带上.
    """
    result = await session.execute(select(Asset))
    assets = list(result.scalars().all())
    entries = {a.code: asset_to_index_entry(a) for a in assets}
    if override and override.get("code"):
        entries[override["code"]] = override
    for c in (exclude or ()):
        entries.pop(c, None)
    ordered = sorted(entries.values(), key=lambda e: e.get("code", ""))
    text = render_index_entries(ordered)
    git_sync.write_text(INDEX_PATH, text)
    return text


async def read_index() -> dict[str, Any] | None:
    """读本地工作区里的 index.json (工作区就是仓库 working copy, 不走 API)."""
    raw = git_sync.read_text(INDEX_PATH)
    if not raw:
        return None
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        return None


def write_index(entries: list[dict[str, Any]]) -> None:
    """把 index.json 写回本地工作区 (下一次 git commit 会带上它)."""
    git_sync.write_text(INDEX_PATH, render_index_entries(entries))


async def apply_index_to_db(session) -> tuple[int, int]:
    """把 index.json 回灌进 DB 镜像. 返回 (新增数, 更新数).

    不会删除 DB 里 index 中不存在的行 —— 那些可能是刚上传但 commit 还在途.
    """
    idx = await read_index()
    if not idx:
        return 0, 0

    entries = idx.get("assets") or []
    codes = [e.get("code") for e in entries if e.get("code")]
    if not codes:
        return 0, 0

    existing = {
        a.code: a
        for a in (await session.execute(select(Asset).where(Asset.code.in_(codes)))).scalars().all()
    }

    added = updated = 0
    for e in entries:
        code = e.get("code")
        if not code or e.get("kind") not in VALID_KINDS:
            continue
        a = existing.get(code)
        if a is None:
            a = Asset(code=code)
            session.add(a)
            added += 1
        else:
            updated += 1
        a.name = e.get("name") or code
        a.icon = e.get("icon") or "🧩"
        a.kind = e["kind"]
        a.version = e.get("version") or "0.1.0"
        a.summary = e.get("summary") or ""
        a.description = e.get("description") or ""
        a.use_when = e.get("use_when") or ""
        a.not_for = e.get("not_for") or ""
        a.category = e.get("category") or ""
        a.tags = list(e.get("tags") or [])
        a.keywords = list(e.get("keywords") or [])
        a.author = e.get("author") or ""
        a.featured = 1 if e.get("featured") else 0
        a.homepage = e.get("homepage")
        a.permissions = dict(e.get("permissions") or {})
        a.install_steps = list(e.get("install_steps") or [])
        a.bindings = dict(e.get("bindings") or {})
        a.git_path = e.get("git_path") or ""
        # 上下架状态: 索引里没有这一项的旧数据按 published 处理
        a.publish_status = e.get("publish_status") or "published"
        if e.get("install_count") is not None:
            a.install_count = int(e["install_count"])
        if e.get("updated_at"):
            from datetime import datetime

            try:
                a.updated_at = datetime.fromisoformat(e["updated_at"])
            except ValueError:
                pass
    await session.commit()
    return added, updated
