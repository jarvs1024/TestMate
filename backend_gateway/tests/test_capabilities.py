"""能力 (capability) 的形态模型 —— 2026-10-25 能力墙重构.

盯住四件事:
   ① 每条 SEED 都带 kind (tool / board / catalog / library);
   ② **知识库存从侧栏顶级项变成了一张卡** (kind=library, route=page:kb-manage);
   ③ GET /agents **匿名可读** (首页对未登录用户开放只读);
   ④ GET /agents?kind=... 能按形态过滤.
"""
from app.api.agents import SEED_AGENTS, seed_agents
from app.models.agent import AgentKind

VALID_KINDS = {k.value for k in AgentKind}


def test_seed_entries_all_have_valid_kind():
    """每条 seed 都要声明形态 —— 漏了前端就会把它当工具卡渲染 (引擎/调用次数全是假的)."""
    for cfg in SEED_AGENTS:
        assert cfg.get("kind") in VALID_KINDS, f"{cfg['code']} 的 kind 不合法: {cfg.get('kind')}"


def test_seed_kinds_match_real_nature():
    """形态要跟卡片**实际**是什么东西对得上 —— 形态错了卡片就渲染错了."""
    by_code = {c["code"]: c for c in SEED_AGENTS}
    assert by_code["code-review"]["kind"] == AgentKind.board.value      # 只读看板
    assert by_code["agent-market"]["kind"] == AgentKind.catalog.value  # 资产目录
    assert by_code["kb-inventory"]["kind"] == AgentKind.library.value  # 知识库存
    for code in ("log-analysis", "env-ops", "test-plan-gen", "testcase-gen"):
        assert by_code[code]["kind"] == AgentKind.tool.value           # 真能跑的


def test_kb_inventory_seed():
    """知识库存卡: 名字/图标/域标签/路由都要对, 否则首页点进去跳错页."""
    kb = next(c for c in SEED_AGENTS if c["code"] == "kb-inventory")
    assert kb["name"] == "知识库存"
    assert kb["icon"] == "📚"
    assert kb["category"] == "ssd-kb"
    assert kb["route"] == "page:kb-manage"
    assert kb["status"] != "draft", "知识库是**已实现**的能力, 不能是规划中"


async def test_seed_agents_persists_kind():
    """seed_agents 真跑一遍后, 库里每行的 kind 都要对得上 seed 配置."""
    from sqlalchemy import select

    from app.db.session import AsyncSessionLocal
    from app.models.agent import Agent

    await seed_agents()

    async with AsyncSessionLocal() as s:
        rows = (await s.execute(select(Agent))).scalars().all()
    kinds = {r.code: r.kind.value for r in rows}
    assert kinds["code-review"] == "board"
    assert kinds["agent-market"] == "catalog"
    assert kinds["kb-inventory"] == "library"
    assert kinds["log-analysis"] == "tool"


async def test_seed_agents_syncs_kind_of_existing_row():
    """存量行的 kind 也要被 seed 改回来 —— 它是**平台级契约**, 前端整张卡都靠它."""
    from sqlalchemy import select

    from app.db.session import AsyncSessionLocal
    from app.models.agent import Agent

    await seed_agents()
    async with AsyncSessionLocal() as s:
        row = (await s.execute(select(Agent).where(Agent.code == "code-review"))).scalar_one()
        row.kind = AgentKind.tool  # 故意改坏
        s.add(row)
        await s.commit()

    await seed_agents()
    async with AsyncSessionLocal() as s:
        row = (await s.execute(select(Agent).where(Agent.code == "code-review"))).scalar_one()
        assert row.kind.value == "board"


async def test_list_agents_is_anonymous_readable(client):
    """首页对匿名用户开放只读 —— 不带 token 也要能拿到能力清单."""
    await seed_agents()
    r = await client.get("/api/v1/agents")
    assert r.status_code == 200, r.text()
    items = r.json()["items"]
    assert len(items) > 0
    codes = {i["code"] for i in items}
    assert "kb-inventory" in codes, "知识库存必须跟其他能力同列"


async def test_list_agents_carries_kind(client):
    """列表里每项都要带 kind —— 前端按它决定形态徽标 / CTA / meta."""
    await seed_agents()
    r = await client.get("/api/v1/agents")
    assert r.status_code == 200
    for item in r.json()["items"]:
        assert item["kind"] in VALID_KINDS


async def test_list_agents_filter_by_kind(client):
    """按形态过滤 —— 首页的形态筛选条直接用它."""
    await seed_agents()
    r = await client.get("/api/v1/agents", params={"kind": "library"})
    assert r.status_code == 200
    items = r.json()["items"]
    assert items, "库里应该至少有一张 library 卡"
    assert all(i["kind"] == "library" for i in items)
    assert any(i["code"] == "kb-inventory" for i in items)


async def test_get_capability_anonymous(client):
    """单项能力详情也匿名可读 (点卡片前要先知道它是什么形态)."""
    await seed_agents()
    r = await client.get("/api/v1/agents/kb-inventory")
    assert r.status_code == 200, r.text()
    assert r.json()["kind"] == "library"
