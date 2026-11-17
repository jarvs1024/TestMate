"""评论站内通知的写入 (聚合 + 收件人解析).

不改评论接口的成败: 通知写失败只记日志, 绝不回滚已经提交的评论.
"""
from __future__ import annotations

import logging
from datetime import datetime

from sqlalchemy import select

from app.core.identity import lookup_candidates, name_matches
from app.db.session import AsyncSessionLocal
from app.models.notification import UserNotification
from app.models.user import User

log = logging.getLogger(__name__)

_MAX_TITLE = 200
_MAX_BODY = 140


def _norm(s: str | None) -> str:
    return (s or "").strip().lower()


def _excerpt(text: str) -> str:
    return " ".join((text or "").split())[:_MAX_BODY]


def _clip(s: str, limit: int) -> str:
    return s if len(s) <= limit else s[: limit - 1] + "…"


async def _resolve_user(session, name: str | None) -> User | None:
    """用户名 / 邮箱写法 → 账号 (先精确, 再按候选)."""
    cands = lookup_candidates(name)
    if not cands:
        return None
    rows = (
        await session.execute(select(User).where(User.username.in_(cands)))
    ).scalars().all()
    if not rows:
        return None
    raw = _norm(name)
    for u in rows:
        if _norm(u.username) == raw:
            return u
    return rows[0]


def _recipient_filter(user_id: int | None, username: str):
    """聚合时找「同一收件人的未读行」—— 有 id 用 id, 否则用用户名候选."""
    if user_id:
        return UserNotification.user_id == user_id
    cands = lookup_candidates(username) or [""]
    return UserNotification.username.in_(cands)


async def notify_new_comment(
    *,
    asset_code: str,
    asset_name: str,
    asset_author: str,
    actor_id: int | None,
    actor_name: str,
    comment_id: int,
    content: str,
    is_reply: bool,
    parent_comment_id: int | None = None,
    parent_user_id: int | None = None,
    parent_username: str = "",
) -> None:
    """评论/回复成功落库后调用.

    · 主评论 → 收件人 = 资产作者 (评论者就是作者 → 跳过)
    · 回复   → 收件人 = 被回复主评论的作者 (自己回自己 → 跳过)
    """
    now = datetime.utcnow()
    if not is_reply:
        if name_matches({_norm(asset_author)}, actor_name):
            return
        async with AsyncSessionLocal() as s:
            recipient = await _resolve_user(s, asset_author)
            if recipient is None:
                return
            rid, rname = recipient.id, recipient.username
            kind = "asset_comment"
            dedupe = f"asset_comment:{asset_code}"
            title = f"{actor_name} 评论了你的资产「{asset_name}」"
    else:
        if parent_user_id is not None:
            if parent_user_id == actor_id:
                return
            rid, rname = parent_user_id, parent_username
        else:
            if not parent_username or name_matches({_norm(parent_username)}, actor_name):
                return
            rid, rname = None, parent_username
        kind = "comment_reply"
        dedupe = f"comment_reply:{parent_comment_id}"
        title = f"{actor_name} 回复了你在「{asset_name}」下的评论"

    title = _clip(title, _MAX_TITLE)
    body = _excerpt(content)

    async with AsyncSessionLocal() as s:
        # 回复的收件人可能只留了 username 快照 —— 顺手补一次 id (有就补)
        if rid is None:
            resolved = await _resolve_user(s, rname)
            if resolved is not None:
                rid, rname = resolved.id, resolved.username

        row = (
            await s.execute(
                select(UserNotification)
                .where(
                    _recipient_filter(rid, rname),
                    UserNotification.kind == kind,
                    UserNotification.dedupe_key == dedupe,
                    UserNotification.read_at.is_(None),
                )
                .order_by(UserNotification.id.desc())
                .limit(1)
                .with_for_update()
            )
        ).scalar_one_or_none()

        if row is not None:
            row.actor_id = actor_id
            row.actor_name = actor_name
            row.asset_name = asset_name
            row.comment_id = comment_id
            row.parent_comment_id = parent_comment_id
            row.title = title
            row.body = body
            row.event_count = (row.event_count or 0) + 1
            row.updated_at = now
        else:
            s.add(
                UserNotification(
                    user_id=rid,
                    username=rname or "",
                    actor_id=actor_id,
                    actor_name=actor_name,
                    kind=kind,
                    dedupe_key=dedupe,
                    asset_code=asset_code,
                    asset_name=asset_name,
                    comment_id=comment_id,
                    parent_comment_id=parent_comment_id,
                    title=title,
                    body=body,
                    event_count=1,
                    created_at=now,
                    updated_at=now,
                )
            )
        await s.commit()
