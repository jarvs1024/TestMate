"""git 同步层单元测试 —— 提交/推送/错误分类/版本比较."""
from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from app.core import git_sync


# ---------- 版本比较 (高 semver 胜) ----------

@pytest.mark.parametrize(
    "raw,expect",
    [
        ("1.2.3", (1, 2, 3)),
        ("v1.2.3", (1, 2, 3)),
        ("1.2", (1, 2, 0)),
        ("1", (1, 0, 0)),
        ("1.2.3-beta.1", (1, 2, 3)),
        ("1.2.3+build", (1, 2, 3)),
        ("", (0, 0, 0)),
        ("abc", (0, 0, 0)),
    ],
)
def test_parse_semver(raw, expect):
    assert git_sync.parse_semver(raw) == expect


def test_semver_gt():
    assert git_sync.semver_gt("1.2.4", "1.2.3")
    assert not git_sync.semver_gt("1.2.3", "1.2.3")
    assert not git_sync.semver_gt("1.2.3", "1.3.0")
    assert git_sync.semver_gt("2.0.0", "1.99.99")


# ---------- 错误分类 ----------

def test_classify_permission_denied_is_not_retryable():
    e = git_sync._classify("Permission denied (publickey).", 128)
    assert e.category in ("auth", "repo")
    assert e.retryable is False


def test_classify_network_is_retryable():
    e = git_sync._classify("ssh: connect to host port 22: Connection timed out", 255)
    assert e.category in ("network", "unknown")
    assert e.retryable is True


def test_classify_nonfastforward_is_not_retryable():
    e = git_sync._classify("! [rejected] main -> main (non-fast-forward)", 1)
    assert e.category == "nonfastforward"
    assert e.retryable is False


def test_classify_unknown_is_retryable():
    e = git_sync._classify("something odd happened", 1)
    assert e.retryable is True


def test_sync_error_carries_hint():
    e = git_sync.SyncError("msg", "auth", hint="配好 SSH key")
    assert e.hint == "配好 SSH key"
    assert e.category == "auth"
    assert e.retryable is False


# ---------- 工作区读写 ----------

def test_write_read_remove(ws):
    git_sync.write_text("assets/x/SKILL.md", "内容\n")
    assert (ws / "assets/x/SKILL.md").read_text() == "内容\n"
    assert git_sync.read_text("assets/x/SKILL.md") == "内容\n"
    assert git_sync.read_text("不存在.md") is None
    git_sync.remove_path("assets/x")
    assert not (ws / "assets/x").exists()


def test_write_text_creates_parent_dirs(ws):
    git_sync.write_text("a/b/c/d.md", "x")
    assert (ws / "a/b/c/d.md").exists()


def test_lock_file_lives_outside_workspace(ws, tmp_path):
    """锁文件在工作区外 —— 放里面会变成 git untracked 文件, 污染工作区."""
    assert str(git_sync.LOCK_FILE) != str(ws)
    assert not str(git_sync.LOCK_FILE).startswith(str(ws) + "/")


def test_ensure_workspace_keeps_existing_repo(ws):
    """已有 .git 的工作区直接用, 不重新 init."""
    assert git_sync.ensure_workspace() == ws
    assert (ws / ".git").exists()


# ---------- 提交与推送 ----------

def test_sync_paths_commits_and_pushes(ws):
    git_sync.write_text("assets/demo/SKILL.md", "内容\n")
    res = git_sync.sync_paths_blocking(
        paths=["assets/demo"], message="test: 提交", author=("tester", "t@test.local"),
    )
    assert res.pushed is True
    assert len(res.commit_sha) == 40

    # 远端真的收到了
    out = subprocess.run(
        ["git", "show", "main:assets/demo/SKILL.md"],
        cwd=str(ws.parent / "remote.git"), capture_output=True, text=True,
    )
    assert out.returncode == 0
    assert out.stdout == "内容\n"


def test_sync_paths_no_change_is_idempotent(ws):
    git_sync.write_text("assets/demo/SKILL.md", "内容\n")
    git_sync.sync_paths_blocking(
        paths=["assets/demo"], message="test: 1", author=("tester", "t@test.local"),
    )
    res = git_sync.sync_paths_blocking(
        paths=["assets/demo"], message="test: 2", author=("tester", "t@test.local"),
    )
    assert res.no_change is True


def test_sync_paths_pushes_when_commit_was_already_done(ws, monkeypatch):
    """提交成功但推送失败 → 重试时没有新提交, 但**必须继续推**.

    这是高可用里最要命的一条: 不推的话, 本地永远领先远端,
    资产就卡在这台机器上, 谁都不知道.
    """
    git_sync.write_text("assets/demo/SKILL.md", "内容\n")
    real_push = git_sync._push
    calls = {"push": 0}

    def flaky_push() -> str:
        calls["push"] += 1
        if calls["push"] == 1:
            raise git_sync.SyncError("远端不可达", "network")
        return real_push()

    monkeypatch.setattr(git_sync, "_push", flaky_push)
    with pytest.raises(git_sync.SyncError):
        git_sync.sync_paths_blocking(
            paths=["assets/demo"], message="test: 1", author=("tester", "t@test.local"),
        )
    # 第一次: 提交已落地, 推送失败
    head = subprocess.run(
        ["git", "rev-parse", "HEAD"], cwd=str(ws), capture_output=True, text=True,
    ).stdout.strip()
    remote_head = subprocess.run(
        ["git", "rev-parse", "main"], cwd=str(ws.parent / "remote.git"),
        capture_output=True, text=True,
    ).stdout.strip()
    assert head != remote_head, "第一次应当只提交未推送"

    # 重试: 没有新提交, 但本地领先 → 继续推
    res = git_sync.sync_paths_blocking(
        paths=["assets/demo"], message="test: 重试", author=("tester", "t@test.local"),
    )
    assert res.pushed is True
    remote_head2 = subprocess.run(
        ["git", "rev-parse", "main"], cwd=str(ws.parent / "remote.git"),
        capture_output=True, text=True,
    ).stdout.strip()
    assert remote_head2 == head, "重试应当把之前的提交推上去"


def test_sync_paths_can_delete(ws):
    git_sync.write_text("assets/demo/SKILL.md", "内容\n")
    git_sync.sync_paths_blocking(
        paths=["assets/demo"], message="test: add", author=("tester", "t@test.local"),
    )
    git_sync.remove_path("assets/demo")
    git_sync.sync_paths_blocking(
        paths=["assets/demo"], message="test: del", author=("tester", "t@test.local"),
    )
    out = subprocess.run(
        ["git", "ls-tree", "-r", "--name-only", "main"],
        cwd=str(ws.parent / "remote.git"), capture_output=True, text=True,
    )
    assert "assets/demo/SKILL.md" not in out.stdout


# ---------- 远端探测 ----------

def test_probe_remote_ok(ws):
    ok, msg = git_sync.probe_remote()
    assert ok is True
    assert "main" in msg


def test_probe_remote_fails_for_bad_remote(ws, monkeypatch):
    git_sync.set_git_config(remote="ssh://git@127.0.0.1:1/nonexistent.git", branch="main")
    ok, msg = git_sync.probe_remote()
    assert ok is False
    assert msg


# ---------- 状态概览 ----------

def test_workspace_status(ws):
    st = git_sync.workspace_status()
    assert st["is_repo"] is True
    assert st["branch"] == "main"
    assert st["remote"] == git_sync.git_remote()
    assert "head" in st


def test_ensure_workspace_syncs_remote_url(ws):
    """设置页改了仓库地址 → 本地 origin 必须跟着改, 否则还推去老仓库."""
    import subprocess

    subprocess.run(
        ["git", "remote", "set-url", "origin", "ssh://git@old.local:22/old.git"],
        cwd=str(ws), check=True, capture_output=True,
    )
    git_sync.set_git_config(remote="ssh://git@new.local:22/new.git", branch="main")
    git_sync.ensure_workspace()
    out = subprocess.run(
        ["git", "remote", "get-url", "origin"], cwd=str(ws),
        capture_output=True, text=True,
    )
    assert out.stdout.strip() == "ssh://git@new.local:22/new.git"


def test_git_config_setter(ws):
    git_sync.set_git_config(remote="ssh://git@example.local:22/x.git", branch="dev")
    assert git_sync.git_remote() == "ssh://git@example.local:22/x.git"
    assert git_sync.git_branch() == "dev"
    # 空值不覆盖 (防止误清空)
    git_sync.set_git_config(remote="", branch="")
    assert git_sync.git_remote() == "ssh://git@example.local:22/x.git"
    assert git_sync.git_branch() == "dev"
