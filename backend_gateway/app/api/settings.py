"""/api/v1/settings — DB-backed 配置读写 + 测试连接."""
from __future__ import annotations
import logging
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
    "agents":     "🤖 智能体",
    "knowledge":       "📚 知识库 / RAGFlow",
    "notification": "🔔 通知 / 钉钉",
    "general":    "⚙️ 通用",
    "search":     "🔎 知识检索",
    "chat":       "💬 知识对话",
    "code-review": "🧪 代码检视 (pr-agent)",
    "data-source": "📡 数据源",
    "marketplace": "🏪 AI 资产市场",
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
    return SettingOut.model_validate(row)


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
