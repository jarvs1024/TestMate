"""资产市场的权限判定 —— 谁能发布 / 谁能审核 / 谁能改这个资产.

⚠️ 判定逻辑放这里 (纯逻辑, 可单测), api 层只留 Depends 装饰器的薄壳 ——
   以前判定散在路由里, 每加一条路径就可能漏掉一处身份判断.
"""
from __future__ import annotations

import json
import re

from app.core.settings_store import get
from app.models.asset import Asset
from app.models.user import User

PUBLISHER_IDS_KEY = "marketplace.publisher_ids"
PUBLISHER_NAMES_KEY = "marketplace.publisher_usernames"
REVIEWER_NAMES_KEY = "marketplace.review.reviewer_usernames"


def split_list(raw: str) -> list[str]:
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


def role_of(user: User) -> str:
    """用户角色 (统一取法: role 可能是枚举也可能是字符串)."""
    role = getattr(user, "role", "")
    return role.value if hasattr(role, "value") else str(role)


def is_admin(user: User) -> bool:
    return role_of(user) == "admin"


async def publisher_ids() -> set[int]:
    raw = await get(PUBLISHER_IDS_KEY, "[]") or "[]"
    return {int(x) for x in split_list(str(raw)) if str(x).isdigit()}


async def publisher_names() -> set[str]:
    """允许发布的**用户名**集合 (比填用户 ID 友好)."""
    raw = await get(PUBLISHER_NAMES_KEY, "") or ""
    return {x.lower() for x in split_list(str(raw))}


async def reviewer_names() -> set[str]:
    """被授权的审核人 (管理员永远有审核权)."""
    raw = await get(REVIEWER_NAMES_KEY, "") or ""
    return {
        x.strip().lower()
        for x in str(raw).replace("，", ",").replace(";", ",").split(",")
        if x.strip()
    }


async def is_reviewer(user: User) -> bool:
    """能不能审核 (管理员永远可以)."""
    if is_admin(user):
        return True
    role = role_of(user)
    if role == "anonymous":
        return False
    names = await reviewer_names()
    return bool(names) and (user.username or "").strip().lower() in names


async def can_publish(user: User) -> bool:
    """能不能发布 (白名单两个口径任一命中 + admin 恒可)."""
    if is_admin(user):
        return True
    if role_of(user) == "anonymous":
        return False
    if user.id in await publisher_ids():
        return True
    names = await publisher_names()
    return bool(names) and (user.username or "").strip().lower() in names


def can_modify(asset: Asset, user: User) -> bool:
    """能不能改这个资产 (**作者本人或管理员**).

    ⚠️ 共享 GitLab 仓库下, 任何白名单用户都能改别人的资产的话,
       别人精心写的内容会被无声覆盖 —— 所以这里必须严.
    """
    if is_admin(user):
        return True
    return (asset.author or "").strip().lower() == (user.username or "").strip().lower()
