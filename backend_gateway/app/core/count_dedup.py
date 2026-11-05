"""下载/复制计数的冷却窗口去重 (2026-11-05).

同一 dedup_key 在 DEDUP_WINDOW_SECONDS 内对同一 code 只计一次, 窗口过后照常计.
并发安全: count_marks 的 (code, dedup_key) 唯一索引兜底 —— 两个并发请求
抢同一个新 key 时, 后 INSERT 的那个撞唯一索引 → 视为重复 (对方已计).
"""
from __future__ import annotations

from datetime import datetime, timedelta

from fastapi import Request
from sqlalchemy import update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.count import CountMark

DEDUP_WINDOW_SECONDS = 3600


def client_ip(request: Request) -> str:
    """客户端真实 IP —— 取 X-Forwarded-For 第一跳.

    ⚠️ 裸机部署里后端只监听 127.0.0.1、由 nginx 反代 → request.client.host
       恒为 127.0.0.1, 直接用它会把**所有人的**匿名下载都去重成一次.
    """
    fwd = request.headers.get("x-forwarded-for", "")
    if fwd:
        return fwd.split(",")[0].strip()
    return request.client.host if request.client else "unknown"


def user_key(uid: int) -> str:
    """登录用户的去重键."""
    return f"u:{uid}"


def ip_key(ip: str) -> str:
    """匿名请求的去重键."""
    return f"ip:{ip}"


def version_scope(code: str, version: str) -> str:
    """软件库版本计数的去重目标 —— 版本计数独立于条目计数."""
    return f"{code}@{version}"


async def bump_count(session: AsyncSession, code: str, dedup_key: str) -> bool:
    """判断这次操作要不要计数.

    窗口内重复 → False (不 +1); 新事件 / 窗口已过 → True (应 +1).

    ⚠️ 顺序必须是**先 INSERT 后 UPDATE** (标准 upsert): 反过来
       (先 UPDATE 后 INSERT) 时, 两个并发请求会各持一个 gap lock 再互相
       等对方的插入意向锁 → MySQL 间隙锁死锁, 在高并发下必现
       (单测单跑不触发, 全量并发跑会随机炸 —— 2026-11-05 实测).
       INSERT-first 只有一条"后插者等先插者"的锁链, 无环, 死锁免疫.
    """
    now = datetime.utcnow()
    cutoff = now - timedelta(seconds=DEDUP_WINDOW_SECONDS)

    # 1. 先试插入新标记; 撞唯一索引 = 行已存在 (savepoint 隔离, 不动 session
    #    里已 flush 的其他标记 —— 软件库一次下载要插两条: 条目 + 版本).
    try:
        async with session.begin_nested():
            session.add(CountMark(code=code, dedup_key=dedup_key, last_counted_at=now))
            await session.flush()
        return True
    except IntegrityError:
        pass

    # 2. 行存在 → 只翻新**已过期**的行: 行锁保证两个并发请求只有一个拿到
    #    rowcount=1 (另一个等锁释放后 WHERE 不再命中); 行没过期 → 窗口内重复.
    res = await session.execute(
        update(CountMark)
        .where(
            CountMark.code == code,
            CountMark.dedup_key == dedup_key,
            CountMark.last_counted_at < cutoff,
        )
        .values(last_counted_at=now)
    )
    return res.rowcount == 1
