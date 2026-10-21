"""AI 资产市场 API.

数据流:
    上传(压缩包) → 服务端解压 → 写工作区 files/ + package/ → 建 job(staged) → 立即 202
                  → 后台 git commit + push → job(pushed)

    读: 全部读本地工作区 (快, 不走 GitLab API)
    写: GitLab 是远端真身, 本地工作区是它的 working copy

安装双通道:
    A(server)   后端解包写盘到配置的安装目录
    B(frontend) 前端用 File System Access API 写用户本机目录
    两条通道拿到的都是**已解压的明文文件**, 前端不接触归档格式.
"""
from __future__ import annotations

import json
import logging
import shutil
import uuid
from datetime import datetime
from pathlib import Path
from typing import Any

from fastapi import APIRouter, BackgroundTasks, Depends, File, Form, HTTPException, Query, UploadFile
from fastapi import Response
from sqlalchemy import select, or_

from app.api.auth import get_current_user
from app.core import git_sync, pkg
from app.core.asset_jobs import enqueue, retry_job, start_worker
from app.core.dingtalk import notify_market
from app.core.market_catalog import (
    CATEGORY_SLUGS,
    INDEX_PATH,
    ManifestError,
    apply_index_to_db,
    asset_to_index_entry,
    build_manifest,
    read_index,
    stage_index,
    validate_files,
)
from app.db.session import AsyncSessionLocal
from app.models.asset import Asset, AssetAudit, AssetInstall, AssetJob
from app.models.user import User
from app.schemas.asset import (
    AssetAuditListOut,
    AssetAuditOut,
    AssetDocOut,
    AssetFileBundleOut,
    AssetFileContent,
    AssetFileNode,
    AssetFilesOut,
    AssetInstallTargetOut,
    AssetJobListOut,
    AssetJobOut,
    AssetListOut,
    AssetOut,
    ProbeOut,
    SyncOut,
    SyncStatusOut,
    UploadAssetIn,
)

logger = logging.getLogger(__name__)
router = APIRouter()

# 容器内宿主家目录的挂载点 (compose: ${HOME}/.qoder-cn → /host-home/.qoder-cn)
HOST_HOME = "/host-home"


# ---------- 路径与权限 ----------

def resolve_host_path(raw: str) -> Path:
    """把配置里的**宿主路径**翻译成容器内路径.

    设置项存宿主路径 (如 ~/.qoder-cn/skills), 容器内要换成 /host-home/...
    """
    raw = (raw or "").strip()
    if not raw:
        return Path("/host-home/.qoder-cn")
    if raw.startswith("~/"):
        return Path(HOST_HOME) / raw[2:]
    if raw == "~":
        return Path(HOST_HOME)
    return Path(raw)


async def _setting(key: str, default: str = "") -> str:
    try:
        from app.core.settings_store import get

        return (await get(key, default)) or default
    except Exception:  # noqa: BLE001
        return default


async def _publisher_ids() -> set[int]:
    raw = await _setting("marketplace.publisher_ids", "[]")
    try:
        data = json.loads(raw) if raw.strip() else []
    except json.JSONDecodeError:
        data = []
    return {int(x) for x in data if str(x).isdigit()}


async def require_publisher(user: User = Depends(get_current_user)) -> User:
    """发布者白名单 + admin 恒可发布."""
    role = user.role.value if hasattr(user.role, "value") else str(user.role)
    if role == "admin":
        return user
    if role == "anonymous":
        raise HTTPException(status_code=401, detail="未登录")
    if user.id in await _publisher_ids():
        return user
    raise HTTPException(status_code=403, detail="不在发布者白名单内, 联系管理员开通")


def _author_of(user: User) -> tuple[str, str]:
    name = user.username or "unknown"
    return (name, f"{name}@testmate.internal")


async def _audit(
    session,
    *,
    code: str,
    action: str,
    actor: User | None = None,
    asset_id: int | None = None,
    comment: str = "",
    detail: dict | None = None,
) -> None:
    session.add(
        AssetAudit(
            asset_id=asset_id,
            code=code,
            action=action,
            actor_id=actor.id if actor else None,
            actor_name=actor.username if actor else "",
            comment=comment,
            detail=detail or {},
        )
    )


# ---------- 读 ----------

def _to_out(a: Asset, installs: dict[str, tuple[str, str, str]]) -> AssetOut:
    out = AssetOut.model_validate(a)
    ver, status, path = installs.get(a.code, ("", "", ""))
    out.installed = status == "installed"
    out.install_path = path
    out.updatable = bool(out.installed and ver and ver != a.version)
    return out


async def _install_map(codes: list[str], client_id: str) -> dict[str, tuple[str, str, str]]:
    if not codes:
        return {}
    async with AsyncSessionLocal() as session:
        rows = (
            await session.execute(
                select(AssetInstall).where(
                    AssetInstall.code.in_(codes), AssetInstall.client_id == client_id
                )
            )
        ).scalars().all()
    out: dict[str, tuple[str, str, str]] = {}
    for r in rows:
        # 同一 code 可能有历史重复行, 取最新的一条
        cur = out.get(r.code)
        if cur is None or (r.installed_at or datetime.min) > (cur[0] or datetime.min):
            out[r.code] = (r.version, r.status, r.install_path)
    return out


@router.get("", response_model=AssetListOut)
async def list_assets(
    kind: str | None = Query(None),
    category: str | None = Query(None),
    q: str | None = Query(None),
    sort: str = Query("hot", pattern="^(hot|new|name)$"),
    include_unpublished: bool = Query(False),
    limit: int = Query(100, ge=1, le=500),
    offset: int = Query(0, ge=0),
    client_id: str = Query("local"),
    _user: User = Depends(get_current_user),
) -> AssetListOut:
    async with AsyncSessionLocal() as session:
        stmt = select(Asset)
        if kind:
            stmt = stmt.where(Asset.kind == kind)
        if category:
            stmt = stmt.where(Asset.category == category)
        if not include_unpublished:
            stmt = stmt.where(Asset.publish_status == "published")
        if q:
            like = f"%{q.strip()}%"
            stmt = stmt.where(
                or_(
                    Asset.name.like(like),
                    Asset.summary.like(like),
                    Asset.description.like(like),
                    Asset.author.like(like),
                )
            )
        rows = list((await session.execute(stmt)).scalars().all())
        total = len(rows)
        if sort == "new":
            rows.sort(key=lambda a: a.updated_at or datetime.min, reverse=True)
        elif sort == "name":
            rows.sort(key=lambda a: a.name)
        else:
            rows.sort(key=lambda a: (bool(a.featured), a.install_count or 0), reverse=True)
        page = rows[offset : offset + limit]

    installs = await _install_map([a.code for a in page], client_id)
    return AssetListOut(items=[_to_out(a, installs) for a in page], total=total)


@router.get("/categories")
async def list_categories(_user: User = Depends(get_current_user)) -> dict[str, Any]:
    async with AsyncSessionLocal() as session:
        rows = (
            await session.execute(
                select(Asset.category, Asset.kind).where(
                    Asset.publish_status == "published"
                )
            )
        ).all()
    counts: dict[str, dict[str, int]] = {}
    for cat, k in rows:
        if not cat:
            continue
        counts.setdefault(cat, {})[k] = counts.setdefault(cat, {}).get(k, 0) + 1
    return {
        "items": [
            {
                "name": c,
                "slug": CATEGORY_SLUGS.get(c, "misc"),
                "by_kind": v,
                "total": sum(v.values()),
            }
            for c, v in sorted(counts.items(), key=lambda kv: -sum(kv[1].values()))
        ]
    }


@router.get("/jobs", response_model=AssetJobListOut)
async def list_jobs(
    limit: int = Query(20, ge=1, le=100),
    _user: User = Depends(get_current_user),
) -> AssetJobListOut:
    async with AsyncSessionLocal() as session:
        rows = (
            await session.execute(select(AssetJob).order_by(AssetJob.id.desc()).limit(limit))
        ).scalars().all()
        return AssetJobListOut(items=[AssetJobOut.model_validate(j) for j in rows], total=len(rows))


@router.get("/jobs/{job_id}", response_model=AssetJobOut)
async def get_job(job_id: int, _user: User = Depends(get_current_user)) -> AssetJobOut:
    async with AsyncSessionLocal() as session:
        job = await session.get(AssetJob, job_id)
        if job is None:
            raise HTTPException(status_code=404, detail="job 不存在")
        return AssetJobOut.model_validate(job)


@router.post("/jobs/{job_id}/retry", response_model=AssetJobOut)
async def retry_failed_job(
    job_id: int, _user: User = Depends(require_publisher)
) -> AssetJobOut:
    ok = await retry_job(job_id)
    if not ok:
        raise HTTPException(status_code=404, detail="job 不存在")
    async with AsyncSessionLocal() as session:
        job = await session.get(AssetJob, job_id)
        return AssetJobOut.model_validate(job)


@router.get("/audits", response_model=AssetAuditListOut)
async def list_audits(
    code: str | None = Query(None),
    limit: int = Query(50, ge=1, le=200),
    _user: User = Depends(get_current_user),
) -> AssetAuditListOut:
    async with AsyncSessionLocal() as session:
        stmt = select(AssetAudit).order_by(AssetAudit.id.desc()).limit(limit)
        if code:
            stmt = stmt.where(AssetAudit.code == code)
        rows = (await session.execute(stmt)).scalars().all()
        return AssetAuditListOut(
            items=[AssetAuditOut.model_validate(r) for r in rows], total=len(rows)
        )


@router.get("/sync-status", response_model=SyncStatusOut)
async def sync_status(
    client_id: str = Query("local"),
    _user: User = Depends(get_current_user),
) -> SyncStatusOut:
    """前端顶部状态条: 待同步 / 失败 / 有更新 / 有冲突."""
    from app.core.sync_puller import get_puller

    async with AsyncSessionLocal() as session:
        pending = failed = unpublished = 0
        rows = (await session.execute(select(Asset))).scalars().all()
        for a in rows:
            if a.sync_status == "staged":
                pending += 1
            elif a.sync_status == "failed":
                failed += 1
            if a.publish_status == "unpublished":
                unpublished += 1

    installs = await _install_map([a.code for a in rows], client_id)
    updatable = sum(
        1
        for a in rows
        if installs.get(a.code, ("", "", ""))[0] and installs[a.code][0] != a.version
    )
    puller = get_puller()
    return SyncStatusOut(
        has_remote_updates=puller.has_remote_updates,
        conflict_count=puller.conflict_count,
        pending_count=pending,
        failed_count=failed,
        updatable_count=updatable,
        unpublished_count=unpublished,
        last_sync_at=puller.last_sync_at,
    )


@router.get("/me/installed", response_model=AssetListOut)
async def my_installed(
    client_id: str = Query("local"),
    _user: User = Depends(get_current_user),
) -> AssetListOut:
    async with AsyncSessionLocal() as session:
        inst = (
            await session.execute(
                select(AssetInstall).where(
                    AssetInstall.client_id == client_id,
                    AssetInstall.status == "installed",
                )
            )
        ).scalars().all()
        codes = [i.code for i in inst]
        if not codes:
            return AssetListOut(items=[], total=0)
        rows = (
            await session.execute(select(Asset).where(Asset.code.in_(codes)))
        ).scalars().all()
    installs = await _install_map(codes, client_id)
    return AssetListOut(items=[_to_out(a, installs) for a in rows], total=len(rows))


@router.get("/me/updates", response_model=AssetListOut)
async def my_updates(
    client_id: str = Query("local"),
    _user: User = Depends(get_current_user),
) -> AssetListOut:
    """本地已装版本 vs 远端最新版本 —— 不一致就是"可更新"."""
    async with AsyncSessionLocal() as session:
        inst = (
            await session.execute(
                select(AssetInstall).where(
                    AssetInstall.client_id == client_id,
                    AssetInstall.status == "installed",
                )
            )
        ).scalars().all()
        codes = [i.code for i in inst]
        if not codes:
            return AssetListOut(items=[], total=0)
        rows = (
            await session.execute(select(Asset).where(Asset.code.in_(codes)))
        ).scalars().all()
    installs = await _install_map(codes, client_id)
    out = [
        _to_out(a, installs)
        for a in rows
        if installs.get(a.code, ("", "", ""))[0]
        and installs[a.code][0] != a.version
    ]
    return AssetListOut(items=out, total=len(out))


@router.get("/{code}", response_model=AssetOut)
async def get_asset(
    code: str,
    client_id: str = Query("local"),
    _user: User = Depends(get_current_user),
) -> AssetOut:
    async with AsyncSessionLocal() as session:
        a = (
            await session.execute(select(Asset).where(Asset.code == code))
        ).scalar_one_or_none()
        if a is None:
            raise HTTPException(status_code=404, detail=f"资产 {code} 不存在")
        installs = await _install_map([code], client_id)
        return _to_out(a, installs)


@router.get("/{code}/doc", response_model=AssetDocOut)
async def get_asset_doc(code: str, _user: User = Depends(get_current_user)) -> AssetDocOut:
    """详情页展示的文档正文: skill→SKILL.md, plugin→README.md."""
    async with AsyncSessionLocal() as session:
        a = (
            await session.execute(select(Asset).where(Asset.code == code))
        ).scalar_one_or_none()
    if a is None:
        raise HTTPException(status_code=404, detail=f"资产 {code} 不存在")

    root = pkg.files_root(git_sync.WORKSPACE / a.git_path)
    wanted = "SKILL.md" if a.kind == "skill" else "README.md"
    target = root / wanted
    if not target.is_file():
        # 退而求其次: 包里任意层级的同名文件
        cands = sorted(
            (p for p in root.rglob(wanted) if p.is_file()),
            key=lambda p: (len(p.parts), p.name),
        )
        if not cands:
            raise HTTPException(status_code=404, detail=f"资产包内没有 {wanted}")
        target = cands[0]

    raw = pkg.read_text_safe(target)
    if raw is None:
        raise HTTPException(status_code=404, detail=f"{wanted} 读取失败")
    meta, body = pkg.parse_frontmatter(raw)
    return AssetDocOut(
        kind=a.kind, filename=target.name, frontmatter=meta, content=body or raw
    )


@router.get("/{code}/files", response_model=AssetFilesOut)
async def get_asset_files(code: str, _user: User = Depends(get_current_user)) -> AssetFilesOut:
    """本地工作区里该资产的文件树 (证明数据真实落盘)."""
    async with AsyncSessionLocal() as session:
        a = (
            await session.execute(select(Asset).where(Asset.code == code))
        ).scalar_one_or_none()
    if a is None:
        raise HTTPException(status_code=404, detail=f"资产 {code} 不存在")

    root = pkg.files_root(git_sync.WORKSPACE / a.git_path)
    nodes: list[AssetFileNode] = []
    if root.is_dir():
        for p in sorted(root.rglob("*")):
            rel = p.relative_to(root)
            if rel.parts and rel.parts[0] in pkg.RESERVED_DIRS:
                continue
            if rel.name in pkg.RESERVED_NAMES:
                continue
            nodes.append(
                AssetFileNode(
                    name=p.name,
                    path=str(rel),
                    type="tree" if p.is_dir() else "blob",
                    size=None if p.is_dir() else p.stat().st_size,
                )
            )
    return AssetFilesOut(code=code, git_path=a.git_path, files=nodes)


@router.get("/{code}/bundle", response_model=AssetFileBundleOut)
async def get_asset_bundle(
    code: str, _user: User = Depends(get_current_user)
) -> AssetFileBundleOut:
    """前端通道安装用: 已解压的明文文件清单 + 内容 (前端只写文件, 不解压)."""
    async with AsyncSessionLocal() as session:
        a = (
            await session.execute(select(Asset).where(Asset.code == code))
        ).scalar_one_or_none()
    if a is None:
        raise HTTPException(status_code=404, detail=f"资产 {code} 不存在")

    base = git_sync.WORKSPACE / a.git_path
    root = pkg.files_root(base)
    if not root.is_dir():
        raise HTTPException(status_code=404, detail="资产文件尚未落盘")

    out: list[AssetFileContent] = []
    for p in pkg.content_files(base):
        rel = p.relative_to(root).as_posix()
        raw = p.read_bytes()
        try:
            out.append(AssetFileContent(path=rel, encoding="text",
                                       content=raw.decode("utf-8")))
        except UnicodeDecodeError:
            import base64

            out.append(
                AssetFileContent(
                    path=rel, encoding="base64",
                    content=base64.b64encode(raw).decode("ascii"),
                )
            )
    return AssetFileBundleOut(code=code, version=a.version, files=out, total=len(out))


def _find_stored_package(base: Path, version: str) -> Path | None:
    """找该版本已存的原始安装包 (名字是 {version}.zip / {version}.tar.gz)."""
    pkg_dir = base / "package"
    if not pkg_dir.is_dir():
        return None
    if version:
        exact = sorted(pkg_dir.glob(f"{version}.*"))
        if exact:
            return exact[0]
    # 找不到对应版本 → 用目录里第一个 (下载端点返回的是"该资产当前可下载的包")
    any_pkg = sorted(p for p in pkg_dir.iterdir() if p.is_file())
    return any_pkg[0] if any_pkg else None


@router.get("/{code}/versions/{version}/download")
async def download_package(
    code: str, version: str, _user: User = Depends(get_current_user)
) -> Response:
    """下载安装包 (原始 zip; 老资产没有存包则即时确定性打包)."""
    async with AsyncSessionLocal() as session:
        a = (
            await session.execute(select(Asset).where(Asset.code == code))
        ).scalar_one_or_none()
    if a is None:
        raise HTTPException(status_code=404, detail=f"资产 {code} 不存在")

    base = git_sync.WORKSPACE / a.git_path
    stored = _find_stored_package(base, version)
    if stored is not None:
        data = stored.read_bytes()
        name = stored.name
    else:
        root = pkg.files_root(base)
        if not root.is_dir():
            raise HTTPException(status_code=404, detail="资产文件不存在")
        data = pkg.build_zip(root)
        name = f"{code}-{version}.zip"

    return Response(
        content=data,
        media_type="application/zip",
        headers={
            "Content-Disposition": f'attachment; filename="{name}"',
            "X-Content-Sha256": pkg.sha256_bytes(data),
        },
    )


# ---------- 安装 ----------

@router.get("/{code}/install-target", response_model=AssetInstallTargetOut)
async def get_install_target(
    code: str, _user: User = Depends(get_current_user)
) -> AssetInstallTargetOut:
    """前端点安装时先查这个: 本地安装目录 + 解析后的目标路径."""
    async with AsyncSessionLocal() as session:
        a = (
            await session.execute(select(Asset).where(Asset.code == code))
        ).scalar_one_or_none()
    if a is None:
        raise HTTPException(status_code=404, detail=f"资产 {code} 不存在")

    skill_raw = await _setting("marketplace.install.skill_dir", "~/.qoder-cn/skills")
    plugin_raw = await _setting(
        "marketplace.install.plugin_dir", "~/.qoder-cn/plugins/cache/qoder-marketplace"
    )
    skill_dir = resolve_host_path(skill_raw)
    plugin_dir = resolve_host_path(plugin_raw)
    if a.kind == "skill":
        target = skill_dir / a.code
    else:
        target = plugin_dir / a.code / a.version

    enabled = (await _setting("marketplace.install.enabled", "true")).lower()
    server_ok = enabled in ("true", "1", "yes", "on")
    return AssetInstallTargetOut(
        code=a.code,
        kind=a.kind,
        version=a.version,
        skill_dir=str(skill_dir),
        plugin_dir=str(plugin_dir),
        target=str(target),
        server_channel_available=server_ok,
    )


def _install_files(base: Path, target: Path, kind: str) -> None:
    """把资产**内容文件**原子地装到 target.

    只拷内容文件 —— manifest.json 与 package/ 是仓库侧的东西, 不该进用户目录.
    兼容新旧两种布局 (files/ 子目录 or 直接在资产根下).

    原子性: 先写临时目录 → 校验 → 旧目录改名备份 → rename → 删备份.
    失败时清理临时目录, **不动原目录**.
    """
    root = pkg.files_root(base)
    target.parent.mkdir(parents=True, exist_ok=True)
    tmp = target.parent / f".tmp-{target.name}-{uuid.uuid4().hex[:8]}"
    backup = target.parent / f".bak-{target.name}-{uuid.uuid4().hex[:8]}"
    try:
        tmp.mkdir(parents=True)
        for src in pkg.content_files(base):
            rel = src.relative_to(root)
            dst = tmp / rel
            dst.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(src, dst)
        if kind == "skill":
            if not any(tmp.rglob("SKILL.md")):
                raise pkg.PackageError("安装包内没有 SKILL.md")
        elif not any(tmp.rglob(".qoder-plugin")) and not any(tmp.rglob("plugin.json")):
            raise pkg.PackageError("安装包内没有 .qoder-plugin/plugin.json")
        if target.exists():
            target.rename(backup)
        tmp.rename(target)
        shutil.rmtree(backup, ignore_errors=True)
    except Exception:
        shutil.rmtree(tmp, ignore_errors=True)
        if backup.exists() and not target.exists():
            backup.rename(target)
        raise


@router.post("/{code}/install")
async def install_asset(
    code: str,
    version: str = Form(...),
    channel: str = Form("server"),
    client_id: str = Form("local"),
    client_kind: str = Form("web"),
    install_path: str = Form(""),
    _user: User = Depends(get_current_user),
) -> dict[str, Any]:
    """记录本机安装. channel=server 时由后端真正写盘; frontend 时前端已写好, 这里只记录."""
    async with AsyncSessionLocal() as session:
        a = (
            await session.execute(select(Asset).where(Asset.code == code))
        ).scalar_one_or_none()
        if a is None:
            raise HTTPException(status_code=404, detail=f"资产 {code} 不存在")
        if a.kind == "mcp":
            raise HTTPException(status_code=409, detail="连接器暂不支持一键安装")

        written = ""
        if channel == "server":
            enabled = (await _setting("marketplace.install.enabled", "true")).lower()
            if enabled not in ("true", "1", "yes", "on"):
                raise HTTPException(status_code=503, detail="安装功能已关闭")
            base = git_sync.WORKSPACE / a.git_path
            src = pkg.files_root(base)
            if not src.is_dir():
                raise HTTPException(status_code=404, detail="资产文件尚未落盘")
            skill_raw = await _setting("marketplace.install.skill_dir", "~/.qoder-cn/skills")
            plugin_raw = await _setting(
                "marketplace.install.plugin_dir",
                "~/.qoder-cn/plugins/cache/qoder-marketplace",
            )
            if a.kind == "skill":
                target = resolve_host_path(skill_raw) / a.code
            else:
                target = resolve_host_path(plugin_raw) / a.code / a.version
            try:
                with git_sync._FileLock(target.parent / f".install-{a.code}.lock"):
                    _install_files(base, target, a.kind)
            except pkg.PackageError as e:
                # 包本身不合规 (缺 SKILL.md / plugin.json) —— 是资产的问题, 不是服务端的
                raise HTTPException(status_code=422, detail=f"安装包不合规: {e}") from e
            except Exception as e:  # noqa: BLE001
                logger.error("install 失败 code=%s err=%s", a.code, e)
                raise HTTPException(status_code=500, detail=f"安装失败: {e}") from e
            written = str(target)
        else:
            written = install_path

        row = (
            await session.execute(
                select(AssetInstall).where(
                    AssetInstall.code == code, AssetInstall.client_id == client_id
                )
            )
        ).scalars().first()
        if row is None:
            row = AssetInstall(code=code, client_id=client_id, user_id=_user.id)
            session.add(row)
            a.install_count = (a.install_count or 0) + 1
        row.version = version or a.version
        row.client_kind = client_kind
        row.status = "installed"
        row.install_path = written
        row.channel = channel
        row.sha256 = a.git_commit_sha
        await session.commit()

        await _audit(
            session, code=code, action="install", actor=_user,
            asset_id=a.id, detail={"version": row.version, "channel": channel,
                                   "install_path": written},
        )
        await session.commit()
        return {"ok": True, "code": code, "version": row.version,
                "install_path": written, "channel": channel}


@router.delete("/{code}/install")
async def uninstall_asset(
    code: str,
    client_id: str = Query("local"),
    _user: User = Depends(get_current_user),
) -> dict[str, Any]:
    async with AsyncSessionLocal() as session:
        rows = (
            await session.execute(
                select(AssetInstall).where(
                    AssetInstall.code == code, AssetInstall.client_id == client_id
                )
            )
        ).scalars().all()
        if not rows:
            return {"ok": True, "code": code, "removed": False}
        removed_path = ""
        for row in rows:
            row.status = "uninstalled"
            if row.install_path and row.channel == "server":
                removed_path = row.install_path
        await session.commit()

        if removed_path:
            try:
                p = Path(removed_path)
                if p.is_dir() and p.exists():
                    shutil.rmtree(p, ignore_errors=True)
            except Exception as e:  # noqa: BLE001
                logger.warning("卸载时删除目录失败 path=%s err=%s", removed_path, e)

        await _audit(
            session, code=code, action="uninstall", actor=_user,
            detail={"client_id": client_id},
        )
        await session.commit()
        return {"ok": True, "code": code, "removed": True}


# ---------- 上架 / 下架 ----------

@router.post("/{code}/unpublish")
async def unpublish_asset(
    code: str,
    comment: str = Form(""),
    _user: User = Depends(require_publisher),
) -> dict[str, Any]:
    """下架: 标记 + 从 index.json 移除, 但**保留文件** (在用用户要能看到"已下架")."""
    async with AsyncSessionLocal() as session:
        a = (
            await session.execute(select(Asset).where(Asset.code == code))
        ).scalar_one_or_none()
        if a is None:
            raise HTTPException(status_code=404, detail=f"资产 {code} 不存在")
        if a.publish_status == "unpublished":
            return {"ok": True, "code": code, "publish_status": "unpublished"}

        a.publish_status = "unpublished"
        await session.commit()
        # index.json 里移除该条目 (派生物, 权威是 manifest)
        async with AsyncSessionLocal() as s2:
            idx = await read_index()
            entries = (idx or {}).get("assets") or []
            entries = [e for e in entries if e.get("code") != code]
            from app.core.market_catalog import render_index_entries

            git_sync.write_text(INDEX_PATH, render_index_entries(entries))

        await _audit(session, code=code, action="unpublish", actor=_user,
                     asset_id=a.id, comment=comment)
        await session.commit()

    await notify_market(
        "unpublish", name=a.name, version=a.version, actor=_user.username,
        detail=comment or "已从市场下架", link="",
    )
    return {"ok": True, "code": code, "publish_status": "unpublished"}


@router.post("/{code}/publish")
async def publish_asset(
    code: str,
    comment: str = Form(""),
    _user: User = Depends(require_publisher),
) -> dict[str, Any]:
    """重新上架."""
    async with AsyncSessionLocal() as session:
        a = (
            await session.execute(select(Asset).where(Asset.code == code))
        ).scalar_one_or_none()
        if a is None:
            raise HTTPException(status_code=404, detail=f"资产 {code} 不存在")
        a.publish_status = "published"
        await session.commit()
        await stage_index(session, asset_to_index_entry(a))
        await _audit(session, code=code, action="publish", actor=_user,
                     asset_id=a.id, comment=comment)
        await session.commit()

    await notify_market(
        "publish", name=a.name, version=a.version, actor=_user.username,
        detail=comment or "重新上架", link="",
    )
    return {"ok": True, "code": code, "publish_status": "published"}


# ---------- 上传 ----------

async def _parse_uploads(files: list[UploadFile] | None) -> dict[str, str]:
    if not files:
        return {}
    collected: dict[str, str] = {}
    for f in files:
        name = (f.filename or "").strip()
        if not name:
            continue
        try:
            collected[name] = (await f.read()).decode("utf-8")
        except UnicodeDecodeError as e:
            raise HTTPException(status_code=400, detail=f"{name} 不是 UTF-8 文本: {e}") from e
    return validate_files(collected)


async def _stage_asset(
    *,
    action: str,
    payload_in: UploadAssetIn,
    files: dict[str, str],
    package: bytes | None,
    package_name: str,
    user: User,
) -> AssetJobOut:
    """同步阶段: 解包 → 写工作区 → 写 index.json → 建 job(staged)."""
    try:
        manifest = build_manifest(
            code=payload_in.code,
            kind=payload_in.kind,
            name=payload_in.name,
            version=payload_in.version,
            summary=payload_in.summary,
            description=payload_in.description,
            use_when=payload_in.use_when,
            not_for=payload_in.not_for,
            category=payload_in.category,
            tags=payload_in.tags,
            keywords=payload_in.keywords,
            icon=payload_in.icon,
            author=payload_in.author or user.username,
            featured=payload_in.featured,
            homepage=payload_in.homepage,
            permissions=payload_in.permissions,
            install_steps=payload_in.install_steps,
            bindings=payload_in.bindings,
        )
    except ManifestError as e:
        raise HTTPException(status_code=422, detail=str(e)) from e

    base = manifest["git_path"]
    author = _author_of(user)
    files_dir = git_sync.WORKSPACE / base / "files"

    # ---- 1. 落盘 ----
    try:
        if package is not None:
            max_mb = int(await _setting("marketplace.max_package_mb", "50") or 50)
            extracted = pkg.extract_package(
                package, package_name, files_dir,
                max_package_bytes=max_mb * 1024 * 1024,
            )
            # 必须有展示文档
            doc_name = pkg.find_doc_file(extracted.files, manifest["kind"])
            if not doc_name:
                shutil.rmtree(files_dir, ignore_errors=True)
                want = "SKILL.md" if manifest["kind"] == "skill" else "README.md"
                raise HTTPException(
                    status_code=422,
                    detail=f"安装包内缺少 {want} (技能包需要 SKILL.md, 插件包需要 README.md)",
                )
            manifest["package_sha256"] = extracted.package_sha256
            manifest["package_name"] = f"{manifest['version']}{extracted.suffix}"
            manifest["files"] = extracted.files
            manifest["doc_file"] = doc_name
            # 原始包也存进 git —— Qoder marketplace 的 source.url 需要字节稳定的归档
            pkg_dir = git_sync.WORKSPACE / base / "package"
            pkg_dir.mkdir(parents=True, exist_ok=True)
            (pkg_dir / manifest["package_name"]).write_bytes(package)
        else:
            # 旧路径: 多文件文本上传
            # 先清空旧内容 —— 「更新版本」应当**替换**内容, 而不是让新旧文件叠加
            shutil.rmtree(files_dir, ignore_errors=True)
            for rel, content in files.items():
                git_sync.write_text(f"{base}/files/{rel}", content)
            manifest["package_sha256"] = ""
            manifest["package_name"] = ""
            manifest["files"] = sorted(files.keys())
            doc_name = pkg.find_doc_file(manifest["files"], manifest["kind"])
            if not doc_name:
                raise HTTPException(
                    status_code=422,
                    detail="缺少 SKILL.md / README.md",
                )
            manifest["doc_file"] = doc_name

        git_sync.write_text(
            f"{base}/manifest.json",
            json.dumps(manifest, ensure_ascii=False, indent=2),
        )
        if manifest.get("description"):
            git_sync.write_text(f"{base}/README.md", manifest["description"])
    except pkg.PackageError as e:
        raise HTTPException(status_code=422, detail=f"安装包不合规: {e}") from e
    except git_sync.SyncError as e:
        raise HTTPException(status_code=500, detail=f"写入本地工作区失败: {e}") from e

    # ---- 2. DB 镜像 + index.json ----
    async with AsyncSessionLocal() as session:
        existing = (
            await session.execute(select(Asset).where(Asset.code == manifest["code"]))
        ).scalar_one_or_none()
        if action == "create" and existing is not None:
            raise HTTPException(
                status_code=409, detail=f"资产 {manifest['code']} 已存在, 请用更新接口"
            )
        if action == "update" and existing is None:
            raise HTTPException(
                status_code=404, detail=f"资产 {manifest['code']} 不存在, 无法更新"
            )
        a = existing or Asset(code=manifest["code"])
        if existing is None:
            session.add(a)
        a.name = manifest.get("name") or a.code
        a.icon = manifest.get("icon") or "🧩"
        a.kind = manifest.get("kind") or "skill"
        a.version = manifest.get("version") or "0.1.0"
        a.summary = manifest.get("summary") or ""
        a.description = manifest.get("description") or ""
        a.use_when = manifest.get("use_when") or ""
        a.not_for = manifest.get("not_for") or ""
        a.category = manifest.get("category") or ""
        a.tags = list(manifest.get("tags") or [])
        a.keywords = list(manifest.get("keywords") or [])
        a.author = manifest.get("author") or ""
        a.featured = 1 if manifest.get("featured") else 0
        a.homepage = manifest.get("homepage")
        a.permissions = dict(manifest.get("permissions") or {})
        a.install_steps = list(manifest.get("install_steps") or [])
        a.bindings = dict(manifest.get("bindings") or {})
        a.git_path = base
        a.sync_status = "staged"
        a.last_error = ""
        await session.commit()
        await session.refresh(a)

        try:
            await stage_index(session, asset_to_index_entry(a))
        except git_sync.SyncError as e:
            raise HTTPException(status_code=500, detail=f"更新 index.json 失败: {e}") from e

        job = AssetJob(
            action=action,
            status="staged",
            code=a.code,
            asset_name=a.name,
            kind=a.kind,
            payload={
                "manifest": manifest,
                "files": files,
                "author": [author[0], author[1]],
                "commit_message": (
                    f"{'chore(market): 更新资产' if action == 'update' else 'feat(market): 上架资产'}"
                    f" {a.name} {a.version}"
                ),
            },
            git_path=a.git_path,
            created_by=user.id,
        )
        session.add(job)
        await session.commit()
        await session.refresh(job)
        out = AssetJobOut.model_validate(job)

        await _audit(
            session, code=a.code, action=action, actor=user, asset_id=a.id,
            detail={"version": a.version, "name": a.name},
        )
        await session.commit()

    # ---- 3. 入队, 后台 commit + push ----
    enqueue(out.id)
    await notify_market(
        "publish" if action == "create" else "update",
        name=manifest.get("name", ""), version=manifest.get("version", ""),
        actor=user.username,
        detail=manifest.get("summary", ""), link="",
    )
    return out


@router.post("/upload", response_model=AssetJobOut, status_code=202)
async def upload_asset(
    code: str = Form(...),
    kind: str = Form(...),
    name: str = Form(...),
    summary: str = Form(...),
    version: str = Form("0.1.0"),
    description: str = Form(""),
    use_when: str = Form(""),
    not_for: str = Form(""),
    category: str = Form(""),
    icon: str = Form("🧩"),
    tags: str = Form("[]"),
    keywords: str = Form("[]"),
    author: str = Form(""),
    featured: bool = Form(False),
    permissions: str = Form("{}"),
    install_steps: str = Form("[]"),
    bindings: str = Form("{}"),
    files: list[UploadFile] | None = File(None),
    package: UploadFile | None = File(None),
    user: User = Depends(require_publisher),
) -> AssetJobOut:
    """上架新资产: 安装包(压缩) 或 多文件文本. 立即返回 job, 后台 push 到 GitLab."""
    try:
        payload = UploadAssetIn(
            code=code, kind=kind, name=name, summary=summary, version=version,
            description=description, use_when=use_when, not_for=not_for,
            category=category, icon=icon,
            tags=json.loads(tags or "[]"), keywords=json.loads(keywords or "[]"),
            author=author, featured=featured,
            permissions=json.loads(permissions or "{}"),
            install_steps=json.loads(install_steps or "[]"),
            bindings=json.loads(bindings or "{}"),
        )
    except json.JSONDecodeError as e:
        raise HTTPException(status_code=422, detail=f"JSON 字段解析失败: {e}") from e

    if package is not None and files:
        raise HTTPException(status_code=422, detail="package 与 files 只能二选一")

    file_map: dict[str, str] = {}
    pkg_bytes: bytes | None = None
    pkg_name = ""
    if package is not None:
        pkg_bytes = await package.read()
        pkg_name = package.filename or "package.zip"
    else:
        file_map = await _parse_uploads(files)

    return await _stage_asset(
        action="create", payload_in=payload, files=file_map,
        package=pkg_bytes, package_name=pkg_name, user=user,
    )


@router.put("/{code}", response_model=AssetJobOut, status_code=202)
async def update_asset(
    code: str,
    kind: str = Form(...),
    name: str = Form(...),
    summary: str = Form(...),
    version: str = Form(...),
    description: str = Form(""),
    use_when: str = Form(""),
    not_for: str = Form(""),
    category: str = Form(""),
    icon: str = Form("🧩"),
    tags: str = Form("[]"),
    keywords: str = Form("[]"),
    author: str = Form(""),
    featured: bool = Form(False),
    permissions: str = Form("{}"),
    install_steps: str = Form("[]"),
    bindings: str = Form("{}"),
    files: list[UploadFile] | None = File(None),
    package: UploadFile | None = File(None),
    user: User = Depends(require_publisher),
) -> AssetJobOut:
    """发布新版本 (覆盖同名文件, git 历史保留旧版)."""
    try:
        payload = UploadAssetIn(
            code=code, kind=kind, name=name, summary=summary, version=version,
            description=description, use_when=use_when, not_for=not_for,
            category=category, icon=icon,
            tags=json.loads(tags or "[]"), keywords=json.loads(keywords or "[]"),
            author=author, featured=featured,
            permissions=json.loads(permissions or "{}"),
            install_steps=json.loads(install_steps or "[]"),
            bindings=json.loads(bindings or "{}"),
        )
    except json.JSONDecodeError as e:
        raise HTTPException(status_code=422, detail=f"JSON 字段解析失败: {e}") from e

    if package is not None and files:
        raise HTTPException(status_code=422, detail="package 与 files 只能二选一")

    file_map: dict[str, str] = {}
    pkg_bytes: bytes | None = None
    pkg_name = ""
    if package is not None:
        pkg_bytes = await package.read()
        pkg_name = package.filename or "package.zip"
    else:
        file_map = await _parse_uploads(files)

    return await _stage_asset(
        action="update", payload_in=payload, files=file_map,
        package=pkg_bytes, package_name=pkg_name, user=user,
    )


# ---------- 同步 / 运维 ----------

@router.post("/sync", response_model=SyncOut)
async def sync_from_workspace(
    _user: User = Depends(require_publisher),
) -> SyncOut:
    """从本地工作区的 index.json 回灌 DB 镜像, 并把待同步的任务重新入队."""
    idx = await read_index()
    async with AsyncSessionLocal() as session:
        added, updated = await apply_index_to_db(session)
    async with AsyncSessionLocal() as session:
        rows = (
            await session.execute(
                select(AssetJob).where(AssetJob.status.in_(("staged", "syncing")))
            )
        ).scalars().all()
        for j in rows:
            enqueue(j.id)
    st = git_sync.workspace_status()
    return SyncOut(
        ok=True,
        added=added,
        updated=updated,
        index_present=idx is not None,
        gitlab=(
            f"工作区 {st['workspace']} · branch {st['branch']} · head {st.get('head') or '-'}"
            f" · 待提交 {len(st.get('dirty_files') or [])} 个文件"
        ),
    )


@router.get("/probe/gitlab", response_model=ProbeOut)
async def probe_gitlab(_user: User = Depends(get_current_user)) -> ProbeOut:
    st = git_sync.workspace_status()
    if not st.get("is_repo"):
        return ProbeOut(
            ok=False, status="warn",
            message=f"工作区还不是 git 仓库: {st['workspace']}",
        )
    dirty = len(st.get("dirty_files") or [])
    return ProbeOut(
        ok=True, status="ok",
        message=(
            f"工作区就绪 · branch {st['branch']} · head {st.get('head') or '-'}"
            + (f" · {dirty} 个文件待提交" if dirty else "")
        ),
    )
