"""资产上传/更新任务 — 两阶段状态机.

    [API 同步阶段]  写本地工作区 + 更新 index.json + 建 job(staged)
                    → 用户立刻看到资产, 但状态是"待同步"
    [后台阶段]      git add → commit → push → job(pushed)
                    → 用户看到"已同步到 GitLab", 这才算真正共享出去

状态流转:
    pending ──写盘成功──> staged ──入队──> syncing ──push 成功──> pushed
                              ▲                 │
                              │                 ├── 可重试失败 ──> failed(待退避重试)
                              └───── 退避后重试 ─┘
                                                └── 需人工失败 ──> failed(终态)

为什么用单消费者队列而不是"每个 job 一个任务":
    git 的 index.lock 是**仓库级**的, 两个 job 并发 commit 必有一个失败.
    单消费者队列让同步天然串行, 不用在业务层处理冲突, 也不会把 index.lock
    错误暴露给用户.
"""
from __future__ import annotations

import asyncio
import logging
import re
from datetime import datetime, timedelta

from sqlalchemy import select

from app.core import git_sync
from app.db.session import AsyncSessionLocal
from app.models.asset import Asset, AssetJob

logger = logging.getLogger(__name__)

# git 阶段的最大自动重试次数 (超过就不再自动重试, 留给人工)
MAX_GIT_ATTEMPTS = 3
# 退避基数 (秒): 2s, 4s, 8s ...
BACKOFF_BASE_SEC = 2

# 单消费者队列 —— 保证 git 操作串行
_queue: asyncio.Queue[int] = asyncio.Queue()
_worker: asyncio.Task | None = None


# ==================== 队列 ====================

def start_worker() -> None:
    """启动后台消费者 (应用启动时调一次)."""
    global _worker
    if _worker is None or _worker.done():
        _worker = asyncio.create_task(_worker_loop())
        logger.info("asset_jobs.worker started")


def enqueue(job_id: int) -> None:
    _queue.put_nowait(job_id)


async def _worker_loop() -> None:
    logger.info("asset_jobs.worker loop running")
    while True:
        job_id = await _queue.get()
        try:
            await _process(job_id)
        except Exception:  # noqa: BLE001 — worker 绝不能因为单个 job 崩掉
            logger.exception("asset_jobs.worker unexpected error job=%s", job_id)
        finally:
            _queue.task_done()


# ==================== 处理单个 job ====================

async def _process(job_id: int) -> None:
    async with AsyncSessionLocal() as session:
        job = await session.get(AssetJob, job_id)
        if job is None:
            return
        if job.status == "pushed":
            return  # 幂等: 已完成的不重复推

        job.status = "syncing"
        job.attempts = (job.attempts or 0) + 1
        await session.commit()

        payload = dict(job.payload or {})
        asset_path = job.git_path or payload.get("manifest", {}).get("git_path", "")
        # author 存的是 [name, email]; 兼容历史上写成 "name <email>" 字符串的旧记录
        raw_author = payload.get("author")
        if isinstance(raw_author, (list, tuple)) and len(raw_author) == 2:
            author = (str(raw_author[0]), str(raw_author[1]))
        else:
            s = str(raw_author or "")
            m = re.match(r"^\s*(.*?)\s*<([^>]*)>\s*$", s)
            author = (m.group(1), m.group(2)) if m else ("testmate", "testmate@local")
        message = payload.get("commit_message") or (
            f"{'chore(market): 更新资产' if job.action == 'update' else 'feat(market): 上架资产'}"
            f" {job.asset_name} {payload.get('manifest', {}).get('version', '')}"
        )
        # 只提交本次资产目录 + index.json —— 绝不能 add -A
        paths = [p for p in [asset_path, "index.json"] if p]

        try:
            result = await git_sync.sync_paths(
                paths=paths, message=message, author=author
            )
        except git_sync.SyncError as e:
            await _handle_failure(session, job, e)
            return
        except Exception as e:  # noqa: BLE001
            # 自身代码的异常重试也没用 —— 归为 internal, 不自动重试
            await _handle_failure(
                session, job,
                git_sync.SyncError(
                    f"内部错误: {type(e).__name__}: {e}", "internal",
                    hint="这是服务端 bug, 请查看后端日志",
                ),
            )
            return

        job = await session.get(AssetJob, job_id)
        if job is None:
            return
        if result.no_change:
            job.status = "pushed"
            job.error = ""
            job.pushed_at = datetime.utcnow()
            logger.info("asset_job no-change, treated as pushed code=%s", job.code)
        else:
            job.status = "pushed"
            job.commit_sha = result.commit_sha
            job.error = ""
            job.pushed_at = datetime.utcnow()
            logger.info(
                "asset_job pushed id=%s code=%s sha=%s",
                job_id, job.code, result.commit_sha[:12],
            )
        await session.commit()

        # 同步 DB 镜像里的 commit sha + 同步状态
        if result.commit_sha:
            async with AsyncSessionLocal() as s2:
                a = (
                    await s2.execute(select(Asset).where(Asset.code == job.code))
                ).scalar_one_or_none()
                if a is not None:
                    a.git_commit_sha = result.commit_sha
                    a.sync_status = "pushed"
                    a.last_error = ""
                    await s2.commit()
        else:
            # 无变更也算已同步 (内容本来就与远端一致)
            async with AsyncSessionLocal() as s2:
                a = (
                    await s2.execute(select(Asset).where(Asset.code == job.code))
                ).scalar_one_or_none()
                if a is not None:
                    a.sync_status = "pushed"
                    a.last_error = ""
                    await s2.commit()


async def _handle_failure(session, job: AssetJob, err: git_sync.SyncError) -> None:
    """失败处理: 可重试 → 退避后重新入队; 不可重试 → 停在 failed 等人工."""
    job = await session.get(AssetJob, job.id)
    if job is None:
        return
    job.status = "failed"
    job.error = (f"[{err.category}] {err}" + (f" — {err.hint}" if err.hint else ""))[:2000]
    # 资产本身仍在本地工作区, 只是没推到 GitLab —— 同步状态记 failed
    async with AsyncSessionLocal() as s2:
        a = (
            await s2.execute(select(Asset).where(Asset.code == job.code))
        ).scalar_one_or_none()
        if a is not None:
            a.sync_status = "failed"
            a.last_error = job.error
            await s2.commit()

    if err.retryable and (job.attempts or 0) < MAX_GIT_ATTEMPTS:
        delay = BACKOFF_BASE_SEC ** (job.attempts or 1)
        job.next_retry_at = datetime.utcnow() + timedelta(seconds=delay)
        await session.commit()
        logger.warning(
            "asset_job retryable failure code=%s attempt=%s/%s in %ss: %s",
            job.code, job.attempts, MAX_GIT_ATTEMPTS, delay, err,
        )
        asyncio.create_task(_delayed_requeue(job.id, delay))
    else:
        job.next_retry_at = None
        await session.commit()
        logger.error(
            "asset_job failed (final) code=%s attempt=%s category=%s: %s",
            job.code, job.attempts, err.category, err,
        )


async def _delayed_requeue(job_id: int, delay: int) -> None:
    await asyncio.sleep(delay)
    enqueue(job_id)


# ==================== 启动恢复 ====================

async def recover_pending_jobs() -> int:
    """启动时把待同步 / 卡住的 job 重新入队.

    staged   —— 文件已落本地, 但上次没推上去 → 继续推
    syncing  —— 上次推到一半崩了 → 继续推
    pending  —— 还没写盘 (极少见) → 重新走一遍
    failed   —— 不自动重试 (只有明确可重试的才会被重新入队)
    """
    async with AsyncSessionLocal() as session:
        rows = (
            await session.execute(
                select(AssetJob).where(AssetJob.status.in_(("staged", "syncing", "pending")))
            )
        ).scalars().all()
        ids = [j.id for j in rows]
    if ids:
        for i in ids:
            enqueue(i)
        logger.info("asset_jobs.recover re-queued %s job(s)", len(ids))
    return len(ids)


async def retry_job(job_id: int) -> bool:
    """人工重试: 把 job 置回 staged 并重新入队."""
    async with AsyncSessionLocal() as session:
        job = await session.get(AssetJob, job_id)
        if job is None:
            return False
        job.status = "staged"
        job.error = ""
        job.attempts = 0
        job.next_retry_at = None
        await session.commit()
    enqueue(job_id)
    return True
