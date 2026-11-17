"""站内通知 (消息箱) —— 只读写自己的."""
from __future__ import annotations

from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import delete, exists, func, or_, select

from app.api.auth import get_current_user
from app.core.identity import lookup_candidates
from app.db.session import AsyncSessionLocal
from app.models.asset import AssetComment
from app.models.notification import UserNotification
from app.models.user import User
from app.schemas.notification import (
    NotificationListOut,
    NotificationOut,
    ReadOut,
    UnreadCountOut,
)

router = APIRouter()


def _mine(user: User):
    """收件人匹配 —— 有 id 按 id; 老数据只留了用户名时按候选写法比."""
    cands = lookup_candidates(user.username) or [""]
    return or_(
        UserNotification.user_id == user.id,
        UserNotification.username.in_(cands),
    )


def _is_mine(row: UserNotification, user: User) -> bool:
    if row.user_id is not None:
        return row.user_id == user.id
    return (row.username or "").lower() in set(lookup_candidates(user.username))


def _target_alive():
    """通知指向的评论还活着 (未被软删, 也没随资产物理删除).

    删除评论时已经同步删过通知; 这里兜的是删除同步上线前的存量和别的
    路径留下的孤儿 —— 它们点进去只会落到评论首页, 不能当成有效消息.
    """
    return exists().where(
        AssetComment.id == UserNotification.comment_id,
        AssetComment.deleted_at.is_(None),
    )


def _out(n: UserNotification) -> NotificationOut:
    return NotificationOut(
        id=n.id, kind=n.kind, actor_name=n.actor_name,
        asset_code=n.asset_code, asset_name=n.asset_name,
        comment_id=n.comment_id, parent_comment_id=n.parent_comment_id,
        title=n.title, body=n.body, event_count=n.event_count or 1,
        read_at=n.read_at, created_at=n.created_at, updated_at=n.updated_at,
    )


@router.get("", response_model=NotificationListOut)
async def list_notifications(
    limit: int = Query(20, ge=1, le=50),
    offset: int = Query(0, ge=0),
    unread_only: bool = Query(False),
    user: User = Depends(get_current_user),
) -> NotificationListOut:
    """我的通知 (按最近活动倒序). 列表里同时带未读总数, 顶栏角标一次拿全."""
    async with AsyncSessionLocal() as s:
        mine = _mine(user)
        # 评论没了的通知没有可跳转的目标 —— 打开消息时顺手清掉
        await s.execute(delete(UserNotification).where(mine, ~_target_alive()))
        await s.commit()
        total = (
            await s.execute(select(func.count()).select_from(UserNotification).where(mine))
        ).scalar_one()
        unread = (
            await s.execute(
                select(func.count()).select_from(UserNotification).where(
                    mine, UserNotification.read_at.is_(None),
                )
            )
        ).scalar_one()
        stmt = select(UserNotification).where(mine)
        if unread_only:
            stmt = stmt.where(UserNotification.read_at.is_(None))
        rows = (
            await s.execute(
                stmt.order_by(UserNotification.updated_at.desc(), UserNotification.id.desc())
                .limit(limit)
                .offset(offset)
            )
        ).scalars().all()
    return NotificationListOut(
        items=[_out(n) for n in rows], total=total or 0, unread_count=unread or 0,
    )


@router.get("/unread-count", response_model=UnreadCountOut)
async def unread_count(user: User = Depends(get_current_user)) -> UnreadCountOut:
    """顶栏轮询 —— 轻量, 只回一个数."""
    async with AsyncSessionLocal() as s:
        n = (
            await s.execute(
                select(func.count()).select_from(UserNotification).where(
                    _mine(user), UserNotification.read_at.is_(None), _target_alive(),
                )
            )
        ).scalar_one()
    return UnreadCountOut(count=n or 0)


@router.post("/{notification_id}/read", response_model=ReadOut)
async def read_notification(
    notification_id: int, user: User = Depends(get_current_user),
) -> ReadOut:
    async with AsyncSessionLocal() as s:
        row = await s.get(UserNotification, notification_id)
        if row is None or not _is_mine(row, user):
            raise HTTPException(status_code=404, detail="通知不存在")
        if row.read_at is None:
            row.read_at = datetime.utcnow()
            await s.commit()
            await s.refresh(row)
    return ReadOut(ok=True, id=notification_id, read_at=row.read_at)


@router.post("/read-all", response_model=dict)
async def read_all(user: User = Depends(get_current_user)) -> dict:
    async with AsyncSessionLocal() as s:
        rows = (
            await s.execute(
                select(UserNotification).where(
                    _mine(user), UserNotification.read_at.is_(None),
                )
            )
        ).scalars().all()
        now = datetime.utcnow()
        for row in rows:
            row.read_at = now
        await s.commit()
    return {"ok": True, "updated": len(rows)}
