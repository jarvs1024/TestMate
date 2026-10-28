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
import json
import logging
import os
import re
import shutil
import threading
import time
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from app.core.file_lock import file_lock
from app.core.settings_store import _in_container

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


def _rewrite_remote(url: str) -> str:
    """把远端地址里的"本机"改成**当前这个进程能连上的那个本机** —— 两个方向都改.

    ⚠️ 为什么 git 远端要单独改写, 不能直接套 settings_store 的那套:
       git 远端是 **SSH URL** (`ssh://git@host:port/path`), 不是 HTTP ——
       正则不一样, 而且 SSH 的 "本机" 有两层含义:
         · 容器里的 127.0.0.1 是容器自己 → 要走 host.docker.internal 才到得了宿主
         · 宿主上的 host.docker.internal 解析到 Docker 虚拟网卡 (198.18.x.x),
           从宿主侧 TCP 能连上但**没有服务应答** → 要换回 127.0.0.1
       (GitLab 的 SSH 端口是 Docker 映射出来的, 宿主上 127.0.0.1:8922 就是它.)

    好处跟 HTTP 那套一样: **同一个设置值在两种部署模式下都通** ——
    裸机部署 (deploy/native) 的后端在宿主上跑, 不用改 /etc/hosts (那要 root),
    也不用为了切模式去改设置页里的仓库地址.
    """
    raw = (url or "").strip()
    if not raw:
        return url
    m = re.match(
        r"^(?P<scheme>[A-Za-z][A-Za-z0-9+.\-]*://)"
        r"(?:(?P<user>[^@/]+)@)?"
        r"(?P<host>[^:/]+)"
        r"(?P<tail>.*)$",
        raw,
    )
    if not m:
        return url
    host = m.group("host")
    if _in_container():
        if host in ("127.0.0.1", "localhost", "::1"):
            host = "host.docker.internal"
    elif host == "host.docker.internal":
        host = "127.0.0.1"
    if host == m.group("host"):
        return url
    user = m.group("user")
    return (
        f"{m.group('scheme')}"
        f"{user + '@' if user else ''}"
        f"{host}{m.group('tail')}"
    )


def git_remote() -> str:
    """当前生效的 GitLab 远端地址 (已按当前部署模式改写过 host)."""
    return _rewrite_remote(_git_cfg["remote"])


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
# (missing 不在其中: 文件压根没落盘, 重试无意义;
#  repo 不在其中: 远端没这个分支 / 没鉴权, 重试没用, 得人工处理)
#
# ⚠️ concurrent (2026-10-25): 远端有他人提交导致的 push 被拒 —— 退避后重试通常就过去了,
#    以前归成 nonfastforward (不可重试) → 一次瞬时并发就把资产打成终态失败.
RETRYABLE = {"lock", "commit", "network", "unknown", "concurrent"}


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
        # ⚠️ git 被超时杀掉时, 可能留下 .git/index.lock —— 之后**所有** git 操作都会
        #    撞它, 被归类成可重试的 "lock", 但重试永远不会成功 (没人删这个文件).
        #    这里主动清一次: 只在锁文件"存在且明显陈旧"时才删, 免得删掉别人正在用的.
        _cleanup_stale_index_lock()
        raise SyncError(f"git {args[0]} 超时 ({timeout}s)", "network") from e


def _cleanup_stale_index_lock() -> None:
    """清掉陈旧的 .git/index.lock (git 被超时杀掉时留下的).

    ⚠️ 只在**明显陈旧** (超过 2 分钟) 时才删 —— 正常的 git 操作持锁是毫秒级的,
       2 分钟还在的话基本可以断定是残留 (2026-10-25 审计).
    """
    lock = WORKSPACE / ".git" / "index.lock"
    try:
        if not lock.exists():
            return
        age = time.time() - lock.stat().st_mtime
        if age < 120:
            return
        lock.unlink()
        logger.warning("清理了陈旧的 index.lock (已存在 %.0f 秒)", age)
    except OSError as e:
        logger.warning("清理 index.lock 失败: %s", e)


def _classify(stderr: str, rc: int) -> SyncError:
    """把 git 的 stderr 归类成可重试 / 需人工."""
    s = (stderr or "").lower()
    hint = ""

    if "index.lock" in s or "cannot lock ref" in s or "unable to create" in s and "lock" in s:
        return SyncError("仓库被占用 (index.lock), 稍后重试", "lock",
                         hint="等待当前 git 操作完成; 若一直报这个, 检查 .git/index.lock "
                              "是不是上次超时的残留 (超过 2 分钟会被自动清理)")
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
        # ⚠️ 归为 **concurrent (可重试)**: 这通常是"另一个 job 正在提交 / 远端刚被别人推了",
        #    退避后重试通常就过去了.
        #    以前归成 nonfastforward (不可重试) → 一次瞬时并发就把资产打成**终态失败**,
        #    而 recover_pending_jobs 不重排 failed → 重启也不自愈, 只能人工重试.
        return SyncError("远端有新提交, 本地被拒绝 (并发提交冲突)", "concurrent",
                         hint="通常是并发提交导致的瞬时冲突, 系统会自动退避重试")
    if "couldn't find remote ref" in s or "could not find remote ref" in s:
        # ⚠️ 远端**没有这个分支** —— 不是并发, 重试多少次都没用, 得人工建分支.
        #    以前落到 unknown (可重试) → 每次都耗满退避次数, 最后报个看不懂的错.
        return SyncError("远端没有这个分支", "repo",
                         hint="在 GitLab 上创建该分支, 或改设置里的分支名")
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
    """写一个文件到工作区 (自动建目录).

    ⚠️ **原子写** (2026-10-25): 以前是 `target.write_text(...)` —— 直接截断重写.
       两个线程同时写 index.json 时会写出**截断的 JSON**, 而 read_index 遇解析失败
       是静默返回 None 的 (market_catalog.py:282-290) → 回灌无声无息地什么都不做.
       现在先写同目录的临时文件, 再 os.replace 原子替换 —— 读者要么看到旧内容,
       要么看到新内容, 不会是半截的.
    """
    target = WORKSPACE / rel_path
    tmp = None
    try:
        target.parent.mkdir(parents=True, exist_ok=True)
        # 临时文件必须**同目录** —— os.replace 只在同一文件系统内保证原子性
        tmp = target.with_name(target.name + f".tmp-{os.getpid()}-{threading.get_ident()}")
        tmp.write_text(content, encoding="utf-8")
        os.replace(tmp, target)
        tmp = None
    except OSError as e:
        raise SyncError(f"写入 {rel_path} 失败: {e.strerror or e}", "disk") from e
    finally:
        if tmp is not None:
            try:
                tmp.unlink()
            except OSError:
                pass


def index_codes_at_ref(ref: str) -> set[str]:
    """某个 ref 上的 index.json 里有哪些 code.

    用途: 上传前查"git 里是不是已经有这个 code" ——
    本地 DB 只是远端的镜像, 可能落后, 只查 DB 会漏掉**幽灵资产**
    (git 里有、DB 里没有), 同 code 的新上传就会静默覆盖别人的资产.
    """
    raw = read_text_at_ref("index.json", ref)
    if not raw:
        return set()
    try:
        data = json.loads(raw)
    except (json.JSONDecodeError, TypeError):
        return set()
    out: set[str] = set()
    for e in (data.get("assets") or []):
        if isinstance(e, dict) and e.get("code"):
            out.add(str(e["code"]))
    return out


def remove_path(rel_path: str) -> None:
    target = WORKSPACE / rel_path
    if target.is_dir():
        shutil.rmtree(target, ignore_errors=True)
    elif target.exists():
        target.unlink()


def safe_rel_path(rel_path: str) -> str | None:
    """把"仓库里的相对路径"归一化; 不安全就返回 None.

    ⚠️ 为什么需要这道闸: index.json 是**远端**内容 (GitLab 仓库里的文件) ——
       谁有仓库写权限, 谁就能改它. 而里面的 ``git_path`` 会被拼成
       ``WORKSPACE / git_path`` 去**读文件** (下载 / 看文件列表 / 打包).
       不挡的话, 一个 "../../../app/.env" 就能把容器里的 JWT_SECRET 读出来 ——
       **仓库写权限 ≠ 服务器文件读权限**, 这中间不能有一步跳跃.

    规则 (刻意保守, 合法路径本来就不含这些):
      · 不许绝对路径 (``/etc/passwd``)
      · 不许任何 ``..`` 段 (哪怕是 ``a/../b`` 这种"看着无害"的)
      · 不许空路径
    """
    s = (rel_path or "").strip().replace("\\", "/")
    if not s or s.startswith("/"):
        return None
    parts: list[str] = []
    for seg in s.split("/"):
        if seg in ("", "."):
            continue
        if seg == "..":
            return None
        parts.append(seg)
    if not parts:
        return None
    return "/".join(parts)


def resolve_in_workspace(rel_path: str) -> Path | None:
    """把相对路径解析成工作区内的绝对路径; 越界就返回 None.

    ⚠️ 这是**读侧**的第二道闸 —— 即使 DB 里已经存进了脏数据 (比如老版本留下的),
       也不会被拼成 WORKSPACE 之外的路径.
    """
    safe = safe_rel_path(rel_path)
    if not safe:
        return None
    base = WORKSPACE.resolve()
    target = (base / safe).resolve()
    # resolve 之后还在 base 之下才算合法 (挡掉符号链接逃逸)
    if target != base and base not in target.parents:
        return None
    return target


def clean_path(rel_path: str) -> bool:
    """删掉某路径下**未被 git 跟踪**的文件 (落盘失败的残留清理用).

    ⚠️ 为什么不用 rmtree: 更新场景下目录里还有**上一个版本**的文件 (已经被提交到
       git 了), 整个删掉等于"下次提交会把旧版本的文件也删了".
       先 checkout 回 HEAD 恢复旧文件, 再用这个把 HEAD 里没有的残留清掉.
    """
    rc, so, se = _run_git(["clean", "-fd", "--", rel_path], cwd=WORKSPACE)
    if rc != 0:
        logger.warning("git_sync.clean_path 失败 path=%s err=%s", rel_path, se.strip()[:200])
        return False
    return True


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


def head_sha() -> str:
    """当前 HEAD 的 sha (公开版).

    调用方在**做一件可能失败的事之前**记下来 —— push 失败时靠它把本地那条
    commit 撤掉 (见 undo_local_commit). 不记的话就只能"猜"HEAD 是不是自己的.
    """
    return _head_sha()


def _remote_branch_exists() -> bool:
    """远端**有没有**这个分支."""
    rc, so, _ = _run_git(
        ["ls-remote", "--heads", git_remote(), git_branch()], cwd=WORKSPACE, timeout=15
    )
    return rc == 0 and bool(so.strip())


def _remote_has_any_ref() -> bool:
    """远端仓库上**有没有任何**分支 (用来区分"空仓库"和"分支名写错了")."""
    rc, so, _ = _run_git(["ls-remote", "--heads", git_remote()], cwd=WORKSPACE, timeout=15)
    return rc == 0 and bool(so.strip())


def _ahead_of_remote() -> int:
    """本地 HEAD 比远端多几个 commit.

    ⚠️ 远端**没有这个 ref** 时返回 **-1** (不是 0) ——
       0 会被当成"没有待推的 commit", 于是 no_change 快捷路径把资产标成"已推送",
       而远端其实什么都没有 (2026-10-25 审计).
    """
    rc, so, _ = _run_git(
        ["rev-list", "--count", f"origin/{git_branch()}..HEAD"], cwd=WORKSPACE
    )
    if rc != 0:
        return -1 if not _remote_branch_exists() else 0
    try:
        return int(so.strip()) if rc == 0 else 0
    except ValueError:
        return 0


def _push() -> str:
    """push 到远端. 远端有新提交时先 rebase, 冲突则放弃并报需人工处理."""
    rc, so, se = _run_git(["fetch", "origin", git_branch()], cwd=WORKSPACE, timeout=120)
    if rc != 0:
        low = (se or "").lower()
        if ("couldn't find remote ref" in low or "not found" in low) \
                and not _remote_has_any_ref():
            # 远端仓库**完全空的** → 直接推, 由 git 把分支建出来 (首次部署的正常路径)
            logger.info("git_sync.push: 远端还是空仓库, 直接推送并建分支 %s", git_branch())
        else:
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
    # ⚠️ 本次 commit **之前**的 HEAD —— push 失败时用它撤销本地那条 commit
    #    (见 undo_local_commit). 没有它就无法安全回退.
    prev_sha: str = ""


def undo_local_commit(prev_sha: str, paths: list[str]) -> bool:
    """撤销本地刚产生的 commit (push 失败时用).

    ⚠️ **为什么必须撤** (2026-10-25 审计):
       commit 成功、push 失败 → 本地分支领先远端 1 个 commit. 而 `_push()` 推的是
       `HEAD:<branch>` —— **下一次任何 job 的 push 都会把它一起带走**.
       对"删除"这种操作, 那意味着: API 刚返回"删除未生效", 过一会儿别的 job 一推,
       删除在 GitLab 上**悄悄生效了**, 而 DB 里的资产行还在 → 幽灵资产
       (列表里有, 文档 404).

    ⚠️ **只在确定 HEAD 还是我们那条 commit 时才撤** —— 中间若被别人提交过,
       `reset --soft` 会把人家的 commit 一起撤掉. 判断依据: HEAD 的上一个
       必须正好是 prev_sha.

    ⚠️ 整个过程持 LOCK_FILE —— 否则跟另一个 job 撞车.
    """
    if not prev_sha:
        return False
    with _FileLock(LOCK_FILE):
        head = _head_sha()
        if not head:
            return False
        rc, so, _ = _run_git(["rev-parse", "--verify", f"{head}~1"], cwd=WORKSPACE)
        if rc != 0 or so.strip() != prev_sha:
            logger.warning(
                "undo_local_commit 跳过: HEAD~1 不是我们那条 commit (可能中间有别的提交)"
            )
            return False
        # 1) 分支指针移回去 (--soft: 不动工作区, 别人的未提交改动不受影响)
        rc, _, se = _run_git(["reset", "--soft", prev_sha], cwd=WORKSPACE)
        if rc != 0:
            logger.error("undo_local_commit reset 失败: %s", se.strip()[:200])
            return False
        # 2) index 里这几条路径也要撤回来 —— reset --soft 之后 index 还是"提交后"
        #    的状态 (新文件是 staged-added), 不撤的话工作区看着干净、index 是脏的,
        #    `git status` 照样报 AD → 反向同步的安全闸照样命中.
        if paths:
            _run_git(["reset", "--quiet", "HEAD", "--", *paths], cwd=WORKSPACE)
        # 3) 把我们改过的那几条路径恢复成 prev_sha 的内容
        #    (checkout <tree> -- paths 同时改工作区和 index → 相对新 HEAD 就是干净的)
        restore = _paths_in_tree(prev_sha, paths)
        if restore:
            rc, _, se = _run_git(["checkout", prev_sha, "--", *restore], cwd=WORKSPACE)
            if rc != 0:
                logger.error("undo_local_commit checkout 失败: %s", se.strip()[:200])
                return False
        # prev_sha 里没有的路径 = 我们**这次新增**的 → 从工作区删掉, 别留半截
        for p in paths:
            if p.rstrip("/") not in restore:
                remove_path(p)
        logger.warning("undo_local_commit 已撤销本地 commit %s", head[:12])
        return True


def _paths_in_tree(ref: str, paths: list[str]) -> list[str]:
    """给定路径里, 哪些在 ref 这棵树里**存在** (目录按前缀匹配).

    ⚠️ `git checkout <tree> -- <pathspec>` 里, pathspec 匹配不到任何文件时
       整条命令会失败 ("pathspec did not match") —— 连**其他**正常的路径也一起不生效.
       所以只能 checkout 确实存在的那些.
    """
    rc, so, _ = _run_git(["ls-tree", "-r", "--name-only", ref], cwd=WORKSPACE)
    if rc != 0:
        return []
    files = set(so.split())
    out: list[str] = []
    for p in paths:
        p = (p or "").rstrip("/")
        if not p:
            continue
        if p in files or any(f.startswith(p + "/") for f in files):
            out.append(p)
    return out


def sync_paths_blocking(
    *,
    paths: list[str],
    message: str,
    author: tuple[str, str],
    commit_paths: list[str] | None = None,
) -> SyncResult:
    """把指定路径 commit + push. 阻塞版本 (在线程里跑).

    ⚠️ `commit_paths` 与 `paths` 分开, 是为了**目录搬家**这种场景:
       资产从 `assets/skills/diagnose/x` 搬到 `assets/skills/quality/x` 时,
       `git mv` 已经把旧路径从索引里删掉了 —— 这时
         · `git add -A -- <旧路径>` 会直接失败:
           "pathspec did not match any files" (旧路径既不在索引也不在工作区)
         · 但 `git commit -- <旧路径> <新路径>` **是好的** ——
           提交用的临时索引是 "HEAD + pathspec 对应的工作区内容",
           旧路径的删除已经在索引里, 会一起进这次提交.
       所以: `paths` 给**还能 add 的**路径 (新路径 + index.json),
       `commit_paths` 给**要进提交**的路径 (新路径 + 旧路径 + index.json).
       不传就等于两者相同 (原来的行为).
    """
    with _FileLock(LOCK_FILE):
        ensure_workspace()
        # ⚠️ 记下 commit **之前**的 HEAD —— push 失败时要靠它把本地那条 commit 撤掉
        #    (否则它会滞留到下次任意 job 的 push, 被悄悄带上远端)
        prev_sha = _head_sha()
        _stage(paths)
        sha = _commit(message, commit_paths or paths, author)
        if not sha:
            # 没有新提交 —— 但可能是「上次提交成功、推送失败」后的重试,
            # 这时**必须继续推**, 否则本地永远领先远端, 资产卡在机器上.
            head = _head_sha()
            # ⚠️ 判定用 `== 0` 而不是 `<= 0` —— _ahead_of_remote 远端 ref 不存在时返回 -1
            #    (意思是"全部待推"), 那个情况**不能**当成"无需推送".
            if not head or _ahead_of_remote() == 0:
                return SyncResult(commit_sha="", pushed=False, no_change=True, prev_sha=prev_sha)
            sha = head
        pushed_sha = _push()
        return SyncResult(commit_sha=pushed_sha or sha, pushed=True, prev_sha=prev_sha)


async def sync_paths(
    *,
    paths: list[str],
    message: str,
    author: tuple[str, str],
    commit_paths: list[str] | None = None,
) -> SyncResult:
    """异步版: 进程内锁 + 线程池执行阻塞的 git 操作."""
    async with _async_lock:
        return await asyncio.to_thread(
            sync_paths_blocking, paths=paths, message=message, author=author,
            commit_paths=commit_paths,
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
