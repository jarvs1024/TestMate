"""资产市场 — 本地 git 工作区 + GitLab SSH 同步层.

设计 (方案 A):
    读路径 (同步, 快)  前端 → 后端 → 本地工作区 (git working copy)
    写路径 (异步)      上传 → 写本地目录 (毫秒) → job=staged
                                  → 后台 git add/commit/push → job=pushed

为什么不用 GitLab REST API:
    本地工作区就是仓库的 working copy, 读列表/读文件/预览全部本地直读,
    不需要任何 API 调用 —— 也就没有 PAT、没有 token 过期、没有 API 限流.
    只有"远端有没有被人改过"需要 fetch, 走 SSH 即可.

并发安全 (两层):
    1. asyncio.Lock —— 同一进程内串行化
    2. fcntl.flock  —— 跨进程串行化 (宿主机上若另有 git 操作, 也不会撞 index.lock)

错误分类 (决定前端提示 + 是否自动重试):
    validation / disk / auth / repo / nonfastforward → 需人工, 不自动重试
    lock / commit / network / unknown               → 可重试, 指数退避
"""
from __future__ import annotations

import asyncio
import logging
import os
import re
import shutil
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from app.core.file_lock import file_lock

logger = logging.getLogger(__name__)

# ===== 配置 =====
WORKSPACE = Path(os.environ.get("MARKET_WORKSPACE", "/workspace"))
# 远端与分支是**运行时配置** —— 设置页可以改, 改完立即生效.
# 为什么不是直接读 settings_store: 这里是**同步**代码, 而 settings_store.get 是 async.
# 折中: 设置变更时 (settings API) 调 set_git_config() 更新内存值,
#       进程启动时再从 DB 装载一次 (见 app/main.py 的 lifespan).
# env 只作初值 —— 改了设置页的值, env 就该让位.
DEFAULT_GIT_REMOTE = "ssh://git@host.docker.internal:8922/root/testmate-market.git"
_git_cfg: dict[str, str] = {
    "remote": os.environ.get("MARKET_GIT_REMOTE", DEFAULT_GIT_REMOTE),
    "branch": os.environ.get("MARKET_GIT_BRANCH", "main"),
}


def git_remote() -> str:
    """当前生效的 GitLab 远端地址."""
    return _git_cfg["remote"]


def git_branch() -> str:
    """当前生效的 GitLab 分支."""
    return _git_cfg["branch"]


def set_git_config(*, remote: str | None = None, branch: str | None = None) -> None:
    """设置页改了仓库地址/分支后调用 —— 立即生效, 无需重启."""
    if remote is not None and remote.strip():
        _git_cfg["remote"] = remote.strip()
    if branch is not None and branch.strip():
        _git_cfg["branch"] = branch.strip()


# 锁文件放在工作区**外面** —— 放里面会变成 git untracked 文件, 污染 status
# (工作区本身是远端仓库的 working copy, 不能随便往里塞文件)
LOCK_FILE = WORKSPACE.parent / f"{WORKSPACE.name}.sync.lock"

# 可重试的错误类别 —— 这些会走后台指数退避重试
# (missing 不在其中: 文件压根没落盘, 重试无意义)
RETRYABLE = {"lock", "commit", "network", "unknown"}


class SyncError(RuntimeError):
    """带错误分类的同步异常."""

    def __init__(self, message: str, category: str, *, hint: str = ""):
        super().__init__(message)
        self.category = category
        self.hint = hint

    @property
    def retryable(self) -> bool:
        return self.category in RETRYABLE


# ===== git 命令封装 =====

def _run_git(args: list[str], *, cwd: Path, timeout: int = 60) -> tuple[int, str, str]:
    """跑一条 git 命令, 返回 (rc, stdout, stderr)."""
    import subprocess

    env = {**os.environ, "GIT_TERMINAL_PROMPT": "0", "GIT_ASKPASS": "/bin/true"}
    try:
        p = subprocess.run(
            ["git", "-C", str(cwd), *args],
            capture_output=True,
            text=True,
            timeout=timeout,
            env=env,
        )
        return p.returncode, p.stdout, p.stderr
    except FileNotFoundError as e:
        raise SyncError("容器内没有 git 可执行文件", "repo", hint="镜像需安装 git") from e
    except subprocess.TimeoutExpired as e:
        raise SyncError(f"git {args[0]} 超时 ({timeout}s)", "network") from e


def _classify(stderr: str, rc: int) -> SyncError:
    """把 git 的 stderr 归类成可重试 / 需人工."""
    s = (stderr or "").lower()
    hint = ""

    if "index.lock" in s or "cannot lock ref" in s or "unable to create" in s and "lock" in s:
        return SyncError("仓库被占用 (index.lock), 稍后重试", "lock", hint="等待当前 git 操作完成")
    if "cannot pull with rebase" in s or "unstaged changes" in s or "please commit your changes" in s:
        # 并发上传往工作区写了新文件, 导致 rebase 拒绝 —— 是瞬时状态, 重试即可
        return SyncError("工作区有并发写入, 稍后重试", "lock")
    if "host key verification failed" in s:
        return SyncError(
            "SSH 主机密钥校验失败", "auth",
            hint="把 GitLab 的主机公钥加入 known_hosts 后重试",
        )
    if "permission denied" in s and "publickey" in s:
        return SyncError(
            "SSH 认证失败 (公钥未被接受)", "auth",
            hint="确认 ~/.ssh/id_ed25519 已添加到 GitLab 账号的 SSH Keys",
        )
    if "could not resolve hostname" in s or "connection refused" in s \
            or "connection timed out" in s or "network is unreachable" in s \
            or "connection reset" in s or "broken pipe" in s:
        return SyncError("网络异常, 无法连接 GitLab", "network")
    if "non-fast-forward" in s or "fetch first" in s or "rejected" in s and "push" in s:
        return SyncError("远端有新提交, 本地被拒绝", "nonfastforward",
                         hint="远端有他人改动, 需人工合并")
    if "does not appear to be a git repository" in s or "not a git repository" in s:
        return SyncError("工作区不是 git 仓库", "repo", hint="检查 MARKET_WORKSPACE 挂载")
    if "could not read from remote repository" in s or "repository not found" in s:
        return SyncError("远端仓库不存在或无访问权限", "repo")
    if "no space left" in s or "disk" in s and "full" in s:
        return SyncError("磁盘空间不足", "disk", hint="清理磁盘后重试")
    if "permission denied" in s and "lock" not in s:
        return SyncError("文件权限不足", "disk", hint="检查工作区目录权限")
    if "nothing to commit" in s or "no changes added to commit" in s:
        return SyncError("没有需要提交的变更", "commit")
    if "pathspec" in s and "did not match" in s:
        # 资产目录在工作区里不存在 —— 说明落盘环节没成功, 重试也没用
        return SyncError("资产文件在工作区中不存在", "missing",
                         hint="重新上传该资产以补齐文件")
    return SyncError(f"git 失败 (rc={rc}): {(stderr or '').strip()[:300]}", "unknown")


# ===== 进程内 + 跨进程 串行锁 =====

_async_lock = asyncio.Lock()

# 跨进程锁用共享实现 (app/core/file_lock.py) —— 安装写盘也要用同一把锁
_FileLock = file_lock


# ===== 工作区准备 =====

def _sync_remote_url() -> None:
    """把本地仓库的 origin 指向当前配置的远端."""
    rc, so, _ = _run_git(["remote", "get-url", "origin"], cwd=WORKSPACE)
    if rc != 0:
        _run_git(["remote", "add", "origin", git_remote()], cwd=WORKSPACE)
        return
    if so.strip() != git_remote().strip():
        logger.info(
            "git_sync 更新 origin: %s → %s", so.strip(), git_remote(),
        )
        _run_git(["remote", "set-url", "origin", git_remote()], cwd=WORKSPACE)


def ensure_workspace() -> Path:
    """确保工作区是一个可用的 git working copy.

    已有 .git → 直接用 (宿主机上 clone 过).
    没有     → init + remote add + fetch + checkout.
    """
    WORKSPACE.mkdir(parents=True, exist_ok=True)
    if (WORKSPACE / ".git").exists():
        # 仓库已在 —— 但**远端地址可能被设置页改过**, 必须同步, 否则
        # "改了仓库地址却说生效了, 实际还推去老仓库" (实测踩过).
        _sync_remote_url()
        return WORKSPACE

    logger.info("git_sync.init_workspace path=%s remote=%s", WORKSPACE, git_remote())
    rc, so, se = _run_git(["init"], cwd=WORKSPACE)
    if rc != 0:
        raise SyncError(f"git init 失败: {se.strip()[:200]}", "repo")

    rc, so, se = _run_git(["remote", "add", "origin", git_remote()], cwd=WORKSPACE)
    if rc != 0:
        # 已经存在 origin → 改 URL (远端地址可能被改过)
        _run_git(["remote", "set-url", "origin", git_remote()], cwd=WORKSPACE)
    rc, so, se = _run_git(["fetch", "origin", git_branch()], cwd=WORKSPACE, timeout=120)
    if rc != 0:
        # 远端还没有任何 commit (空仓库) — 没关系, 本地建个孤儿分支即可
        if "couldn't find remote ref" in se.lower() or "not found" in se.lower():
            _run_git(["checkout", "-b", git_branch()], cwd=WORKSPACE)
            return WORKSPACE
        raise _classify(se, rc)

    _run_git(["checkout", "-B", git_branch(), f"origin/{git_branch()}"], cwd=WORKSPACE)
    return WORKSPACE


# ===== 写本地 =====

def write_text(rel_path: str, content: str) -> None:
    """写一个文件到工作区 (自动建目录)."""
    target = WORKSPACE / rel_path
    try:
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content, encoding="utf-8")
    except OSError as e:
        raise SyncError(f"写入 {rel_path} 失败: {e.strerror or e}", "disk") from e


def remove_path(rel_path: str) -> None:
    target = WORKSPACE / rel_path
    if target.is_dir():
        shutil.rmtree(target, ignore_errors=True)
    elif target.exists():
        target.unlink()


def read_text(rel_path: str) -> str | None:
    target = WORKSPACE / rel_path
    if not target.is_file():
        return None
    try:
        return target.read_text(encoding="utf-8")
    except OSError:
        return None


# ===== git 操作 =====

def _stage(paths: list[str]) -> None:
    """只 add 指定路径 —— 绝不能用 add -A, 否则会把别的 job 正在写的文件混进本次 commit."""
    if not paths:
        return
    rc, so, se = _run_git(["add", "-A", "--", *paths], cwd=WORKSPACE)
    if rc != 0:
        raise _classify(se, rc)


def _commit(message: str, paths: list[str], author: tuple[str, str]) -> str:
    name, email = author
    rc, so, se = _run_git(
        ["-c", f"user.name={name}", "-c", f"user.email={email}",
         "commit", "-m", message, "--", *paths],
        cwd=WORKSPACE,
    )
    if rc != 0:
        # ⚠️ git 的 "nothing to commit" 打在 **stdout**, 不是 stderr ——
        #    只查 stderr 会把"没东西可提交"当成硬错误抛出去.
        #    (实测踩过: 提交成功但推送失败后的重试, 每次都卡在这, 资产永远推不上去)
        combined = f"{se}\n{so}".lower()
        if "nothing to commit" in combined or "no changes added to commit" in combined:
            return ""   # 内容没变, 视为无事可做 (幂等)
        raise _classify(se, rc)
    rc, so, se = _run_git(["rev-parse", "HEAD"], cwd=WORKSPACE)
    return so.strip()


def tracked_files(rel_path: str) -> list[str]:
    """该路径下已被 git 跟踪的文件列表 (没跟踪过就是空).

    用途: 删除资产时, 如果这个资产**从来没被提交过** (比如推送失败),
    它的路径就不在 git 里 —— 此时再拿它去 `git commit -- <path>` 会报
    "pathspec did not match any files", 整个删除操作失败 (502).
    """
    rc, so, _ = _run_git(["ls-files", "--", rel_path], cwd=WORKSPACE)
    return [ln for ln in so.splitlines() if ln.strip()] if rc == 0 else []


def _head_sha() -> str:
    rc, so, _ = _run_git(["rev-parse", "HEAD"], cwd=WORKSPACE)
    return so.strip() if rc == 0 else ""


def _ahead_of_remote() -> int:
    """本地 HEAD 比远端多几个 commit (没 fetch 过就算 0)."""
    rc, so, _ = _run_git(
        ["rev-list", "--count", f"origin/{git_branch()}..HEAD"], cwd=WORKSPACE
    )
    try:
        return int(so.strip()) if rc == 0 else 0
    except ValueError:
        return 0


def _push() -> str:
    """push 到远端. 远端有新提交时先 rebase, 冲突则放弃并报需人工处理."""
    rc, so, se = _run_git(["fetch", "origin", git_branch()], cwd=WORKSPACE, timeout=120)
    if rc != 0:
        raise _classify(se, rc)

    rc, so, se = _run_git(
        ["rev-list", "--count", f"HEAD..origin/{git_branch()}"], cwd=WORKSPACE
    )
    behind = so.strip() if rc == 0 else "0"
    if behind and behind != "0":
        # 本地落后 → rebase 到远端之上
        rc, so, se = _run_git(
            ["pull", "--rebase", "origin", git_branch()], cwd=WORKSPACE, timeout=120
        )
        if rc != 0:
            _run_git(["rebase", "--abort"], cwd=WORKSPACE)
            low = se.lower()
            if "conflict" in low:
                raise SyncError(
                    "远端有改动, rebase 冲突需人工处理", "nonfastforward",
                    hint="在宿主工作区手动 git pull --rebase 解决冲突后重试",
                )
            if "unstaged changes" in low or "cannot pull with rebase" in low:
                # 并发上传正在写工作区 → 本次跳过 rebase, 直接试 push
                # (push 会被拒 → 归为 nonfastforward, 由重试机制兜底)
                logger.warning("git_sync.push skip rebase: 工作区有并发写入")
            else:
                raise _classify(se, rc)

    rc, so, se = _run_git(
        ["push", "origin", f"HEAD:{git_branch()}"], cwd=WORKSPACE, timeout=180
    )
    if rc != 0:
        raise _classify(se, rc)
    rc, so, se = _run_git(["rev-parse", "HEAD"], cwd=WORKSPACE)
    return so.strip()


# ===== 对外主入口 =====

@dataclass
class SyncResult:
    commit_sha: str
    pushed: bool
    no_change: bool = False


def sync_paths_blocking(
    *,
    paths: list[str],
    message: str,
    author: tuple[str, str],
) -> SyncResult:
    """把指定路径 commit + push. 阻塞版本 (在线程里跑)."""
    with _FileLock(LOCK_FILE):
        ensure_workspace()
        _stage(paths)
        sha = _commit(message, paths, author)
        if not sha:
            # 没有新提交 —— 但可能是「上次提交成功、推送失败」后的重试,
            # 这时**必须继续推**, 否则本地永远领先远端, 资产卡在机器上.
            head = _head_sha()
            if not head or _ahead_of_remote() <= 0:
                return SyncResult(commit_sha="", pushed=False, no_change=True)
            sha = head
        pushed_sha = _push()
        return SyncResult(commit_sha=pushed_sha or sha, pushed=True)


async def sync_paths(
    *,
    paths: list[str],
    message: str,
    author: tuple[str, str],
) -> SyncResult:
    """异步版: 进程内锁 + 线程池执行阻塞的 git 操作."""
    async with _async_lock:
        return await asyncio.to_thread(
            sync_paths_blocking, paths=paths, message=message, author=author
        )


def probe_remote() -> tuple[bool, str]:
    """探当前配置的远端能不能连上 (SSH 鉴权 + 仓库可达).

    设置页的「测试仓库连接」用这个 —— 测的是**真正会用来推送的那个地址**,
    而不是某个写死的默认值. 返回 (ok, 给人看的说明).
    """
    remote, branch = git_remote(), git_branch()
    if not remote:
        return False, "未配置 GitLab 仓库地址 (marketplace.git.remote)"
    rc, so, se = _run_git(
        ["ls-remote", "--heads", remote], cwd=WORKSPACE, timeout=15,
    )
    if rc != 0:
        return False, f"连不上 {remote} —— {(se or so).strip()[:180]}"
    heads: list[str] = []
    for ln in so.splitlines():
        ln = ln.strip()
        if not ln:
            continue
        ref = ln.split()[-1]          # refs/heads/main
        if ref.startswith("refs/heads/"):
            heads.append(ref[len("refs/heads/"):])
    if branch not in heads:
        return False, (
            f"仓库可达, 但没有分支 {branch} (现有分支: {', '.join(heads) or '无'})"
        )
    return True, f"仓库可达 · 分支 {branch} · 共 {len(heads)} 个分支"


def workspace_status() -> dict:
    """给设置页/探针用: 工作区与远端的状态概览."""
    info: dict = {
        "workspace": str(WORKSPACE),
        "remote": git_remote(),
        "branch": git_branch(),
        "is_repo": (WORKSPACE / ".git").exists(),
    }
    if not info["is_repo"]:
        return info
    rc, so, se = _run_git(["status", "--porcelain"], cwd=WORKSPACE)
    info["dirty_files"] = [ln for ln in so.splitlines() if ln.strip()][:50]
    rc, so, se = _run_git(["rev-parse", "--short", "HEAD"], cwd=WORKSPACE)
    info["head"] = so.strip() if rc == 0 else ""
    return info


# ---------- 拉取侧原语 (GitLab → TestMate) ----------

def read_text_at_ref(file_path: str, ref: str) -> str | None:
    """读某个 ref 上的文件内容 (不落盘)."""
    rc, so, se = _run_git(["show", f"{ref}:{file_path}"], cwd=WORKSPACE)
    return so if rc == 0 else None


def list_files_at_ref(ref: str) -> list[str]:
    """列出某个 ref 上的全部文件路径."""
    rc, so, se = _run_git(["ls-tree", "-r", "--name-only", ref], cwd=WORKSPACE)
    return [ln for ln in so.splitlines() if ln.strip()] if rc == 0 else []


def checkout_from_ref(ref: str, paths: list[str]) -> bool:
    """把指定路径恢复到某个 ref 的内容 (用于把远端版本拉到本地工作区)."""
    if not paths:
        return True
    rc, so, se = _run_git(["checkout", ref, "--", *paths], cwd=WORKSPACE)
    if rc != 0:
        logger.warning("git_sync.checkout_from_ref 失败 ref=%s paths=%s err=%s", ref, paths, se.strip()[:200])
    return rc == 0


def commit_time(ref: str) -> datetime | None:
    """取某个 ref 的最新提交时间 (冲突判定用: 同版本时后推的胜)."""
    rc, so, se = _run_git(["log", "-1", "--format=%cI", ref], cwd=WORKSPACE)
    if rc != 0 or not so.strip():
        return None
    try:
        return datetime.fromisoformat(so.strip())
    except ValueError:
        return None


def parse_semver(v: str) -> tuple[int, int, int]:
    """解析 semver 前三段; 解析不出来按 0 处理."""
    core = (v or "").lstrip("v").split("+")[0].split("-")[0]
    parts = core.split(".")
    out = []
    for i in range(3):
        try:
            out.append(int(parts[i]) if i < len(parts) else 0)
        except ValueError:
            out.append(0)
    return (out[0], out[1], out[2])


def semver_gt(a: str, b: str) -> bool:
    """a 的版本是否严格高于 b."""
    return parse_semver(a) > parse_semver(b)
