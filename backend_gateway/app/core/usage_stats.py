"""用户使用统计 —— 在线心跳 + 按日活跃去重.

口径:
    · 在线 = 最近 ONLINE_WINDOW_MINUTES 分钟内有过已登录请求;
    · 日活 = 当天有一次**实际操作** (排除未读通知轮询等后台请求), 按人去重;
    · 日期按 settings.TIMEZONE (默认 Asia/Shanghai) 切.

为什么不落访问明细:
    管理员只需要「谁这天来过」, 不需要看某人访问了哪个页面/IP.
    只存日活去重行, 隐私面和数据量都最小.
"""
from __future__ import annotations

import logging
import time
from datetime import date, datetime, timedelta, timezone
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from sqlalchemy import update
from sqlalchemy.dialects.mysql import insert as mysql_insert

from app.core.config import settings
from app.db.session import AsyncSessionLocal
from app.models.user import User, UserActivityDaily

logger = logging.getLogger(__name__)

ONLINE_WINDOW_MINUTES = 5
TOUCH_INTERVAL_SECONDS = 60
# 这些是前台自动轮询, 只能证明「页面还开着」, 不能证明人还在用.
# 它们更新在线状态, 但不计入日活 —— 否则挂着标签页一整天就算活跃.
BACKGROUND_PATHS = frozenset({
    "/api/v1/notifications/unread-count",
    "/api/v1/health",
    # 设置页「使用统计」每 60 秒刷新在线名单 —— 开着页面不等于人在操作
    "/api/v1/auth/stats/online",
})

try:
    _LOCAL_TZ = ZoneInfo(settings.TIMEZONE or "Asia/Shanghai")
except ZoneInfoNotFoundError:  # pragma: no cover — 目标环境都带 tzdata
    _LOCAL_TZ = timezone(timedelta(hours=8))

# 进程内节流/去重: 每个进程每分钟最多写一次在线, 每人每天最多尝试插一次日活.
_last_touch: dict[int, float] = {}
_daily_seen: set[tuple[int, date]] = set()


def local_today() -> date:
    return datetime.now(_LOCAL_TZ).date()


def online_cutoff() -> datetime:
    """在线判定下界 —— 库里存的是 naive UTC."""
    return datetime.utcnow() - timedelta(minutes=ONLINE_WINDOW_MINUTES)


def is_background_path(path: str) -> bool:
    return (path or "").rstrip("/") in BACKGROUND_PATHS


def is_online(last_seen_at: datetime | None) -> bool:
    return bool(last_seen_at and last_seen_at >= online_cutoff())


def reset_tracking_state() -> None:
    """测试用: 清空进程内节流缓存 (清库后 user_id 会被复用)."""
    _last_touch.clear()
    _daily_seen.clear()


async def touch_user(user: User, *, path: str = "") -> None:
    """记录一次已登录访问 —— 失败只记日志, 绝不影响业务请求."""
    uid = int(getattr(user, "id", 0) or 0)
    if uid <= 0:
        return
    if getattr(getattr(user, "role", None), "value", None) == "anonymous":
        return

    now_mono = time.monotonic()
    today = local_today()
    mark_online = now_mono - _last_touch.get(uid, 0.0) >= TOUCH_INTERVAL_SECONDS
    mark_daily = not is_background_path(path) and (uid, today) not in _daily_seen
    if not (mark_online or mark_daily):
        return

    try:
        async with AsyncSessionLocal() as session:
            if mark_online:
                await session.execute(
                    update(User)
                    .where(User.id == uid)
                    # 钉住 updated_at —— 在线心跳不是账号资料变更
                    .values(last_seen_at=datetime.utcnow(), updated_at=User.updated_at)
                )
            if mark_daily:
                await session.execute(
                    mysql_insert(UserActivityDaily)
                    .values(stat_date=today, user_id=uid, created_at=datetime.utcnow())
                    .prefix_with("IGNORE")
                )
            await session.commit()
    except Exception as e:  # noqa: BLE001 — 统计不能挡住正常请求
        logger.warning("使用统计写入失败 user_id=%s error=%s", uid, e)
        return

    if mark_online:
        _last_touch[uid] = now_mono
    if mark_daily:
        _daily_seen.add((uid, today))
