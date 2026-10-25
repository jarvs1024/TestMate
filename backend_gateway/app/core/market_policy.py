"""资产市场的权限判定 —— 谁能发布 / 谁能审核 / 谁能改这个资产.

⚠️ 判定逻辑放这里 (纯逻辑, 可单测), api 层只留 Depends 装饰器的薄壳 ——
   以前判定散在路由里, 每加一条路径就可能漏掉一处身份判断.

发布权 (can_publish) 是**两条路**:
   ① 角色 —— marketplace.publisher_roles, 默认 tester (测试工程) 就能发;
   ② 白名单 —— publisher_ids / publisher_usernames, 给角色不在列表里的人开口子.
   admin 恒可发布.
"""
from __future__ import annotations

import json
import re

from app.core.identity import name_matches
from app.core.settings_store import get
from app.models.asset import Asset
from app.models.user import User

PUBLISHER_IDS_KEY = "marketplace.publisher_ids"
PUBLISHER_NAMES_KEY = "marketplace.publisher_usernames"
PUBLISHER_ROLES_KEY = "marketplace.publisher_roles"
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


async def publisher_roles() -> set[str]:
    """**按角色**默认可发布 (逗号分隔, 默认 tester = 测试工程).

    ⚠️ 为什么要有这一层 (2026-10-25): 原来"谁能发布"只认白名单, 白名单空着
       就等于**除 admin 外谁都发不了** —— 连"测试工程"这种天天要往市场里
       沉淀插件/技能/连接器的角色也被挡住, 报错还只说"不在白名单内",
       让人以为是配置漏了, 其实是模型本身把角色能力忽略了.
       现在是**角色 + 白名单两条路**: 角色在列表里就能发, 白名单是给
       "角色不在列表里、但也需要发"的人开的额外口子.
    """
    raw = await get(PUBLISHER_ROLES_KEY, "tester") or ""
    return {x.strip().lower() for x in str(raw).replace("，", ",").replace(";", ",").split(",") if x.strip()}


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
    return name_matches(names, user.username)


async def can_publish(user: User) -> bool:
    """能不能发布 —— **角色**或**白名单**任一命中即可 (admin 恒可).

    三条通路:
      ① admin                    —— 恒可
      ② 角色在 publisher_roles 里 —— 默认 tester (测试工程) 就能发
      ③ 白名单命中 (用户 ID / 用户名) —— 给角色不在列表里的人开的额外口子
    """
    if is_admin(user):
        return True
    role = role_of(user)
    if role == "anonymous":
        return False
    if role in await publisher_roles():
        return True
    if user.id in await publisher_ids():
        return True
    names = await publisher_names()
    return name_matches(names, user.username)


def can_modify(asset: Asset, user: User) -> bool:
    """能不能改这个资产 (**作者本人或管理员**).

    ⚠️ 共享 GitLab 仓库下, 任何白名单用户都能改别人的资产的话,
       别人精心写的内容会被无声覆盖 —— 所以这里必须严.
    """
    if is_admin(user):
        return True
    # ⚠️ 容错: 白名单/作者名可能是短名 ('zhangsan'), 用户名是邮箱形式
    #    ('zhangsan@twsc.com.cn') —— 两种写法都算命中 (见 identity.name_matches)
    return name_matches({(asset.author or "").strip().lower()}, user.username)
