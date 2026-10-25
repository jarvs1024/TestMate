"""失败路径 / 残留 / 冲突 —— 资产市场的**边界**用例.

为什么单独一个文件 (2026-10-25 审计):
    正常路径测得再多, 也不保证**失败时**干净. 这一轮审计发现的问题几乎全在失败
    路径上 —— 失败后留下脏工作区、滞留 commit、DB 与 git 不一致, 而这些一旦发生,
    轻则资产卡住, 重则别人的资产被牵连 (新上传把老数据从索引里抹掉).

这里用的都是**真实 git 仓库** (conftest 的 ws fixture: 真的裸库当远端),
    真的跑 commit/push —— 假的远端测不出"push 失败之后工作区是什么状态".
"""
from __future__ import annotations

import subprocess

import pytest

from app.core import git_sync


def _git(*args: str, cwd) -> str:
    out = subprocess.run(
        ["git", *args], cwd=str(cwd), capture_output=True, text=True,
    )
    return out.stdout.strip()


def _remote_head(ws) -> str:
    return _git("rev-parse", "main", cwd=ws.parent / "remote.git")


# ---------- 原子写 ----------

def test_write_text_is_atomic_on_failure(ws):
    """写失败时**原文件不能被破坏** (以前是截断重写 → 半个 JSON)."""
    target = ws / "keep.md"
    target.write_text("原来的内容\n", encoding="utf-8")
    # 让父路径变成一个**文件** → mkdir 必然失败
    (ws / "blocker").write_text("x", encoding="utf-8")
    with pytest.raises(git_sync.SyncError):
        git_sync.write_text("blocker/child.md", "新内容")
    assert target.read_text(encoding="utf-8") == "原来的内容\n"


def test_write_text_leaves_no_tmp_files(ws):
    """原子写的临时文件不能留在工作区 (会污染 git status)."""
    git_sync.write_text("assets/x/SKILL.md", "内容\n")
    leftovers = [p.name for p in (ws / "assets" / "x").iterdir() if ".tmp-" in p.name]
    assert leftovers == []


# ---------- push 失败 → 撤销本地 commit ----------

def test_undo_local_commit_reverts_the_failed_push(ws, monkeypatch):
    """push 失败后**必须把本地那条 commit 撤掉**.

    ⚠️ 不撤的话: 下一次任何 job 的 push 都会把它一起带走 (`push origin HEAD:branch`
       推的是 HEAD 可达的全部 commit) → 对"删除"来说, 就是 API 刚说"删除未生效",
       过一会儿删除在 GitLab 上**悄悄生效了**, 而 DB 里资产行还在 → 幽灵资产.
    """
    git_sync.write_text("assets/demo/SKILL.md", "内容\n")
    prev_sha = git_sync.head_sha()

    real_push = git_sync._push

    def failing_push() -> str:
        raise git_sync.SyncError("远端不可达", "network")

    monkeypatch.setattr(git_sync, "_push", failing_push)
    with pytest.raises(git_sync.SyncError):
        git_sync.sync_paths_blocking(
            paths=["assets/demo"], message="test: 删除", author=("tester", "t@test.local"),
        )
    # 提交确实产生了 (但没推上去)
    assert git_sync.head_sha() != prev_sha
    assert _remote_head(ws) == prev_sha

    # 撤销 → 本地回到操作前, 工作区干净
    monkeypatch.setattr(git_sync, "_push", real_push)
    assert git_sync.undo_local_commit(prev_sha, ["assets/demo"]) is True
    assert git_sync.head_sha() == prev_sha
    assert _remote_head(ws) == prev_sha
    # 工作区里那个文件也不该留下 (撤销 = 回到操作前的样子)
    assert not (ws / "assets" / "demo" / "SKILL.md").exists()
    assert _git("status", "--porcelain", cwd=ws) == ""


def test_undo_local_commit_restores_deleted_path(ws, monkeypatch):
    """删除场景: 撤销后**被删掉的资产目录要回来** (否则 DB 有、git 没有 = 幽灵)."""
    git_sync.write_text("assets/demo/SKILL.md", "内容\n")
    git_sync.sync_paths_blocking(
        paths=["assets/demo"], message="test: add", author=("tester", "t@test.local"),
    )
    prev_sha = git_sync.head_sha()

    # 模拟"删除": 先删目录, 再提交
    git_sync.remove_path("assets/demo")
    real_push = git_sync._push
    monkeypatch.setattr(
        git_sync, "_push",
        lambda: (_ for _ in ()).throw(git_sync.SyncError("远端不可达", "network")),
    )
    with pytest.raises(git_sync.SyncError):
        git_sync.sync_paths_blocking(
            paths=["assets/demo"], message="test: 删除", author=("tester", "t@test.local"),
        )
    monkeypatch.setattr(git_sync, "_push", real_push)

    assert git_sync.undo_local_commit(prev_sha, ["assets/demo"]) is True
    assert git_sync.head_sha() == prev_sha
    # 资产目录回来了 ✓
    assert (ws / "assets" / "demo" / "SKILL.md").exists()
    assert _git("status", "--porcelain", cwd=ws) == ""


def test_undo_local_commit_refuses_when_head_is_not_ours(ws, monkeypatch):
    """HEAD 不是我们那条 commit 时**不能撤** (会把别人的提交一起撤掉)."""
    git_sync.write_text("assets/demo/SKILL.md", "内容\n")
    git_sync.sync_paths_blocking(
        paths=["assets/demo"], message="test: add", author=("tester", "t@test.local"),
    )
    head = git_sync.head_sha()
    # 假装 prev_sha 是很久以前的某个 commit → HEAD~1 对不上 → 必须拒绝
    assert git_sync.undo_local_commit("0" * 40, ["assets/demo"]) is False
    assert git_sync.head_sha() == head


# ---------- 索引条目 ----------

def test_index_codes_at_ref(ws):
    """从某个 ref 的 index.json 里读出所有 code (上传前查幽灵资产用)."""
    git_sync.write_text("index.json", '{"assets": [{"code": "a"}, {"code": "b"}]}')
    git_sync.sync_paths_blocking(
        paths=["index.json"], message="test: index", author=("tester", "t@test.local"),
    )
    assert git_sync.index_codes_at_ref("HEAD") == {"a", "b"}
    assert git_sync.index_codes_at_ref("origin/main") == {"a", "b"}
    # 没有 index.json 的 ref → 空集合 (不能抛)
    assert git_sync.index_codes_at_ref("HEAD~1") == set()


def test_index_codes_at_ref_survives_broken_json(ws):
    """index.json 坏了 → 返回空集合, 不能抛 (否则上传全挂)."""
    git_sync.write_text("index.json", "{ 坏了")
    git_sync.sync_paths_blocking(
        paths=["index.json"], message="test: broken", author=("tester", "t@test.local"),
    )
    assert git_sync.index_codes_at_ref("HEAD") == set()


# ---------- 清理残留 ----------

def test_clean_path_removes_only_untracked(ws):
    """clean_path 只清**没被跟踪**的文件 (更新的旧版本文件不能被误删)."""
    git_sync.write_text("assets/demo/SKILL.md", "已提交\n")
    git_sync.sync_paths_blocking(
        paths=["assets/demo"], message="test: add", author=("tester", "t@test.local"),
    )
    # 未跟踪的残留
    (ws / "assets" / "demo" / "leftover.tmp").write_text("残留", encoding="utf-8")
    assert git_sync.clean_path("assets/demo") is True
    assert not (ws / "assets" / "demo" / "leftover.tmp").exists()
    # 已跟踪的还在
    assert (ws / "assets" / "demo" / "SKILL.md").exists()


# ---------- 错误分类 ----------

def test_classify_concurrent_is_retryable():
    """远端有他人提交导致的 push 被拒 = **可重试** (退避后通常就过去了).

    ⚠️ 以前归成 nonfastforward (不可重试) → 一次瞬时并发就把资产打成终态失败,
       而启动恢复不重排 failed → 重启也不自愈.
    """
    e = git_sync._classify("! [rejected] main -> main (non-fast-forward)", 1)
    assert e.category == "concurrent"
    assert e.retryable is True


def test_classify_missing_remote_branch_is_not_retryable():
    """远端**没有这个分支** → 重试没用, 得人工建分支 (别再当 unknown 耗满重试)."""
    e = git_sync._classify("fatal: couldn't find remote ref main", 128)
    assert e.category == "repo"
    assert e.retryable is False


# ---------- 远端 ref 缺失不能误判成"无需推送" ----------

def test_ahead_of_remote_returns_minus_one_when_remote_ref_missing(ws, monkeypatch):
    """远端没有这个 ref → 返回 -1 (不是 0).

    ⚠️ 0 会被当成"没有待推的 commit" → no_change 快捷路径把资产标成"已推送",
       而远端其实什么都没有.
    """
    real_run = git_sync._run_git

    def fake_run(args, **kw):
        if args[:2] == ["rev-list", "--count"]:
            return 1, "", "fatal: bad revision 'origin/main'"
        return real_run(args, **kw)

    monkeypatch.setattr(git_sync, "_run_git", fake_run)
    monkeypatch.setattr(git_sync, "_remote_branch_exists", lambda: False)
    assert git_sync._ahead_of_remote() == -1

    # 远端**有**这个分支 (只是 rev-list 失败) → 0 (别乱报 -1)
    monkeypatch.setattr(git_sync, "_remote_branch_exists", lambda: True)
    assert git_sync._ahead_of_remote() == 0
