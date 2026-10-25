"""权限边界 —— 谁能看什么 / 谁能做什么.

为什么单独一个文件 (2026-10-25 审计):
    以前"谁能看"这件事**没有测试** —— 后端多个端点只挂了 `get_current_user`,
    于是普通用户能读到:
      · 钉钉 webhook 的完整 URL (里面就是机器人的 access_token → 拿到就能
        绕过本系统直接往公司市场群/审核群发消息)
      · 全部操作记录 (谁上架/下架/驳回/删了哪个资产, 带备注)
      · 全部通知回执 (真正发到群里去的内容)
      · 工作区绝对路径 + Git 远端地址
    这类"越权可见"不会报错、不会崩, 只能靠测试钉住.

这里全部用**真实的普通用户** (stranger_user: viewer 角色, 不在任何白名单里).
"""
from __future__ import annotations

import pytest

API = "/api/v1/assets"
SETTINGS = "/api/v1/settings"


def _stranger_headers(stranger_user) -> dict:
    return {"Authorization": f"Bearer {stranger_user['token']}"}


def _admin_headers(admin_user) -> dict:
    return {"Authorization": f"Bearer {admin_user['token']}"}


def _schema_keys(resp) -> set[str]:
    out: set[str] = set()
    for g in resp.json().get("groups", []):
        for it in g.get("items", []):
            out.add(it["key"])
    return out


# ---------- 设置: 凭据类条目只给管理员 ----------

async def test_normal_user_cannot_read_credentials(client, stranger_user):
    """普通用户读设置 schema → 拿不到任何"拿到就能用"的条目."""
    r = await client.get(f"{SETTINGS}/schema", headers=_stranger_headers(stranger_user))
    assert r.status_code == 200, r.text
    keys = _schema_keys(r)
    for k in (
        "dingtalk.market_webhook",     # URL 里带 access_token
        "dingtalk.review_webhook",
        "ragflow.api_key",
        "review_agent.api_token",
        "dingtalk.market_secret",
        "dingtalk.review_secret",
        # 权限白名单 —— 谁能上架/谁能审核, 是管理员的配置
        "marketplace.publisher_ids",
        "marketplace.publisher_usernames",
        "marketplace.review.reviewer_usernames",
    ):
        assert k not in keys, f"普通用户不该看到 {k}: {sorted(keys)}"


async def test_normal_user_schema_has_no_webhook_url(client, stranger_user):
    """响应里**不能出现**任何钉钉 webhook URL (哪怕在别的字段里)."""
    r = await client.get(f"{SETTINGS}/schema", headers=_stranger_headers(stranger_user))
    assert r.status_code == 200, r.text
    body = r.text
    assert "oapi.dingtalk.com" not in body, "普通用户拿到了钉钉 webhook"
    assert "access_token" not in body, "普通用户拿到了带 token 的 URL"


async def test_admin_still_sees_credentials(client, admin_user):
    """管理员照常能看到 (别把管理员自己挡在门外)."""
    r = await client.get(f"{SETTINGS}/schema", headers=_admin_headers(admin_user))
    assert r.status_code == 200, r.text
    keys = _schema_keys(r)
    assert "dingtalk.market_webhook" in keys
    assert "dingtalk.review_webhook" in keys
    assert "ragflow.api_key" in keys


async def test_normal_user_cannot_change_settings(client, stranger_user):
    """改设置一直是 admin only —— 补一条回归."""
    r = await client.put(
        f"{SETTINGS}/marketplace.sync.interval_seconds",
        json={"value": "999"}, headers=_stranger_headers(stranger_user),
    )
    assert r.status_code == 403, r.text


# ---------- 设置: 测试连接端点只给管理员 ----------

@pytest.mark.parametrize("path", [
    "/test/ragflow", "/test/pr_agent",
    "/test/review_agent", "/test/gitlab", "/test/dingtalk",
])
async def test_normal_user_cannot_run_connection_tests(client, stranger_user, path):
    """「测试连接」全是 admin only (以前 ragflow/pr_agent/review_agent 漏了)."""
    r = await client.post(f"{SETTINGS}{path}", headers=_stranger_headers(stranger_user))
    assert r.status_code == 403, f"{path} 应该 403, 实际 {r.status_code}: {r.text}"


# ---------- 资产: 审计 / 回执只给管理员 ----------

async def test_normal_user_cannot_read_audits(client, stranger_user):
    """操作记录 = 运营数据 (谁上架/下架/驳回/删了哪个资产) → admin only."""
    r = await client.get(f"{API}/audits?limit=20", headers=_stranger_headers(stranger_user))
    assert r.status_code == 403, r.text


async def test_normal_user_cannot_read_notification_receipts(client, stranger_user):
    """通知回执 = 真正发到群里去的内容 → admin only."""
    r = await client.get(f"{API}/notifications?limit=20", headers=_stranger_headers(stranger_user))
    assert r.status_code == 403, r.text


async def test_admin_can_read_audits_and_receipts(client, admin_user):
    """管理员照常能读 (审计台是给管理员用的)."""
    h = _admin_headers(admin_user)
    r1 = await client.get(f"{API}/audits?limit=5", headers=h)
    assert r1.status_code == 200, r1.text
    r2 = await client.get(f"{API}/notifications?limit=5", headers=h)
    assert r2.status_code == 200, r2.text


# ---------- 资产: 配置端点不暴露内部路径 ----------

async def test_normal_user_config_hides_workspace_and_remote(client, stranger_user):
    """工作区绝对路径 + Git 远端地址 = 部署内部信息 → 只给管理员."""
    r = await client.get(f"{API}/config", headers=_stranger_headers(stranger_user))
    assert r.status_code == 200, r.text
    j = r.json()
    assert not j.get("workspace"), j
    assert not j.get("remote"), j


async def test_admin_config_shows_workspace(client, admin_user):
    """管理员照常能看到 (设置页要展示工作区)."""
    r = await client.get(f"{API}/config", headers=_admin_headers(admin_user))
    assert r.status_code == 200, r.text
    assert r.json().get("workspace")


# ---------- 同步状态: 系统级计数只给管理员 ----------

async def test_normal_user_sync_status_hides_system_counts(
    client, stranger_user, ws,  # noqa: ARG001
    restore_git_config, publisher_user,
):
    """普通用户看 sync-status → 系统级计数归零, 但"我自己"的还在."""
    from tests.test_market_api import _enable_publisher, _upload

    await _enable_publisher(publisher_user)
    pauth = {"Authorization": f"Bearer {publisher_user['token']}"}
    await _upload(client, pauth, code="sync-count-demo")

    r = await client.get(f"{API}/sync-status", headers=_stranger_headers(stranger_user))
    assert r.status_code == 200, r.text
    j = r.json()
    # 系统级 → 0
    assert j["pending_count"] == 0, j
    assert j["failed_count"] == 0, j
    assert j["awaiting_review_count"] == 0, j
    assert j["conflict_count"] == 0, j
    assert j["has_remote_updates"] is False, j


async def test_publisher_sees_own_counts(client, publisher_user):
    """作者本人看得到"我的待审"这些 (前端顶部提示条靠它们)."""
    h = {"Authorization": f"Bearer {publisher_user['token']}"}
    r = await client.get(f"{API}/sync-status", headers=h)
    assert r.status_code == 200, r.text
    j = r.json()
    # my_* 是按人算的 → 非管理员也拿得到 (只是这里没数据所以是 0)
    assert "my_review_count" in j and "my_unpublish_count" in j
