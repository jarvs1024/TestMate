"""记录按用户统计的下载/复制事件.

⚠️ 只在 count_dedup.bump_count() 返回 True 时调用 —— 与卡片上的
   download_count 保持同一口径, 不要每个 HTTP 请求都记.
"""
from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncSession

from app.models.download_event import DownloadEvent


async def record_download_event(
    session: AsyncSession,
    *,
    user_id: int | None,
    username: str,
    kind: str,
    code: str,
    name: str,
    action: str = "download",
) -> None:
    session.add(
        DownloadEvent(
            user_id=user_id or None,
            username=(username or "")[:64],
            kind=kind,
            action=action,
            code=(code or "")[:64],
            name=(name or "")[:128],
        )
    )
