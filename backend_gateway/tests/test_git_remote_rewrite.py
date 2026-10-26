"""git 远端地址的「本机」改写 —— **双向**改 (容器 ↔ 宿主).

背景 (2026-10-27): 裸机部署 (deploy/native) 的后端**跑在宿主上**, 但资产市场
的 git 远端默认是 `ssh://git@host.docker.internal:8922/...` —— 那个名字在宿主上
解析到 Docker 虚拟网卡 (198.18.x.x), 从宿主侧**连不通** (GitLab 的 SSH 端口
是 Docker 映射出来的, 宿主上真正能连的是 127.0.0.1:8922).

以前只有 `sudo tmctl.sh local hosts fix` 一条路 (改宿主 /etc/hosts, 要 root).
现在改成**代码层双向改写**: 同一个设置值在两种部署模式下都通 —— 不用改
/etc/hosts, 也不用为了切部署模式去改设置页里的仓库地址.
"""
from __future__ import annotations

import pytest

from app.core import git_sync, settings_store


@pytest.fixture
def in_container(monkeypatch):
    """假装后端跑在容器里."""
    monkeypatch.setattr(settings_store, "_IN_CONTAINER", True)


@pytest.fixture
def on_host(monkeypatch):
    """假装后端跑在宿主上 (裸机部署)."""
    monkeypatch.setattr(settings_store, "_IN_CONTAINER", False)


# ---------- 宿主上: host.docker.internal → 127.0.0.1 ----------

@pytest.mark.parametrize(
    "raw,expected",
    [
        (
            "ssh://git@host.docker.internal:8922/root/testmate-market.git",
            "ssh://git@127.0.0.1:8922/root/testmate-market.git",
        ),
        (
            "ssh://git@host.docker.internal/root/testmate-market.git",
            "ssh://git@127.0.0.1/root/testmate-market.git",
        ),
        # 没有 user@ 的写法也要改
        (
            "ssh://host.docker.internal:8922/root/testmate-market.git",
            "ssh://127.0.0.1:8922/root/testmate-market.git",
        ),
    ],
)
def test_宿主上_host_docker_internal_换成_127_0_0_1(raw, expected, on_host):
    """裸机部署的后端在宿主上 —— host.docker.internal 从宿主侧连不通."""
    assert git_sync._rewrite_remote(raw) == expected


# ---------- 容器里: 127.0.0.1 → host.docker.internal ----------

@pytest.mark.parametrize(
    "raw,expected",
    [
        (
            "ssh://git@127.0.0.1:8922/root/testmate-market.git",
            "ssh://git@host.docker.internal:8922/root/testmate-market.git",
        ),
        (
            "ssh://git@localhost:8922/root/testmate-market.git",
            "ssh://git@host.docker.internal:8922/root/testmate-market.git",
        ),
    ],
)
def test_容器里_127_0_0_1_换成_host_docker_internal(raw, expected, in_container):
    """容器里的 127.0.0.1 是容器自己 —— 要到宿主得走 host.docker.internal."""
    assert git_sync._rewrite_remote(raw) == expected


# ---------- 别的地址一律不动 ----------

@pytest.mark.parametrize(
    "raw",
    [
        "ssh://git@gitlab.example.com:8922/root/testmate-market.git",
        "ssh://git@10.0.0.5:8922/root/testmate-market.git",
        "file:///Users/jarvs/testmate-data/market-remote.git",
        "",
    ],
)
def test_别的远端_任何情况下都不改(raw, in_container):
    assert git_sync._rewrite_remote(raw) == raw
    settings_store._IN_CONTAINER = False
    assert git_sync._rewrite_remote(raw) == raw


def test_git_remote_返回改写后的地址(on_host, monkeypatch):
    """git_remote() 是对外口径 —— 必须已经改写过 (fetch/push 都用它)."""
    monkeypatch.setitem(
        git_sync._git_cfg, "remote",
        "ssh://git@host.docker.internal:8922/root/testmate-market.git",
    )
    assert git_sync.git_remote() == "ssh://git@127.0.0.1:8922/root/testmate-market.git"
