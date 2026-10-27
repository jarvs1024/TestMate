"""能力 (capability) 的角色模型 —— 2026-10-25 能力墙重构 (第二版: 三角色).

盯住六件事:
   ① 每条 SEED 都带 kind, 且只有三种角色 (tool 干活 / board 看数 / platform 供料);
   ② 角色**不许泄漏实现** —— 曾经有 catalog(目录) / library(知识) 两个角色,
      一个说的是目录结构, 一个说的是内容形态, 都被收进 platform(资产);
   ③ **知识库从侧栏顶级项变成了一张卡** (kind=platform, route=page:kb-manage);
   ④ 每张卡自带 cta —— 同角色的卡动法不同 (浏览资产 vs 检索语料 vs 浏览软件);
   ⑤ GET /agents **匿名可读** + 能按角色过滤;
   ⑥ 2026-10-27: **工具只留「环境运维」**; 「AI 资产市场」改名「插件·技能·连接」;
      新增「软件库」卡; 环境运维的文案不许再提温箱 / 稳定性那一摊.
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
    assert by_code["agent-market"]["kind"] == AgentKind.platform.value  # 资产
    assert by_code["kb-inventory"]["kind"] == AgentKind.platform.value  # 资产
    assert by_code["software-library"]["kind"] == AgentKind.platform.value  # 资产
    for code in ("env-ops",):
        assert by_code[code]["kind"] == AgentKind.tool.value           # 干活


def test_roles_do_not_leak_implementation():
    """角色只有三种, 且**不许**再有「目录」「知识」这种泄漏实现的角色.

    2026-10-25 第二版: catalog(目录) / library(知识) 收成 platform(资产) ——
    前者说的是目录结构, 后者说的是内容形态, 用户脑子里的分类是"这卡干嘛".
    """
    assert {k.value for k in AgentKind} == {"tool", "board", "platform"}


def test_every_seed_card_has_its_own_cta():
    """CTA 必须每张卡自带 —— 资产组里"浏览资产"/"检索语料"/"浏览软件"动法不同."""
    for cfg in SEED_AGENTS:
        assert cfg.get("cta"), f"{cfg['code']} 缺 cta"
    by_code = {c["code"]: c for c in SEED_AGENTS}
    assert by_code["agent-market"]["cta"] == "浏览资产"
    assert by_code["kb-inventory"]["cta"] == "检索语料"
    assert by_code["software-library"]["cta"] == "浏览软件"
    assert by_code["code-review"]["cta"] == "查看看板"


def test_kb_inventory_seed():
    """知识库卡: 名字/图标/域标签/路由都要对, 否则首页点进去跳错页."""
    kb = next(c for c in SEED_AGENTS if c["code"] == "kb-inventory")
    assert kb["name"] == "知识库"
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
    assert kinds["software-library"] == "platform"
    assert kinds["env-ops"] == "tool"


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
    assert "kb-inventory" in codes, "知识库必须跟其他能力同列"
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
    assert "software-library" in codes


async def test_get_capability_anonymous(client):
    """单项能力详情也匿名可读 (点卡片前要先知道它是什么角色)."""
    await seed_agents()
    r = await client.get("/api/v1/agents/kb-inventory")
    assert r.status_code == 200, r.text()
    assert r.json()["kind"] == "platform"
    assert r.json()["cta"] == "检索语料"


# ===== 主词统一: 「智能体」→「能力」(2026-10-26) =====
#
# 能力墙重构之后首页/侧栏都叫「能力」了, 后端却还在往外送「智能体」——
# 用户在首页看到「能力」, 点进详情页却写着「智能体」, 会以为是两套东西.
# 注释里提历史随便提, 但**会渲染出去的字**必须统一.


def test_seed_cards_avoid_legacy_agent_wording():
    """能力卡上的文案不许再出现「智能体」—— 名字/简介/CTA/什么时候用 都一样."""
    for cfg in SEED_AGENTS:
        for field in ("name", "summary", "cta", "use_when", "not_for"):
            text = cfg.get(field) or ""
            assert "智能体" not in text, f"{cfg['code']} 的 {field} 还留着「智能体」: {text}"


def test_settings_category_labels_avoid_legacy_agent_wording():
    """设置页的分类标签同理 —— 后端不再发「🤖 智能体」这种旧叫法."""
    from app.api.settings import CATEGORY_LABELS

    for cat, label in CATEGORY_LABELS.items():
        assert "智能体" not in label, f"分类 {cat} 的标签还留着「智能体」: {label}"


# ===== 2026-10-27: 能力墙重排 =====

def test_only_env_ops_remains_as_tool():
    """⚠️ 工具组**只留「环境运维」** —— 日志分析 / 测试方案生成 / 文本用例生成 已移出清单.

    为什么要盯死: 那三张卡是"规划中"状态, 挂在侧栏里占位又不点不动 ——
    用户看到三个点不动的入口, 只会以为平台坏了.
    """
    tools = [c["code"] for c in SEED_AGENTS if c["kind"] == "tool"]
    assert tools == ["env-ops"], f"工具组应该只剩环境运维, 实际: {tools}"


def test_env_ops_copy_has_no_temperature_chamber_or_burn_in():
    """环境运维的文案**不许**再提温箱 / 老化那摊.

    范围划定 (2026-10-27): 环境运维 = 基本的服务操作 + SSD 盘符/设备运维,
    由 AI 辅助完成. 温箱环境分析、长时老化派发是另一类活 (要看趋势、要跑很久),
    混进来会让这张卡既不像"运维"也不像"环境监控".
    """
    env = next(c for c in SEED_AGENTS if c["code"] == "env-ops")
    blob = " ".join(
        str(env.get(f) or "")
        for f in ("name", "summary", "use_when", "not_for", "tags")
    )
    for word in ("温箱", "老化", "温度", "功耗"):
        assert word not in blob, f"环境运维的文案里还有「{word}」: {blob}"


def test_env_ops_copy_covers_the_intended_scope():
    """反过来也要盯: 该说的得在 —— 服务操作 / SSD 盘符设备 / AI 辅助."""
    env = next(c for c in SEED_AGENTS if c["code"] == "env-ops")
    summary = env["summary"]
    assert "服务" in summary, summary
    assert "SSD" in summary, summary
    assert "AI" in summary, summary


def test_agent_market_renamed_to_plugin_skill_connector():
    """「AI 资产市场」→「插件·技能·连接」 —— 老名字跟角色名「资产」撞了, 用户分不清."""
    mkt = next(c for c in SEED_AGENTS if c["code"] == "agent-market")
    assert mkt["name"] == "插件·技能·连接"
    assert "AI 资产市场" not in mkt["name"]
    # 改名了, route 不能变 (前端按 route 跳 /market)
    assert mkt["route"] == "page:market"


def test_software_library_seed():
    """软件库卡: 存内部软件, 展示功能 / 详情 / 适用 / 发布更新说明."""
    sw = next(c for c in SEED_AGENTS if c["code"] == "software-library")
    assert sw["name"] == "软件库"
    assert sw["kind"] == "platform"
    assert sw["category"] == "sw-library"
    assert sw["cta"] == "浏览软件"
    # ⚠️ 2026-10-27: 功能已落地 (/software 页) —— 从"规划中"改成 beta 并接上路由.
    #    以前是 draft 且**没有** route —— 那是"点进去什么都不发生"的死路.
    assert sw["status"] == "beta"
    assert sw["route"] == "page:software"
    blob = " ".join(str(sw.get(f) or "") for f in ("summary", "use_when"))
    for word in ("功能", "详情", "适用", "更新"):
        assert word in blob, f"软件库的说明里少了「{word}」: {blob}"
