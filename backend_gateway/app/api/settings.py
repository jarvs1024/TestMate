"""/api/v1/settings — DB-backed 配置读写 + 测试连接."""
from __future__ import annotations
import logging
import os
import re
from urllib.parse import parse_qs, urlencode, urlunparse, urlparse
from typing import Any
import httpx

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy import select

from app.api.auth import get_current_user
from app.core.settings_store import SETTING_SCHEMA, get, get_all, to_bool
from app.db.session import AsyncSessionLocal
from app.models.system_setting import SystemSetting
from app.models.user import User
from app.schemas.system_setting import (
    SettingGroupOut, SettingOut, SettingUpdateIn, SettingTestOut,
)

logger = logging.getLogger(__name__)
router = APIRouter()


# ===== 分组显示 =====
CATEGORY_LABELS: dict[str, str] = {
    "agents":     "🗂️ 能力墙",
    "knowledge":       "📚 知识库 / RAGFlow",
    "notification": "🔔 通知 / 钉钉",
    "general":    "⚙️ 通用",
    "search":     "🔎 知识检索",
    "chat":       "💬 知识对话",
    "code-review": "🧪 代码检视 (pr-agent)",
    "data-source": "📡 数据源",
    "marketplace": "🏪 插件·技能·连接",
    "software": "🧰 软件库",
}


def _mask(v: Any, is_secret: bool) -> Any:
    if not is_secret:
        return v
    if not v:
        return ""
    s = str(v)
    if len(s) <= 8:
        return "••••"
    return s[:4] + "•" * max(4, len(s) - 8) + s[-4:]


def _is_default(value: Any, default: Any, value_type: str) -> bool:
    """当前值是不是就是默认值 (决定 UI 上的「已定制」标记)."""
    if value_type == "bool":
        return to_bool(value) == to_bool(default)
    return value == default


# ⚠️ **非管理员看不到的条目** —— 里面是"拿到就能直接用"的东西:
#   · 钉钉 webhook 的 URL 里就带着机器人的 access_token → 拿到就能绕过本系统
#     直接往公司市场群/审核群发消息 (实测: 以前普通用户读 schema 能拿到完整 URL)
#   · api_key / api_token / 加签密钥 = 凭据本身
#   · publisher_ids / publisher_usernames / reviewer_usernames = 权限白名单
#     (谁能上架/谁能审核 —— 这是管理员的配置, 普通用户该问管理员, 不该自己看)
#   · marketplace.git.remote = SSH 地址 + 仓库路径 (拿到就能知道资产仓库在哪,
#     配合 git.branch 就能拼出完整的目标); publisher_roles = 谁能发布的策略
#
# ⚠️ 为什么是**整条不返回**而不是打个码: 掩码后的字符串照样进了 JS,
#    而且「已设置 / 未设置」本身就是信息.
#
# ⚠️ **不要只靠这个正则** —— 正则漏项的代价是"凭据/内网地址直接泄露给普通用户"
#    (2026-10-26 实测: git.remote / git.branch / publisher_roles 三项就漏在这).
#    新的敏感项请在 settings_store.SETTING_SCHEMA 里显式标 ``"admin_only": True``,
#    正则只作为兜底.
_ADMIN_ONLY_SETTING_RE = re.compile(
    r"(webhook|secret|token|api_key|password|publisher_ids|publisher_usernames|reviewer_usernames)",
    re.IGNORECASE,
)


def _is_admin_only(schema: dict) -> bool:
    """这条设置是不是"只给管理员看"."""
    return bool(schema.get("admin_only")) or bool(_ADMIN_ONLY_SETTING_RE.search(schema["key"]))


@router.get("/schema")
async def get_schema(user: User = Depends(get_current_user)) -> dict:
    """返回所有 setting 的 schema + 当前 DB 值 (secret 掩码).

    ⚠️ 非管理员**拿不到凭据类条目** (见 _ADMIN_ONLY_SETTING_RE) ——
       打码不够, 钉钉 webhook 这种"URL 里带 token"的必须整条不给.
    """
    is_admin = user.role.value == "admin"
    values = await get_all()
    by_cat: dict[str, list[dict]] = {}
    for s in SETTING_SCHEMA:
        if not is_admin and _is_admin_only(s):
            continue
        raw = values.get(s["key"], s["default"])
        if s["value_type"] == "bool":
            raw = to_bool(raw, to_bool(s["default"]))
        item = {
            "key": s["key"],
            "category": s["category"],
            "value": _mask(raw, s["is_secret"]),
            "value_type": s["value_type"],
            "description": s["description"],
            "is_secret": s["is_secret"],
            # ⚠️ default 也**掩码** —— secret 项的默认值可能本身就是一个凭据
            #    (比如 .env 里写死的 api_key). 掩码跟 value 用同一套规则.
            "default": _mask(s["default"], s["is_secret"]),
            # "已定制" = 当前值跟默认值不一样 (bool 要按语义比, 不能拿 False == "false")
            "is_default": _is_default(raw, s["default"], s["value_type"]),
        }
        by_cat.setdefault(s["category"], []).append(item)
    groups = [
        SettingGroupOut(category=cat, label=CATEGORY_LABELS.get(cat, cat), items=items).model_dump()
        for cat, items in by_cat.items()
    ]
    return {"groups": groups, "total": sum(len(g["items"]) for g in groups)}


@router.put("/{key}", response_model=SettingOut)
async def update_setting(
    key: str, payload: SettingUpdateIn,
    user: User = Depends(get_current_user),
) -> SettingOut:
    """改一个 setting. admin only."""
    if user.role.value != "admin":
        raise HTTPException(status_code=403, detail="admin only")
    schema = next((s for s in SETTING_SCHEMA if s["key"] == key), None)
    if not schema:
        raise HTTPException(status_code=404, detail=f"unknown setting '{key}'")
    if schema["is_secret"] and (payload.value == "" or payload.value is None):
        # ⚠️ secret 项**空值一律当"不改"** —— 跟前端"留空 = 不改"的契约一致.
        #    原来只在 update_secret=false 时才保护, 而 update_secret 默认是 true,
        #    于是 PUT {"value":""} 会把 RAGFlow api_key / 钉钉 webhook 直接**清空**,
        #    接口还回"保存成功", 之后带空 Bearer 去打 RAGFlow 才报 502.
        async with AsyncSessionLocal() as session:
            row = await session.get(SystemSetting, key)
            return SettingOut.model_validate(row) if row else _empty_out(key, schema)
    # bool 开关统一存成真正的布尔 —— 字符串 "false" 读的时候会被当成真
    value = to_bool(payload.value) if schema["value_type"] == "bool" else payload.value
    # ⚠️ 换存储根目录时, **旧根必须在写入新值之前**抓出来 (2026-10-28).
    #    提交之后再回读读到的已经是新值了 —— 那样 old == new, 历史根永远记不上,
    #    "换根后老文件变孤儿" 就又复现了.
    old_storage = ""
    if key == "software.storage_path":
        async with AsyncSessionLocal() as s:
            r0 = await s.get(SystemSetting, key)
            if r0 is not None:
                v = r0.value
                old_storage = (v.get("v") if isinstance(v, dict) else v) or ""
    async with AsyncSessionLocal() as session:
        row = await session.get(SystemSetting, key)
        if row is None:
            row = SystemSetting(
                key=key,
                value={"v": value},
                category=schema["category"],
                description=schema["description"],
                is_secret=schema["is_secret"],
                updated_by=user.id,
            )
            session.add(row)
        else:
            row.value = {"v": value}
            row.updated_by = user.id
        await session.commit()
        await session.refresh(row)
    # 市场的仓库地址/分支是**运行时配置** —— 改完立即生效, 不用重启后端
    if key in ("marketplace.git.remote", "marketplace.git.branch"):
        from app.core import git_sync

        git_sync.set_git_config(
            remote=payload.value if key.endswith("remote") else None,
            branch=payload.value if key.endswith("branch") else None,
        )
        logger.info(
            "设置已生效: %s → remote=%s branch=%s",
            key, git_sync.git_remote(), git_sync.git_branch(),
        )
    # ⚠️ 换软件库存储根目录时, 把**旧根**记进历史 (2026-10-28).
    #    为什么: 软件包在库里存的是**相对路径**, 换根目录后"当前根 + 相对路径"
    #    找不到老文件 —— 下载 404、删除删不掉, 文件变成删不掉的孤儿.
    #    记下旧根之后, 平台会去各个根目录里找文件, 老文件照样能下、照样能删.
    if key == "software.storage_path":
        await _remember_old_storage_root(old_storage, value, user)
    return SettingOut.model_validate(row)


async def _remember_old_storage_root(old_value, new_value, user) -> None:
    """换存储根目录时, 把**旧根**追加进 ``software.storage_path_history``.

    ⚠️ ``old_value`` 必须由调用方在**写入新值之前**取好 —— 这里再回读数据库
       拿到的已经是新值了.
    """
    from app.core import software_store

    old = str(old_value or "").strip()
    new = str(new_value or "").strip()
    if not old or old == new:
        return
    # 旧值可能是**空** (用的是环境变量) —— 那就把环境变量指向的根记下来
    if not old:
        env_root = (os.environ.get("SOFTWARE_STORAGE_PATH") or "").strip()
        if not env_root:
            return
        old = env_root
    async with AsyncSessionLocal() as session:
        row_h = await session.get(SystemSetting, "software.storage_path_history")
        hist_raw = ""
        if row_h is not None:
            v = row_h.value
            hist_raw = (v.get("v") if isinstance(v, dict) else v) or ""
        parts = [p.strip() for p in str(hist_raw).split(",") if p.strip()]
        # 归一成绝对路径再存 —— 否则"相对仓库根"的写法换个 cwd 就对不上了
        try:
            old_abs = str(software_store.resolve_root(old))
        except Exception:  # noqa: BLE001 —— 路径解析失败就原样存
            old_abs = old
        if old_abs in parts:
            return
        parts.append(old_abs)
        val = ",".join(parts[-20:])
        if row_h is None:
            schema = next(
                (s for s in SETTING_SCHEMA if s["key"] == "software.storage_path_history"),
                None,
            )
            row_h = SystemSetting(
                key="software.storage_path_history",
                value={"v": val},
                category=(schema or {}).get("category", "software"),
                description=(schema or {}).get("description", ""),
                is_secret=False,
                updated_by=user.id,
            )
            session.add(row_h)
        else:
            row_h.value = {"v": val}
            row_h.updated_by = user.id
        await session.commit()
    logger.info("软件库存储根目录已变更, 旧根已记入历史: %s", old)


def _empty_out(key: str, schema: dict) -> SettingOut:
    from datetime import datetime
    return SettingOut(
        key=key, value=schema["default"], category=schema["category"],
        description=schema["description"], is_secret=schema["is_secret"],
        updated_by=None, updated_at=datetime.utcnow(),
    )


# ===== 测试连接 =====

@router.post("/test/ragflow", response_model=SettingTestOut)
async def test_ragflow(user: User = Depends(get_current_user)) -> SettingTestOut:
    """用当前 DB (或 fallback env) 的 ragflow 配置打 datasets 端点."""
    if user.role.value != "admin":
        raise HTTPException(status_code=403, detail="admin only")
    from app.core.settings_store import _rewrite_loopback
    raw_url = (await get("ragflow.base_url", "")) or ""
    base_url = _rewrite_loopback(raw_url).rstrip("/")
    api_key = await get("ragflow.api_key", "") or ""
    if not base_url or "xxxxx" in api_key or "mock" in api_key:
        return SettingTestOut(ok=False, status="off", message="未配置或仍在 mock 占位", detail=None)
    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            r = await client.get(
                f"{base_url.rstrip('/')}/datasets?page=1&page_size=1",
                headers={"Authorization": f"Bearer {api_key}"},
            )
            if r.status_code >= 500:
                return SettingTestOut(ok=False, status="warn", message=f"HTTP {r.status_code}", detail=None)
            data = r.json()
            if data.get("code") != 0:
                return SettingTestOut(ok=False, status="warn", message=data.get("message", "RAGFlow 返回错误"), detail=data)
            total = len(data.get("data") or [])
            return SettingTestOut(ok=True, status="ok", message=f"连通 · 可访问 {total} 个数据集", detail={"datasets": total})
    except Exception as e:
        return SettingTestOut(ok=False, status="off", message=f"不可达: {type(e).__name__}: {e}", detail=None)



# ===== 运行时拼 URL =====
# 设计: KB 页面 iframe 需要 userId (按登录用户) + theme (按浏览器当前主题),
# DB 里 admin 只配 raw URL + 是否拼, 运行时由后端拿当前用户 / 接前端传的 theme 拼好返回.



class EmbedOut(BaseModel):
    url: str




@router.post("/test/gitlab", response_model=SettingTestOut)
async def test_gitlab(_user: User = Depends(get_current_user)) -> SettingTestOut:
    """探当前配置的 GitLab 仓库能不能连上 (SSH 鉴权 + 分支是否存在)."""
    if _user.role.value != "admin":
        raise HTTPException(status_code=403, detail="admin only")
    from app.core import git_sync

    ok, message = git_sync.probe_remote()
    return SettingTestOut(
        ok=ok, status="ok" if ok else "warn", message=message,
        detail={"remote": git_sync.git_remote(), "branch": git_sync.git_branch()},
    )


@router.post("/test/dingtalk", response_model=SettingTestOut)
async def test_dingtalk(
    channel: str = Query("market", pattern="^(market|review)$"),
    _user: User = Depends(get_current_user),
) -> SettingTestOut:
    """用当前 DB 的钉钉配置真发一条消息.

    走完整发送路径 (webhook / 关键词 / 加签密钥), 所以:
      - 配对了 → 群里立刻收到一条自检消息
      - 配错了 → 返回钉钉的原始 errcode 与原因 (比如「关键词不匹配」)

    ⚠️ 两个频道各配各的 (市场群 / 审核群), 所以要分别自检 —— channel 参数选群.
    """
    if _user.role.value != "admin":
        raise HTTPException(status_code=403, detail="admin only")
    from app.core.dingtalk import send_test_market_message

    ok, message, detail = await send_test_market_message(channel)
    return SettingTestOut(
        ok=ok, status="ok" if ok else "warn", message=message, detail=detail,
    )


@router.post("/test/review_agent", response_model=SettingTestOut)
async def test_review_agent(user: User = Depends(get_current_user)) -> SettingTestOut:
    """用当前 DB 的 review_agent.base_url 测 ReviewAgent HTTP /api/v1/telemetry/health (调 review_agent_client.probe)."""
    if user.role.value != "admin":
        raise HTTPException(status_code=403, detail="admin only")
    from app.core import review_agent_client
    if not await review_agent_client.is_configured():
        return SettingTestOut(ok=False, status="off", message="未配置 db_path 或文件不存在", detail=None)
    status, msg = await review_agent_client.probe()
    if status == "ok":
        return SettingTestOut(ok=True, status="ok", message=f"连通 · {msg}", detail=None)
    return SettingTestOut(ok=False, status="warn", message=f"不可读: {msg}", detail=None)

@router.post("/test/software_storage", response_model=SettingTestOut)
async def test_software_storage(user: User = Depends(get_current_user)) -> SettingTestOut:
    """体检**软件库存储根目录** —— 能不能写、还剩多少空间、哪些版本的文件丢了.

    ⚠️ 为什么单独做一个端点 (而不是让前端去调 /software/path-check):
       · 那个接口返回的是**软件库领域**的结构 (missing 列表带 code/version),
         设置页要的是**能不能用**的一句话结论 + 缺文件的数量;
       · 设置页是"改配置"的地方, 改完存储路径最想知道的是
         "这个路径能不能写" —— 写不了的话传文件必然失败, 但没人在传之前就知道.

    ⚠️ admin only —— 存储根目录是**服务端路径**, 泄露等于告诉别人目录结构.
    """
    if user.role.value != "admin":
        raise HTTPException(status_code=403, detail="admin only")

    from app.core import software_store
    from app.core.settings_store import get
    from app.db.session import AsyncSessionLocal
    from app.models.software import SoftwareItem, SoftwareVersion
    from sqlalchemy import select

    configured = await get("software.storage_path", "") or ""
    root = software_store.resolve_root(configured)
    info = software_store.usage_info(root)

    if not info["exists"]:
        return SettingTestOut(
            ok=False, status="warn",
            message=f"目录不存在: {root} —— 建出来或者换个已经存在的路径",
            detail={"root": str(root), "exists": False},
        )
    if not info["writable"]:
        return SettingTestOut(
            ok=False, status="warn",
            message=f"目录存在但不可写: {root} —— 权限不对 (容器里通常是没挂卷)",
            detail={"root": str(root), "writable": False},
        )

    # 有多少版本的文件真的在盘上? (换过存储根目录的话会缺)
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

    # ⚠️ 2026-10-28: 分清两种"缺" ——
    #   · **在别的根目录里** (文件没丢, 只是不在当前根 —— 下载/删除会自动去找)
    #   · **所有根里都没有** (真丢了)
    #   以前只报一种, 管理员换完根目录一看"缺 3 个文件"就以为软件没了.
    history_raw = await get("software.storage_path_history", "") or ""
    history = [h.strip() for h in history_raw.split(",") if h.strip()]
    roots = software_store.candidate_roots(root, history)
    elsewhere: list[dict] = []
    lost: list[dict] = []
    for v in rows:
        if software_store.file_exists(root, v.file_path):
            continue
        found = software_store.locate_under(roots, v.file_path)
        item = {"version": v.version, "code": v.file_path.split("/")[0]}
        if found is not None:
            elsewhere.append({**item, "found_in": str(found.parent.parent.parent)})
        else:
            lost.append(item)

    # 孤儿目录: 根目录下有目录, 但 DB 里没有对应条目 (下架残留 / 手工塞的)
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

    # ⚠️ **两个"占用"是两回事** (2026-10-28 踩过):
    #   · software_store.used_bytes(root) —— 软件库目录**自己**占了多少
    #   · info["used_bytes"]              —— 整块磁盘的已用 (disk_usage)
    #     拿错的话会显示"软件库占了 725GB" —— 那是整块盘.
    lib_bytes = software_store.used_bytes(root)
    free_gb = int(info["free_bytes"]) / 1024 / 1024 / 1024
    lib_gb = lib_bytes / 1024 / 1024 / 1024
    detail = {
        "root": str(root),
        "exists": True,
        "writable": True,
        "used_bytes": int(lib_bytes),
        "free_bytes": int(info["free_bytes"]),
        # 所有候选根 —— 管理员能看到文件实际在哪
        "roots": [str(r) for r in roots],
        "missing_count": len(elsewhere),
        "missing": elsewhere[:50],
        "lost_count": len(lost),
        "lost": lost[:50],
        "orphan_count": len(orphan_dirs),
        "orphan_dirs": orphan_dirs[:50],
        # 设置项 / 环境变量 / 默认 —— 让管理员知道这个路径**是哪来的**
        "source": (
            "setting" if configured.strip()
            else ("env" if (os.environ.get("SOFTWARE_STORAGE_PATH") or "").strip() else "default")
        ),
    }
    if lost:
        return SettingTestOut(
            ok=False, status="warn",
            message=(
                f"可写, 但有 {len(lost)} 个版本的文件**在所有根目录里都找不到** "
                f"(真的丢了?) · 另有 {len(elsewhere)} 个在旧根目录里 (还能用)"
            ),
            detail=detail,
        )
    if elsewhere:
        return SettingTestOut(
            ok=False, status="warn",
            message=(
                f"可写 · {len(elsewhere)} 个版本的文件不在这个目录里, "
                f"但在**旧根目录**里找到了 (不影响下载/删除)"
            ),
            detail=detail,
        )
    return SettingTestOut(
        ok=True, status="ok",
        message=f"可写 · 软件库已占 {lib_gb:.1f} GB / 磁盘剩余 {free_gb:.1f} GB · 文件都在",
        detail=detail,
    )


@router.get("/embed/{key:path}", response_model=EmbedOut)
async def build_embed_url(
    key: str,
    theme: str | None = None,
    user: User = Depends(get_current_user),
) -> EmbedOut:
    """把 <prefix>.embed_url 拼上 userId / theme (按 schema 中的 <prefix>.append_user_id / <prefix>.append_theme 开关).

    - key: 配置项的 prefix (search / chat / agent), 不带 .embed_url 后缀, 跟 schema 解耦
    - theme: 浏览器当前主题 light / dark, 不传或传 auto 都视作不拼 theme
    """
    prefix = key.split(".")[0]   # 接受 "search" / "search.embed_url" / "search/foo" 都行, 取首段
    raw_key = f"{prefix}.embed_url"
    raw = (await get(raw_key, "")) or ""
    if not raw:
        raise HTTPException(status_code=404, detail=f"{raw_key} 未配置")

    pr = urlparse(raw)
    q = parse_qs(pr.query, keep_blank_values=True)

    append_user = to_bool(await get(f"{prefix}.append_user_id", True), True)
    append_theme = to_bool(await get(f"{prefix}.append_theme", True), True)

    if append_user and user and user.username and "userId" not in q:
        # userId 只在不存在时拼, 避免覆盖手动配置的固定值
        q["userId"] = [user.username]
    if append_theme and theme and theme in ("light", "dark"):
        # theme 总是用当前主题覆盖 — 浏览器切主题,iframe 必须立刻跟着切,
        # 否则会出现 "前端是 light, RAGFlow 还是 dark" 这种错位
        q["theme"] = [theme]

    new_q = urlencode({k: v[0] for k, v in q.items()}, doseq=False)
    final = urlunparse(pr._replace(query=new_q))
    return EmbedOut(url=final)
