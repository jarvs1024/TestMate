"""能力 (capability) 的角色模型 —— 2026-10-25 能力墙重构 (第二版: 三角色).

盯住五件事:
   ① 每条 SEED 都带 kind, 且只有三种角色 (tool 干活 / board 看数 / platform 供料);
   ② 角色**不许泄漏实现** —— 曾经有 catalog(目录) / library(知识) 两个角色,
      一个说的是目录结构, 一个说的是内容形态, 都被收进 platform(底座);
   ③ **知识库存从侧栏顶级项变成了一张卡** (kind=platform, route=page:kb-manage);
   ④ 每张卡自带 cta —— 同角色的卡动法不同 (浏览技能包 vs 检索语料);
   ⑤ GET /agents **匿名可读** + 能按角色过滤.
"""
from app.api.agents import SEED_AGENTS, seed_agents
from app.models.agent import AgentKind

VALID_KINDS = {k.value for k in AgentKind}


def test_seed_entries_all_have_valid_kind():
    """每条 seed 都要声明角色 —— 漏了前端就会把它当工具卡渲染 (引擎/调用次数全是假的)."""
    for cfg in SEED_AGENTS:
        assert cfg.get("kind") in VALID_KINDS, f"{cfg['code']} 的 kind 不合法: {cfg.get('kind')}"


def test_seed_kinds_match_real_role():
    """角色要跟卡片**实际**扮演的东西对得上 —— 角色错了卡片就渲染错了."""
    by_code = {c["code"]: c for c in SEED_AGENTS}
    assert by_code["code-review"]["kind"] == AgentKind.board.value      # 看数
    assert by_code["agent-market"]["kind"] == AgentKind.platform.value  # 供料
    assert by_code["kb-inventory"]["kind"] == AgentKind.platform.value  # 供料
    for code in ("log-analysis", "env-ops", "test-plan-gen", "testcase-gen"):
        assert by_code[code]["kind"] == AgentKind.tool.value           # 干活


def test_roles_do_not_leak_implementation():
    """角色只有三种, 且**不许**再有「目录」「知识」这种泄漏实现的角色.

    2026-10-25 第二版: catalog(目录) / library(知识) 收成 platform(底座) ——
    前者说的是目录结构, 后者说的是内容形态, 用户脑子里的分类是"这卡干嘛".
    """
    assert {k.value for k in AgentKind} == {"tool", "board", "platform"}


def test_every_seed_card_has_its_own_cta():
    """CTA 必须每张卡自带 —— 底座里"浏览技能包"和"检索语料"动法不同."""
    for cfg in SEED_AGENTS:
        assert cfg.get("cta"), f"{cfg['code']} 缺 cta"
    by_code = {c["code"]: c for c in SEED_AGENTS}
    assert by_code["agent-market"]["cta"] == "浏览技能包"
    assert by_code["kb-inventory"]["cta"] == "检索语料"
    assert by_code["code-review"]["cta"] == "查看看板"


def test_kb_inventory_seed():
    """知识库存卡: 名字/图标/域标签/路由都要对, 否则首页点进去跳错页."""
    kb = next(c for c in SEED_AGENTS if c["code"] == "kb-inventory")
    assert kb["name"] == "知识库存"
    assert kb["icon"] == "📚"
    assert kb["category"] == "ssd-kb"  # Python 侧的值; MySQL ENUM 存的是 name(ssd_kb)
    assert kb["route"] == "page:kb-manage"
    assert kb["status"] != "draft", "知识库是**已实现**的能力, 不能是规划中"


async def test_seed_agents_persists_kind():
    """seed_agents 真跑一遍后, 库里每行的角色都要对得上 seed 配置."""
    from sqlalchemy import select

    from app.db.session import AsyncSessionLocal
    from app.models.agent import Agent

    await seed_agents()

    async with AsyncSessionLocal() as s:
        rows = (await s.execute(select(Agent))).scalars().all()
    kinds = {r.code: r.kind.value for r in rows}
    assert kinds["code-review"] == "board"
    assert kinds["agent-market"] == "platform"
    assert kinds["kb-inventory"] == "platform"
    assert kinds["log-analysis"] == "tool"


async def test_seed_agents_syncs_kind_of_existing_row():
    """存量行的角色也要被 seed 改回来 —— 它是**平台级契约**, 前端整张卡都靠它."""
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


async def test_seed_agents_syncs_cta_of_existing_row():
    """CTA 也是平台级契约 —— 存量行的 CTA 要被 seed 改回来."""
    from sqlalchemy import select

    from app.db.session import AsyncSessionLocal
    from app.models.agent import Agent

    await seed_agents()
    async with AsyncSessionLocal() as s:
        row = (await s.execute(select(Agent).where(Agent.code == "kb-inventory"))).scalar_one()
        row.cta = ""
        s.add(row)
        await s.commit()

    await seed_agents()
    async with AsyncSessionLocal() as s:
        row = (await s.execute(select(Agent).where(Agent.code == "kb-inventory"))).scalar_one()
        assert row.cta == "检索语料"


async def test_list_agents_is_anonymous_readable(client):
    """首页对匿名用户开放只读 —— 不带 token 也要能拿到能力清单."""
    await seed_agents()
    r = await client.get("/api/v1/agents")
    assert r.status_code == 200, r.text()
    items = r.json()["items"]
    assert len(items) > 0
    codes = {i["code"] for i in items}
    assert "kb-inventory" in codes, "知识库存必须跟其他能力同列"
    for i in items:
        assert i["cta"], f"{i['code']} 缺 cta"


async def test_list_agents_carries_kind(client):
    """列表里每项都要带 kind —— 前端按它决定角色徽标 / CTA / meta."""
    await seed_agents()
    r = await client.get("/api/v1/agents")
    assert r.status_code == 200
    for item in r.json()["items"]:
        assert item["kind"] in VALID_KINDS


async def test_list_agents_filter_by_kind(client):
    """按角色过滤 —— 首页的角色筛选条直接用它."""
    await seed_agents()
    r = await client.get("/api/v1/agents", params={"kind": "platform"})
    assert r.status_code == 200
    items = r.json()["items"]
    assert items, "库里应该至少有一张 platform 卡"
    assert all(i["kind"] == "platform" for i in items)
    codes = {i["code"] for i in items}
    assert "kb-inventory" in codes
    assert "agent-market" in codes


async def test_get_capability_anonymous(client):
    """单项能力详情也匿名可读 (点卡片前要先知道它是什么角色)."""
    await seed_agents()
    r = await client.get("/api/v1/agents/kb-inventory")
    assert r.status_code == 200, r.text()
    assert r.json()["kind"] == "platform"
    assert r.json()["cta"] == "检索语料"
