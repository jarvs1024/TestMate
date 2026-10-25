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
#   tool 工具(干活) / board 看板(看数) / platform 底座(供料)
# CTA 由每张卡自带 (cta 字段) —— 同一角色下的卡动法不同 (浏览技能包 vs 检索语料)
# status=draft 的卡照常展示, 但点进去显示"规划中", 真实 workflow 待资源到位后接
SEED_AGENTS: list[dict] = [
    {
        "code": "log-analysis",
        "name": "日志分析",
        "icon": "📜",
        "category": AgentCategory.ssd_trace.value,  # 复用 trace 域 (取 log 来源)
        "kind": AgentKind.tool.value,
        "cta": "开始使用",
        "version": "v0.1.0-demo",
        "status": AgentStatus.beta.value,
        "summary": "SSD 测试日志分析: 贴 kernel ring buffer / 应用日志, 自动分段 + 异常标注 + 错误分类",
        "use_when": "SSD 测试中产生的 syslog / dmesg / FW log 需要结构化解读 (demo 模式: 客户端规则分类)",
        "not_for": "NVMe pcap trace 请用 Trace 医生",
        "tags": ["日志", "诊断", "Demo"],
        "engine": AgentEngine.builtin.value,
        "engine_config": {"demo": True},
        "input_schema": [
            {"key": "log_text", "label": "日志文本", "type": "textarea", "required": True,
             "placeholder": "直接粘贴 syslog / dmesg / FW log (多行). 例: [ 1234.56] nvme nvme0: I/O 234 QID 5 timeout, aborting"},
            {"key": "log_type", "label": "日志类型", "type": "select",
             "options": ["auto", "dmesg", "syslog", "fw-log"],
             "default": "auto", "required": True},
        ],
        "data_sources": [],
        "tools": [],
        "is_featured": False,
    },
    {
        "code": "env-ops",
        "name": "环境运维",
        "icon": "🛠",
        "category": AgentCategory.ssd_ops.value,  # 机台/环境
        "kind": AgentKind.tool.value,
        "cta": "开始使用",
        "version": "v0.0.0",
        "status": AgentStatus.draft.value,
        "summary": "环境运维: 查询测试机状态 / 温箱与通道占用 / 环境分析 (温度/功耗/吞吐), 一键执行常用运维命令 (拉日志 / 复位 / 升级 FW)",
        "use_when": "(规划中) 测试过程中要快速查机台 / 看环境 / 跑常用运维动作",
        "not_for": "(规划中) 长时老化派发请用 老化守望",
        "tags": ["机台", "运维", "规划中"],
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
        "code": "test-plan-gen",
        "name": "测试方案生成",
        "icon": "📝",
        "category": AgentCategory.ssd_spec.value,  # 协议 / 知识类
        "kind": AgentKind.tool.value,
        "cta": "开始使用",
        "version": "v0.0.0",
        "status": AgentStatus.draft.value,
        "summary": "给 Spec / 场景 / 工况描述,自动出一版测试方案 + 步骤 + 风险点",
        "use_when": "(规划中) 客户新功能上线前要出测试方案",
        "not_for": "(规划中) 已有 case 模板请用模板库 (后续接入)",
        "tags": ["测试方案", "Spec", "规划中"],
        "engine": AgentEngine.builtin.value,
        "engine_config": {},
        "input_schema": [
            {"key": "spec_doc", "label": "Spec / 需求描述", "type": "text", "required": True,
             "placeholder": "粘贴 spec 章节 / 客户需求 / 工况约束"},
        ],
        "data_sources": [],
        "tools": [],
        "is_featured": False,
    },
    {
        "code": "testcase-gen",
        "name": "文本用例生成",
        "icon": "🧪",
        "category": AgentCategory.ssd_spec.value,
        "kind": AgentKind.tool.value,
        "cta": "开始使用",
        "version": "v0.0.0",
        "status": AgentStatus.draft.value,
        "summary": "指定 Spec + 测试方案,自动展开成可执行的 case 列表 + 预期结果",
        "use_when": "(规划中) QA 拿到方案要快速落 case",
        "not_for": "(规划中) 已有 case 库请用 case 库 (后续接入)",
        "tags": ["用例", "Spec", "规划中"],
        "engine": AgentEngine.builtin.value,
        "engine_config": {},
        "input_schema": [
            {"key": "test_plan", "label": "测试方案", "type": "text", "required": True,
             "placeholder": "贴方案 / 选已有方案"},
            {"key": "style", "label": "用例粒度", "type": "select",
             "options": ["粗 (步骤级)", "中 (操作级)", "细 (断言级)"],
             "default": "中 (操作级)", "required": True},
        ],
        "data_sources": [],
        "tools": [],
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
        # AI 资产市场: 能力墙入口卡片, 点击跳 /market 页 (仿 Qoder 插件市场的浏览页).
        # 原型期数据为前端静态 (frontend_web/src/views/Market/marketCatalog.ts), 后端只提供这张入口卡.
        # route 走 "page:" 前缀 → Home/index.vue onOpen 会 router.push({ name: 'market' }).
        # ⚠️ status 不能是 draft: CapabilityCard 对 draft 直接 return 不跳转 + 盖"规划中"遮罩.
        "code": "agent-market",
        "name": "AI 资产市场",
        "icon": "🏪",
        "category": AgentCategory.ai_market.value,
        "kind": AgentKind.platform.value,
        "cta": "浏览技能包",
        "version": "v0.1.0",
        "status": AgentStatus.beta.value,
        "summary": "智能体的技能沉淀: 插件 / 技能 / 连接器, 挑一个装进你的 Agent",
        "use_when": "想找团队里现成的 AI 能力 (技能包 / 连接器 / 插件), 或要把自己沉淀的资产上架共享",
        "not_for": "运行具体的 SSD 测试任务请直接点对应的工具型能力",
        "tags": ["技能包", "插件", "连接器"],
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
        # 现在所有能力同列, 知识库跟工具/看板一样是其中一张 (底座角色).
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
]


async def seed_agents() -> None:
    """启动时跑一次:
       - SEED_AGENTS 里的 code 已存在 → 同步元信息 (含 kind / category)
       - 不在 SEED_AGENTS 里的旧 agent → 标记 deprecated (首页不显示, 但 DB 里留痕可回滚)
       - 新增的 code → 插入
       这样切换能力路线图时, DB 自动收敛到 SEED_AGENTS 的状态.
    """
    async with AsyncSessionLocal() as session:
        seed_codes = {cfg["code"] for cfg in SEED_AGENTS}
        # 1) 把不在 SEED 里的旧 agent 标 deprecated (广场列表会过滤掉)
        old_stmt = select(Agent).where(Agent.code.notin_(seed_codes))
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
            # status 升级: 仅 draft → 非 draft 自动升, 不降档
            if agent.status == AgentStatus.draft and cfg["status"] != AgentStatus.draft.value:
                agent.status = AgentStatus(cfg["status"])
                changed = True
            if changed:
                session.add(agent)
        await session.commit()


# ===== API =====

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
    # 引擎值先校验: 直接丢给 DB 的话, 传个已下线的值 (如 dify) 会变成 500 的
    # LookupError, 调用方看不出是自己参数不对.
    try:
        AgentEngine(payload.engine)
    except ValueError:
        valid = ", ".join(e.value for e in AgentEngine)
        raise HTTPException(
            status_code=422,
            detail=f"unknown engine '{payload.engine}' (可用: {valid})",
        )
    async with AsyncSessionLocal() as session:
        result = await session.execute(select(Agent).where(Agent.code == payload.code))
        if result.scalar_one_or_none():
            raise HTTPException(status_code=409, detail=f"code '{payload.code}' exists")
        agent = Agent(**payload.model_dump(), created_by=_user.id)
        session.add(agent)
        await session.commit()
        await session.refresh(agent)
        return AgentOut.model_validate(agent)
