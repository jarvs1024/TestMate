"""loopback 地址改写的单测 —— **只在容器里改**.

背景 (2026-10-26): 裸机部署 (deploy/native 的 systemd 与 macOS local 两种 driver)
的后端**跑在宿主上**, 而 `_rewrite_loopback` 以前是**无条件**把
`127.0.0.1` / `localhost` 改写成 `host.docker.internal` —— 那个名字在宿主上
解析到 Docker 虚拟网卡, 从宿主侧连不通.

症状: 用户在设置页把 ReviewAgent 地址填成 `http://127.0.0.1:3000`,
"测试连接"却报 HTTP 502, 而且**改不回来** —— 改完又被后端改写掉.
根因就在这个函数.
"""
from __future__ import annotations

import pytest

from app.core import settings_store
from app.core.settings_store import _rewrite_loopback


@pytest.fixture
def in_container(monkeypatch):
    """假装后端跑在容器里."""
    monkeypatch.setattr(settings_store, "_IN_CONTAINER", True)


@pytest.fixture
def on_host(monkeypatch):
    """假装后端跑在宿主上 (裸机部署)."""
    monkeypatch.setattr(settings_store, "_IN_CONTAINER", False)


# ---------- 容器里: 该改写 ----------

@pytest.mark.parametrize(
    "raw,expected",
    [
        ("http://127.0.0.1:3000", "http://host.docker.internal:3000"),
        ("http://127.0.0.1:3000/api/v1", "http://host.docker.internal:3000/api/v1"),
        ("http://localhost:18080/api/v1", "http://host.docker.internal:18080/api/v1"),
        ("https://127.0.0.1:8443", "http://host.docker.internal:8443"),
    ],
)
def test_容器里_loopback_被改成宿主可达地址(raw, expected, in_container):
    assert _rewrite_loopback(raw) == expected


# ---------- 宿主上: 绝不能改 ----------

@pytest.mark.parametrize(
    "raw",
    [
        "http://127.0.0.1:3000",
        "http://localhost:18080/api/v1",
        "https://127.0.0.1:8443",
    ],
)
def test_宿主上_loopback_原样保留(raw, on_host):
    """⚠️ 这条是本次修复的核心 —— 宿主上 127.0.0.1 就是宿主自己, 改了就连不通."""
    assert _rewrite_loopback(raw) == raw


# ---------- 两种情况下都不该动的 ----------

@pytest.mark.parametrize(
    "raw",
    [
        "http://host.docker.internal:3000",   # 已经是宿主可达地址
        "http://review-agent.internal:3000",  # 另一个容器 (service name)
        "http://10.0.0.5:3000",               # 具体 IP
        "",
    ],
)
def test_非_loopback_地址_任何情况下都不改(raw, in_container):
    assert _rewrite_loopback(raw) == raw
    settings_store._IN_CONTAINER = False
    assert _rewrite_loopback(raw) == raw


def test_宿主上_RAGFlow_的_127_0_0_1_也不被改写(on_host):
    """RAGFlow 走同一个函数 —— 裸机部署时它同样跑在宿主上."""
    assert _rewrite_loopback("http://127.0.0.1:18080/api/v1") == "http://127.0.0.1:18080/api/v1"


def test_容器判定有缓存且可被重置(monkeypatch):
    """_IN_CONTAINER 是缓存的模块级变量 —— 测试要能重置它."""
    monkeypatch.setattr(settings_store, "_IN_CONTAINER", None)
    first = settings_store._in_container()
    assert isinstance(first, bool)
    # 再算一次走缓存, 结果一致
    assert settings_store._in_container() is first
