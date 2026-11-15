"""健康检查聚合: 外部服务 + 平台认证都要报"此刻能不能连上", 不是"上次登录成没成".

侧栏「数据 / 工具」用这个接口渲染状态点: 平台认证断了必须显示不可达,
不能因为 DB 里存着上次登录成功就显示「正常」.
"""
from __future__ import annotations

from app.core import ragflow_client, review_agent_client
from app.integrations.pingcode import client as pingcode_client
from app.integrations.plm import client as plm_client


async def test_health_services_reports_integration_reachability(client, monkeypatch):
    async def rf_probe(space_id=None):
        return ("ok", "正常")

    async def ra_configured():
        return True

    async def ra_probe():
        return ("ok", "正常")

    async def pingcode_probe():
        return ("off", "不可达: ConnectError")

    async def plm_probe():
        return ("warn", "HTTP 502")

    monkeypatch.setattr(ragflow_client, "probe", rf_probe)
    monkeypatch.setattr(review_agent_client, "is_configured", ra_configured)
    monkeypatch.setattr(review_agent_client, "probe", ra_probe)
    monkeypatch.setattr(pingcode_client, "probe", pingcode_probe)
    monkeypatch.setattr(plm_client, "probe", plm_probe)

    response = await client.get("/api/v1/health/services")

    assert response.status_code == 200, response.text
    assert response.json() == {
        "ragflow": "ok",
        "review_agent": "ok",
        "pingcode": "off",
        "plm": "warn",
    }


async def test_health_services_marks_review_agent_off_when_unconfigured(client, monkeypatch):
    async def rf_probe(space_id=None):
        return ("ok", "正常")

    async def ra_configured():
        return False

    async def pingcode_probe():
        return ("ok", "正常")

    async def plm_probe():
        return ("ok", "正常")

    monkeypatch.setattr(ragflow_client, "probe", rf_probe)
    monkeypatch.setattr(review_agent_client, "is_configured", ra_configured)
    monkeypatch.setattr(pingcode_client, "probe", pingcode_probe)
    monkeypatch.setattr(plm_client, "probe", plm_probe)

    response = await client.get("/api/v1/health/services")

    assert response.status_code == 200, response.text
    assert response.json()["review_agent"] == "off"
