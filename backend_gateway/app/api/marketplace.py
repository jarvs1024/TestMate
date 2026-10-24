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
import re
import shutil
import tempfile
from datetime import datetime
from pathlib import Path
from typing import Any

from fastapi import APIRouter, BackgroundTasks, Depends, File, Form, HTTPException, Query, UploadFile
from fastapi import Response
from sqlalchemy import select, or_, update

from app.api.auth import get_current_user
from app.core import git_sync, pkg
from app.core.asset_jobs import enqueue, retry_job, start_worker
from app.core.asset_locks import code_lock
from app.core.dingtalk import list_notifications, notify_market
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
from app.models.asset import Asset, AssetAudit, AssetJob
from app.models.user import User
from app.schemas.asset import (
    AssetAuditListOut,
    AssetAuditOut,
    AssetDeleteOut,
    AssetDocOut,
    AssetFileBundleOut,
    AssetFileContent,
    AssetFileNode,
    AssetFilesOut,
    AssetJobListOut,
    AssetJobOut,
    AssetListOut,
    AssetNotificationListOut,
    MarketConfigOut,
    AssetOut,
    PackagePreviewOut,
    ProbeOut,
    SyncOut,
    SyncStatusOut,
    UploadAssetIn,
)

logger = logging.getLogger(__name__)
router = APIRouter()

# 建议的安装目录 (给「下载安装包」方式用) —— 跟 Qoder 的标准布局一致:
#   skill  → ~/.qoder-cn/skills/<code>/
#   plugin → ~/.qoder-cn/plugins/cache/qoder-marketplace/<code>/<version>/
# ⚠️ 后端**不写盘**了 —— 安装一律在用户本机完成 (选目录 / 下载安装包自行解压).
SKILL_INSTALL_DIR = "~/.qoder-cn/skills"
PLUGIN_INSTALL_DIR = "~/.qoder-cn/plugins/cache/qoder-marketplace"


async def _setting(key: str, default: str = "") -> str:
    try:
        from app.core.settings_store import get

        return (await get(key, default)) or default
    except Exception:  # noqa: BLE001
        return default


def _split_list(raw: str) -> list[str]:
    """把设置项里的列表值拆成元素列表.

    ⚠️ 容错是刚需: 设置页里「允许发布的用户 ID (JSON 数组)」和
    「允许发布的用户名 (逗号分隔)」两个框紧挨着, 用户照抄彼此格式
    太常见了. 而格式写错**没有任何报错** —— 只是白名单解析成空集,
    结果是"配了白名单, 但除 admin 外所有人都发不了布", 极难排查.
    所以两种格式都要认:
        "zhangsan,lisi"      → ["zhangsan", "lisi"]
        '["zhangsan","lisi"]' → ["zhangsan", "lisi"]
        "zhangsan、lisi"      → ["zhangsan", "lisi"]   (中文/顿号分隔)
    """
    s = (raw or "").strip()
    if not s:
        return []
    if s.startswith("["):
        try:
            data = json.loads(s)
        except json.JSONDecodeError:
            data = None
        if isinstance(data, list):
            out: list[str] = []
            for x in data:
                # 布尔在白名单里没有意义, 跳过 (str(True) 会变成 "True" 这种鬼名字)
                if isinstance(x, bool):
                    continue
                t = str(x).strip().strip("\"'")
                if t:
                    out.append(t)
            return out
    # 不是合法 JSON 数组 → 退化成分隔符切分 (顺手剥掉方括号/引号)
    s = s.strip().strip("[]").strip()
    parts = re.split(r"[,;、，\s]+", s)
    return [p.strip().strip("\"'") for p in parts if p.strip().strip("\"'")]


async def _publisher_ids() -> set[int]:
    raw = await _setting("marketplace.publisher_ids", "[]")
    return {int(x) for x in _split_list(raw) if str(x).isdigit()}


async def _publisher_names() -> set[str]:
    """允许发布的**用户名**集合 (比填用户 ID 友好)."""
    raw = await _setting("marketplace.publisher_usernames", "")
    return {x.lower() for x in _split_list(raw)}


async def require_publisher(user: User = Depends(get_current_user)) -> User:
    """发布者白名单 + admin 恒可发布.

    白名单两个口径任一命中即可: 用户 ID (JSON 数组) 或 用户名 (逗号分隔).
    """
    role = user.role.value if hasattr(user.role, "value") else str(user.role)
    if role == "admin":
        return user
    if role == "anonymous":
        raise HTTPException(status_code=401, detail="未登录")
    if user.id in await _publisher_ids():
        return user
    names = await _publisher_names()
    if names and (user.username or "").strip().lower() in names:
        return user
    raise HTTPException(status_code=403, detail="不在发布者白名单内, 联系管理员开通")


async def _reviewer_names() -> set[str]:
    """被授权的审核人 (管理员永远有审核权)."""
    raw = await _setting("marketplace.review.reviewer_usernames", "")
    return {
        x.strip().lower()
        for x in raw.replace("，", ",").replace(";", ",").split(",")
        if x.strip()
    }


async def _is_reviewer(user: User) -> bool:
    role = user.role.value if hasattr(user.role, "value") else str(user.role)
    if role == "admin":
        return True
    names = await _reviewer_names()
    return bool(names) and (user.username or "").strip().lower() in names


async def require_reviewer(user: User = Depends(get_current_user)) -> User:
    """能审上架审核的人 —— 管理员, 或被授权的审核人.

    团队里 admin 一个人审不过来 (那是唯一的瓶颈). 所以允许把**审核权**
    单独授予别人 —— 但只给审核权, **不给**改别人资产的权限 (那是作者的事).
    """
    role = user.role.value if hasattr(user.role, "value") else str(user.role)
    if role == "admin":
        return user
    if role == "anonymous":
        raise HTTPException(status_code=401, detail="未登录")
    if await _is_reviewer(user):
        return user
    raise HTTPException(status_code=403, detail="只有管理员或审核人可以审核上架")


async def require_admin(user: User = Depends(get_current_user)) -> User:
    """管理员 —— 上架审核人."""
    role = user.role.value if hasattr(user.role, "value") else str(user.role)
    if role == "admin":
        return user
    if role == "anonymous":
        raise HTTPException(status_code=401, detail="未登录")
    raise HTTPException(status_code=403, detail="只有管理员可以审核上架")


async def _assert_can_modify(code: str, user: User) -> Asset:
    """校验操作者有权改动这个资产 —— **作者本人或管理员**.

    ⚠️ 以前这些写操作只查"是不是发布者"(白名单), 于是**任何在白名单里的用户
    都能下架/删除/更新别人的资产** —— 多用户场景下这是越权.
    白名单的含义是"可以往市场上放东西", 不是"可以改别人放的东西".

    管理员仍然可以改任何人的资产 (运营需要, 比如清理不合规的资产).
    """
    async with AsyncSessionLocal() as session:
        a = (
            await session.execute(select(Asset).where(Asset.code == code))
        ).scalar_one_or_none()
    if a is None:
        raise HTTPException(status_code=404, detail=f"资产 {code} 不存在")
    role = user.role.value if hasattr(user.role, "value") else str(user.role)
    if role == "admin":
        return a
    if (a.author or "").strip().lower() != (user.username or "").strip().lower():
        raise HTTPException(
            status_code=403,
            detail="只能操作自己上传的资产 (管理员可操作任意资产)",
        )
    return a


async def _review_required(user: User) -> bool:
    """这次上传要不要走审核.

    - 审核总开关关 → 谁都直接上架 (旧行为)
    - 管理员自己上传 → 默认免审 (不然没人能审自己)
    - 其余发布者 → 一律待审核
    """
    enabled = (await _setting("marketplace.review.enabled", "true")).lower()
    if enabled not in ("true", "1", "yes", "on"):
        return False
    role = user.role.value if hasattr(user.role, "value") else str(user.role)
    if role == "admin":
        self_approve = (await _setting("marketplace.review.admin_self_approve", "true")).lower()
        return self_approve not in ("true", "1", "yes", "on")
    return True


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

def _to_out(a: Asset, can_review: bool = False) -> AssetOut:
    out = AssetOut.model_validate(a)
    # 当前用户能不能审这个资产 —— 前端据此显示「通过审核 / 驳回」按钮
    out.can_review = can_review
    return out


async def _apply_git_web_url(items: list[AssetOut]) -> None:
    """按当前配置的 GitLab 网页地址补上每个资产的网页链接.

    这是**派生值** —— 改了 marketplace.git.web_url 立刻反映, 不必回填数据库.
    """
    base = ((await _setting("marketplace.git.web_url", "")) or "").strip().rstrip("/")
    if not base:
        return
    branch = git_sync.git_branch()
    for it in items:
        if it.git_path:
            it.git_web_url = f"{base}/-/tree/{branch}/{it.git_path}"


@router.get("", response_model=AssetListOut)
async def list_assets(
    kind: str | None = Query(None),
    category: str | None = Query(None),
    q: str | None = Query(None),
    sort: str = Query("hot", pattern="^(hot|new|name)$"),
    include_unpublished: bool = Query(False),
    status: str = Query(
        # 默认空串 = 走默认可见性规则 (⚠️ pattern 必须允许空串: FastAPI 会拿默认值去过校验)
        "", pattern="^(|published|pending|rejected|unpublished|mine|all)$",
        description="按上架状态过滤; 留空 = 默认可见性规则",
    ),
    limit: int = Query(100, ge=1, le=500),
    offset: int = Query(0, ge=0),
    client_id: str = Query("local"),
    user: User = Depends(get_current_user),
) -> AssetListOut:
    """资产列表.

    默认可见性 (**不是**简单的 publish_status=='published'):
        · 在架的          —— 所有人可见
        · 我已安装的       —— 哪怕已下架也要看得见 (否则用户根本打不开详情,
                              「已下架」提示就形同虚设)
        · 我提交的         —— 待审核 / 已驳回的, 提交者自己要看得到
    status 可以显式过滤: pending(待审核) / rejected(已驳回) /
    unpublished(已下架) / mine(我提交的) / all(全部).

    ⚠️ 非管理员按状态过滤时**只能看自己的** —— 待审核/已驳回的资产还没对外发布,
    别人的不该被列出来.
    """
    username = (user.username or "").strip()
    role = user.role.value if hasattr(user.role, "value") else str(user.role)
    is_admin = role == "admin"
    # 审核人 (admin 或被授权的人) 能处理所有待审资产 —— 团队里 admin 一个人审不过来
    is_reviewer = await _is_reviewer(user)

    async with AsyncSessionLocal() as session:
        stmt = select(Asset)
        if kind:
            stmt = stmt.where(Asset.kind == kind)
        if category:
            stmt = stmt.where(Asset.category == category)

        if status == "mine":
            stmt = stmt.where(Asset.author == username)
        elif status in ("pending", "rejected", "unpublished", "published"):
            stmt = stmt.where(Asset.publish_status == status)
            if not (is_admin or is_reviewer) and status != "published":
                # 别人只能看自己的未发布资产 —— 别人的待审/被驳回内容不该被列出来.
                # 审核人例外: 他要处理的就是这一批.
                stmt = stmt.where(Asset.author == username)
        elif status == "all" or include_unpublished:
            # 不限上架状态 —— 但只对管理员/审核人开放
            # (include_unpublished 是旧参数, 语义等同 all)
            if not (is_admin or is_reviewer):
                stmt = stmt.where(
                    or_(
                        Asset.publish_status == "published",
                        Asset.author == username,
                    )
                )
        elif is_admin or is_reviewer:
            # 管理员/审核人是市场运营者 —— 列表里能看到**全部**资产
            # (含待审核/已驳回/已下架), 每张卡片自己标着状态
            pass
        else:
            # 默认可见性: 在架 ∪ 我提交的
            # (以前还有「我已安装的」—— 现在安装只是下载, 后端不知道用户装没装,
            #  拿下载记录当"已安装"是虚假语义, 去掉更干净)
            stmt = stmt.where(
                or_(
                    Asset.publish_status == "published",
                    Asset.author == username,
                )
            )
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
            # 精选优先, 再按下载次数 (热门度), 最后按最近更新
            rows.sort(
                key=lambda a: (
                    bool(a.featured),
                    a.download_count or 0,
                    a.updated_at or datetime.min,
                ),
                reverse=True,
            )
        page = rows[offset : offset + limit]

    is_reviewer = await _is_reviewer(user)
    items = [_to_out(a, can_review=is_reviewer) for a in page]
    await _apply_git_web_url(items)
    return AssetListOut(items=items, total=total)


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

    mine = (_user.username or "").strip()
    async with AsyncSessionLocal() as session:
        pending = failed = unpublished = 0
        awaiting_review = rejected = my_review = my_pending = 0
        rows = (await session.execute(select(Asset))).scalars().all()
        for a in rows:
            if a.sync_status == "staged":
                pending += 1
            elif a.sync_status == "failed":
                failed += 1
            if a.publish_status == "unpublished":
                unpublished += 1
            elif a.publish_status == "pending":
                awaiting_review += 1
            elif a.publish_status == "rejected":
                rejected += 1
            if mine and (a.author or "") == mine:
                if a.publish_status == "pending":
                    my_pending += 1
                    my_review += 1      # 需要处理 = 在等审核 + 被驳回
                elif a.publish_status == "rejected":
                    my_review += 1

    puller = get_puller()
    return SyncStatusOut(
        has_remote_updates=puller.has_remote_updates,
        conflict_count=puller.conflict_count,
        pending_count=pending,
        failed_count=failed,
        unpublished_count=unpublished,
        awaiting_review_count=awaiting_review,
        rejected_count=rejected,
        my_review_count=my_review,
        my_pending_count=my_pending,
        last_sync_at=puller.last_sync_at,
    )


# ---------- 通知回执 ----------
# ⚠️ 必须注册在 `GET /{code}` **之前** —— FastAPI 按注册顺序匹配路由,
#    放在后面会被 `/{code}` 抢先命中 (表现为 404 "资产 notifications 不存在").

@router.get("/notifications", response_model=AssetNotificationListOut)
async def list_notification_receipts(
    limit: int = Query(50, ge=1, le=200),
    _user: User = Depends(get_current_user),
) -> AssetNotificationListOut:
    """钉钉通知的送达回执 (最近 N 条)."""
    items, total = await list_notifications(limit)
    return AssetNotificationListOut(items=items, total=total)


# ---------- 当前生效配置 (只读) ----------

@router.get("/config", response_model=MarketConfigOut)
async def get_market_config(_user: User = Depends(get_current_user)) -> MarketConfigOut:
    """市场当前生效的配置 —— 设置页用来展示"工作区在哪 / 远端是哪个".

    注意是**生效值** (DB 设置 > env 初值), 不是 schema 里的默认值.
    """
    st = git_sync.workspace_status()
    return MarketConfigOut(
        workspace=str(git_sync.WORKSPACE),
        remote=git_sync.git_remote(),
        branch=git_sync.git_branch(),
        web_url=((await _setting("marketplace.git.web_url", "")) or "").strip(),
        skill_dir=SKILL_INSTALL_DIR,
        plugin_dir=PLUGIN_INSTALL_DIR,
        install_enabled=True,
        is_repo=bool(st.get("is_repo")),
        head=st.get("head", ""),
    )


@router.get("/{code}", response_model=AssetOut)
async def get_asset(
    code: str,
    client_id: str = Query("local"),
    user: User = Depends(get_current_user),
) -> AssetOut:
    async with AsyncSessionLocal() as session:
        a = (
            await session.execute(select(Asset).where(Asset.code == code))
        ).scalar_one_or_none()
        if a is None:
            raise HTTPException(status_code=404, detail=f"资产 {code} 不存在")
        out = [_to_out(a, can_review=await _is_reviewer(user))]
        await _apply_git_web_url(out)
        return out[0]


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

    # 下载次数 +1 —— 原子自增 (先读后写会丢计数: 并发下载时互相覆盖)
    async with AsyncSessionLocal() as session:
        await session.execute(
            update(Asset).where(Asset.code == code)
            .values(download_count=Asset.download_count + 1)
        )
        await session.commit()

    return Response(
        content=data,
        media_type="application/zip",
        headers={
            "Content-Disposition": f'attachment; filename="{name}"',
            "X-Content-Sha256": pkg.sha256_bytes(data),
        },
    )


# ---------- 安装 ----------

# ---------- 包预检 (上传前体检) ----------

@router.post("/preview-package", response_model=PackagePreviewOut)
async def preview_package(
    package: UploadFile = File(...),
    kind: str = Form(""),
    _user: User = Depends(get_current_user),
) -> PackagePreviewOut:
    """上传前体检: 这个包装不装得上?

    走的是**和真正上传完全相同的解包路径** (pkg.extract_package), 所以体检结论
    就是提交后的结论 —— 不会出现"体检说没问题, 提交才被拒".
    """
    data = await package.read()
    filename = package.filename or "package.zip"
    out = PackagePreviewOut(filename=filename, size_bytes=len(data), kind=kind)

    tmp = Path(tempfile.mkdtemp(prefix="tm-preview-"))
    try:
        try:
            extracted = pkg.extract_package(data, filename, tmp)
        except pkg.PackageError as e:
            out.ok = False
            out.issues.append(f"包不合规: {e}")
            return out

        files = extracted.files
        out.ok = True
        out.total_files = len(files)
        out.files = files[:200]
        names = [f.rsplit("/", 1)[-1] for f in files]
        out.has_skill_md = "SKILL.md" in names
        out.has_plugin_manifest = any(
            n == "plugin.json" or ".qoder-plugin" in f.split("/")[:-1]
            for f, n in zip(files, names)
        )
        out.has_mcp_config = any(n == ".mcp.json" for n in names)

        # 展示文档: skill→SKILL.md, plugin/mcp→README.md
        want = "SKILL.md" if kind == "skill" else "README.md"
        out.doc_file = pkg.find_doc_file(files, kind) or ""
        if not out.doc_file:
            out.issues.append(
                f"缺少展示文档 {want} (技能包需要 SKILL.md, 插件包需要 README.md)"
            )

        reason = _install_block_reason(kind or "plugin", files)
        out.installable = not reason
        out.block_reason = reason

        # 安全提示: 包里带了不该进仓库的东西 (解包阶段已硬拦, 这里只做软提示)
        for f in files:
            low = f.lower()
            if low.endswith((".env", ".pem", ".key", ".p12")) or ".ssh/" in low:
                out.warnings.append(f"包含敏感文件, 提交前请确认: {f}")
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
    return out



def _content_files(base: Path) -> list[str]:
    """资产工作区里的内容文件 (相对 files_root 的路径), 用于判断"这个包装不装得上"."""
    root = pkg.files_root(base)
    if not root.is_dir():
        return []
    return [p.relative_to(root).as_posix() for p in pkg.content_files(base)]


def _install_block_reason(kind: str, files: list[str]) -> str:
    """这个包按 kind 能不能装? 不能就返回原因 (空串 = 能装).

    判定口径: skill 必须有 SKILL.md, plugin 必须有 .qoder-plugin/plugin.json ——
    与前端写盘时的校验一致, 否则会出现"前端说能装, 点了却失败"的割裂.
    """
    if kind == "mcp":
        return "连接器不支持一键安装, 请在宿主 MCP 配置里手动添加"
    names = [f.rsplit("/", 1)[-1] for f in files]
    if kind == "skill":
        if "SKILL.md" not in names:
            return "技能包内没有 SKILL.md"
        return ""
    # plugin: 需要 .qoder-plugin/ 目录或 plugin.json
    for f, n in zip(files, names):
        if n == "plugin.json":
            return ""
        parts = f.split("/")
        if ".qoder-plugin" in parts[:-1]:
            return ""
    return "插件包内没有 .qoder-plugin/plugin.json"


# ---------- 上架 / 下架 ----------

async def _set_publish_state(
    *,
    code: str,
    publish_status: str,
    action: str,
    comment: str,
    user: User,
    review_note: str | None = None,
) -> dict[str, Any]:
    """上下架 —— 改 DB + 写单资产 manifest + 更新 index.json + **提交到 GitLab**.

    为什么必须提交到 GitLab:
      上下架只改资产文件, 改的是 index.json (派生物) 与 manifest.json (权威).
      不提交的话, 别的 TestMate 实例永远不知道这个资产被下架了 —— 共享市场就废了.
      所以这里也建 job, 走同一条 commit + push 队列.

    文件**保留** —— 在用的人还能继续用, 只是列表里标「已下架」.

    publish_status 四态: pending(待审核) / published(在架) / rejected(已驳回) / unpublished(已下架)
    """
    async with AsyncSessionLocal() as session:
        a = (
            await session.execute(select(Asset).where(Asset.code == code))
        ).scalar_one_or_none()
        if a is None:
            raise HTTPException(status_code=404, detail=f"资产 {code} 不存在")
        if a.publish_status == publish_status and (
            review_note is None or a.review_note == review_note
        ):
            return {
                "ok": True, "code": code, "publish_status": publish_status,
                "changed": False,
            }

        a.publish_status = publish_status
        if review_note is not None:
            a.review_note = review_note
        await session.commit()

        # 权威是单资产 manifest.json —— 生命周期状态也写进去
        manifest_path = f"{a.git_path}/manifest.json"
        raw = git_sync.read_text(manifest_path)
        try:
            manifest = json.loads(raw) if raw else {}
        except json.JSONDecodeError:
            manifest = {}
        if not isinstance(manifest, dict):
            manifest = {}
        manifest["publish_status"] = publish_status
        if review_note is not None:
            manifest["review_note"] = review_note
        git_sync.write_text(manifest_path, json.dumps(manifest, ensure_ascii=False, indent=2))

        # index.json 是派生物, 从 DB 重新渲染 (现在它带 publish_status)
        await stage_index(session, asset_to_index_entry(a))

        await _audit(session, code=code, action=action, actor=user,
                     asset_id=a.id, comment=comment,
                     detail={"publish_status": publish_status, "version": a.version,
                             "review_note": a.review_note})
        await session.commit()

        job = AssetJob(
            action=action,
            status="staged",
            code=a.code,
            asset_name=a.name,
            kind=a.kind,
            payload={
                "author": list(_author_of(user)),
                "commit_message": (
                    f"chore(market): {'下架' if action == 'unpublish' else '上架'}资产 "
                    f"{a.name} {a.version}"
                ),
            },
            git_path=a.git_path,
            created_by=user.id,
        )
        session.add(job)
        await session.commit()
        await session.refresh(job)
        job_id = job.id
        name, version = a.name, a.version

    enqueue(job_id)
    return {
        "ok": True, "code": code, "publish_status": publish_status,
        "changed": True, "job_id": job_id, "name": name, "version": version,
    }


@router.post("/{code}/unpublish")
async def unpublish_asset(
    code: str,
    comment: str = Form(""),
    user: User = Depends(require_publisher),
) -> dict[str, Any]:
    """下架: 标记 + 从索引里移除, 但**保留文件** (在用用户要能看到"已下架")."""
    await _assert_can_modify(code, user)
    out = await _set_publish_state(
        code=code, publish_status="unpublished", action="unpublish",
        comment=comment, user=user,
    )
    if not out.get("changed"):
        return out
    await notify_market(
        "unpublish", name=out["name"], version=out["version"], actor=user.username,
        detail=comment or "已从市场下架", link="", code=code,
    )
    return {"ok": True, "code": code, "publish_status": "unpublished"}


# ---------- 上架审核 ----------

@router.post("/{code}/review")
async def review_asset(
    code: str,
    decision: str = Form(..., description="approve | reject"),
    comment: str = Form(""),
    _user: User = Depends(require_reviewer),
) -> dict[str, Any]:
    """管理员审核上架.

    approve → publish_status=published (资产在市场可见)
    reject  → publish_status=rejected  (发布者能看到驳回理由, 改了重新提交)

    审核结果同样会 commit + push 到 GitLab —— 别的实例要立刻看到"这件通过了".
    """
    if decision not in ("approve", "reject"):
        raise HTTPException(status_code=400, detail="decision 只能是 approve 或 reject")

    if decision == "approve":
        out = await _set_publish_state(
            code=code, publish_status="published", action="approve",
            comment=comment or "审核通过", user=_user, review_note=comment or "",
        )
        if out.get("changed"):
            await notify_market(
                "publish", name=out["name"], version=out["version"], actor=_user.username,
                detail=comment or "审核通过, 已上架", link="", code=code,
            )
        return out

    note = comment or "审核未通过, 请修改后重新提交"
    out = await _set_publish_state(
        code=code, publish_status="rejected", action="reject",
        comment=note, user=_user, review_note=note,
    )
    if out.get("changed"):
        await notify_market(
            "reject", name=out["name"], version=out["version"], actor=_user.username,
            detail=note, link="", code=code,
        )
    return out


@router.post("/{code}/submit")
async def submit_for_review(
    code: str,
    comment: str = Form(""),
    _user: User = Depends(require_publisher),
) -> dict[str, Any]:
    """把被驳回(或自己新建)的资产重新提交审核.

    只有资产作者本人或管理员能提交 —— 别人不能替别人把资产推上去.
    """
    async with AsyncSessionLocal() as session:
        a = (
            await session.execute(select(Asset).where(Asset.code == code))
        ).scalar_one_or_none()
        if a is None:
            raise HTTPException(status_code=404, detail=f"资产 {code} 不存在")
        role = _user.role.value if hasattr(_user.role, "value") else str(_user.role)
        is_author = (a.author or "").strip().lower() == (_user.username or "").strip().lower()
        if role != "admin" and not is_author:
            raise HTTPException(status_code=403, detail="只有资产作者本人可以提交审核")
        if a.publish_status == "published":
            raise HTTPException(status_code=409, detail="资产已在架, 无需重复提交审核")

    out = await _set_publish_state(
        code=code, publish_status="pending", action="submit",
        comment=comment or "重新提交审核", user=_user, review_note="",
    )
    if out.get("changed"):
        await notify_market(
            "review", name=out["name"], version=out["version"], actor=_user.username,
            detail=comment or "提交审核", link="", code=code,
        )
    return out


@router.post("/{code}/publish")
async def publish_asset(
    code: str,
    comment: str = Form(""),
    user: User = Depends(require_publisher),
) -> dict[str, Any]:
    """重新上架."""
    await _assert_can_modify(code, user)
    out = await _set_publish_state(
        code=code, publish_status="published", action="publish",
        comment=comment, user=user,
    )
    if not out.get("changed"):
        return out
    await notify_market(
        "publish", name=out["name"], version=out["version"], actor=user.username,
        detail=comment or "重新上架", link="", code=code,
    )
    return {"ok": True, "code": code, "publish_status": "published"}


# ---------- 硬删 ----------

@router.delete("/{code}", response_model=AssetDeleteOut)
async def delete_asset(
    code: str,
    comment: str = Query("", description="删除原因 (记入审计)"),
    _user: User = Depends(require_publisher),
) -> AssetDeleteOut:
    """彻底删除一个资产 (不只是下架).

    ⚠️ 只能删**自己上传的**资产 (管理员例外) —— 白名单只是"能发布"的意思.

    与「下架」的区别:
      下架 —— 标记 + 从索引移除, **文件保留**; 已装的用户还能继续用, 看到「已下架」提示
      删除 —— 连文件带索引带 DB 记录一起没, 不可恢复

    顺序很关键 (**先推 GitLab, 后动 DB**):
      1. index.json 剔除该资产 (DB 行还在, 用 exclude 参数)
      2. 删掉工作区里的资产目录
      3. commit + push 到 GitLab —— 失败就把工作区从 HEAD 恢复, DB 一个字节都不动
      4. 推送成功 → 删 DB 行 + 安装记录, 记审计, 发通知
    反过来做的话, push 失败会导致"DB 没了但 GitLab 还在" → 拉取同步器会把资产复活.
    """
    await _assert_can_modify(code, _user)
    async with AsyncSessionLocal() as session:
        a = (
            await session.execute(select(Asset).where(Asset.code == code))
        ).scalar_one_or_none()
        if a is None:
            raise HTTPException(status_code=404, detail=f"资产 {code} 不存在")
        git_path = a.git_path
        asset_name = a.name
        version = a.version
        asset_id = a.id

    if not git_path:
        raise HTTPException(status_code=409, detail="资产没有 git 路径, 无法安全删除")

    async with code_lock(code):
        # 1) 索引剔除 + 删工作区目录
        async with AsyncSessionLocal() as session:
            await stage_index(session, exclude={code})
        git_sync.remove_path(git_path)

        # 2) commit + push
        #    ⚠️ 只有**被 git 跟踪过**的资产目录才能进 pathspec —— 从没提交过的
        #    资产 (推送失败留下的), 路径不在 git 里, `git commit -- <path>` 会报
        #    "pathspec did not match any files", 删除就永远 502.
        paths = [INDEX_PATH]
        if git_sync.tracked_files(git_path):
            paths.insert(0, git_path)
        try:
            result = await git_sync.sync_paths(
                paths=paths,
                message=f"chore(market): 删除资产 {asset_name} {version}",
                author=_author_of(_user),
            )
        except git_sync.SyncError as e:
            # 回滚工作区: 目录与 index.json 都从最后一次提交恢复
            git_sync.checkout_from_ref("HEAD", [git_path, INDEX_PATH])
            logger.error("delete 推送失败, 工作区已回滚 code=%s err=%s", code, e)
            raise HTTPException(
                status_code=502,
                detail=f"删除未生效: 推送到 GitLab 失败 ({e}). 资产未被删除, 可稍后重试",
            ) from e

        # 3) 推送成功 → 动 DB
        async with AsyncSessionLocal() as session:
            a = await session.get(Asset, asset_id)
            if a is not None:
                await session.delete(a)
            await _audit(
                session, code=code, action="delete", actor=_user, asset_id=asset_id,
                comment=comment or "管理员删除",
                detail={"git_path": git_path},
            )
            await session.commit()
        # ⚠️ 用户本机的安装目录不动 —— 后端够不着, 也不该替用户删文件.
        #    (服务端写盘通道已下线)

    await notify_market(
        "delete", name=asset_name, version=version, actor=_user.username,
        detail=comment or "资产已从市场删除", link="", code=code,
    )
    logger.info("delete 资产 code=%s", code)
    return AssetDeleteOut(
        ok=True, code=code,
        commit_sha=result.commit_sha,
    )


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
    # 限额来自设置页 (可在前端改), 传 None 则用模块默认值
    try:
        max_files = int(await _setting("marketplace.upload.max_files", "") or 0) or None
    except (TypeError, ValueError):
        max_files = None
    try:
        max_mb = int(await _setting("marketplace.upload.max_total_mb", "") or 0) or None
    except (TypeError, ValueError):
        max_mb = None
    max_bytes = max_mb * 1024 * 1024 if max_mb else None
    try:
        return validate_files(collected, max_files=max_files, max_total_bytes=max_bytes)
    except ManifestError as e:
        # 校验失败是**用户上传内容**的问题 (文件数/体积/路径/后缀), 不是服务端故障
        raise HTTPException(status_code=422, detail=f"上传文件不合规: {e}") from e


async def _stage_asset(
    *,
    action: str,
    payload_in: UploadAssetIn,
    files: dict[str, str],
    package: bytes | None,
    package_name: str,
    user: User,
) -> AssetJobOut:
    """落盘阶段 —— 整个过程在同一把 code 锁内.

    落盘 (解包 → 写 files/ → 写 manifest.json) 发生在请求线程里, **不在** git 提交
    队列里. 不加锁的话, 两个并发上传同一个 code 会各自往 files/ 里写, 写出来的
    是两份文件的交错体, 然后被先完成的那个 job 一起 commit 上去.
    """
    async with code_lock(payload_in.code):
        return await _stage_asset_locked(
            action=action, payload_in=payload_in, files=files,
            package=package, package_name=package_name, user=user,
        )


async def _stage_asset_locked(
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
            # ⚠️ 作者**强制**取上传者, 不接受前端指定.
            #    否则任何人都能把资产挂到别人名下 (冒充), 而作者的权限
            #    (改自己的资产) 也就跟着落到别人头上了.
            author=user.username,
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

    # ---- 0. 存在性检查 (必须在落盘**之前**) ----
    # 顺序反了会出事: 冲突的创建请求会先把文件写进工作区, 再报 409.
    # 工作区因此变脏 → 拉取同步器的安全闸认为"有未提交的资产改动" → 整轮跳过,
    # 而那份半截文件永远没人提交. 整个反向同步就此卡住.
    async with AsyncSessionLocal() as session:
        existing = (
            await session.execute(select(Asset).where(Asset.code == manifest["code"]))
        ).scalar_one_or_none()
    if action == "create" and existing is not None:
        raise HTTPException(
            status_code=409,
            detail=(
                f"资产 {manifest['code']} 已存在 (作者: {existing.author or '未知'}), "
                "请用更新接口"
            ),
        )
    if action == "update" and existing is None:
        raise HTTPException(
            status_code=404, detail=f"资产 {manifest['code']} 不存在, 无法更新"
        )

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
        # 上架审核: 需要审核 → 进「待审核」(不对普通用户可见), 免审 → 直接上架
        # 更新已上架的资产同样走审核 —— 内容变了, 审核的意义就在这
        need_review = await _review_required(user)
        if need_review:
            a.publish_status = "pending"
            a.review_note = ""
        elif existing is None:
            a.publish_status = "published"

        # ⚠️ manifest.json 是**权威** —— 必须带上 publish_status.
        #    少了它, 同步器 (sync_puller) 读到 None 会当成 published →
        #    **待审核的资产会被自动改成已上架**, 审核形同虚设.
        #    (上下架走 _set_publish_state, 那里本来就写这个字段 —— 上传这条路漏了)
        manifest["publish_status"] = a.publish_status
        git_sync.write_text(
            f"{base}/manifest.json",
            json.dumps(manifest, ensure_ascii=False, indent=2),
        )
        # 资产在 GitLab 上的网页地址 —— 市场页可以给个「在 GitLab 查看」链接
        web_base = ((await _setting("marketplace.git.web_url", "")) or "").strip().rstrip("/")
        a.git_web_url = (
            f"{web_base}/-/tree/{git_sync.git_branch()}/{base}" if web_base else ""
        )
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
                "publish_status": a.publish_status,
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
    # 通知: 待审核的资产通知"有人提交了, 请审核"; 直接上架的才通知"已上架"
    if a.publish_status == "pending":
        await notify_market(
            "review",
            name=manifest.get("name", ""), version=manifest.get("version", ""),
            actor=user.username,
            detail=manifest.get("summary", "") or "新资产待审核",
            link="", code=manifest.get("code", ""),
        )
    else:
        await notify_market(
            "publish" if action == "create" else "update",
            name=manifest.get("name", ""), version=manifest.get("version", ""),
            actor=user.username,
            detail=manifest.get("summary", ""), link="",
            code=manifest.get("code", ""),
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
            author=user.username, featured=featured,
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
    featured: bool = Form(False),
    permissions: str = Form("{}"),
    install_steps: str = Form("[]"),
    bindings: str = Form("{}"),
    files: list[UploadFile] | None = File(None),
    package: UploadFile | None = File(None),
    user: User = Depends(require_publisher),
) -> AssetJobOut:
    """更新一个已存在的资产 (发新版本).

    ⚠️ 只能更新**自己上传的**资产 (管理员例外) —— 否则任何白名单用户都能
    改别人的资产, 覆盖掉别人精心写的内容.
    """
    await _assert_can_modify(code, user)

    # 发布新版本 (覆盖同名文件, git 历史保留旧版)
    try:
        payload = UploadAssetIn(
            code=code, kind=kind, name=name, summary=summary, version=version,
            description=description, use_when=use_when, not_for=not_for,
            category=category, icon=icon,
            tags=json.loads(tags or "[]"), keywords=json.loads(keywords or "[]"),
            author=user.username, featured=featured,
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
