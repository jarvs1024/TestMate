"""软件库 API —— /api/v1/software/*.

⚠️ 与「插件·技能·连接」(/api/v1/assets) 的分工:
    资产市场存的是**装进 Agent 的文本包**, 真身在 GitLab; 软件库存的是
    **给人用的内部软件** (任意格式二进制), 真身在**服务端磁盘**.
    两者在存储 / 权限 / 审核三个维度都不同, 所以各有各的命名空间.

核心设计 (2026-10-27):
    · **单次流式上传** —— 两步:
        ① POST /software            (JSON 元数据) → 建条目, 版本行 awaiting_file
        ② PUT  /software/{code}/file (原始字节流) → 边收边写盘, 状态转 published
      ⚠️ 不走 multipart: starlette 的 multipart 会把文件先 spool 到系统临时目录
        (1MB 后落盘) —— 5G 的包会在临时目录里**再存一份**, 磁盘翻倍,
        容器模式下还会撑爆可写层.
    · **下载走短时票据** —— 5G 的包不能走 blob (浏览器会爆内存):
        POST /software/{code}/download-ticket → 10 分钟有效的票
        GET  /software/dl?t=...              → FileResponse 流式回传
      ⚠️ 长期 token 落 URL 会进 nginx access_log 和浏览器历史, 所以必须用短时票.
    · **上架即上架** —— 没有审核队列, 有发布权的人传完就能下, 动作全进审计流水.
"""
from __future__ import annotations

import logging
import os
from datetime import datetime, timedelta
from pathlib import Path
from urllib.parse import quote, unquote

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import FileResponse
from sqlalchemy import cast, func, or_, select, update, Text

from app.api.auth import get_current_user, get_optional_user
from app.core import market_policy, software_store
from app.core.asset_locks import code_lock
from app.core.dingtalk import notify_market
from app.core.identity import author_forms
from app.core.security import create_download_ticket as sign_download_ticket
from app.core.security import decode_download_ticket
from app.db.session import AsyncSessionLocal
from app.models.asset import AssetAudit
from app.models.software import SoftwareItem, SoftwareVersion
from app.models.user import User
from app.schemas.software import (
    SoftwareCategoryListOut,
    SoftwareCategoryOut,
    SoftwareConfigOut,
    SoftwareCreateIn,
    SoftwareDeleteOut,
    SoftwareDetailOut,
    SoftwareDownloadTicketOut,
    SoftwareListOut,
    SoftwareOut,
    SoftwareUpdateIn,
    SoftwareUploadOut,
    SoftwareVersionCreateIn,
    SoftwareVersionOut,
    SoftwareVersionUpdateIn,
)

logger = logging.getLogger(__name__)
router = APIRouter()

#: 默认单个软件包上限 (MB) —— 与设置项 software.max_size_mb 的默认值一致
DEFAULT_MAX_SIZE_MB = 5120

#: 版本行卡在 "uploading" 超过这么久 → 认为是上次中断留下的, 允许重新传
STALE_UPLOAD_MINUTES = 30

#: **保留**的 code —— 这些词被路由占用了 (``GET /software/config`` 等),
#: 软件标识撞上它们的话, 详情页会被静态路由抢走.
RESERVED_CODES = frozenset({"dl", "config", "categories", "path-check"})


# ---------- 设置项读取 ----------


async def _setting(key: str, default: str = "") -> str:
    try:
        from app.core.settings_store import get

        return (await get(key, default)) or default
    except Exception:  # noqa: BLE001
        return default


async def _setting_int(key: str, default: int) -> int:
    raw = await _setting(key, str(default))
    try:
        return int(str(raw).strip())
    except (TypeError, ValueError):
        return default


async def _setting_bool(key: str, default: bool) -> bool:
    from app.core.settings_store import to_bool

    return to_bool(await _setting(key, "true" if default else "false"), default)


async def _root() -> Path:
    """当前生效的存储根目录 (设置项 → 环境变量 → 仓库内默认)."""
    return software_store.resolve_root(await _setting("software.storage_path", ""))


async def _roots() -> list[Path]:
    """所有**可能**存放软件包的根目录 (按优先级).

    ⚠️ 为什么不止当前根 (2026-10-28 修的真 bug):
       落库的 ``file_path`` 是**相对**路径, 基准是"当前根". 管理员改了
       ``software.storage_path`` 之后, "当前根 + 相对路径" 就找不到老文件了 ——
       文件还在旧根, 但下载 404、删除删不掉 (删不掉的孤儿).

       候选根 = 当前根 + 历史根 + 环境变量根 + 默认根 (见
       :func:`software_store.candidate_roots`). 环境变量根/默认根天然覆盖了
       "改设置项之前" 的存放位置, 所以绝大多数情况不用额外维护.
    """
    configured = await _setting("software.storage_path", "")
    history_raw = await _setting("software.storage_path_history", "")
    history = [h.strip() for h in (history_raw or "").split(",") if h.strip()]
    return software_store.candidate_roots(
        software_store.resolve_root(configured), history
    )


def _storage_source(configured: str) -> str:
    """当前根目录是**哪来的** —— setting / env / default.

    ⚠️ "我改了设置项怎么没生效" 是最常见的问法: 实际多半是环境变量把它盖住了.
       光看路径猜不出来, 所以后端直接告诉前端.
    """
    if (configured or "").strip():
        return "setting"
    if (os.environ.get("SOFTWARE_STORAGE_PATH") or "").strip():
        return "env"
    return "default"


async def _max_bytes() -> int:
    mb = await _setting_int("software.max_size_mb", DEFAULT_MAX_SIZE_MB)
    return max(1, mb) * 1024 * 1024


async def _keep_versions() -> int:
    return max(0, await _setting_int("software.keep_versions", 10))


async def require_publisher(user: User = Depends(get_current_user)) -> User:
    """谁能往软件库传东西 —— **复用市场的发布权判定**, 不另造一套.

    ⚠️ 为什么不新设一个设置项: 同一批人 (测试工程 + 白名单), 少一套配置少一处
       "两边不一致" 的坑 —— 用户在市场上能发, 在软件库里发不了, 只会觉得是 bug.
    """
    if not await market_policy.can_publish(user):
        role = market_policy.role_of(user)
        if role == "anonymous":
            raise HTTPException(status_code=401, detail="未登录")
        roles = ", ".join(sorted(await market_policy.publisher_roles())) or "(空)"
        raise HTTPException(
            status_code=403,
            detail=(
                f"当前角色「{role}」没有发布权限 —— "
                f"可发布角色: {roles}; 或让管理员把你的用户名加进发布者白名单"
            ),
        )
    return user


def _is_admin(user: User) -> bool:
    return market_policy.is_admin(user)


def _is_author(item: SoftwareItem, user: User) -> bool:
    """是不是这个条目的作者 (短名/全邮箱都认 —— 见 identity.name_matches)."""
    from app.core.identity import name_matches

    return name_matches({(item.author or "").strip().lower()}, user.username)


def _assert_can_modify(item: SoftwareItem, user: User) -> None:
    """改/删别人条目 → 403.

    ⚠️ 这是**越权链路的闸**: 只校验"是不是发布者"是不够的 —— 那意味着
       任何有发布权的人都能改别人的软件说明/删掉别人的包.
    """
    if _is_admin(user):
        return
    if _is_author(item, user):
        return
    raise HTTPException(status_code=403, detail="只有上传者本人或管理员能操作这个软件")


async def _assert_icon_free(
    session,
    icon: str,
    *,
    exclude_code: str = "",
) -> None:
    """图标不能跟**别的软件**重复 —— 两张卡长得一样, 用户分不清谁是谁.

    ⚠️ 2026-10-28 加: 图标重复会让能力墙上一片"红工具箱", 看着像同一个软件.
       前端会把已占用的图标标成"已用"并禁掉, 这里再兜一道 ——
       前端只拿到当前列表页里的图标, 后端看的是全量.

    ⚠️⚠️ **必须用二进制 collation 比较** (2026-10-28 踩过的坑):
       software_items.icon 的 collation 是 ``utf8mb4_unicode_ci``, 而 MySQL 的
       UCA 4.0.0 **不认识 supplementary plane 的字符** —— 它给**所有 emoji**
       套了同一个"通用权重". 结果就是 🚀 和 💿 在这一列上**互相相等**!
       写成 ``icon == '🚀'`` 的话, 任何 emoji 都会跟任何 emoji 撞车
       (第一个条目 🧰, 第二个条目 📦 → 409 "图标重复").
       所以这里用 ``collate('utf8mb4_bin')`` 按字节比 —— 一个字节都不差才算同一个图标.

    ``exclude_code`` = 改自己的条目时排除自己 (不改图标当然不该跟自己撞).
    """
    icon = (icon or "").strip()
    if not icon:
        return
    stmt = select(SoftwareItem).where(
        # 按字节比 —— utf8mb4_bin 是 MySQL 的二进制 collation
        SoftwareItem.icon.collate("utf8mb4_bin") == icon,
        SoftwareItem.deleted_at.is_(None),
    )
    if exclude_code:
        stmt = stmt.where(SoftwareItem.code != exclude_code)
    hit = (await session.execute(stmt)).scalars().first()
    if hit is not None:
        raise HTTPException(
            status_code=409,
            detail=f"图标 {icon} 已经被「{hit.name}」用了, 换一个不一样的",
        )


async def _audit(
    session,
    *,
    code: str,
    action: str,
    actor: User | None = None,
    comment: str = "",
    detail: dict | None = None,
) -> None:
    """写审计流水 —— 复用 asset_audits 表, 命名空间 ``sw:<code>``.

    ⚠️ 不建新表: 这张表本来就是**通用流水** (已经用 code='user:<名>' 记账号操作),
       软件库的动作记进去, 设置页「操作记录」就能一起看.
    """
    session.add(
        AssetAudit(
            asset_id=None,
            code=f"sw:{code}",
            action=action,
            actor_id=actor.id if actor else None,
            actor_name=actor.username if actor else "",
            comment=comment,
            detail=detail or {},
        )
    )


def _author_cond(user: User):
    """"作者是当前用户" 这个 SQL 条件.

    ⚠️ 用户名为空时 ``in_([])`` 会变成恒假 —— 那样"自己的条目"就一条都看不见,
       所以空用户名直接给一个恒假条件, 不参与 or_ 的"看得见"分支.
    """
    forms = author_forms(user.username)
    if not forms:
        return SoftwareItem.id < 0
    return SoftwareItem.author.in_(forms)


async def _get_item(code: str, session=None) -> SoftwareItem:
    """按 code 取条目 —— 不存在或已软删 → 404."""
    if session is not None:
        item = (
            await session.execute(select(SoftwareItem).where(SoftwareItem.code == code))
        ).scalar_one_or_none()
    else:
        async with AsyncSessionLocal() as s:
            item = (
                await s.execute(select(SoftwareItem).where(SoftwareItem.code == code))
            ).scalar_one_or_none()
    if item is None or item.deleted_at is not None:
        raise HTTPException(status_code=404, detail=f"软件 {code} 不存在")
    return item


def _to_out(item: SoftwareItem, *, can_edit: bool = False, download_version: str = "") -> SoftwareOut:
    out = SoftwareOut.model_validate(item)
    out.can_edit = can_edit
    # 当前可下载的版本 (最新的 ready) —— 前端据此决定要不要显示下载按钮
    out.download_version = download_version
    return out


# ---------- 读 ----------


@router.get("", response_model=SoftwareListOut)
async def list_software(
    q: str = Query("", description="搜索名称/简介/标签/关键词"),
    category: str = Query("", description="分类 (留空 = 全部)"),
    platform: str = Query("", description="适用平台 (留空 = 全部)"),
    sort: str = Query("new", description="排序: hot(下载多) / new(最新) / name(名称)"),
    status: str = Query("", description="状态筛选: ''(默认) / mine(我的) / all(全部, 仅管理员)"),
    limit: int = Query(60, ge=1, le=500),
    offset: int = Query(0, ge=0),
    user: User = Depends(get_current_user),
) -> SoftwareListOut:
    """软件列表.

    可见性:
      · 已上架 (published) —— 所有人都能看见
      · 自己的条目 (含 awaiting_file) —— 只有作者能看见 (不然传一半的东西会漏给别人)
      · 管理员 —— 能看全部 (含 hidden)
    """
    async with AsyncSessionLocal() as session:
        conds = [SoftwareItem.deleted_at.is_(None)]

        if status == "mine":
            conds.append(_author_cond(user))
        elif not _is_admin(user):
            # ⚠️ 管理员默认看**全部** (含别人传了一半的) —— 管理员要能管这些条目.
            #    普通用户只看: 已上架的 + 自己的 (传了一半的别漏给别人看).
            conds.append(
                or_(
                    SoftwareItem.publish_status == "published",
                    _author_cond(user),
                )
            )

        if category:
            conds.append(SoftwareItem.category == category)
        if platform:
            conds.append(SoftwareItem.platform == platform)

        kw = (q or "").strip()
        if kw:
            like = f"%{kw}%"
            conds.append(
                or_(
                    SoftwareItem.name.like(like),
                    SoftwareItem.summary.like(like),
                    SoftwareItem.description.like(like),
                    # ⚠️ tags/keywords 是 JSON 列 —— 直接 LIKE 会让 MySQL 报错,
                    #    得先 CAST 成文本 (与 marketplace.py 里的做法一致)
                    cast(SoftwareItem.tags, Text).like(like),
                    cast(SoftwareItem.keywords, Text).like(like),
                )
            )

        total = (
            await session.execute(select(func.count()).select_from(SoftwareItem).where(*conds))
        ).scalar_one()

        if sort == "hot":
            order = (SoftwareItem.download_count.desc(), SoftwareItem.updated_at.desc())
        elif sort == "name":
            order = (SoftwareItem.name.asc(),)
        else:
            order = (SoftwareItem.created_at.desc(),)

        rows = (
            await session.execute(
                select(SoftwareItem).where(*conds).order_by(*order).limit(limit).offset(offset)
            )
        ).scalars().all()

        # 每个条目"当前可下载的版本" —— 一次查询搞定 (避免 N+1)
        ready_map = await _latest_ready_versions(session, [r.id for r in rows])

        items = [
            _to_out(
                r,
                can_edit=_is_admin(user) or _is_author(r, user),
                download_version=ready_map.get(r.id, ""),
            )
            for r in rows
        ]
    return SoftwareListOut(items=items, total=total)


async def _latest_ready_versions(session, item_ids: list[int]) -> dict[int, str]:
    """条目 id → 当前可下载的版本号.

    ⚠️ 2026-10-28 改: **优先取「推荐版本」**, 没有推荐才取时间上最新的.
       之前是"永远取最新" —— 但一个软件挂两个版本、两个都有用时
       (如「Windows版」和「LTS版」), "最新"不等于"该下的那个".
       上传者可以手动把某个版本标成推荐 (is_default).

    ⚠️ 一次查询批量取 —— 逐条查就是 N+1 (列表 60 条 = 60 次往返).
    """
    if not item_ids:
        return {}
    rows = (
        await session.execute(
            select(SoftwareVersion.item_id, SoftwareVersion.version)
            .where(
                SoftwareVersion.item_id.in_(item_ids),
                SoftwareVersion.status == "ready",
            )
            .order_by(
                # 推荐版本排最前 (同一条目只应有一个 is_default, 后端保证)
                SoftwareVersion.is_default.desc(),
                SoftwareVersion.created_at.desc(),
                SoftwareVersion.id.desc(),
            )
        )
    ).all()
    out: dict[int, str] = {}
    for item_id, version in rows:
        if item_id not in out:
            out[item_id] = version
    return out


@router.get("/categories", response_model=SoftwareCategoryListOut)
async def list_categories(
    user: User = Depends(get_current_user),
) -> SoftwareCategoryListOut:
    """分类清单 —— **后端下发**, 前端动态渲染 chip.

    ⚠️ 不硬编码分类清单: 用户自建的分类没有 chip 就筛不出来.
    """
    async with AsyncSessionLocal() as session:
        conds = [SoftwareItem.deleted_at.is_(None), SoftwareItem.publish_status == "published"]
        rows = (
            await session.execute(
                select(SoftwareItem.category, func.count())
                .where(*conds, SoftwareItem.category != "")
                .group_by(SoftwareItem.category)
                .order_by(func.count().desc())
            )
        ).all()
    items = [SoftwareCategoryOut(name=name, total=int(total)) for name, total in rows]
    return SoftwareCategoryListOut(items=items, total=len(items))


@router.get("/config", response_model=SoftwareConfigOut)
async def get_config(user: User = Depends(get_current_user)) -> SoftwareConfigOut:
    """前端要知道的运行时配置.

    ⚠️ 存储路径**只有管理员能看到** —— 那是服务端目录结构, 普通用户拿到没意义.
    """
    is_admin = _is_admin(user)
    configured = await _setting("software.storage_path", "")
    root = software_store.resolve_root(configured)
    out = SoftwareConfigOut(
        max_bytes=await _max_bytes(),
        can_publish=await market_policy.can_publish(user),
        is_admin=is_admin,
        public_download=await _setting_bool("software.public_download", False),
        storage_source=_storage_source(configured),
    )
    if is_admin:
        info = software_store.usage_info(root)
        out.storage_root = str(root)
        out.path_ok = bool(info["exists"] and info["writable"])
        out.used_bytes = software_store.used_bytes(root)
        out.free_bytes = int(info["free_bytes"])
    # 已被占用的图标 (全量, 不分页) —— 前端把用过的图标禁掉
    async with AsyncSessionLocal() as session:
        rows = (
            await session.execute(
                select(SoftwareItem).where(
                    SoftwareItem.deleted_at.is_(None),
                    SoftwareItem.icon != "",
                )
            )
        ).scalars().all()
    out.used_icons = {r.icon: r.name for r in rows}
    return out


@router.get("/path-check")
async def check_path(user: User = Depends(require_publisher)) -> dict:
    """管理员的「检查路径」—— **每个候选根**下各缺哪些文件 + 哪些是孤儿目录.

    ⚠️ 换存储根目录 = 文件不会自动搬过去 —— 但**也不会丢**:
       文件还在旧根里, 只是"当前根 + 相对路径"找不到它.
       所以这里要分清两种情况:
         · **missing**  —— 当前根里没有, 但在**别的根**里找到了
           (文件没丢, 只是不在当前根 —— 下载/删除会自动去别的根找)
         · **lost**     —— 所有候选根里都找不到 (真丢了, 或者被手工删了)
       以前只报一种, 用户看着像"软件凭空消失", 实际只是换了根目录.
    """
    if not _is_admin(user):
        raise HTTPException(status_code=403, detail="admin only")
    root = await _root()
    roots = await _roots()
    info = software_store.usage_info(root)
    missing: list[dict] = []      # 当前根没有, 但别的根有
    lost: list[dict] = []         # 所有根都没有
    async with AsyncSessionLocal() as session:
        rows = (
            await session.execute(
                select(SoftwareVersion).where(SoftwareVersion.status == "ready")
            )
        ).scalars().all()
        code_rows = (
            await session.execute(select(SoftwareItem.code))
        ).scalars().all()
        known_codes = {(c or "").strip() for c in code_rows}
    for v in rows:
        if software_store.file_exists(root, v.file_path):
            continue
        found = software_store.locate_under(roots, v.file_path)
        entry = {
            "code": v.file_path.split("/")[0],
            "version": v.version,
            "file_name": v.file_name,
        }
        if found is not None:
            missing.append({**entry, "found_in": str(found.parent.parent.parent)})
        else:
            lost.append(entry)
    # ⚠️ 孤儿目录: 根目录下有目录, 但 DB 里**没有**对应条目 (下架残留 / 手工塞的)
    orphan_dirs: list[dict] = []
    for r in roots:
        if not r.is_dir():
            continue
        try:
            children = list(r.iterdir())
        except OSError:
            continue
        for d in children:
            if not d.is_dir() or d.name.startswith("."):
                continue
            if d.name in known_codes:
                continue
            orphan_dirs.append({"name": d.name, "root": str(r)})
    return {
        "root": str(root),
        "exists": info["exists"],
        "writable": info["writable"],
        "used_bytes": software_store.used_bytes(root),
        "free_bytes": int(info["free_bytes"]),
        # 所有候选根 (管理员能看到"文件其实在哪")
        "roots": [str(r) for r in roots],
        "missing": missing[:200],
        "missing_count": len(missing),
        "lost": lost[:200],
        "lost_count": len(lost),
        "orphan_dirs": orphan_dirs[:200],
        "orphan_count": len(orphan_dirs),
    }


@router.get("/dl")
async def download_by_ticket(
    t: str = Query("", description="短时下载票"),
    v: str = Query("", description="版本号 (与票里的必须一致)"),
) -> FileResponse:
    """凭短时票下载软件包 —— **流式回传, 不进内存**.

    ⚠️ 为什么不用 ``<a href>`` 直连一个带 token 的 URL:
       长期 token 落 URL 会进 nginx access_log 和浏览器历史 —— 谁都能捡走.
       所以这里用 10 分钟有效、绑定具体版本的短时票.
    """
    payload = decode_download_ticket(t)
    if not payload:
        raise HTTPException(status_code=401, detail="下载票据无效或已过期, 请重新点下载")

    uid = int(payload.get("uid", 0) or 0)
    code = str(payload.get("code") or "")
    version = str(payload.get("ver") or "")
    if not code or not version:
        raise HTTPException(status_code=401, detail="下载票据内容不完整, 请重新点下载")
    if v and v != version:
        raise HTTPException(status_code=403, detail="下载票据与版本不匹配")

    # 票据签发之后账号被停用/删除 → 一律拒绝 (票只有 10 分钟, 但这 10 分钟也得算数)
    if uid:
        async with AsyncSessionLocal() as session:
            user = await session.get(User, uid)
            if user is None:
                raise HTTPException(status_code=401, detail="账号不存在, 请重新登录")
            if not user.is_active:
                raise HTTPException(status_code=401, detail="账号已停用")
    else:
        # 匿名票 —— 只在管理员明确开了公开下载时有效
        if not await _setting_bool("software.public_download", False):
            raise HTTPException(status_code=401, detail="下载需要登录")

    async with AsyncSessionLocal() as session:
        item = (
            await session.execute(select(SoftwareItem).where(SoftwareItem.code == code))
        ).scalar_one_or_none()
        if item is None or item.deleted_at is not None:
            raise HTTPException(status_code=404, detail=f"软件 {code} 不存在")
        ver = (
            await session.execute(
                select(SoftwareVersion).where(
                    SoftwareVersion.item_id == item.id,
                    SoftwareVersion.version == version,
                )
            )
        ).scalar_one_or_none()
        if ver is None or ver.status != "ready":
            raise HTTPException(status_code=404, detail="这个版本还没有可下载的文件")

        # ⚠️ 2026-10-28: 在**所有候选根**里找文件 ——
        #   管理员改了 storage_path 之后, 文件还在旧根, 只查当前根会 404.
        roots = await _roots()
        path = software_store.locate_under(roots, ver.file_path)
        if path is None:
            raise HTTPException(status_code=404, detail="文件不在服务器上了, 请联系管理员")

        # 下载次数 +1 —— 原子自增 (先读后写会丢计数)
        await session.execute(
            update(SoftwareItem).where(SoftwareItem.id == item.id)
            .values(download_count=SoftwareItem.download_count + 1)
        )
        await session.execute(
            update(SoftwareVersion).where(SoftwareVersion.id == ver.id)
            .values(download_count=SoftwareVersion.download_count + 1)
        )
        await session.commit()

        file_name = ver.file_name or f"{code}-{version}.bin"
        sha = ver.sha256

    return FileResponse(
        path,
        filename=file_name,
        media_type="application/octet-stream",
        headers={
            "X-Content-Sha256": sha,
            # ⚠️ 任意格式的二进制 —— 绝不能让浏览器"猜"类型然后执行
            "X-Content-Type-Options": "nosniff",
        },
    )


@router.get("/{code}", response_model=SoftwareDetailOut)
async def get_software(code: str, user: User = Depends(get_current_user)) -> SoftwareDetailOut:
    """详情: 条目 + 版本历史 (每版带更新说明/大小/sha256/下载次数)."""
    async with AsyncSessionLocal() as session:
        item = (
            await session.execute(select(SoftwareItem).where(SoftwareItem.code == code))
        ).scalar_one_or_none()
        if item is None or item.deleted_at is not None:
            raise HTTPException(status_code=404, detail=f"软件 {code} 不存在")

        can_edit = _is_admin(user) or _is_author(item, user)
        if item.publish_status != "published" and not can_edit:
            raise HTTPException(status_code=404, detail=f"软件 {code} 不存在")

        versions = (
            await session.execute(
                select(SoftwareVersion)
                .where(SoftwareVersion.item_id == item.id)
                .order_by(SoftwareVersion.created_at.desc(), SoftwareVersion.id.desc())
            )
        ).scalars().all()
        ready_map = await _latest_ready_versions(session, [item.id])

    out = SoftwareDetailOut.model_validate(item)
    out.can_edit = can_edit
    out.download_version = ready_map.get(item.id, "")
    out.versions = [SoftwareVersionOut.model_validate(v) for v in versions]
    return out


# ---------- 写 ----------


async def _unique_code(session, base: str) -> str:
    """给 base 找一个**没被占用**的 code —— 撞名就自动加序号 (base2 / base3 …).

    ⚠️ 2026-10-28: 以前撞名直接 409 "标识已经存在了", 让用户自己想一个.
       现在 code 是从**文件名**派生的, 同名文件本来就常见 (同一套工具的不同构建),
       所以自动加序号更符合直觉 —— 用户什么都不用管.
    """
    code = base
    n = 1
    while n < 1000:
        exists = (
            await session.execute(select(SoftwareItem).where(SoftwareItem.code == code))
        ).scalar_one_or_none()
        if exists is None:
            return code
        n += 1
        suffix = str(n)
        code = base[: 64 - len(suffix)] + suffix
    return code


@router.post("", status_code=201)
async def create_software(
    payload: SoftwareCreateIn, user: User = Depends(require_publisher)
) -> dict:
    """建条目 (第 ① 步) —— 只填元数据, 文件随后用 PUT /{code}/file 传.

    返回 ``upload_path`` —— 前端拿着它直接传字节流, 不用自己拼 URL.

    ⚠️ 2026-10-28: **code 不再让用户填** —— 由软件包文件名自动派生, 撞名自动加序号.
       文件名同时要过**英文数字+标准字符**的校验 (不合规当场 422).
    """
    # ---- 文件名: 有就**校验**, 不合规当场拒 (别等传完文件才发现) ----
    # ⚠️ 空文件名是**允许**的 (老调用方只传元数据) —— 这时用兜底名
    #    ``<code>-<version>.bin``. 校验只针对"用户真的传了文件名"的情况.
    file_name = (payload.file_name or "").strip()
    if file_name:
        try:
            file_name = software_store.validate_file_name(file_name)
        except software_store.InvalidPath as e:
            raise HTTPException(status_code=422, detail=str(e)) from e

    # ---- code: 用户没填就从文件名派生 ----
    raw_code = (payload.code or "").strip()
    if not raw_code:
        if not file_name:
            raise HTTPException(
                status_code=422,
                detail="需要提供软件标识, 或者先选好软件包 (用文件名自动生成)",
            )
        raw_code = software_store.code_from_file_name(file_name)
    try:
        code = software_store.validate_code(raw_code)
    except software_store.InvalidPath as e:
        raise HTTPException(status_code=422, detail=str(e)) from e
    if code in RESERVED_CODES:
        raise HTTPException(
            status_code=422,
            detail=f"软件标识不能叫 {code} —— 这个词被系统里的固定路径占用了",
        )

    version = (payload.version or "1.0.0").strip()[:32]
    if "/" in version or "\\" in version or version in (".", ".."):
        raise HTTPException(status_code=422, detail="版本号不合法")
    file_name = file_name or f"{code}-{version}.bin"

    async with AsyncSessionLocal() as session:
        # ⚠️ 撞名不报错, **自动加序号** (2026-10-28) ——
        #   code 是从文件名派生的, 同名文件很常见 (比如同一套工具的不同构建).
        #   以前让用户自己填, 现在自动变成 xxx2 / xxx3, 省得用户瞎猜.
        code = await _unique_code(session, code)

        # ⚠️ 图标不能跟别的软件重复 (2026-10-28)
        await _assert_icon_free(session, payload.icon)

        item = SoftwareItem(
            code=code,
            name=payload.name.strip(),
            icon=payload.icon or "🧰",
            version=version,
            summary=payload.summary.strip(),
            description=payload.description,
            features=[f.strip() for f in payload.features if f and f.strip()],
            use_when=payload.use_when,
            not_for=payload.not_for,
            install_steps=payload.install_steps,
            caveats=payload.caveats,
            platform=payload.platform.strip(),
            category=payload.category.strip(),
            tags=[t.strip() for t in payload.tags if t and t.strip()],
            keywords=[k.strip() for k in payload.keywords if k and k.strip()],
            author=user.username,
            publish_status="awaiting_file",
        )
        session.add(item)
        await session.flush()

        ver = SoftwareVersion(
            item_id=item.id,
            version=version,
            release_notes=payload.release_notes,
            # 变体标签 (选填) —— 如「Windows版」
            variant=payload.variant.strip()[:32],
            # 第一个版本默认就是推荐下载的那个
            is_default=True,
            # ⚠️ 用**已校验过**的文件名 —— 不再 sanitize (sanitize 是静默改名,
            #    用户不知道自己传的文件叫什么了). 不合规的早就 422 掉了.
            file_name=file_name,
            declared_size=int(payload.file_size or 0),
            status="awaiting_file",
            author=user.username,
        )
        session.add(ver)
        await session.flush()

        await _audit(
            session,
            code=code,
            action="create",
            actor=user,
            comment=f"新建软件 {payload.name}",
            detail={"version": version, "file_name": ver.file_name},
        )
        await session.commit()

    return {
        "ok": True,
        "code": code,
        "version": version,
        "upload_path": f"/api/v1/software/{quote(code)}/file",
    }


@router.post("/{code}/versions", status_code=201)
async def create_version(
    code: str, payload: SoftwareVersionCreateIn, user: User = Depends(require_publisher)
) -> dict:
    """发新版本 (第 ① 步) —— 建一行版本记录, 文件随后用 PUT /{code}/file 传.

    ⚠️ 当前版本指针会切到新版本 —— 但**文件没传完之前它是不能下的**:
       详情页按版本状态区分, 只有 ready 的版本能下载.

    ⚠️ 2026-10-30 加 `replace_version` —— **覆盖**已有版本 (不再只能新增):
       · 不填 = 照旧新增一条 (版本 N → N+1);
       · 填了 = 把那一行**原地改成**本次的版本 (版本号/说明/文件全换), 版本总条数不变.
       ⚠️ 覆盖**不删行**, 只重置字段 + 删旧文件目录 —— 删行的话,
          "文件没传成功" 就变成"版本凭空消失", 用户根本看不出来少了什么.
    """
    # ⚠️ 2026-10-30: 同一 code 的写操作**串行** ——
    #    覆盖版本要删文件 + 改版本行, 两个并发上传会互相把对方的版本行改掉/删掉.
    #    跟 DELETE /{code}/versions/{version} 用同一把锁 (asset_locks.code_lock).
    async with code_lock(code):
        return await _create_version_locked(code, payload, user)


async def _create_version_locked(
    code: str, payload: SoftwareVersionCreateIn, user: User
) -> dict:
    async with AsyncSessionLocal() as session:
        item = (
            await session.execute(select(SoftwareItem).where(SoftwareItem.code == code))
        ).scalar_one_or_none()
        if item is None or item.deleted_at is not None:
            raise HTTPException(status_code=404, detail=f"软件 {code} 不存在")
        _assert_can_modify(item, user)

        version = (payload.version or "").strip()[:32]
        if not version or "/" in version or "\\" in version or version in (".", ".."):
            raise HTTPException(status_code=422, detail="版本号不合法")

        # ---- 覆盖模式: 先定位**要被改掉**的那一行 ----
        replace_version = (payload.replace_version or "").strip()[:32]
        target: SoftwareVersion | None = None
        if replace_version:
            target = (
                await session.execute(
                    select(SoftwareVersion).where(
                        SoftwareVersion.item_id == item.id,
                        SoftwareVersion.version == replace_version,
                    )
                )
            ).scalar_one_or_none()
            if target is None:
                raise HTTPException(status_code=404, detail=f"版本 {replace_version} 不存在")

        dup = (
            await session.execute(
                select(SoftwareVersion).where(
                    SoftwareVersion.item_id == item.id,
                    SoftwareVersion.version == version,
                )
            )
        ).scalar_one_or_none()
        # ⚠️ 覆盖模式下, **正在改的那一行**不算撞号 —— 同名覆盖 (1.0.0 → 1.0.0) 是合法的.
        #    但撞的是**别的**行 → 还是 409 (否则会出现两个同名版本).
        if dup is not None and (target is None or dup.id != target.id):
            raise HTTPException(status_code=409, detail=f"版本 {version} 已经存在了")

        # ⚠️ 发新版本的文件名同样要过规范校验 (2026-10-28) —— 跟新建一个口径
        file_name = (payload.file_name or "").strip()
        if file_name:
            try:
                file_name = software_store.validate_file_name(file_name)
            except software_store.InvalidPath as e:
                raise HTTPException(status_code=422, detail=str(e)) from e
        else:
            file_name = f"{code}-{version}.bin"

        if target is not None:
            # ===== 覆盖: **复用目标版本行** =====
            # ⚠️ 不删行 (删了行 + 文件没传成功 = 版本凭空消失) —— 只重置字段,
            #    让它回到 "awaiting_file", 等 PUT /{code}/file 把新文件传上来.
            old_version = target.version
            target.version = version
            target.release_notes = payload.release_notes
            target.variant = payload.variant.strip()[:32]
            target.is_default = bool(payload.is_default)
            target.file_name = file_name
            target.declared_size = int(payload.file_size or 0)
            target.status = "awaiting_file"
            target.last_error = ""
            # ⚠️ 旧文件的路径/校验和一起清掉 —— 不然行上留着旧包的路径,
            #    而旧目录已经被删了, 一看就是"文件在, 就是下不动".
            target.file_path = ""
            target.sha256 = ""
            target.file_size = 0
            target.author = user.username
            target.created_at = datetime.utcnow()
            target.updated_at = datetime.utcnow()
            ver = target
            await session.flush()
            # ⚠️ 旧文件目录要删 —— 否则:
            #    ① 版本号改了 → <root>/<code>/<旧版本号>/ 变成没人引用的孤儿目录;
            #    ② 版本号没改、文件名也变了 → 目录里躺着两个包, 下到的可能是旧的.
            await _purge_version_files(code, old_version)
        else:
            ver = SoftwareVersion(
                item_id=item.id,
                version=version,
                release_notes=payload.release_notes,
                # 变体标签 (选填) —— 如「LTS版」; 不填就留空, 版本号本身够用
                variant=payload.variant.strip()[:32],
                is_default=bool(payload.is_default),
                file_name=file_name,
                declared_size=int(payload.file_size or 0),
                status="awaiting_file",
                author=user.username,
            )
            session.add(ver)
            # ⚠️ 必须**先 flush** —— ver.id 要拿到才能在 WHERE 里排除自己.
            #    (flush 前 ver.id 是 None, 拼出来的 `id != NULL` 在 SQL 里恒不成立,
            #    而 SQLAlchemy 的 synchronize_session='evaluate' 又会在 Python 侧
            #    按同样的条件改内存对象 —— 两边不一致, 推荐标记会错乱.)
            await session.flush()
        # ⚠️ 一个条目**最多一个**推荐版本 (2026-10-28) ——
        #    新版本设成推荐时, 把旧的推荐标记摘掉, 否则两个都是 is_default,
        #    "该下哪个" 就有歧义了.
        #    ⚠️ 覆盖模式下也要跑 —— 否则覆盖完可能两个都是推荐.
        if payload.is_default:
            await session.execute(
                update(SoftwareVersion)
                .where(
                    SoftwareVersion.item_id == item.id,
                    SoftwareVersion.id != ver.id,
                    SoftwareVersion.is_default.is_(True),
                )
                .values(is_default=False)
                # ⚠️ 不让 ORM 自动同步内存状态 —— 上面那句 UPDATE 的影响范围
                #    只有"同条目的别的版本", 手工改比 ORM 猜得准.
                .execution_options(synchronize_session=False)
            )
        # 指针切到新版本 (并发保护: 指针没被别人改过才切)
        item.version = version

        await _audit(
            session,
            code=code,
            action="replace_version" if target is not None else "new_version",
            actor=user,
            comment=(
                f"覆盖版本 {replace_version} 为 {version}"
                if target is not None
                else f"发布新版本 {version}"
            ),
            detail={
                "version": version,
                "replaced_version": replace_version or None,
                "release_notes": payload.release_notes,
            },
        )
        await session.commit()

    return {
        "ok": True,
        "code": code,
        "version": version,
        "upload_path": f"/api/v1/software/{quote(code)}/file",
    }


async def _purge_version_files(code: str, version: str) -> int:
    """删掉某个版本的**旧文件目录** (覆盖版本时用).

    ⚠️ 只删 ``<root>/<code>/<version>/`` 这一层, **绝不删父目录** ——
       父目录 ``<root>/<code>/`` 里还有别的版本.
    """
    if not version:
        return 0
    roots = await _roots()
    deleted = software_store.remove_version_dir_anywhere(roots, code, version)
    for r in roots:
        software_store.remove_item_dir_if_empty(r, code)
    return deleted


async def _notify_software_published(
    code: str, version: str, was_published: bool, user: User
) -> None:
    """软件包传完 → 通知钉钉 (2026-10-30 第十一轮).

    ⚠️ **上架**和**发布新版本**共用一个开关 (`dingtalk.notify_on_software`) ——
       用户原话「上架和发布新版本共有一个配置」. 开关映射在 dingtalk._SWITCH_KEY 里.

    ⚠️ 通知正文:
        · 类型 → 「软件包」 (跟插件/技能/连接器**区分开**, 见 dingtalk._KIND_LABEL);
        · 上架 → 带上**简介** (这软件是干嘛的);
        · 发新版本 → 带上**更新说明** (这次改了啥) —— 软件库有这个字段;
        · 链接 → 自动指向 /software (dingtalk._DEFAULT_LINK_PATH).
    """
    try:
        async with AsyncSessionLocal() as session:
            item = (
                await session.execute(select(SoftwareItem).where(SoftwareItem.code == code))
            ).scalar_one_or_none()
            if item is None:
                return
            ver = (
                await session.execute(
                    select(SoftwareVersion).where(
                        SoftwareVersion.item_id == item.id,
                        SoftwareVersion.version == version,
                    )
                )
            ).scalar_one_or_none()
            name = item.name
            summary = item.summary or ""
            category = item.category or ""
            author = item.author or ""
            release_notes = (ver.release_notes if ver is not None else "") or ""
        event = "software_update" if was_published else "software_publish"
        await notify_market(
            event,
            name=name,
            version=version,
            actor=user.username,
            kind="software",
            category=category,
            author=author,
            code=code,
            summary=summary,
            release_notes=release_notes,
        )
    except Exception as e:  # noqa: BLE001 — 通知失败**不能**影响上传结果
        logger.warning("软件库钉钉通知失败 code=%s err=%s", code, e)


@router.patch("/{code}/versions/{version}", response_model=SoftwareVersionOut)
async def update_version(
    code: str,
    version: str,
    payload: SoftwareVersionUpdateIn,
    user: User = Depends(require_publisher),
) -> SoftwareVersionOut:
    """改某个版本的元信息 —— **变体标签** / **推荐标记** (不动文件).

    ⚠️ 2026-10-28 加: 一个软件挂两个版本、两个都有用时, 光有版本号分不清谁是谁.
       变体标签 (如「Windows版」「LTS版」) 就是那个"小名";
       推荐标记决定头部那个「⬇ 下载」按钮下的是哪个.

    ⚠️ 改推荐标记时, **同一个条目的其他版本会被摘掉推荐** ——
       "推荐哪个" 必须唯一, 否则前端不知道该显示哪个.
    """
    async with AsyncSessionLocal() as session:
        item = (
            await session.execute(select(SoftwareItem).where(SoftwareItem.code == code))
        ).scalar_one_or_none()
        if item is None or item.deleted_at is not None:
            raise HTTPException(status_code=404, detail=f"软件 {code} 不存在")
        _assert_can_modify(item, user)

        ver = (
            await session.execute(
                select(SoftwareVersion).where(
                    SoftwareVersion.item_id == item.id,
                    SoftwareVersion.version == version,
                )
            )
        ).scalar_one_or_none()
        if ver is None:
            raise HTTPException(status_code=404, detail=f"版本 {version} 不存在")

        data = payload.model_dump(exclude_unset=True)
        if "variant" in data and data["variant"] is not None:
            ver.variant = data["variant"].strip()[:32]
        if data.get("is_default") is True:
            # 摘掉别的版本的推荐标记 —— 推荐必须唯一
            await session.execute(
                update(SoftwareVersion)
                .where(
                    SoftwareVersion.item_id == item.id,
                    SoftwareVersion.id != ver.id,
                    SoftwareVersion.is_default.is_(True),
                )
                .values(is_default=False)
            )
            ver.is_default = True
        elif data.get("is_default") is False:
            # ⚠️ 不允许把最后一个 ready 版本取消推荐 ——
            #    否则条目就没有"该下哪个"了 (头部按钮会空).
            others = (
                await session.execute(
                    select(func.count())
                    .select_from(SoftwareVersion)
                    .where(
                        SoftwareVersion.item_id == item.id,
                        SoftwareVersion.id != ver.id,
                        SoftwareVersion.status == "ready",
                    )
                )
            ).scalar_one()
            if others == 0:
                raise HTTPException(
                    status_code=409,
                    detail="这个软件只有这一个能下载的版本, 不能取消推荐",
                )
            ver.is_default = False

        await _audit(
            session,
            code=code,
            action="update_version",
            actor=user,
            comment=f"修改版本 {version} 的信息",
            detail={"version": version, **data},
        )
        await session.commit()
        await session.refresh(ver)

    return SoftwareVersionOut.model_validate(ver)


@router.delete("/{code}/versions/{version}", response_model=SoftwareDeleteOut)
async def delete_version(
    code: str, version: str, user: User = Depends(require_publisher)
) -> SoftwareDeleteOut:
    """**下架单个版本** —— 只删这一个版本的文件, 其他版本不受影响.

    ⚠️ 2026-10-28 加: 一个软件挂两个版本、两个都有用时, 传错的那版要能单独撤掉,
       不能为了删一个版本把整个软件连别的版本一起下架.

    ⚠️ 删的是**最后一个**能下载的版本 → 整个条目一起下架 (条目不能空着上架).

    ⚠️ 2026-10-28 修: 删文件要在**所有候选根**里删 (见 :func:`_roots`),
       而且版本删光后要把**空壳目录** ``<root>/<code>/`` 一并删掉 ——
       以前只删了 ``<root>/<code>/<version>/``, 上面那层空目录留着,
       用户看着像"没删干净" (这正是用户报的: 目录还在).

    ⚠️ 2026-10-30: 加**同一把 code 锁** —— 下架版本跟"覆盖版本"(POST /versions)
       都会改版本行 + 删文件, 两个并发操作会互相把对方的版本行搞没.
    """
    async with code_lock(code):
        return await _delete_version_locked(code, version, user)


async def _delete_version_locked(code: str, version: str, user: User) -> SoftwareDeleteOut:
    roots = await _roots()
    async with AsyncSessionLocal() as session:
        item = (
            await session.execute(select(SoftwareItem).where(SoftwareItem.code == code))
        ).scalar_one_or_none()
        if item is None or item.deleted_at is not None:
            raise HTTPException(status_code=404, detail=f"软件 {code} 不存在")
        _assert_can_modify(item, user)

        ver = (
            await session.execute(
                select(SoftwareVersion).where(
                    SoftwareVersion.item_id == item.id,
                    SoftwareVersion.version == version,
                )
            )
        ).scalar_one_or_none()
        if ver is None:
            raise HTTPException(status_code=404, detail=f"版本 {version} 不存在")

        # 这个条目还剩几个能下载的版本?
        remaining = (
            await session.execute(
                select(func.count())
                .select_from(SoftwareVersion)
                .where(
                    SoftwareVersion.item_id == item.id,
                    SoftwareVersion.id != ver.id,
                    SoftwareVersion.status == "ready",
                )
            )
        ).scalar_one()

        await session.delete(ver)
        if remaining == 0:
            # 没有可下载的版本了 → 条目不能空着上架, 一起下架
            item.publish_status = "hidden"
            item.deleted_at = datetime.utcnow()

        await _audit(
            session,
            code=code,
            action="delete_version",
            actor=user,
            comment=f"下架版本 {version}",
            detail={"version": version, "item_unpublished": remaining == 0},
        )
        await session.commit()

    # ⚠️ 在所有候选根里删 —— 换过存储根目录时, 老文件在旧根, 只删当前根删不掉
    deleted = software_store.remove_version_dir_anywhere(roots, code, version)
    # ⚠️ 版本删光后, 条目目录会剩个空壳 (``<root>/<code>/``) —— 顺手删掉,
    #    不然用户看着像"东西还在" (2026-10-28 用户报的坑)
    for r in roots:
        software_store.remove_item_dir_if_empty(r, code)
    return SoftwareDeleteOut(
        ok=True,
        code=code,
        deleted_files=max(1, deleted),
        # ⚠️ 条目是不是被连带下架了 —— 前端要靠这个决定"是刷新详情还是关抽屉"
        item_unpublished=remaining == 0,
        remaining_versions=remaining,
    )


@router.put("/{code}/file")
async def upload_file(
    code: str, request: Request, user: User = Depends(require_publisher)
) -> SoftwareUploadOut:
    """传软件包 (第 ② 步) —— **原始字节流**, 边收边写盘.

    请求:
        PUT /api/v1/software/{code}/file
        Content-Type: application/octet-stream
        X-File-Name: <URL 编码的原始文件名>
        X-File-Size: <声明的字节数 (可选)>
        Body: 文件字节

    ⚠️ 为什么要**原始流**而不是 multipart:
       starlette 1.10 的 multipart 会把文件字段先 spool 到系统临时目录 (1MB 后落盘) ——
       5G 的包会在临时目录**再存一份**, 磁盘翻倍, 容器模式下还撑可写层.
    """
    async with AsyncSessionLocal() as session:
        item = (
            await session.execute(select(SoftwareItem).where(SoftwareItem.code == code))
        ).scalar_one_or_none()
        if item is None or item.deleted_at is not None:
            raise HTTPException(status_code=404, detail=f"软件 {code} 不存在")
        _assert_can_modify(item, user)

        ver = (
            await session.execute(
                select(SoftwareVersion).where(
                    SoftwareVersion.item_id == item.id,
                    SoftwareVersion.version == item.version,
                )
            )
        ).scalar_one_or_none()
        if ver is None:
            raise HTTPException(status_code=404, detail="这个软件还没有版本记录")
        if ver.status == "ready":
            raise HTTPException(
                status_code=409,
                detail=f"版本 {ver.version} 已经传过了, 想换文件请发一个新版本",
            )

        # ---- 抢占这一行 (乐观锁): 防两个人同时传同一个版本 ----
        stale_before = datetime.utcnow() - timedelta(minutes=STALE_UPLOAD_MINUTES)
        claimed = await session.execute(
            update(SoftwareVersion)
            .where(
                SoftwareVersion.id == ver.id,
                or_(
                    SoftwareVersion.status.in_(("awaiting_file", "failed")),
                    (SoftwareVersion.status == "uploading")
                    & (SoftwareVersion.updated_at < stale_before),
                ),
            )
            .values(status="uploading", last_error="", updated_at=datetime.utcnow())
        )
        if claimed.rowcount == 0:
            await session.rollback()
            raise HTTPException(
                status_code=409, detail="这个版本已经有人在上传了, 请刷新看看"
            )
        await session.commit()
        ver_id = ver.id
        version = ver.version
        declared = int(ver.declared_size or 0)
        file_name = ver.file_name or f"{code}-{version}.bin"

    # ---- 大小上限: 头里声明的就先拦一道 (不收 body) ----
    max_bytes = await _max_bytes()
    header_size = request.headers.get("content-length")
    if header_size:
        try:
            declared_len = int(header_size)
        except ValueError:
            declared_len = 0
        if declared_len > max_bytes:
            raise HTTPException(
                status_code=413,
                detail=f"文件太大 ({declared_len / 1024 / 1024:.1f} MB), "
                f"上限是 {max_bytes / 1024 / 1024:.0f} MB",
            )

    # 头里的文件大小优先 (前端知道真实大小) —— 跟版本行里声明的不一致时以头为准
    header_file_size = request.headers.get("x-file-size")
    if header_file_size:
        try:
            declared = int(header_file_size)
        except ValueError:
            declared = declared

    raw_name = request.headers.get("x-file-name") or ""
    if raw_name:
        # ⚠️ 2026-10-28: 这里也**校验**而不是静默改名 ——
        #   落库的文件名会变成磁盘目录名和下载文件名, 不合规就该当场拒,
        #   而不是悄悄换成 "xxx.bin" (用户下回来发现名字变了都不知道).
        try:
            file_name = software_store.validate_file_name(unquote(raw_name))
        except software_store.InvalidPath as e:
            await _mark_failed(ver_id, str(e))
            raise HTTPException(status_code=422, detail=str(e)) from e

    root = await _root()
    try:
        saved = await software_store.save_stream(
            request.stream(),
            root=root,
            code=code,
            version=version,
            file_name=file_name,
            max_bytes=max_bytes,
            declared_size=declared,
        )
    except software_store.UploadTooLarge as e:
        await _mark_failed(ver_id, f"文件超过上限 ({e.size / 1024 / 1024:.1f} MB)")
        raise HTTPException(
            status_code=413,
            detail=f"文件太大, 上限是 {max_bytes / 1024 / 1024:.0f} MB",
        ) from e
    except software_store.SizeMismatch as e:
        await _mark_failed(ver_id, "文件大小与声明的不一致, 可能是传输中断")
        raise HTTPException(
            status_code=409,
            detail="文件大小与声明的不一致 —— 传输可能中断了, 请重传",
        ) from e
    except software_store.InvalidPath as e:
        await _mark_failed(ver_id, str(e))
        raise HTTPException(status_code=400, detail=str(e)) from e
    except software_store.StorageFull as e:
        await _mark_failed(ver_id, str(e))
        raise HTTPException(status_code=500, detail=str(e)) from e

    # ---- 落盘成功 → 版本 ready + 条目上架 ----
    async with AsyncSessionLocal() as session:
        await session.execute(
            update(SoftwareVersion)
            .where(SoftwareVersion.id == ver_id)
            .values(
                status="ready",
                file_name=file_name,
                file_path=saved["rel_path"],
                file_size=saved["size"],
                sha256=saved["sha256"],
                declared_size=saved["size"],
                last_error="",
            )
        )
        item = (
            await session.execute(select(SoftwareItem).where(SoftwareItem.code == code))
        ).scalar_one_or_none()
        # ⚠️ 2026-10-30 (第十一轮): 通知要分清是「**新软件上架**」还是「**发了新版本**」——
        #    判据: 上传这个包之前, 条目**有没有已经上架过**.
        #    · publish_status == "awaiting_file" → 头一回传包 → 首次上架;
        #    · 已经是 "published"                    → 发新版本 / 覆盖已有版本.
        #    ⚠️ 用 publish_status 而不是"数 ready 版本" ——
        #       覆盖**唯一一个**版本时, 那一行会先变 awaiting_file, 再变回 ready,
        #       数版本会误判成"首次上架".
        was_published = bool(item and item.publish_status == "published")
        if item is not None:
            item.publish_status = "published"
            item.version = version
        await _audit(
            session,
            code=code,
            action="upload",
            actor=user,
            comment=f"上传文件 {file_name}",
            detail={
                "version": version,
                "size": saved["size"],
                "sha256": saved["sha256"],
            },
        )
        await session.commit()

    await _prune_versions_for(code)

    # ---- 钉钉通知 (2026-10-30 第十一轮) ----
    # ⚠️ 通知放在**文件传完之后** —— 上架是两步 (建条目 → 传包),
    #    只建了条目还没传包的东西别人下不了, 那时候通知等于"上架了个寂寞".
    await _notify_software_published(code, version, was_published, user)

    return SoftwareUploadOut(
        ok=True,
        code=code,
        version=version,
        size=saved["size"],
        sha256=saved["sha256"],
    )


async def _mark_failed(ver_id: int, reason: str) -> None:
    """版本行标成 failed + 记原因 —— 用户能在界面上看到"上次为什么没传上去"."""
    try:
        async with AsyncSessionLocal() as session:
            await session.execute(
                update(SoftwareVersion)
                .where(SoftwareVersion.id == ver_id)
                .values(status="failed", last_error=reason[:500])
            )
            await session.commit()
    except Exception:  # noqa: BLE001
        logger.exception("标记版本失败状态时出错: version_id=%s", ver_id)


async def _prune_versions_for(code: str) -> None:
    """按 ``software.keep_versions`` 清理老版本 (行 + 磁盘文件).

    ⚠️ 保留策略是"保留最近 N 个 ready 版本" —— 正在上传中的版本不参与清理.
    ⚠️ **推荐版本额外豁免** (2026-10-28) —— 上传者特意把某个版本标成推荐,
       正是因为那个版本还在用 (比如给老环境兜底). 悄悄把它清掉, 用户的"该下哪个"
       就悬空了.

    ⚠️ 豁免是**额外加回**而不是"排除在计数之外" ——
       否则 keep=2 就会变成"保留 2 个非推荐的 + 1 个推荐的", 名义上的 N 变了.
    """
    keep = await _keep_versions()
    if keep <= 0:
        return
    roots = await _roots()
    async with AsyncSessionLocal() as session:
        item = (
            await session.execute(select(SoftwareItem).where(SoftwareItem.code == code))
        ).scalar_one_or_none()
        if item is None:
            return
        rows = (
            await session.execute(
                select(SoftwareVersion)
                .where(
                    SoftwareVersion.item_id == item.id,
                    SoftwareVersion.status == "ready",
                )
                .order_by(SoftwareVersion.created_at.desc(), SoftwareVersion.id.desc())
            )
        ).scalars().all()
        # 最近 keep 个 —— 这批之外的都是"老版本"
        stale = rows[keep:]
        # 但推荐版本**永远不删** —— 从待删名单里摘出去
        stale = [v for v in stale if not v.is_default]
        for v in stale:
            await session.delete(v)
        await session.commit()
    # ⚠️ 所有候选根都删 (2026-10-28) —— 换过存储根目录时, 老文件在旧根
    for v in stale:
        software_store.remove_version_dir_anywhere(roots, code, v.version)
    # 版本删光 → 条目目录空壳也清掉
    for r in roots:
        software_store.remove_item_dir_if_empty(r, code)


@router.put("/{code}", response_model=SoftwareOut)
async def update_software(
    code: str, payload: SoftwareUpdateIn, user: User = Depends(require_publisher)
) -> SoftwareOut:
    """改元信息 (不动文件)."""
    async with AsyncSessionLocal() as session:
        item = (
            await session.execute(select(SoftwareItem).where(SoftwareItem.code == code))
        ).scalar_one_or_none()
        if item is None or item.deleted_at is not None:
            raise HTTPException(status_code=404, detail=f"软件 {code} 不存在")
        _assert_can_modify(item, user)

        data = payload.model_dump(exclude_unset=True)
        if "features" in data and data["features"] is not None:
            data["features"] = [f.strip() for f in data["features"] if f and f.strip()]
        # ⚠️ 改图标也要查重 (2026-10-28) —— 排除自己
        if data.get("icon"):
            await _assert_icon_free(session, data["icon"], exclude_code=code)
        for k, v in data.items():
            if v is None:
                continue
            setattr(item, k, v)

        await _audit(
            session,
            code=code,
            action="update",
            actor=user,
            comment="修改软件信息",
            detail={"fields": sorted(data.keys())},
        )
        await session.commit()
        await session.refresh(item)

        ready_map = await _latest_ready_versions(session, [item.id])
        return _to_out(
            item,
            can_edit=True,
            download_version=ready_map.get(item.id, ""),
        )


@router.post("/{code}/download-ticket", response_model=SoftwareDownloadTicketOut)
async def create_download_ticket(
    code: str, version: str = Query("", description="要下载的版本 (留空 = 当前可下载版本)"),
    user: User = Depends(get_optional_user),
) -> SoftwareDownloadTicketOut:
    """签发短时下载票 —— 前端拿到 url 后交给浏览器原生下载器.

    ⚠️ 匿名也能要票, 但只�� ``software.public_download`` 开着才行.
    """
    is_anon = getattr(user, "id", 0) == 0
    if is_anon and not await _setting_bool("software.public_download", False):
        raise HTTPException(status_code=401, detail="下载需要登录")

    async with AsyncSessionLocal() as session:
        item = (
            await session.execute(select(SoftwareItem).where(SoftwareItem.code == code))
        ).scalar_one_or_none()
        if item is None or item.deleted_at is not None:
            raise HTTPException(status_code=404, detail=f"软件 {code} 不存在")
        if item.publish_status != "published" and not (not is_anon and (_is_admin(user) or _is_author(item, user))):
            raise HTTPException(status_code=404, detail=f"软件 {code} 不存在")

        target = version
        if not target:
            ready_map = await _latest_ready_versions(session, [item.id])
            target = ready_map.get(item.id, "")
        if not target:
            raise HTTPException(status_code=404, detail="这个软件还没有可下载的版本")

        ver = (
            await session.execute(
                select(SoftwareVersion).where(
                    SoftwareVersion.item_id == item.id,
                    SoftwareVersion.version == target,
                )
            )
        ).scalar_one_or_none()
        if ver is None or ver.status != "ready":
            raise HTTPException(status_code=404, detail="这个版本还没有可下载的文件")

    uid = 0 if is_anon else int(user.id)
    # ⚠️ 用 sign_download_ticket (别名) —— 本模块里的路由函数也叫 create_download_ticket,
    #    直接同名会把 security 里那个签发函数**遮蔽**掉 (调用时当成路由函数, 参数不匹配).
    ticket, ttl = sign_download_ticket(user_id=uid, code=code, version=target)
    url = f"/api/v1/software/dl?t={quote(ticket)}&v={quote(target)}"
    return SoftwareDownloadTicketOut(url=url, expires_in=ttl)


@router.delete("/{code}", response_model=SoftwareDeleteOut)
async def delete_software(
    code: str, user: User = Depends(require_publisher)
) -> SoftwareDeleteOut:
    """软删条目 —— 文件**留在磁盘上** (跟市场"下架申请 → 管理员确认"一个口径).

    ⚠️ 磁盘不释放是**故意的**: 删错了还能找回来. 管理员可以在详情页做
       「彻底清理」把文件和记录一起删掉.
    """
    async with AsyncSessionLocal() as session:
        item = (
            await session.execute(select(SoftwareItem).where(SoftwareItem.code == code))
        ).scalar_one_or_none()
        if item is None or item.deleted_at is not None:
            raise HTTPException(status_code=404, detail=f"软件 {code} 不存在")
        _assert_can_modify(item, user)

        item.publish_status = "hidden"
        item.deleted_at = datetime.utcnow()
        await _audit(
            session,
            code=code,
            action="delete",
            actor=user,
            comment="删除软件 (软删, 文件保留)",
            detail={},
        )
        await session.commit()
    return SoftwareDeleteOut(ok=True, code=code, deleted_files=0)


@router.delete("/{code}/purge", response_model=SoftwareDeleteOut)
async def purge_software(
    code: str, user: User = Depends(get_current_user)
) -> SoftwareDeleteOut:
    """**下架** —— 删条目行 + 磁盘目录 (记录与文件一起没了).

    ⚠️ 2026-10-28 改: 以前只有**管理员**能彻底清理, 现在
       **上传者本人也能下架自己的软件, 不用管理员审批** ——
       谁传的谁负责, 不想留在平台上了就自己撤下.
       管理员照旧能下架/更新**任何人**的软件.

    ⚠️ 不可恢复 —— 文件本体也一起删. 前端确认框里写清楚了.

    ⚠️ 2026-10-28 修: 删目录要在**所有候选根**里删 ——
       管理员改过存储根目录时, 文件在旧根, 只删当前根 → 文件删不掉, 变成孤儿.
    """
    roots = await _roots()
    async with AsyncSessionLocal() as session:
        item = (
            await session.execute(select(SoftwareItem).where(SoftwareItem.code == code))
        ).scalar_one_or_none()
        if item is None:
            raise HTTPException(status_code=404, detail=f"软件 {code} 不存在")
        # 上传者本人 或 管理员
        _assert_can_modify(item, user)
        versions = (
            await session.execute(
                select(SoftwareVersion).where(SoftwareVersion.item_id == item.id)
            )
        ).scalars().all()
        n = len(versions)
        for v in versions:
            await session.delete(v)
        await session.delete(item)
        await _audit(
            session,
            code=code,
            action="purge",
            actor=user,
            comment="下架软件 (记录与文件一起删除)",
            detail={"versions": n},
        )
        await session.commit()
    # ⚠️ 所有候选根都删 —— 换过存储根目录时, 老文件在旧根 (2026-10-28)
    software_store.remove_item_dir_anywhere(roots, code)
    return SoftwareDeleteOut(ok=True, code=code, deleted_files=n)
