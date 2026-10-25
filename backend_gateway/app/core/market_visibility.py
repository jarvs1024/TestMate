"""资产可见性 —— **列表与详情用同一套规则**.

为什么要有这个模块 (2026-10-25 整改):
    列表端点有可见性过滤 (在架 ∪ 我提交的), **详情端点却没有** ——
    任意登录用户 GET /assets/{code} 就能看到待审核 / 被驳回 / 已下架的资产,
    连接器资产里的 MCP 配置 (env / headers 里可能有令牌) 也一并暴露.

现在可见性只在这里定义一次:
    · 列表 → apply_visibility (SQL 谓词)
    · 详情 → assert_visible (单条断言)
"""
from __future__ import annotations

from sqlalchemy import or_
from sqlalchemy import Select

from app.core.identity import author_forms
from app.core.market_state import ON_SHELF_STATES, PUBLISHED
from app.models.asset import Asset


def _same_author(asset: Asset, username: str) -> bool:
    """作者是不是这个人 —— 短名 / 全邮箱都认 (见 identity.author_forms)."""
    return (asset.author or "").strip().lower() in set(author_forms(username))


def visible_to(
    asset: Asset,
    *,
    username: str,
    is_reviewer: bool = False,
    is_admin: bool = False,
) -> bool:
    """这个人能不能看到这个资产 (详情层).

    规则与列表一致:
        · 在架 (published / unpublish_pending) —— 所有人可见
        · 管理员 / 审核人 —— 全部可见 (他们要处理待审资产)
        · 作者本人 —— 自己的都可见 (待审 / 被驳回 / 待下架)
    """
    if (asset.publish_status or PUBLISHED) in ON_SHELF_STATES:
        return True
    if is_reviewer or is_admin:
        return True
    return _same_author(asset, username)


def apply_visibility(
    stmt: Select,
    *,
    username: str,
    is_reviewer: bool = False,
    is_admin: bool = False,
) -> Select:
    """给列表查询加可见性条件 (SQL 版).

    ⚠️ 作者比较用 `IN (原样, 本地部分)` —— DB 里 author 存的就是登录用户名,
       但存量数据可能是短名 ('zhangsan') 而用户名已是邮箱形式
       ('zhangsan@twsc.com.cn'). 两种都带上, 免得"我的资产"整片消失.
       ⚠️ 别改成大小写不敏感, 否则和详情层的判断会不一致.
    """
    if is_reviewer or is_admin:
        return stmt
    forms = author_forms(username)
    return stmt.where(
        or_(
            Asset.publish_status.in_(ON_SHELF_STATES),
            Asset.author.in_(forms) if forms else Asset.author == username,
        )
    )


def assert_visible(
    asset: Asset,
    *,
    username: str,
    is_reviewer: bool = False,
    is_admin: bool = False,
) -> None:
    """看不到就抛 404 —— **不泄露这个 code 存不存在**.

    ⚠️ 用 404 而不是 403: 403 等于告诉对方"这个资产存在, 只是你没权限看".
    """
    if visible_to(asset, username=username, is_reviewer=is_reviewer, is_admin=is_admin):
        return
    from fastapi import HTTPException

    raise HTTPException(status_code=404, detail="资产不存在")
