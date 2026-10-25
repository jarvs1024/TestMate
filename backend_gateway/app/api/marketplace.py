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
from pydantic import ValidationError
from fastapi import Response
from sqlalchemy import Text, cast, select, or_, update

from app.api.auth import get_current_user
from app.core import git_sync, pkg
from app.core.asset_jobs import enqueue, retry_job, start_worker
from app.core.asset_locks import code_lock
from app.core.dingtalk import list_notifications, notify_market
from app.core import (
    market_notify,
    market_naming,
    market_policy,
    market_projects,
    market_state,
)
from app.core.market_visibility import assert_visible, apply_visibility
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


async def require_publisher(user: User = Depends(get_current_user)) -> User:
    """发布者白名单 + admin 恒可发布.

    白名单两个口径任一命中即可: 用户 ID (JSON 数组) 或 用户名 (逗号分隔).
    判定逻辑在 app/core/market_policy.py (纯逻辑, 可单测).
    """
    if not await market_policy.can_publish(user):
        if market_policy.role_of(user) == "anonymous":
            raise HTTPException(status_code=401, detail="未登录")
        raise HTTPException(status_code=403, detail="不在发布者白名单内, 联系管理员开通")
    return user


async def _is_reviewer(user: User) -> bool:
    """能不能审核 (管理员永远可以) —— 判定在 market_policy."""
    return await market_policy.is_reviewer(user)


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
    """管理员 —— 上架审核人 / 下架审核人 / 直接删资产.

    ⚠️ 下架审核**只限管理员**: 通过就等于删了别人的资产,
    被授权的审核人 (marketplace.review.reviewer_usernames) 只能做上架审核.
    """
    role = user.role.value if hasattr(user.role, "value") else str(user.role)
    if role == "admin":
        return user
    if role == "anonymous":
        raise HTTPException(status_code=401, detail="未登录")
    raise HTTPException(status_code=403, detail="只有管理员可以审核 (下架审核 = 删除, 只限管理员)")


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
    if not market_policy.can_modify(a, user):
        raise HTTPException(
            status_code=403,
            detail="只能操作自己上传的资产 (管理员可操作任意资产)",
        )
    return a


def _assert_naming(
    code: str,
    kind: str,
    mcp_cfg: dict | None,
    package: UploadFile | None,
) -> None:
    """命名契约: 资产 code 必须与「包名 / MCP 连接器名」一致.

    前端已经管了 (选包自动同步 code, 不一致就报错不让上架), 这里是**兜底** ——
    绕过前端直接调 API 时, 也能拦住"资产号与包名对不上"的资产.
    """
    if kind == "mcp":
        msg = market_naming.check_mcp_code_consistency(mcp_cfg, code)
    elif package is not None and (package.filename or "").strip():
        msg = market_naming.check_package_consistency(package.filename, code)
    else:
        # 多文件文本上传 —— 没有"包名"这回事
        return
    if msg:
        raise HTTPException(status_code=422, detail=msg)


async def _resolve_project(code: str, raw: str, *, action: str) -> str:
    """把表单里的项目名归一成正式项目 —— **更新时不丢老归属**.

    项目可能已经从设置项里删掉了 (团队不再跑这个项目), 但资产上的归属是
    **历史事实** —— 归一时把它清成"通用"就等于悄悄改了语义.
    所以: 归一后为空且资产本来有归属 → 保留原值.
    """
    proj = market_projects.normalize(raw, await _project_list())
    if action != "update" or proj:
        return proj
    async with AsyncSessionLocal() as session:
        old = (
            await session.execute(select(Asset).where(Asset.code == code))
        ).scalar_one_or_none()
    if old is not None and (old.project or "").strip():
        return old.project
    return proj


async def _project_list() -> list[str]:
    """项目列表 (设置项 marketplace.projects) —— 没配就用默认列表.

    项目会增减 —— 所以是**配置**而不是写死的常量; 上传表单 / 市场筛选 /
    卡片徽标都用这一份, 免得两处各写一套.
    """
    raw = await _setting(market_projects.SETTINGS_KEY, "")
    projects = market_projects.parse(raw)
    return projects or list(market_projects.DEFAULT_PROJECTS)


async def _setting_bool(key: str, default: bool = False) -> bool:
    """读一个布尔开关.

    ⚠️ 不能用 ``_setting``: 它是 ``(await get(k, d)) or d`` —— DB 里存的是 JSON
    ``false`` 时会被当成"空"换回默认值 (开关关了却当成开着), 存 JSON ``true`` 时
    返回的是布尔, 再调 ``.lower()`` 直接 AttributeError → 500.
    """
    try:
        from app.core.settings_store import get, to_bool

        return to_bool(await get(key, default), default)
    except Exception:  # noqa: BLE001
        return default


async def _review_required(user: User) -> bool:
    """这次上传要不要走审核.

    - 审核总开关关 → 谁都直接上架 (旧行为)
    - 管理员自己上传 → 默认免审 (不然没人能审自己)
    - 其余发布者 → 一律待审核
    """
    if not await _setting_bool("marketplace.review.enabled", True):
        return False
    role = user.role.value if hasattr(user.role, "value") else str(user.role)
    if role == "admin":
        return not await _setting_bool("marketplace.review.admin_self_approve", True)
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
    project: str | None = Query(
        None,
        description=(
            "按项目过滤: 留空=不过滤; __general=只看通用资产; "
            "6100=6100 项目特有 **+ 通用** (通用资产在该项目同样适用)"
        ),
    ),
    q: str | None = Query(
        None,
        description=(
            "关键词检索: 命中 名称 / 简介 / 详细说明 / 作者 / 标签 / 检索词 / "
            "**所属项目** (如 6100; 中文「通用」命中通用资产)"
        ),
    ),
    sort: str = Query("hot", pattern="^(hot|new|name)$"),
    include_unpublished: bool = Query(False),
    status: str = Query(
        # 默认空串 = 走默认可见性规则 (⚠️ pattern 必须允许空串: FastAPI 会拿默认值去过校验)
        "", pattern="^(|published|pending|rejected|unpublished|unpublish_pending|mine|all)$",
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
        if project:
            # ⚠️ 选某个项目 = 该项目特有 **+ 通用** ——
            #    "我在 6100 项目能用什么" 里当然包含通用资产.
            #    __general = 只看通用的 (筛"哪些是共享的").
            if project == "__general":
                stmt = stmt.where(Asset.project == "")
            else:
                stmt = stmt.where(or_(Asset.project == project, Asset.project == ""))

        if status == "mine":
            stmt = stmt.where(Asset.author == username)
        elif status in ("pending", "rejected", "unpublished", "unpublish_pending", "published"):
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
                        Asset.publish_status.in_(("published", "unpublish_pending")),
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
            # ⚠️ unpublish_pending (申请下架, 等管理员确认) **仍在架** ——
            #    管理员确认前它还在被用, 不能从列表里消失 (只是标个待审徽标).
            stmt = stmt.where(
                or_(
                    Asset.publish_status.in_(("published", "unpublish_pending")),
                    Asset.author == username,
                )
            )
        if q:
            raw_q = q.strip()
            like = f"%{raw_q}%"
            # ⚠️ tags / keywords 也参与检索 —— 上传表单里那个「搜索关键词」
            #    字段的承诺是"搜不到时靠它", 后端不搜就等于白填.
            #    (JSON 列没法直接 like, 只能 CAST 成文本; 走不了索引, 但资产量不大)
            #
            # ⚠️ **项目也参与检索** (2026-10-25): 输入项目号 (如 6100) 能搜到
            #    归属该项目的资产 —— 市场页搜索框的承诺就是"按项目也能搜".
            #    (注意: 这是**文本命中**, 不是"项目筛选" —— 选项目 6100 会带上通用资产,
            #     搜 6100 只命中 project='6100' 的那些, 两者语义不同, 别混)
            proj_match = [Asset.project.like(like)]
            if "通用" in raw_q:
                # 「通用」是**显示名** —— 资产里通用 = project 为空串, LIKE 匹配不到
                proj_match.append(Asset.project == "")
            stmt = stmt.where(
                or_(
                    Asset.name.like(like),
                    Asset.summary.like(like),
                    Asset.description.like(like),
                    Asset.author.like(like),
                    cast(Asset.tags, Text).like(like),
                    cast(Asset.keywords, Text).like(like),
                    *proj_match,
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
    """分类表 + 各分类的资产数 (按类型分开).

    ⚠️ 返回的是**完整分类表** (含计数为 0 的) —— 前端据此动态渲染筛选 chip.
    以前前端硬编码 7 个分类, 用户自建的分类**没有 chip** → 筛不出来 (孤儿分类).
    """
    from app.core.market_categories import table as category_table

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

    items = []
    for c in category_table():
        by_kind = counts.get(c["name"], {})
        items.append(
            {
                "name": c["name"],
                "slug": c["slug"],
                "desc": c.get("desc", ""),
                "order": c.get("order", 99),
                "by_kind": by_kind,
                "total": sum(by_kind.values()),
            }
        )
    # 兜底: 表里没有但 DB 里有的 (老数据 / 别的实例写的) 也列出来, 免得资产"消失"
    for cat, by_kind in counts.items():
        if any(i["name"] == cat for i in items):
            continue
        items.append(
            {
                "name": cat,
                "slug": "misc",
                "desc": "未归类的资产",
                "order": 98,
                "by_kind": by_kind,
                "total": sum(by_kind.values()),
            }
        )
    items.sort(key=lambda i: (i["order"], i["name"]))
    return {"items": items, "total": sum(i["total"] for i in items)}


@router.get("/projects")
async def list_projects(_user: User = Depends(get_current_user)) -> dict[str, Any]:
    """项目列表 + 每个项目的资产数.

    ⚠️ 返回的是**完整列表** (含计数为 0 的) —— 前端据此渲染:
      · 上传表单的「适用项目」下拉
      · 市场页的项目筛选 chip
    项目列表来自设置项 marketplace.projects (管理员可改, 不用发版)。
    """
    projects = await _project_list()

    async with AsyncSessionLocal() as session:
        rows = (
            await session.execute(
                select(Asset.project).where(Asset.publish_status == "published")
            )
        ).all()
    counts: dict[str, int] = {}
    for (p,) in rows:
        p = (p or "").strip()
        counts[p] = counts.get(p, 0) + 1

    # ⚠️ 通用项的 code 用 "general" —— 它是**筛选参数**, 不是资产里的 project 值
    #    (资产里通用 = 空串). is_general 标出来, 前端别把它当一个项目列进下拉.
    items = [{
        "code": "general", "name": "通用", "total": counts.get("", 0), "is_general": True,
    }]
    items += [{"code": p, "name": p, "total": counts.get(p, 0)} for p in projects]
    # 兜底: 项目已从列表里删掉, 但还有资产挂着它 —— 也列出来 (别让资产"没有归属")
    for p, n in counts.items():
        if p and not any(i["code"] == p for i in items):
            items.append({"code": p, "name": p, "total": n})
    return {"items": items, "total": len(items)}


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
    user: User = Depends(require_admin),
) -> AssetAuditListOut:
    """资产的操作审计 (谁在什么时候上架/下架/驳回/删了哪个资产). —— **管理员专用**.

    ⚠️ 这是**运营数据**: 别的同事传了什么、被谁驳回的、哪次下架是谁拍板的 ——
       普通用户不需要看, 也不该看. (前端「操作记录」按钮同步隐藏)
    """
    async with AsyncSessionLocal() as session:
        stmt = select(AssetAudit).order_by(AssetAudit.id.desc()).limit(limit)
        if code:
            stmt = stmt.where(AssetAudit.code == code)
        rows = (await session.execute(stmt)).scalars().all()
        items = []
        for r in rows:
            out = AssetAuditOut.model_validate(r)
            # 动作的中文由后端给 (唯一真源) —— 前端不再自己翻译
            out.action_label = market_state.audit_action_label(r.action)
            items.append(out)
        return AssetAuditListOut(items=items, total=len(items))


@router.get("/sync-status", response_model=SyncStatusOut)
async def sync_status(
    client_id: str = Query("local"),
    user: User = Depends(get_current_user),
) -> SyncStatusOut:
    """前端顶部状态条: 待同步 / 失败 / 有更新 / 有冲突.

    ⚠️ **系统级**的计数 (别人几个资产同步失败了 / 有几个冲突 / 全市场几个待审)
       只给管理员 —— 那是运营数据, 普通用户看了也没用.
       但**跟我自己有关的** (我的几个待审 / 我申请下架的) 谁都能看 ——
       前端顶部那两条提示条就是靠这些字段.
    """
    from app.core.sync_puller import get_puller

    is_admin = market_policy.is_admin(user)
    mine = (user.username or "").strip()
    async with AsyncSessionLocal() as session:
        pending = failed = unpublished = 0
        awaiting_review = rejected = my_review = my_pending = 0
        unpublish_pending = my_unpublish = 0
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
            elif a.publish_status == "unpublish_pending":
                unpublish_pending += 1
            if mine and (a.author or "") == mine:
                if a.publish_status == "pending":
                    my_pending += 1
                    my_review += 1      # 需要处理 = 在等审核 + 被驳回
                elif a.publish_status == "rejected":
                    my_review += 1
                elif a.publish_status == "unpublish_pending":
                    my_unpublish += 1

    puller = get_puller()
    if not is_admin:
        # 系统级计数对非管理员一律归零 (前端的状态条自然就不显示了)
        pending = failed = unpublished = awaiting_review = rejected = unpublish_pending = 0
    return SyncStatusOut(
        has_remote_updates=puller.has_remote_updates if is_admin else False,
        conflict_count=puller.conflict_count if is_admin else 0,
        pending_count=pending,
        failed_count=failed,
        unpublished_count=unpublished,
        awaiting_review_count=awaiting_review,
        rejected_count=rejected,
        my_review_count=my_review,
        my_pending_count=my_pending,
        unpublish_pending_count=unpublish_pending,
        my_unpublish_count=my_unpublish,
        last_sync_at=puller.last_sync_at,
    )


# ---------- 通知回执 ----------
# ⚠️ 必须注册在 `GET /{code}` **之前** —— FastAPI 按注册顺序匹配路由,
#    放在后面会被 `/{code}` 抢先命中 (表现为 404 "资产 notifications 不存在").

@router.get("/notifications", response_model=AssetNotificationListOut)
async def list_notification_receipts(
    limit: int = Query(50, ge=1, le=200),
    user: User = Depends(require_admin),
) -> AssetNotificationListOut:
    """钉钉通知的送达回执 (最近 N 条). —— **管理员专用**.

    ⚠️ 回执里是**真正发到群里去的内容** (标题 + 正文) —— 谁上架了什么、
       谁被驳回了, 都写在里面. 普通用户不需要看, 也不该看.
    """
    items, total = await list_notifications(limit)
    return AssetNotificationListOut(items=items, total=total)


# ---------- 当前生效配置 (只读) ----------

@router.get("/config", response_model=MarketConfigOut)
async def get_market_config(user: User = Depends(get_current_user)) -> MarketConfigOut:
    """市场当前生效的配置 —— 设置页用来展示"工作区在哪 / 远端是哪个".

    注意是**生效值** (DB 设置 > env 初值), 不是 schema 里的默认值.

    ⚠️ 非管理员拿不到**工作区绝对路径**和 **Git 远端地址** ——
       那是部署内部信息 (主机名/端口/仓库路径), 对普通用户没意义.
    """
    st = git_sync.workspace_status()
    is_admin = market_policy.is_admin(user)
    return MarketConfigOut(
        workspace=str(git_sync.WORKSPACE) if is_admin else "",
        remote=git_sync.git_remote() if is_admin else "",
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
        is_reviewer = await _is_reviewer(user)
        # ⚠️ 待审核 / 被驳回 / 已下架的资产**不能**让无关的人看到
        #    (连接器的 MCP 配置里还有 env/headers, 可能是令牌)
        assert_visible(a, username=user.username or "", is_reviewer=is_reviewer,
                       is_admin=market_policy.is_admin(user))
        out = [_to_out(a, can_review=is_reviewer)]
        await _apply_git_web_url(out)
        return out[0]


@router.get("/{code}/doc", response_model=AssetDocOut)
async def get_asset_doc(code: str, user: User = Depends(get_current_user)) -> AssetDocOut:
    """详情页展示的文档正文: skill→SKILL.md, plugin→README.md."""
    async with AsyncSessionLocal() as session:
        a = (
            await session.execute(select(Asset).where(Asset.code == code))
        ).scalar_one_or_none()
    if a is None:
        raise HTTPException(status_code=404, detail=f"资产 {code} 不存在")
    assert_visible(a, username=user.username or "", is_reviewer=await _is_reviewer(user),
                   is_admin=market_policy.is_admin(user))

    if a.kind == "mcp":
        # 连接器没有 README —— 它只有一段 MCP 配置 (在 manifest 里, 详情页直接展示)
        raise HTTPException(
            status_code=404,
            detail="连接器没有文档, 只有 MCP 配置 (见资产详情的「MCP 配置」)",
        )

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
async def get_asset_files(code: str, user: User = Depends(get_current_user)) -> AssetFilesOut:
    """本地工作区里该资产的文件树 (证明数据真实落盘)."""
    async with AsyncSessionLocal() as session:
        a = (
            await session.execute(select(Asset).where(Asset.code == code))
        ).scalar_one_or_none()
    if a is None:
        raise HTTPException(status_code=404, detail=f"资产 {code} 不存在")
    assert_visible(a, username=user.username or "", is_reviewer=await _is_reviewer(user),
                   is_admin=market_policy.is_admin(user))

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
    code: str, user: User = Depends(get_current_user)
) -> AssetFileBundleOut:
    """前端通道安装用: 已解压的明文文件清单 + 内容 (前端只写文件, 不解压)."""
    async with AsyncSessionLocal() as session:
        a = (
            await session.execute(select(Asset).where(Asset.code == code))
        ).scalar_one_or_none()
    if a is None:
        raise HTTPException(status_code=404, detail=f"资产 {code} 不存在")
    assert_visible(a, username=user.username or "", is_reviewer=await _is_reviewer(user),
                   is_admin=market_policy.is_admin(user))

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
    code: str, version: str, user: User = Depends(get_current_user)
) -> Response:
    """下载安装包 (原始 zip; 老资产没有存包则即时确定性打包)."""
    async with AsyncSessionLocal() as session:
        a = (
            await session.execute(select(Asset).where(Asset.code == code))
        ).scalar_one_or_none()
    if a is None:
        raise HTTPException(status_code=404, detail=f"资产 {code} 不存在")
    assert_visible(a, username=user.username or "", is_reviewer=await _is_reviewer(user),
                   is_admin=market_policy.is_admin(user))

    if a.kind == "mcp":
        # ⚠️ 连接器没有安装包 —— 它是一段 MCP 配置, 不是一堆文件
        raise HTTPException(
            status_code=400,
            detail="连接器没有安装包, 请照资产详情里的「MCP 配置」手动添加到宿主",
        )

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

# 动作名 → git commit 里的中文描述 (下架申请制之后动作多了好几个)
_ACTION_COMMIT_TEXT = {
    "publish": "上架",
    "unpublish": "下架",
    "unpublish_request": "申请下架",
    "unpublish_approve": "通过下架",
    "unpublish_reject": "驳回下架",
    "unpublish_cancel": "撤销下架",
    "approve": "通过审核, 上架",
    "reject": "驳回审核",
    "submit": "提交审核",
}


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
    # 通知要用: 资产类型 (技能包/插件/连接器) / 分类 / 作者 (不通过时要 @他) / 适用项目
    kind = category = author = project = ""
    # ⚠️ 状态流转必须**加锁** —— manifest 是读-改-写:
    #    上传 v2 与审核通过并发时, 谁后写谁覆盖谁 → GitLab 上的权威 manifest 丢更新
    #    (DB 显示新版本、远端是旧版本).
    async with code_lock(code):
        async with AsyncSessionLocal() as session:
            a = (
                await session.execute(select(Asset).where(Asset.code == code))
            ).scalar_one_or_none()
            if a is None:
                raise HTTPException(status_code=404, detail=f"资产 {code} 不存在")

            # ⚠️ 状态机: 「这个动作在这个状态下、这个人身份下」允许吗?
            #    以前每个端点各自 if 判断, 于是作者能自助上架绕过审核、
            #    审核人能驳回在架资产 —— 现在统一由 market_state 裁决.
            try:
                market_state.assert_transition(
                    action, a.publish_status or market_state.PUBLISHED,
                    is_author=market_policy.can_modify(a, user),
                    is_reviewer=await _is_reviewer(user),
                    is_admin=market_policy.is_admin(user),
                )
            except market_state.TransitionError as e:
                raise HTTPException(status_code=409, detail=str(e)) from e

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
                        f"chore(market): {_ACTION_COMMIT_TEXT.get(action, '更新')}资产 "
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
            kind, category, author = a.kind, a.category, a.author
            project = a.project or ""

    enqueue(job_id)
    return {
        "ok": True, "code": code, "publish_status": publish_status,
        "changed": True, "job_id": job_id, "name": name, "version": version,
        # 通知要用: 资产类型 (技能包/插件/连接器) / 分类 / 作者 (不通过时要 @他) / 适用项目
        "kind": kind, "category": category, "author": author, "project": project,
    }


@router.post("/{code}/unpublish")
async def unpublish_asset(
    code: str,
    confirm_code: str = Form(..., description="必须与资产 code 一致 (防误操作)"),
    comment: str = Form("", description="下架理由 (给管理员看)"),
    user: User = Depends(require_publisher),
) -> dict[str, Any]:
    """**申请下架** —— 提交后等管理员确认, 确认通过资产会被**彻底删除**.

    为什么不是"点了就下架":
      · 下架是**不可逆的终态** —— 确认后资产连文件带索引带 DB 记录一起没
      · 市场是**共享**的 —— 资产下架了, 别人第二天就装不上, 得有人拍板

    所以拆两步: 作者申请 (必须手打 code 确认) → 管理员确认 → 自动删除.

    ⚠️ confirm_code 必须等于 code —— 光靠前端弹窗拦不住, 直接调 API 就绕过了.
    """
    if (confirm_code or "").strip() != code:
        raise HTTPException(
            status_code=400,
            detail=f"确认码不匹配: 请输入资产 code「{code}」以确认下架",
        )
    await _assert_can_modify(code, user)
    async with AsyncSessionLocal() as session:
        a = (
            await session.execute(select(Asset).where(Asset.code == code))
        ).scalar_one_or_none()
        if a is None:
            raise HTTPException(status_code=404, detail=f"资产 {code} 不存在")
        if a.publish_status == "unpublish_pending":
            raise HTTPException(status_code=409, detail="下架申请已提交, 等管理员确认")
        if a.publish_status != "published":
            raise HTTPException(
                status_code=409, detail=f"当前状态是「{a.publish_status}」, 不能申请下架"
            )

    out = await _set_publish_state(
        code=code, publish_status="unpublish_pending", action="unpublish_request",
        comment=comment or "申请下架", user=user, review_note=comment or "",
    )
    # 申请下架 → 通知**审核群** (提醒管理员去确认).
    # ⚠️ 注意跟"彻底下架"的通知分开: 申请阶段资产还在架, 别在市场群说这件事.
    if out.get("changed"):
        await market_notify.notify_asset(
            "unpublish_request", out,
            actor=user.username,
            detail=comment or "有人申请下架, 等管理员确认",
        )
    return {
        "ok": True, "code": code, "publish_status": "unpublish_pending",
        "changed": out.get("changed", False),
    }


@router.post("/{code}/unpublish-review")
async def review_unpublish_asset(
    code: str,
    decision: str = Form(..., description="approve (只有通过这一种)"),
    comment: str = Form("", description="审核备注 (记入审计)"),
    user: User = Depends(require_admin),
) -> dict[str, Any]:
    """管理员审核**下架申请** —— 通过 = 资产被**彻底删除**.

    ⚠️ **没有"驳回"** (2026-10-24): 管理员不点头的话申请就一直挂着,
    作者可以自己撤销 —— 不需要"驳回"这个动作.
    所以这个端点只接受 approve.

    ⚠️ 只有**管理员**能审 —— 通过就等于删了别人的资产.
    被授权的审核人 (marketplace.review.reviewer_usernames) 只能做**上架**审核,
    边界跟之前定的一致: "能审" ≠ "能改别人上传的资产".
    """
    if decision != "approve":
        raise HTTPException(
            status_code=400,
            detail="下架审核只支持 approve (不通过的话不处理即可, 作者可自行撤销申请)",
        )

    async with AsyncSessionLocal() as session:
        a = (
            await session.execute(select(Asset).where(Asset.code == code))
        ).scalar_one_or_none()
        if a is None:
            raise HTTPException(status_code=404, detail=f"资产 {code} 不存在")
        if a.publish_status != "unpublish_pending":
            raise HTTPException(
                status_code=409,
                detail=f"该资产当前状态是「{a.publish_status}」, 没有待审的下架申请",
            )

    if decision != "approve":
        # ⚠️ 下架审核**没有"驳回"这个场景** (2026-10-24):
        #    管理员不点头的话, 申请就一直挂着, 作者可以自己撤销 —— 不需要"驳回"。
        raise HTTPException(
            status_code=400,
            detail="下架审核只支持 approve (不通过的话不处理即可, 作者可自行撤销申请)",
        )

    out = await _hard_delete_asset(
        code=code, user=user,
        comment=comment or "管理员通过下架申请, 资产已删除",
        audit_action="unpublish_approve",
        # ⚠️ 下架通知只在这时候发 —— 资产**彻底下架**了才通知 (@所有人)
        event="unpublish",
    )
    return {
        "ok": True, "code": code, "decision": "approve",
        "deleted": True, "commit_sha": out.commit_sha,
    }


@router.post("/{code}/unpublish-cancel")
async def cancel_unpublish_request(
    code: str,
    comment: str = Form(""),
    user: User = Depends(require_publisher),
) -> dict[str, Any]:
    """作者**撤销**下架申请 —— 资产恢复在架, 不用等管理员驳回."""
    await _assert_can_modify(code, user)
    async with AsyncSessionLocal() as session:
        a = (
            await session.execute(select(Asset).where(Asset.code == code))
        ).scalar_one_or_none()
        if a is None:
            raise HTTPException(status_code=404, detail=f"资产 {code} 不存在")
        if a.publish_status != "unpublish_pending":
            raise HTTPException(
                status_code=409, detail="该资产没有待审的下架申请, 撤销失败"
            )

    out = await _set_publish_state(
        code=code, publish_status="published", action="unpublish_cancel",
        comment=comment or "作者撤销下架申请", user=user, review_note="",
    )
    # ⚠️ 撤销**不通知** —— 资产从头到尾没被移除过 (只是申请被撤回了),
    #    没有"发生了什么"值得往群里说. 审计里留痕就够.
    return {
        "ok": True, "code": code, "publish_status": "published",
        "changed": out.get("changed", False),
    }


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
            await market_notify.notify_asset(
                "publish", out, actor=_user.username,
                detail=comment or "审核通过, 已上架",
            )
        return out

    note = comment or "审核未通过, 请修改后重新提交"
    out = await _set_publish_state(
        code=code, publish_status="rejected", action="reject",
        comment=note, user=_user, review_note=note,
    )
    if out.get("changed"):
        await market_notify.notify_asset(
            "reject", out, actor=_user.username, detail=note,
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
        await market_notify.notify_asset(
            "review", out, actor=_user.username,
            detail=comment or "提交审核",
        )
    return out


@router.post("/{code}/publish")
async def publish_asset(
    code: str,
    comment: str = Form(""),
    user: User = Depends(require_publisher),
) -> dict[str, Any]:
    """重新上架 (已下架的资产恢复在架)."""
    await _assert_can_modify(code, user)
    async with AsyncSessionLocal() as session:
        a = (
            await session.execute(select(Asset).where(Asset.code == code))
        ).scalar_one_or_none()
        if a is None:
            raise HTTPException(status_code=404, detail=f"资产 {code} 不存在")
        if a.publish_status == "unpublish_pending":
            # 有待审的下架申请 —— 走「撤销申请」那条路, 别让两条路打架
            raise HTTPException(
                status_code=409, detail="该资产有待审的下架申请, 请先撤销申请再重新上架"
            )
    out = await _set_publish_state(
        code=code, publish_status="published", action="publish",
        comment=comment, user=user,
    )
    if not out.get("changed"):
        return out
    await market_notify.notify_asset(
        "publish", out, actor=user.username,
        detail=comment or "重新上架",
        # ⚠️ 事件 key 还是 publish (开关映射不变), 只是标题别写成「新资产上架」——
        #    这条是**重新**上架, 不是新资产.
        title_override="🎉 资产重新上架",
    )
    return {"ok": True, "code": code, "publish_status": "published"}


# ---------- 硬删 ----------

async def _hard_delete_asset(
    *,
    code: str,
    user: User,
    comment: str,
    audit_action: str = "delete",
    event: str = "delete",
    notify: bool = True,
) -> AssetDeleteOut:
    """彻底删除一个资产 (GitLab 文件 + 索引 + DB 记录一起没).

    两条路径共用它:
      · 管理员**通过下架申请** (POST /{code}/unpublish-review → approve) → event="unpublish"
      · 管理员**直接删** (DELETE /{code}, 运维口子) → event="delete"
      · 作者删自己**没上架过**的资产 (DELETE /{code}, pending/rejected) → event="delete"

    事件分开是有意的: "走审核下架"和"直接删"在审计里是两回事, 通知也该分得清.
    notify=False 用于"从没公开过"的资产 —— 没必要惊动市场群.

    顺序很关键 (**先推 GitLab, 后动 DB**):
      1. index.json 剔除该资产 (DB 行还在, 用 exclude 参数)
      2. 删掉工作区里的资产目录
      3. commit + push 到 GitLab —— 失败就把工作区从 HEAD 恢复, DB 一个字节都不动
      4. 推送成功 → 删 DB 行, 记审计, 发通知
    反过来做的话, push 失败会导致"DB 没了但 GitLab 还在" → 拉取同步器会把资产复活.
    """
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
        kind, category = a.kind, a.category
        project = a.project or ""

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
        # ⚠️ 记下操作前的 HEAD —— push 失败时靠它把本地那条 commit 撤掉
        prev_sha = git_sync.head_sha()
        try:
            result = await git_sync.sync_paths(
                paths=paths,
                message=f"chore(market): 删除资产 {asset_name} {version}",
                author=_author_of(user),
            )
        except git_sync.SyncError as e:
            # ⚠️ **撤销本地那条 commit** —— 它已经产生了 (commit 成功、push 失败),
            #    而 `_push()` 推的是 `HEAD:<branch>` → **下一次任何 job 的 push 都会
            #    把它一起带走** → 删除在 GitLab 上**悄悄生效了**, 而 DB 里资产行还在
            #    (DB 删在 push 成功之后) → 幽灵资产: 列表里有, 文档 404.
            #
            #    以前这里是 `checkout_from_ref("HEAD", ...)` —— HEAD 已经是那条删除
            #    提交了, "恢复"回去等于恢复到已删除, 形同没回滚.
            rolled = False
            try:
                rolled = git_sync.undo_local_commit(prev_sha, [git_path, INDEX_PATH])
            except Exception as re_:  # noqa: BLE001
                logger.error("delete 回滚失败 code=%s err=%s", code, re_)
            if not rolled:
                logger.error(
                    "delete 推送失败且本地提交没能撤销 —— 仓库状态需要人工检查 code=%s err=%s",
                    code, e,
                )
                raise HTTPException(
                    status_code=502,
                    detail=(
                        f"删除未生效: 推送到 GitLab 失败 ({e}). "
                        "本地提交也没能撤销, 请联系管理员检查仓库状态"
                    ),
                ) from e
            logger.error("delete 推送失败, 本地提交已撤销 code=%s err=%s", code, e)
            raise HTTPException(
                status_code=502,
                detail=f"删除未生效: 推送到 GitLab 失败 ({e}). 本地已回滚, 可稍后重试",
            ) from e

        # 3) 推送成功 → 动 DB
        async with AsyncSessionLocal() as session:
            a = await session.get(Asset, asset_id)
            if a is not None:
                await session.delete(a)
            await _audit(
                session, code=code, action=audit_action, actor=user, asset_id=asset_id,
                comment=comment or "资产已删除",
                detail={"git_path": git_path},
            )
            await session.commit()
        # ⚠️ 用户本机的安装目录不动 —— 后端够不着, 也不该替用户删文件.
        #    (服务端写盘通道已下线)

    if notify:
        await market_notify.notify_asset(
            event,
            {"name": asset_name, "version": version, "code": code,
             "kind": kind, "category": category, "project": project},
            actor=user.username,
            detail=comment or "资产已从市场删除",
        )
    logger.info("delete 资产 code=%s action=%s event=%s", code, audit_action, event)
    return AssetDeleteOut(
        ok=True, code=code,
        commit_sha=result.commit_sha,
    )


@router.delete("/{code}", response_model=AssetDeleteOut)
async def delete_asset(
    code: str,
    comment: str = Query("", description="删除原因 (记入审计)"),
    user: User = Depends(get_current_user),
) -> AssetDeleteOut:
    """彻底删除一个资产 (不只是下架).

    两种人能用:
      · **管理员** —— 任何状态 (运维口子: 有人直接往仓库里塞垃圾资产)
      · **作者本人** —— 但**只限还没上架过的** (待审核 / 被驳回).
        这两种状态的东西从来没对外可见过 (可见性只放行在架的 + 作者自己的),
        所以作者直接删掉是安全的, 不需要走下架审核.
        ⚠️ 以前 pending / rejected 没有出口 —— 作者传错了想撤回、或被驳回后不想留着了,
           都只能干等 (文件还永久躺在 GitLab 里).
        在架的资产**仍然不行**: 那种必须走「申请下架 → 管理员确认」, 有人拍板.

    与「下架申请」的区别:
      申请下架 —— 作者发起, 管理员确认后才真删 (走审核)
      直接删   —— 管理员当场删, 或作者删自己没上架过的 (不走审核)
    """
    async with AsyncSessionLocal() as session:
        a = (
            await session.execute(select(Asset).where(Asset.code == code))
        ).scalar_one_or_none()
        if a is None:
            raise HTTPException(status_code=404, detail=f"资产 {code} 不存在")
        is_admin = market_policy.is_admin(user)
        is_author = market_policy.can_modify(a, user)
        if not is_admin:
            if not is_author:
                raise HTTPException(
                    status_code=403, detail="只有资产作者本人或管理员可以删除"
                )
            # 状态机裁决: 只有 pending / rejected 允许作者直接撤
            try:
                market_state.assert_transition(
                    "discard", a.publish_status or market_state.PUBLISHED,
                    is_author=is_author, is_reviewer=False, is_admin=is_admin,
                )
            except market_state.TransitionError as e:
                raise HTTPException(status_code=409, detail=str(e)) from e
            return await _hard_delete_asset(
                code=code, user=user,
                comment=comment or "作者删除未上架的资产",
                audit_action="discard",
                event="delete",
                notify=False,   # ⚠️ 没过审的东西从没公开过 → 不用惊动市场群
            )
    return await _hard_delete_asset(
        code=code, user=user,
        comment=comment or "管理员删除",
        audit_action="delete",
    )


# ---------- 上传 ----------

def _parse_mcp_form(mcp_config: str, kind: str) -> dict | None:
    """把表单里的 MCP 配置文本解析成对象 (非连接器一律返回 None)."""
    if kind != "mcp":
        if (mcp_config or "").strip():
            raise HTTPException(
                status_code=422,
                detail="只有连接器 (mcp) 才能填 MCP 配置",
            )
        return None
    from app.core.mcp_config import McpConfigError, parse_mcp_config

    try:
        return parse_mcp_config(mcp_config)
    except McpConfigError as e:
        raise HTTPException(status_code=422, detail=f"MCP 配置不合法: {e}") from e


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


def _cleanup_staged_dir(base: str) -> None:
    """落盘失败后的清理: 把资产目录**恢复成 HEAD 里的样子** (本次落的东西全清掉).

    ⚠️ 不能简单 rmtree 整个目录 —— 更新场景下目录里还有**上一个版本**的文件
       (已经被提交到 git 了), 删掉它们等于"下次提交会把旧版本的文件也删了".
       所以: 先 checkout 回 HEAD (恢复旧文件), 再把 HEAD 里没有的残留清掉.
    """
    try:
        git_sync.checkout_from_ref("HEAD", [base])
    except Exception as e:  # noqa: BLE001 — 清理失败不该盖掉原始错误
        logger.warning("清理落盘目录失败 (checkout) base=%s err=%s", base, e)
    try:
        git_sync.clean_path(base)
    except Exception as e:  # noqa: BLE001
        logger.warning("清理落盘目录失败 (clean) base=%s err=%s", base, e)


def _snapshot_asset(a: Asset | None) -> dict:
    """资产行的旧值快照 (补偿时原样还原)."""
    if a is None:
        return {}
    return {
        c.name: getattr(a, c.name)
        for c in a.__table__.columns
        if c.name not in ("id", "created_at")
    }


async def _compensate_staged_asset(
    code: str, base: str, old_snapshot: dict, existed: bool
) -> None:
    """索引写失败后的补偿 —— 把这次操作留下的东西**全部清干净**.

    ⚠️ 以前这里是直接抛 500 (2026-10-25 审计):
       DB 行已提交 (sync_status='staged')、文件在工作区、**但没有 job**
       → 没有任何东西会去提交这些文件 → 工作区永远脏 →
       反向同步的安全闸每轮都跳过 → **整个反向同步永久卡死**, 且无自愈路径.

    补偿三件事:
       ① 工作区: 本次落盘的文件清掉 (恢复成 HEAD 的样子)
       ② index.json: 还原 (原子写保证失败时它没被改坏, 这里是兜底)
       ③ DB 行: 新建 → 删掉; 更新 → 还原成旧值
    """
    _cleanup_staged_dir(base)
    try:
        git_sync.checkout_from_ref("HEAD", [INDEX_PATH])
    except Exception as e:  # noqa: BLE001
        logger.warning("补偿: 还原 index.json 失败 err=%s", e)
    try:
        async with AsyncSessionLocal() as session:
            a = (
                await session.execute(select(Asset).where(Asset.code == code))
            ).scalar_one_or_none()
            if a is not None:
                if existed:
                    for k, v in old_snapshot.items():
                        setattr(a, k, v)
                else:
                    await session.delete(a)
                await session.commit()
    except Exception as e:  # noqa: BLE001
        logger.error("补偿: 还原 DB 行失败 code=%s err=%s", code, e)


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
            project=payload_in.project,
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
            # 连接器专有: MCP 配置 (非 mcp 为 None)
            mcp_config=payload_in.mcp_config,
        )
    except ManifestError as e:
        raise HTTPException(status_code=422, detail=str(e)) from e

    base = manifest["git_path"]
    author = _author_of(user)
    files_dir = git_sync.WORKSPACE / base / "files"
    # 老路径 (改了分类/类型才会跟新路径不同) —— 更新时要连它一起清掉
    old_git_path = ""
    if action == "update":
        async with AsyncSessionLocal() as _s:
            _old = (
                await _s.execute(
                    select(Asset).where(Asset.code == manifest["code"])
                )
            ).scalar_one_or_none()
        if _old is not None and _old.git_path and _old.git_path != base:
            old_git_path = _old.git_path

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
    if action == "create" and existing is None:
        # ⚠️ 除了查 DB, 还要查 **git** (2026-10-25 审计):
        #    本地 DB 只是远端的**镜像**, 而且反向同步器有安全闸 (工作区脏 / 有未推送
        #    commit 时整轮跳过) → DB 完全可能比远端旧.
        #    那种情况下, 同 code 的新上传会**静默覆盖** git 里已有的资产文件,
        #    把别人的资产连同作者一起顶掉 —— 这里直接拒掉, 不给覆盖的机会.
        git_codes = git_sync.index_codes_at_ref("HEAD") | git_sync.index_codes_at_ref(
            f"origin/{git_sync.git_branch()}"
        )
        if manifest["code"] in git_codes:
            raise HTTPException(
                status_code=409,
                detail=(
                    f"资产 {manifest['code']} 在 GitLab 上已经存在 "
                    "(本地索引还没同步到) —— 请换个 code, 或先点「重新同步」"
                ),
            )

    # ---- 1. 落盘 ----
    try:
        if manifest["kind"] == "mcp":
            # ⚠️ 连接器是**配置型**资产: 目录里只有 manifest.json (含 MCP 配置),
            #    没有 files/、没有 README.md、没有 package/ —— 配置就写在 manifest 里.
            #    (老目录里的残留一并清掉, 免得仓库里躺着两份配置)
            shutil.rmtree(files_dir, ignore_errors=True)
            shutil.rmtree(git_sync.WORKSPACE / base / "package", ignore_errors=True)
            git_sync.remove_path(f"{base}/README.md")
            manifest["package_sha256"] = ""
            manifest["package_name"] = ""
            manifest["files"] = []
            manifest["doc_file"] = ""
            git_sync.write_text(
                f"{base}/manifest.json",
                json.dumps(manifest, ensure_ascii=False, indent=2),
            )
        elif package is not None:
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
            # ⚠️ **先清空旧档** (2026-10-25 审计): 归档文件名带版本号
            #    (1.0.0.zip / 1.1.0.zip …), 不清的话每次升版都在仓库里多留一份
            #    完整安装包 —— manifest 只指向最新版, 旧的成纯残留, 仓库体积单调增长.
            shutil.rmtree(pkg_dir, ignore_errors=True)
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
                # ⚠️ 文件已经写进工作区了 —— 不清掉的话会留半截内容,
                #    而 sync_puller 的安全闸会因为"工作区脏"整轮跳过 → 反向同步卡死.
                #    (包上传那条路径有清理, 多文件这条漏了)
                shutil.rmtree(files_dir, ignore_errors=True)
                raise HTTPException(
                    status_code=422,
                    detail="缺少 SKILL.md / README.md",
                )
            manifest["doc_file"] = doc_name

        if manifest["kind"] != "mcp":
            git_sync.write_text(
                f"{base}/manifest.json",
                json.dumps(manifest, ensure_ascii=False, indent=2),
            )
            if manifest.get("description"):
                git_sync.write_text(f"{base}/README.md", manifest["description"])
    except pkg.PackageError as e:
        _cleanup_staged_dir(base)
        raise HTTPException(status_code=422, detail=f"安装包不合规: {e}") from e
    except git_sync.SyncError as e:
        # ⚠️ 落盘中途失败 → 这次写的文件留在工作区 → 工作区脏 →
        #    反向同步的安全闸每轮都跳过 → **整个反向同步永久卡死**.
        #    所以这里必须把本次落的东西**全部清干净** (2026-10-25 审计).
        _cleanup_staged_dir(base)
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
        # ⚠️ 记下**旧值** —— 后面写 index.json 失败时要能把 DB 行原样还原
        #    (更新场景下这一行已经被改成新值了, 不留快照就还原不回去)
        old_snapshot = _snapshot_asset(existing)
        a.name = manifest.get("name") or a.code
        a.icon = manifest.get("icon") or "🧩"
        a.kind = manifest.get("kind") or "skill"
        a.version = manifest.get("version") or "0.1.0"
        a.summary = manifest.get("summary") or ""
        a.description = manifest.get("description") or ""
        a.use_when = manifest.get("use_when") or ""
        a.not_for = manifest.get("not_for") or ""
        a.category = manifest.get("category") or ""
        # 适用项目 (空 = 通用)
        a.project = manifest.get("project") or ""
        # 连接器专有: MCP 配置 (非 mcp 恒为 None)
        a.mcp_config = manifest.get("mcp_config") if (a.kind or "") == "mcp" else None
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
            # ⚠️ 补偿: 索引写失败 → DB 行已提交、文件在工作区、**却没有 job**
            #    → 没人会去提交这些文件 → 工作区永远脏 → 反向同步永久卡死.
            #    这里把本次操作留下的东西全部清干净 (见 _compensate_staged_asset).
            await _compensate_staged_asset(
                manifest["code"], base, old_snapshot, existed=(existing is not None),
            )
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
                # ⚠️ 改了分类 / 类型 → 目录路径变了 → **老目录要清掉**,
                #    否则 GitLab 里留一份残骸副本 (index.json 指向新的, 老的那份还在).
                "old_git_path": old_git_path,
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
    # ⚠️ detail 是**这次操作发生了什么**, 不是资产的简介 ——
    #    把简介塞进来, 群里读起来像重复了一遍卡片副标题, 看不出发生了什么.
    if a.publish_status == "pending":
        await market_notify.notify_asset(
            "review", manifest,
            actor=user.username,
            detail=(
                "提交了新资产, 等管理员审核"
                if action == "create" else "更新了资产, 等管理员审核"
            ),
            author=manifest.get("author", "") or user.username,
        )
    else:
        await market_notify.notify_asset(
            "publish" if action == "create" else "update", manifest,
            actor=user.username,
            # ⚠️ 说明写**动作**, 不写资产简介 (简介在卡片上就有, 通知里再写一遍
            #    看着像重复了一遍, 而且看不出"发生了什么")
            detail="新资产已上架" if action == "create" else "发布了新版本",
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
    project: str = Form("", description="适用项目: 空 = 通用; 6100 = 6100 项目特有"),
    icon: str = Form("🧩"),
    tags: str = Form("[]"),
    keywords: str = Form("[]"),
    featured: bool = Form(False),
    permissions: str = Form("{}"),
    install_steps: str = Form("[]"),
    bindings: str = Form("{}"),
    mcp_config: str = Form("", description="连接器 (mcp) 的 MCP 配置 JSON; 其他类型留空"),
    files: list[UploadFile] | None = File(None),
    package: UploadFile | None = File(None),
    user: User = Depends(require_publisher),
) -> AssetJobOut:
    """上架新资产.

    ⚠️ 两种形态 (2026-10-24):
        技能 / 插件 —— 安装包(压缩) 或 多文件文本
        连接器 (mcp) —— **只要一段 MCP 配置**, 不需要包 (也没有 README)
    """
    cfg = _parse_mcp_form(mcp_config, kind)
    # ⚠️ 命名契约 (前端也管, 这里是**防绕过前端直接调 API**):
    #    包名 / MCP 连接器名 必须与资产 code 一致 —— 否则装出来/抄下来都对不上.
    _assert_naming(code, kind, cfg, package)
    try:
        payload = UploadAssetIn(
            code=code, kind=kind, name=name, summary=summary, version=version,
            description=description, use_when=use_when, not_for=not_for,
            category=category, icon=icon,
            # 适用项目: 不在项目列表里的一律归**通用** (脏值不进 manifest)
            project=await _resolve_project(code, project, action="create"),
            tags=json.loads(tags or "[]"), keywords=json.loads(keywords or "[]"),
            author=user.username, featured=featured,
            permissions=json.loads(permissions or "{}"),
            install_steps=json.loads(install_steps or "[]"),
            bindings=json.loads(bindings or "{}"),
            mcp_config=cfg,
        )
    except json.JSONDecodeError as e:
        raise HTTPException(status_code=422, detail=f"JSON 字段解析失败: {e}") from e
    except ValidationError as e:
        # ⚠️ 表单字段不合法 (超长/为空) 是**用户填错**, 不是服务器故障 ——
        #    不接住的话 pydantic 的异常会变成 500, 用户只看到"服务器错误".
        first = e.errors()[0] if e.errors() else {}
        field = ".".join(str(x) for x in first.get("loc", ()) if x != "body")
        raise HTTPException(
            status_code=422,
            detail=f"字段不合法{f' ({field})' if field else ''}: {first.get('msg', '取值不合法')}",
        ) from e

    if kind == "mcp":
        # 连接器没有安装包 —— 有包反而说明搞混了形态
        if package is not None or files:
            raise HTTPException(
                status_code=422,
                detail="连接器不需要安装包, 只需填 MCP 配置",
            )
        return await _stage_asset(
            action="create", payload_in=payload, files={},
            package=None, package_name="", user=user,
        )

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
        if not file_map:
            raise HTTPException(
                status_code=422,
                detail="请上传安装包 (zip / tar.gz)",
            )

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
    project: str = Form("", description="适用项目: 空 = 通用; 6100 = 6100 项目特有"),
    icon: str = Form("🧩"),
    tags: str = Form("[]"),
    keywords: str = Form("[]"),
    featured: bool = Form(False),
    permissions: str = Form("{}"),
    install_steps: str = Form("[]"),
    bindings: str = Form("{}"),
    mcp_config: str = Form("", description="连接器 (mcp) 的 MCP 配置 JSON; 其他类型留空"),
    files: list[UploadFile] | None = File(None),
    package: UploadFile | None = File(None),
    user: User = Depends(require_publisher),
) -> AssetJobOut:
    """更新一个已存在的资产 (发新版本).

    ⚠️ 只能更新**自己上传的**资产 (管理员例外) —— 否则任何白名单用户都能
    改别人的资产, 覆盖掉别人精心写的内容.

    ⚠️ 连接器 (mcp) 的"新版本" = **只改那段 MCP 配置**, 不涉及包的上传.
    """
    await _assert_can_modify(code, user)

    cfg = _parse_mcp_form(mcp_config, kind)
    # ⚠️ 命名契约 (见 upload 端点的说明)
    _assert_naming(code, kind, cfg, package)

    # 发布新版本 (覆盖同名文件, git 历史保留旧版)
    try:
        payload = UploadAssetIn(
            code=code, kind=kind, name=name, summary=summary, version=version,
            description=description, use_when=use_when, not_for=not_for,
            category=category, icon=icon,
            # 适用项目: 更新时保留老归属 (项目从设置里删掉也不该丢)
            project=await _resolve_project(code, project, action="update"),
            tags=json.loads(tags or "[]"), keywords=json.loads(keywords or "[]"),
            author=user.username, featured=featured,
            permissions=json.loads(permissions or "{}"),
            install_steps=json.loads(install_steps or "[]"),
            bindings=json.loads(bindings or "{}"),
            mcp_config=cfg,
        )
    except json.JSONDecodeError as e:
        raise HTTPException(status_code=422, detail=f"JSON 字段解析失败: {e}") from e
    except ValidationError as e:
        # ⚠️ 表单字段不合法 (超长/为空) 是**用户填错**, 不是服务器故障 ——
        #    不接住的话 pydantic 的异常会变成 500, 用户只看到"服务器错误".
        first = e.errors()[0] if e.errors() else {}
        field = ".".join(str(x) for x in first.get("loc", ()) if x != "body")
        raise HTTPException(
            status_code=422,
            detail=f"字段不合法{f' ({field})' if field else ''}: {first.get('msg', '取值不合法')}",
        ) from e

    if kind == "mcp":
        if package is not None or files:
            raise HTTPException(
                status_code=422,
                detail="连接器不需要安装包, 只需更新 MCP 配置",
            )
        return await _stage_asset(
            action="update", payload_in=payload, files={},
            package=None, package_name="", user=user,
        )

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
        if not file_map:
            raise HTTPException(status_code=422, detail="请上传安装包 (zip / tar.gz)")

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
