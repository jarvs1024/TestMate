"""市场链路的健康信号 —— 判定口径必须是"还有活没推上去", 不是"历史上失败过几次".

起因 (2026-10-27):
    2026-10-22~26 GitLab 挂着那几天, 攒了 219 条 failed job. 对应的资产**后来
    都被删了** —— 它们是纯历史残留, 没有一件待处理.
    但健康判定写的是 `failed_jobs == 0` (**全量**计数) → 从那以后平台一直报
    "市场链路不健康", 哪怕现在一切正常.

    在生产上这是致命的: 监控告警永远亮着, 真出故障时反而没人看.

所以判定改成 `failed_assets` —— 资产表里 `sync_status='failed'` 的数量,
也就是**还有活没推上去**的那些. 历史那 219 条**一条不删** (审计线索).

盯住这三件事:
  ① 资产已删的历史失败 → 市场链路仍然健康;
  ② 资产还在、且它自己 sync_status='failed' → 市场链路**不健康** (真有事要管);
  ③ GitLab 探不通 → 市场链路不健康 (跟失败数无关).
"""
from __future__ import annotations

import pytest

API = "/api/v1"


async def _seed_failed_job(code: str, *, asset_exists: bool) -> None:
    """种一条 failed 的上传任务 + (可选)对应的资产."""
    from app.db.session import AsyncSessionLocal
    from app.models.asset import Asset, AssetJob

    async with AsyncSessionLocal() as s:
        if asset_exists:
            s.add(
                Asset(
                    code=code,
                    name=code,
                    kind="skill",
                    sync_status="failed",
                    publish_status="published",
                    last_error="push failed: 模拟",
                )
            )
        s.add(
            AssetJob(
                action="create",
                status="failed",
                code=code,
                asset_name=code,
                kind="skill",
                payload={},
                error="push failed: 模拟",
            )
        )
        await s.commit()


async def _market_check(client) -> dict:
    r = await client.get(f"{API}/health/ready")
    assert r.status_code == 200, r.text
    return r.json()["checks"]["marketplace"]


def _patch_deps(monkeypatch, *, gitlab_ok: bool = True):
    """把 MySQL/Redis/GitLab 三个探针都钉住.

    ⚠️ Redis 探针必须钉: 测试环境的 REDIS_HOST 默认是容器名 'redis' —— 本机
    解析不了, readiness 会因为**Redis 不可达**返 503, 根本走不到市场判定那步.
    """
    import app.api.health as health_mod

    async def _mysql_ok():
        return True, None

    async def _redis_ok():
        return True, None

    async def _gitlab_ok():
        return True, None

    async def _gitlab_bad():
        return False, "ssh: connect to host:8922 port 22: Connection refused"

    monkeypatch.setattr(health_mod, "_check_mysql", _mysql_ok)
    monkeypatch.setattr(health_mod, "_check_redis", _redis_ok)
    monkeypatch.setattr(health_mod, "_probe_gitlab", _gitlab_ok if gitlab_ok else _gitlab_bad)


async def test_historical_failed_jobs_do_not_break_market_health(client, monkeypatch):
    """① 资产已删的历史失败 → 市场链路**仍然健康**.

    这正是那 219 条残留干的事: 它们对应的资产早没了, 没有任何东西待处理.
    """
    _patch_deps(monkeypatch)
    await _seed_failed_job("gone-asset", asset_exists=False)

    m = await _market_check(client)
    assert m["failed_jobs"] == 1, m           # 历史残留照样如实报出来
    assert m["failed_assets"] == 0, m         # 但没有"待处理的失败"
    assert m["ok"] is True, m                # 所以链路是健康的


async def test_asset_stuck_in_failed_state_breaks_market_health(client, monkeypatch):
    """② 资产还在、且它自己 sync_status='failed' → 市场链路**不健康**.

    这是真的"有活没推上去" —— 资产在库里摆着, 用户下不到最新版本.
    """
    _patch_deps(monkeypatch)
    await _seed_failed_job("stuck-asset", asset_exists=True)

    m = await _market_check(client)
    assert m["failed_assets"] == 1, m
    assert m["ok"] is False, m


async def test_unreachable_gitlab_breaks_market_health(client, monkeypatch):
    """③ GitLab 探不通 → 市场链路不健康 (跟失败数无关)."""
    _patch_deps(monkeypatch, gitlab_ok=False)

    m = await _market_check(client)
    assert m["gitlab"]["ok"] is False, m
    assert m["ok"] is False, m
