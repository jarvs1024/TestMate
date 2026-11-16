"""设置-用户「使用统计」—— 在线人数 / 日活曲线 / 下载排行 (仅管理员)."""
from __future__ import annotations

from datetime import date, timedelta

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.auth import get_current_user
from app.core.usage_stats import ONLINE_WINDOW_MINUTES, local_today, online_cutoff
from app.db.session import get_session
from app.models.asset import Asset
from app.models.software import SoftwareItem
from app.models.user import User, UserActivityDaily, UserRole
from app.schemas.stats import (
    StatsActive,
    StatsDownloadItem,
    StatsDownloadLibrary,
    StatsDownloads,
    StatsOnline,
    StatsOnlineUser,
    StatsSeriesPoint,
    StatsSummary,
)

router = APIRouter()

ALLOWED_DAYS = (7, 30, 90)
TOP_N = 8


async def _stats_admin(user: User = Depends(get_current_user)) -> User:
    if user.role != UserRole.admin:
        raise HTTPException(status_code=403, detail="仅管理员可以查看用户统计")
    return user


async def _online_users(session: AsyncSession) -> list[User]:
    cutoff = online_cutoff()
    rows = await session.execute(
        select(User)
        .where(
            User.is_active.is_(True),
            User.last_seen_at.is_not(None),
            User.last_seen_at >= cutoff,
        )
        .order_by(User.last_seen_at.desc())
    )
    return list(rows.scalars().all())


def _online_out(users: list[User]) -> StatsOnline:
    return StatsOnline(
        count=len(users),
        window_minutes=ONLINE_WINDOW_MINUTES,
        users=[StatsOnlineUser.model_validate(u) for u in users],
    )


async def _software_downloads(session: AsyncSession) -> StatsDownloadLibrary:
    where = (
        SoftwareItem.deleted_at.is_(None),
        SoftwareItem.publish_status == "published",
    )
    total = await session.scalar(
        select(func.coalesce(func.sum(SoftwareItem.download_count), 0)).where(*where)
    )
    rows = await session.execute(
        select(SoftwareItem)
        .where(*where)
        .order_by(SoftwareItem.download_count.desc(), SoftwareItem.id)
        .limit(TOP_N)
    )
    return StatsDownloadLibrary(
        total=int(total or 0),
        items=[
            StatsDownloadItem(
                code=item.code,
                name=item.name,
                icon=item.icon or "",
                count=int(item.download_count or 0),
            )
            for item in rows.scalars().all()
        ],
    )


async def _extension_downloads(session: AsyncSession) -> StatsDownloadLibrary:
    where = (Asset.publish_status == "published",)
    total = await session.scalar(
        select(func.coalesce(func.sum(Asset.download_count), 0)).where(*where)
    )
    rows = await session.execute(
        select(Asset)
        .where(*where)
        .order_by(Asset.download_count.desc(), Asset.id)
        .limit(TOP_N)
    )
    return StatsDownloadLibrary(
        total=int(total or 0),
        items=[
            StatsDownloadItem(
                code=item.code,
                name=item.name,
                icon=item.icon or "",
                count=int(item.download_count or 0),
                kind=item.kind or "",
            )
            for item in rows.scalars().all()
        ],
    )


async def _active_series(session: AsyncSession, days: int) -> StatsActive:
    today = local_today()
    start = today - timedelta(days=days - 1)
    rows = await session.execute(
        select(UserActivityDaily.stat_date, func.count())
        .where(
            UserActivityDaily.stat_date >= start,
            UserActivityDaily.stat_date <= today,
        )
        .group_by(UserActivityDaily.stat_date)
    )
    counts: dict[date, int] = {d: int(c) for d, c in rows.all()}
    series = [
        StatsSeriesPoint(
            date=(start + timedelta(days=i)).isoformat(),
            count=counts.get(start + timedelta(days=i), 0),
        )
        for i in range(days)
    ]
    return StatsActive(today=counts.get(today, 0), series=series)


@router.get("/summary", response_model=StatsSummary)
async def usage_summary(
    days: int = Query(30),
    session: AsyncSession = Depends(get_session),
    _admin: User = Depends(_stats_admin),
):
    """设置页首次加载用 —— 在线 + 日活 + 两库下载排行一次取回."""
    if days not in ALLOWED_DAYS:
        raise HTTPException(status_code=422, detail="统计周期只能是 7、30 或 90 天")
    online = await _online_users(session)
    return StatsSummary(
        online=_online_out(online),
        active=await _active_series(session, days),
        downloads=StatsDownloads(
            software=await _software_downloads(session),
            extensions=await _extension_downloads(session),
        ),
    )


@router.get("/online", response_model=StatsOnline)
async def online_now(
    session: AsyncSession = Depends(get_session),
    _admin: User = Depends(_stats_admin),
):
    """每 60 秒轮询的轻量端点 —— 只查在线名单, 不动图表."""
    return _online_out(await _online_users(session))
