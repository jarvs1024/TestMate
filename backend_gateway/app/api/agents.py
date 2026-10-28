"""能力 API —— 后端仍叫 agents, 用户侧叫「能力」(2026-10-25).

P0: 首页能力墙列表 + 详情 + seed.
P1: 能力注册 CRUD + 调用历史 + 灰度/版本.

⚠️ 列表是**匿名可读**的 (get_optional_user): 首页对未登录用户开放只读,
   登录用户走真实身份, 匿名用户走 anonymous 占位 (跟代码检视看板同一套机制).
   写操作仍然是 get_current_user / admin only.
"""
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select

from app.api.auth import get_current_user, get_optional_user
from app.db.session import AsyncSessionLocal
from app.models.agent import Agent, AgentStatus, AgentCategory, AgentEngine, AgentKind
from app.models.user import User
from app.schemas.agent import AgentOut, AgentListOut, AgentCreateIn

router = APIRouter()

# ===== 平台能力清单 (2026-Q3 路线图) =====
# 每条 = 一张能力卡. kind 决定这张卡在平台里**扮演什么角色**:
#   platform 资产(供料) / tool 工具(干活) / board 看板(看数)
# ⚠️ 角色名 2026-10-27 从"底座"改成"资产" —— "底座"说的是架构位置, 用户看不懂;
#    "资产"说的是"这里放的是可复用的东西"(插件/技能/连接器、知识、软件).
#    顺序也改了: 资产组排最上面 (用户先看到"平台能给我什么", 再看"平台能替我干什么").
# CTA 由每张卡自带 (cta 字段) —— 同一角色下的卡动法不同 (浏览资产 vs 检索语料 vs 浏览软件)
# status=draft 的卡照常展示, 但点进去显示"规划中", 真实 workflow 待资源到位后接
SEED_AGENTS: list[dict] = [
    {
        # ⚠️ 2026-10-27: 工具只保留这一张 (日志分析 / 测试方案生成 / 文本用例生成 已移出清单).
        #
        # 范围说明 (为什么**不**含温箱 / 稳定性那一摊):
        #   环境运维 = **基本的服务操作** + **SSD 盘符/设备的运维**, 由 AI 辅助完成.
        #   温箱环境分析、长时老化派发这类"要看趋势、要跑很久"的活不在这里 ——
        #   它们要的是长周期看护能力, 跟"查一下状态 / 跑一个动作"的运维不是一回事.
        #   (老文案里"温箱与通道占用 / 环境分析 (温度/功耗/吞吐)"就是这部分, 已去掉.)
        "code": "env-ops",
        "name": "环境运维",
        "icon": "🛠",
        "category": AgentCategory.ssd_ops.value,  # 机台/环境
        "kind": AgentKind.tool.value,
        "cta": "开始使用",
        "version": "v0.0.0",
        "status": AgentStatus.draft.value,
        "summary": "环境运维: 基本的服务操作 + SSD 盘符/设备运维 —— 查状态 / 拉日志 / 复位 / 升级固件 / 重启服务, 由 AI 辅助下发与解读",
        "use_when": "(规划中) 要看某台机台上 SSD 盘符/设备的状态, 或顺手执行一个常用运维动作",
        "not_for": "(规划中) 要派发长时批处理任务, 或只想拿原始日志自己判读",
        "tags": ["机台", "运维", "AI 辅助"],
        "engine": AgentEngine.builtin.value,
        "engine_config": {},
        "input_schema": [
            {"key": "query", "label": "查询指令", "type": "text", "required": True,
             "placeholder": "例: 哪些 8 通道机台是空闲的?"},
        ],
        "data_sources": ["machines:status"],
        "tools": ["machine_ssh"],
        "is_featured": False,
    },
    {
        # 原 pr-agent 版代码检视已下线, 广场卡片只剩 ReviewAgent (ReviewAgent 数据更稳定 + 跟 pr-agent 数据可比)
        "code": "code-review",
        "name": "代码检视",
        "icon": "🧬",
        "category": AgentCategory.auto_code.value,  # 自动化代码 (代码检视)
        "kind": AgentKind.board.value,
        "cta": "查看看板",
        "version": "v0.2.0",
        "status": AgentStatus.stable.value,         # 升级 stable: pr-agent 版已下线, 这个是唯一看板
        "summary": "ReviewAgent 评审数据看板: MR 生命周期 / 建议采纳率 / 规则命中 / 作者分布",
        "use_when": "看 MR 评审结果的整体采纳情况, 或下钻到单条 MR 的运行历史 + 建议明细",
        "not_for": "要看单条 review 评论的代码 diff, 直接打开 GitLab MR 页面",
        "tags": ["代码", "检视", "看板"],
        "engine": AgentEngine.builtin.value,
        "engine_config": {},
        "input_schema": [],
        "data_sources": ["review_agent:telemetry"],
        "tools": [],
        "is_featured": True,                        # 提到精选, 占原 pr-agent 版位置
        "route": "page:code-review",
    },
    {
        # 插件·技能·连接: 能力墙入口卡片, 点击跳 /market 页 (仿 Qoder 插件市场的浏览页).
        # 原型期数据为前端静态 (frontend_web/src/views/Market/marketCatalog.ts), 后端只提供这张入口卡.
        # route 走 "page:" 前缀 → Home/index.vue onOpen 会 router.push({ name: 'market' }).
        # ⚠️ status 不能是 draft: CapabilityCard 对 draft 直接 return 不跳转 + 盖"规划中"遮罩.
        #
        # ⚠️ 2026-10-27 改名: "AI 资产市场" → "插件·技能·连接".
        #    老名字里"AI 资产"跟角色名"资产"(platform)撞了 —— 用户分不清
        #    "资产市场"卖的是不是"资产"这个角色. 新名字直接说清卖什么:
        #    三种可复用的扩展 (插件 / 技能 / 连接器).
        "code": "agent-market",
        "name": "插件·技能·连接",
        "icon": "🏪",
        "category": AgentCategory.ai_market.value,
        "kind": AgentKind.platform.value,
        "cta": "浏览资产",
        "version": "v0.1.0",
        "status": AgentStatus.beta.value,
        "summary": "可复用的扩展资产: 插件 / 技能 / 连接器, 挑一个装进你的 Agent",
        "use_when": "想找团队里现成的插件、技能或连接器, 或要把自己沉淀的能力上架共享",
        "not_for": "运行具体的 SSD 测试任务请直接点对应的工具型能力",
        "tags": ["插件", "技能", "连接器"],
        "engine": AgentEngine.builtin.value,
        "engine_config": {},
        "input_schema": [],
        "data_sources": [],
        "tools": [],
        "is_featured": False,
        "route": "page:market",
    },
    {
        # 知识库卡 (2026-10-25): 知识库从**侧栏顶级项**降级成能力墙上的一张卡.
        # 之前它跟"广场"是平级的两个功能区, 用户得先判断"我要去广场还是去知识库";
        # 现在所有能力同列, 知识库跟工具/看板一样是其中一张 (资产角色).
        # 详情页仍是原来的知识库工作区 (数据集 / 文档 / 分段 / 检索 / 对话), route 指过去即可.
        "code": "kb-inventory",
        "name": "知识库",
        "icon": "📚",
        "category": AgentCategory.ssd_kb.value,
        "kind": AgentKind.platform.value,
        "cta": "检索语料",
        "version": "v0.1.0",
        "status": AgentStatus.stable.value,
        "summary": "RAG 知识源: 协议规范 / 历史缺陷 / 测试报告的语料, 检索即用",
        "use_when": "要查协议条款、翻历史缺陷结论、找之前的测试报告, 或把新资料喂进 RAG 知识库",
        "not_for": "要跑具体的测试动作请点对应的工具型能力",
        "tags": ["RAG", "语料", "规范"],
        "engine": AgentEngine.builtin.value,
        "engine_config": {},
        "input_schema": [],
        "data_sources": ["ragflow:datasets"],
        "tools": [],
        "is_featured": False,
        "route": "page:kb-manage",
    },
    {
        # 软件库卡 (2026-10-27 新增): 存**公司内部的软件**, 跟"插件·技能·连接"是两回事.
        #   · 插件·技能·连接 → 装进 Agent 的扩展 (可复用能力)
        #   · 软件库        → 给人用的内部软件 (装在哪 / 怎么用 / 什么版本)
        # 展示维度: 功能 / 详情 / 适用场景 / 发布与更新说明.
        # ⚠️ 2026-10-27: 功能已落地 (/software 页) —— status 从 draft 改 beta,
        #    route 接上 (之前是"规划中", 点了不跳任何地方).
        "code": "software-library",
        "name": "软件库",
        "icon": "🧰",
        "category": AgentCategory.sw_library.value,
        "kind": AgentKind.platform.value,
        "cta": "浏览软件",
        "version": "v1.0.0",
        "status": AgentStatus.beta.value,
        "summary": "公司内部软件的统一入口: 功能清单 / 详情 / 适用场景 / 发布与更新说明",
        "use_when": "想知道某个内部软件能干什么、适不适合自己的场景、装在哪、或者最近更新了什么",
        "not_for": "要找装进 Agent 的插件 / 技能 / 连接器请去「插件·技能·连接」",
        "tags": ["软件", "内部", "工具"],
        "engine": AgentEngine.builtin.value,
        "engine_config": {},
        "input_schema": [],
        "data_sources": [],
        "tools": [],
        "is_featured": False,
        "route": "page:software",
    },
]


async def seed_agents() -> None:
    """启动时跑一次:
       - SEED_AGENTS 里的 code 已存在 → 同步元信息 (含 kind / category)
       - 不在 SEED_AGENTS 里的旧 agent → 标记 deprecated (首页不显示, 但 DB 里留痕可回滚)
       - 新增的 code → 插入
       这样切换能力路线图时, DB 自动收敛到 SEED_AGENTS 的状态.

    ⚠️ 2026-10-25 改: **只废弃"曾经是 seed、后来被移出清单"的那些**,
       不再把所有非 seed 行一律标 deprecated ——
       管理员通过 POST /api/v1/agents 自己建的能力, 会在下次重启时凭空消失
       (写操作当时没有任何提示, 重启后能力墙上就少了一张卡).
       现在靠"这条行曾经被 seed 过"来区分 (created_by IS NULL = seed 建的老行).
    """
    async with AsyncSessionLocal() as session:
        seed_codes = {cfg["code"] for cfg in SEED_AGENTS}
        # 1) 把"曾经是 seed、现在被移出清单"的行标 deprecated
        #    判据: created_by IS NULL (seed 建的老行) 且不在 SEED 清单里
        #    —— 管理员自建的能力 created_by 是管理员 id, 不会被误伤.
        old_stmt = select(Agent).where(
            Agent.code.notin_(seed_codes),
            Agent.created_by.is_(None),
        )
        old_result = await session.execute(old_stmt)
        for old_agent in old_result.scalars().all():
            old_agent.status = AgentStatus.deprecated
            session.add(old_agent)
        # 2) 已存在的 seed agent → 同步元信息字段, 不动运行时统计 / 发布状态
        #    同步: summary / use_when / not_for / version / icon / tags / input_schema /
        #          data_sources / tools / kind (draft→beta/stable 自动升档;
        #          stable/beta 不降档, 防止误操作把已发布 agent 标记 draft)
        #    不动: call_count / last_called_at / created_by / is_featured / engine / category
        #    ⚠️ kind 必须同步: 前端首页按 kind 决定卡片的角色徽标 / 元信息 / CTA,
        #       它是**平台级契约**; 改错了前端整张卡会渲染成别的形态.
        sync_keys = ("name", "summary", "use_when", "not_for", "version", "icon", "tags",
                     "input_schema", "data_sources", "tools", "engine_config", "is_featured",
                     "kind", "cta")
        for cfg in SEED_AGENTS:
            result = await session.execute(
                select(Agent).where(Agent.code == cfg["code"])
            )
            agent = result.scalar_one_or_none()
            if not agent:
                agent = Agent(**cfg, created_by=None)
                session.add(agent)
                continue
            changed = False
            for k in sync_keys:
                if getattr(agent, k) != cfg[k]:
                    setattr(agent, k, cfg[k])
                    changed = True
            # route 是**平台级契约** (卡片点了跳哪儿) —— 跟 kind / cta 同一类.
            # ⚠️ 2026-10-28 修: route 以前不在 sync_keys 里, 所以 seed 同步**从不更新
            #    已有行的 route** —— 库里的 software-library 一直是 NULL,
            #    前端 capabilityRouteName() 拿到 NULL 就回落到 'tool-runner',
            #    点「软件库」卡跳进了工具运行页 (参数配置/运行/重置) —— 死路.
            #    seed 指定了 route 就以平台为准 (平台说这张卡该去哪儿, 就得是哪儿);
            #    seed 没指定 (工具型卡 → 走 /c/:code 运行页) 就不动, 保留管理员自己配的.
            cfg_route = cfg.get("route")
            if cfg_route and agent.route != cfg_route:
                agent.route = cfg_route
                changed = True
            # status 升级: 仅 draft → 非 draft 自动升, 不降档
            if agent.status == AgentStatus.draft and cfg["status"] != AgentStatus.draft.value:
                agent.status = AgentStatus(cfg["status"])
                changed = True
            if changed:
                session.add(agent)
        await session.commit()


# ===== API =====

def _validate_enum(enum_cls, value: str, field: str) -> None:
    """枚举值合法性校验 —— 不合法就 422, 别让它变成 500 的 LookupError.

    ⚠️ 注意 API 出入参用的是**连字符 value** ('auto-code'), 而 DB ENUM 存的是
    **下划线 name** ('auto_code'). 所以这里按 **value** 校验, 而不是 name.
    """
    try:
        enum_cls(value)
    except ValueError:
        valid = ", ".join(e.value for e in enum_cls)
        raise HTTPException(
            status_code=422,
            detail=f"unknown {field} '{value}' (可用: {valid})",
        )


@router.get("", response_model=AgentListOut)
async def list_agents(
    category: str | None = Query(None, description="按域标签过滤"),
    status: str | None = Query(None, description="按状态过滤 (stable/beta/alpha/draft)"),
    kind: str | None = Query(None, description="按能力角色过滤 (tool 干活 / board 看数 / platform 供料)"),
    featured_only: bool = Query(False),
    _user: User = Depends(get_optional_user),
) -> AgentListOut:
    """能力列表 —— 首页能力墙用.

    **匿名可读** (2026-10-25): 首页对未登录用户开放只读, 登录用户走真实身份,
    匿名用户走 anonymous 占位 (get_optional_user). 写操作仍然是 admin only.
    """
    async with AsyncSessionLocal() as session:
        stmt = select(Agent).where(Agent.status != AgentStatus.deprecated)
        if category:
            stmt = stmt.where(Agent.category == category)
        if status:
            stmt = stmt.where(Agent.status == status)
        if kind:
            stmt = stmt.where(Agent.kind == kind)
        if featured_only:
            stmt = stmt.where(Agent.is_featured == True)  # noqa: E712
        stmt = stmt.order_by(Agent.is_featured.desc(), Agent.call_count.desc(), Agent.id.asc())
        result = await session.execute(stmt)
        items = result.scalars().all()
        return AgentListOut(
            items=[AgentOut.model_validate(a) for a in items],
            total=len(items),
        )


@router.get("/{code}", response_model=AgentOut)
async def get_agent(
    code: str,
    _user: User = Depends(get_optional_user),
) -> AgentOut:
    """单项能力详情 —— 同样匿名可读 (首页卡片点进去前要先知道它是什么角色)."""
    async with AsyncSessionLocal() as session:
        result = await session.execute(select(Agent).where(Agent.code == code))
        agent = result.scalar_one_or_none()
        if not agent:
            raise HTTPException(status_code=404, detail=f"capability '{code}' not found")
        return AgentOut.model_validate(agent)


@router.post("", response_model=AgentOut)
async def create_agent(
    payload: AgentCreateIn,
    _user: User = Depends(get_current_user),
) -> AgentOut:
    """新建能力。admin only。"""
    if _user.role.value != "admin":
        raise HTTPException(status_code=403, detail="admin only")
    # 枚举值先校验: 直接丢给 DB 的话, 传个已下线的值 (如 dify) 会变成 500 的
    # LookupError, 调用方看不出是自己参数不对.
    #
    # ⚠️ category / kind / status 同样要校验 —— 而且它们有个**不对称**:
    #    API 出参是**连字符**的 value ('auto-code'), DB ENUM 存的是**下划线**的
    #    name ('auto_code'). 谁要是把 GET /agents 返回的 category 原样回传给
    #    POST /agents, SQLAlchemy 按 name 找就找不到 → LookupError → 500.
    _validate_enum(AgentEngine, payload.engine, "engine")
    _validate_enum(AgentCategory, payload.category, "category")
    _validate_enum(AgentKind, payload.kind, "kind")
    _validate_enum(AgentStatus, payload.status, "status")
    async with AsyncSessionLocal() as session:
        result = await session.execute(select(Agent).where(Agent.code == payload.code))
        if result.scalar_one_or_none():
            raise HTTPException(status_code=409, detail=f"code '{payload.code}' exists")
        agent = Agent(**payload.model_dump(), created_by=_user.id)
        session.add(agent)
        await session.commit()
        await session.refresh(agent)
        return AgentOut.model_validate(agent)
