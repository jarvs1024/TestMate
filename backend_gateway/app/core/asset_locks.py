"""按资产 code 串行化 —— 防止并发写同一个资产时互相覆盖.

为什么需要这把锁:
    git 提交是**仓库级**串行的 (asset_jobs 的单消费者队列), 但**落盘阶段**
    (解包 → 写 files/ → 写 manifest.json) 发生在请求线程里, 不在队列里.
    于是两个并发上传同一个 code 时:
        A 解包写入 files/SKILL.md  (写了一半)
        B 解包写入 files/SKILL.md  (覆盖)
        A 建 job → 队列提交 → 把 B 的半成品一起 commit 上去
    结果是仓库里一个**谁都没上传过**的混合体.

    这里给每个 code 一把锁, 落盘 → 建 job 整段在锁内:
      - asyncio.Lock 保护单进程内的并发请求
      - flock 保护跨进程 (多实例 / 宿主手工操作)

⚠️ 锁文件放在工作区**外面** —— 免得被 `git add -A` 带进仓库, 弄脏工作区.
"""
from __future__ import annotations

import asyncio
import logging
from contextlib import asynccontextmanager
from typing import AsyncIterator

from app.core import git_sync
from app.core.file_lock import file_lock

logger = logging.getLogger(__name__)

_locks: dict[str, asyncio.Lock] = {}
_guard = asyncio.Lock()


def _lock_path(code: str) -> str:
    """锁文件路径 —— 与 git_sync.LOCK_FILE 同套路, 放在工作区外面."""
    return str(git_sync.WORKSPACE.parent / f"{git_sync.WORKSPACE.name}.code-{code}.lock")


class _AsyncFileLock:
    """flock 的异步包装.

    flock 的获取是**阻塞**调用, 直接在事件循环里调会把整个后端卡住 ——
    所以丢到线程池里执行. 锁本身是进程级的 (关联 open file description),
    在别的线程释放也有效.
    """

    def __init__(self, path: str):
        self.path = path
        self._fl: file_lock | None = None

    async def __aenter__(self) -> "_AsyncFileLock":
        self._fl = await asyncio.to_thread(self._acquire)
        return self

    async def __aexit__(self, *exc) -> None:
        if self._fl is not None:
            fl, self._fl = self._fl, None
            await asyncio.to_thread(fl.__exit__, None, None, None)

    def _acquire(self) -> file_lock:
        fl = file_lock(self.path)
        fl.__enter__()
        return fl


@asynccontextmanager
async def code_lock(code: str) -> AsyncIterator[None]:
    """同一 code 的写操作互斥 (上传 / 更新 / 删除)."""
    async with _guard:
        lk = _locks.setdefault(code, asyncio.Lock())
    async with lk:
        async with _AsyncFileLock(_lock_path(code)):
            logger.debug("asset_locks.acquire code=%s", code)
            try:
                yield
            finally:
                logger.debug("asset_locks.release code=%s", code)
