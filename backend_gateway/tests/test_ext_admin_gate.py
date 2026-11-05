"""管理员闸的 403 文案 —— 别再用「下架审核」的文案糊弄别的端点 (2026-11-06).

⚠️ 起因: require_admin 这一个闸被**五个**端点共用
   (审计 / 通知回执 / 通知预览 / 手动同步 / 下架审核),
   而它的 403 文案写死成「只有管理员可以审核 (下架审核 = 删除, 只限管理员)」——
   用户在「看审计列表」被拒时看到的也是「下架审核 = 删除」, 纯误导.

现在: 通用闸说通用的话, 下架审核那个端点用自己的闸说自己的话.
"""
from __future__ import annotations

API = "/api/v1/extensions"


async def test_admin_gate_message_is_generic(client, publisher_user):  # noqa: ARG001
    """通用管理员闸: 403 文案**不该**提「下架审核」."""
    pauth = {"Authorization": f"Bearer {publisher_user['token']}"}
    for path in (f"{API}/audits", f"{API}/notifications", f"{API}/notifications/preview"):
        r = await client.get(path, headers=pauth)
        assert r.status_code == 403, (path, r.status_code, r.text)
        detail = r.json()["detail"]
        assert "下架审核" not in detail, (path, detail)
        assert "管理员" in detail, (path, detail)


async def test_unpublish_review_keeps_its_own_message(client, publisher_user):  # noqa: ARG001
    """下架审核那个端点: 403 文案要保留「下架审核 = 删除」的关键说明."""
    pauth = {"Authorization": f"Bearer {publisher_user['token']}"}
    r = await client.post(f"{API}/whatever/unpublish-review",
                           data={"decision": "approve"}, headers=pauth)
    assert r.status_code == 403, r.text
    assert "下架审核" in r.json()["detail"], r.json()["detail"]


async def test_admin_gate_unauthenticated_is_401(client):  # noqa: ARG001
    """未登录 → 401 (不是 403)."""
    r = await client.get(f"{API}/audits")
    assert r.status_code == 401, r.text
    assert r.json()["detail"] == "未登录"
