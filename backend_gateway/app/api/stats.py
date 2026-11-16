"""设置-用户「使用统计」—— 在线人数 / 日活曲线 / 下载排行 (仅管理员)."""
from __future__ import annotations

from datetime import date, timedelta

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.auth import get_current_user
from app.core.usage_stats import (
    ONLINE_WINDOW_MINUTES,
    is_online,
    local_day_start_utc,
    local_today,
    online_cutoff,
    to_local_date,
)
from app.db.session import get_session
from app.models.asset import Asset
from app.models.download_event import DownloadEvent
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
    StatsUserDownloadItem,
    StatsUserDownloads,
    StatsUserRow,
    StatsUsers,
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


async def _data_since(session: AsyncSession) -> str:
    """用户维度数据最早从哪天开始 —— 两边的表都可能更晚才开始有数据."""
    candidates = []
    event_min = await session.scalar(select(func.min(DownloadEvent.created_at)))
    if event_min is not None:
        candidates.append(to_local_date(event_min))
    activity_min = await session.scalar(select(func.min(UserActivityDaily.stat_date)))
    if activity_min is not None:
        candidates.append(activity_min)
    return (min(candidates) if candidates else local_today()).isoformat()


async def _user_rows(session: AsyncSession, days: int) -> list[StatsUserRow]:
    today = local_today()
    start = today - timedelta(days=days - 1)
    start_utc = local_day_start_utc(start)

    users = list((await session.execute(select(User).order_by(User.id))).scalars().all())

    activity_rows = (
        await session.execute(
            select(UserActivityDaily.user_id, UserActivityDaily.stat_date).where(
                UserActivityDaily.stat_date >= start,
                UserActivityDaily.stat_date <= today,
            )
        )
    ).all()
    active_dates: dict[int, list[str]] = {}
    for uid, stat_date in activity_rows:
        active_dates.setdefault(uid, []).append(stat_date.isoformat())

    download_rows = (
        await session.execute(
            select(
                DownloadEvent.user_id,
                DownloadEvent.kind,
                func.count(),
            )
            .where(
                DownloadEvent.user_id.is_not(None),
                DownloadEvent.created_at >= start_utc,
            )
            .group_by(DownloadEvent.user_id, DownloadEvent.kind)
        )
    ).all()
    downloads: dict[int, dict[str, int]] = {}
    for uid, kind, count in download_rows:
        downloads.setdefault(uid, {})[kind] = int(count)

    rows = []
    for user in users:
        dates = sorted(active_dates.get(user.id, []))
        by_kind = downloads.get(user.id, {})
        software = by_kind.get("software", 0)
        extension = by_kind.get("extension", 0)
        rows.append(
            StatsUserRow(
                id=user.id,
                username=user.username,
                role=user.role,
                is_active=user.is_active,
                is_online=is_online(user.last_seen_at),
                active_days=len(dates),
                active_dates=dates,
                last_seen_at=user.last_seen_at,
                software_downloads=software,
                extension_downloads=extension,
                total_downloads=software + extension,
            )
        )
    rows.sort(key=lambda r: (r.active_days, r.total_downloads, -r.id), reverse=True)
    return rows


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


@router.get("/users", response_model=StatsUsers)
async def user_stats(
    days: int = Query(30),
    session: AsyncSession = Depends(get_session),
    _admin: User = Depends(_stats_admin),
):
    """用户明细 —— 每人周期内活跃天数 + 两库下载次数."""
    if days not in ALLOWED_DAYS:
        raise HTTPException(status_code=422, detail="统计周期只能是 7、30 或 90 天")
    start = local_today() - timedelta(days=days - 1)
    anonymous = await session.scalar(
        select(func.count())
        .select_from(DownloadEvent)
        .where(
            DownloadEvent.user_id.is_(None),
            DownloadEvent.created_at >= local_day_start_utc(start),
        )
    )
    return StatsUsers(
        days=days,
        since=await _data_since(session),
        anonymous_downloads=int(anonymous or 0),
        users=await _user_rows(session, days),
    )


@router.get("/users/{user_id}/downloads", response_model=StatsUserDownloads)
async def user_downloads(
    user_id: int,
    days: int = Query(30),
    session: AsyncSession = Depends(get_session),
    _admin: User = Depends(_stats_admin),
):
    """某个用户在周期内下载过的资产 —— 按资产聚合, 供用户行展开."""
    if days not in ALLOWED_DAYS:
        raise HTTPException(status_code=422, detail="统计周期只能是 7、30 或 90 天")
    user = await session.get(User, user_id)
    if user is None:
        raise HTTPException(status_code=404, detail="用户不存在")

    start = local_today() - timedelta(days=days - 1)
    rows = (
        await session.execute(
            select(
                DownloadEvent.kind,
                DownloadEvent.action,
                DownloadEvent.code,
                func.max(DownloadEvent.name).label("name"),
                func.count().label("count"),
                func.max(DownloadEvent.created_at).label("last_at"),
            )
            .where(
                DownloadEvent.user_id == user_id,
                DownloadEvent.created_at >= local_day_start_utc(start),
            )
            .group_by(DownloadEvent.kind, DownloadEvent.action, DownloadEvent.code)
            .order_by(
                func.count().desc(),
                func.max(DownloadEvent.created_at).desc(),
                DownloadEvent.code,
            )
        )
    ).all()
    return StatsUserDownloads(
        user_id=user_id,
        days=days,
        items=[
            StatsUserDownloadItem(
                kind=row.kind,
                action=row.action,
                code=row.code,
                name=row.name or "",
                count=int(row.count),
                last_at=row.last_at,
            )
            for row in rows
        ],
    )


@router.get("/online", response_model=StatsOnline)
async def online_now(
    session: AsyncSession = Depends(get_session),
    _admin: User = Depends(_stats_admin),
):
    """每 60 秒轮询的轻量端点 —— 只查在线名单, 不动图表."""
    return _online_out(await _online_users(session))
