"""通用跨进程文件锁 (flock).

用途:
  - git 操作串行化 (git 的 index.lock 是**仓库级**的, 并发 commit 必有一个失败)
  - 安装目录写入串行化 (同一目标目录并发安装会互相覆盖)

为什么不用 threading.Lock:
  flock 是**跨进程**的 —— 同一台机器上多个 TestMate 实例 (或宿主手工 git 操作)
  同时操作同一个工作区时, 只有 flock 能互斥. threading.Lock 只能保护单进程.

用法:
    with file_lock(path):
        ... 临界区 ...
"""
from __future__ import annotations

import fcntl
import os
from pathlib import Path


class file_lock:
    """flock 包装. 支持 with 语句."""

    def __init__(self, path: Path | str):
        self.path = Path(path)
        self.fd: int | None = None

    def __enter__(self) -> "file_lock":
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.fd = os.open(self.path, os.O_CREAT | os.O_RDWR, 0o600)
        fcntl.flock(self.fd, fcntl.LOCK_EX)
        return self

    def __exit__(self, *exc) -> None:
        if self.fd is not None:
            try:
                fcntl.flock(self.fd, fcntl.LOCK_UN)
            finally:
                os.close(self.fd)
                self.fd = None
