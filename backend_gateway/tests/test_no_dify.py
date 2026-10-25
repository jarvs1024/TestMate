"""Dify 下线回归 —— 2026-10-25.

平台**不再接入 Dify**. 它一直是个假集成:
  · deploy/.env 从来没配过 DIFY_BASE_URL / DIFY_API_KEY, 跑的一直是 mock 模式;
  · 前端从来没调用过 /api/v1/diagnose/stream (只有 P0 时期那个接口用);
  · 能用的 5 张能力卡全是 builtin 引擎, 只有 2 张规划中的卡标着 dify;
  · 侧栏却显示着 "Dify 正常" —— 其实是 mock 的假象, 设置页还要配一套用不上的数据源.

所以 Dify 的数据源、配置项、接口、文案全部拿掉.

盯住五件事:
  ① 引擎枚举里没有 dify 了 (存量行由迁移 0019 改成 builtin);
  ② SEED 里没有能力再指向 dify 引擎;
  ③ 设置 schema 里没有 dify.* 这几项 (它们在 DEPRECATED_KEYS 里, 启动时清库);
  ④ /health/services 不再返回 dify (前端侧栏少一行);
  ⑤ /settings/test/dify 端点没了 (404), 设置页那个"测试连接"按钮也一起消失.
"""
from app.api.agents import SEED_AGENTS
from app.core.settings_store import DEPRECATED_KEYS, SETTING_SCHEMA
from app.models.agent import AgentEngine


# ---------- 引擎层 ----------

def test_agent_engine_has_no_dify():
    """引擎枚举里不能再有 dify —— 平台没有这个外部依赖了."""
    values = {e.value for e in AgentEngine}
    assert "dify" not in values, f"AgentEngine 还留着 dify: {values}"
    assert "builtin" in values, "内置引擎得留着 (现在所有能用的能力都跑在它上面)"


def test_no_seed_card_uses_dify_engine():
    """没有能力再指向 dify 引擎 —— 卡片上的引擎标识会直接露出来给用户看."""
    for cfg in SEED_AGENTS:
        assert cfg.get("engine") != "dify", f"{cfg['code']} 还指向 dify 引擎"


def test_agent_engine_default_is_builtin():
    """新建能力的默认引擎是内置 —— 不是那个已经下线的外部服务."""
    from app.schemas.agent import AgentCreateIn

    assert AgentCreateIn(
        code="probe", name="探针能力", category="ssd-trace", summary="探针",
    ).engine == "builtin"


# ---------- 设置层 ----------

def test_settings_schema_has_no_dify_keys():
    """设置 schema 里没有 dify.* —— 设置页不该再出现 Dify 数据源组."""
    keys = {s["key"] for s in SETTING_SCHEMA}
    assert not [k for k in keys if k.startswith("dify.")], f"schema 里还有 dify 项: {keys}"


def test_dify_settings_are_marked_deprecated():
    """dify.* 进 DEPRECATED_KEYS —— DB 里的残留行在启动时会被清掉."""
    for key in ("dify.base_url", "dify.api_key", "dify.mock_mode"):
        assert key in DEPRECATED_KEYS, f"{key} 没登记进 DEPRECATED_KEYS, DB 里的残留行清不掉"


def test_settings_schema_description_has_no_dify_wording():
    """设置项的描述文案里也不能再出现 Dify —— 那是 admin 看得见的字."""
    for s in SETTING_SCHEMA:
        desc = str(s.get("description", ""))
        assert "dify" not in desc.lower(), f"{s['key']} 的描述里还有 Dify: {desc}"


# ---------- 接口层 ----------

async def test_health_services_has_no_dify_field(client):
    """健康检查聚合里没有 dify —— 侧栏服务状态面板据此渲染."""
    r = await client.get("/api/v1/health/services")
    assert r.status_code == 200, r.text()
    assert "dify" not in r.json(), f"health/services 还返回 dify: {r.json()}"


async def test_settings_test_dify_endpoint_is_gone(client, admin_user):
    """/settings/test/dify 端点已经下线 (返回 404, 不是 403)."""
    from tests.test_permissions import _admin_headers

    r = await client.post(
        "/api/v1/settings/test/dify", headers=_admin_headers(admin_user)
    )
    assert r.status_code == 404, f"dify 测试端点还在: {r.status_code} {r.text()}"
