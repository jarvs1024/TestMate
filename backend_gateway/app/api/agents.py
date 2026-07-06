"""智能体/工作流 API。

P0: 广场列表 + 详情 + seed.
P1: 智能体注册 CRUD + 调用历史 + 灰度/版本.
"""
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select, or_

from app.api.auth import get_current_user
from app.db.session import AsyncSessionLocal
from app.models.agent import Agent, AgentStatus, AgentCategory, AgentEngine
from app.models.user import User
from app.schemas.agent import AgentOut, AgentListOut, AgentCreateIn

router = APIRouter()

# ===== 在建 4 个智能体 (2026-Q3 路线图) =====
# 全部 status=draft, 广场仍展示, 点进去显示"建设中"; 真实 workflow 待资源到位后接
SEED_AGENTS: list[dict] = [
    {
        "code": "log-analysis",
        "name": "日志分析",
        "icon": "📜",
        "category": AgentCategory.ssd_trace.value,  # 复用 trace 域 (取 log 来源)
        "version": "v0.1.0-demo",
        "status": AgentStatus.beta.value,
        "summary": "SSD 测试日志分析: 贴 kernel ring buffer / 应用日志, 自动分段 + 异常标注 + 错误分类",
        "use_when": "SSD 测试中产生的 syslog / dmesg / FW log 需要结构化解读 (demo 模式: 客户端规则分类, 真实 AI 推理待接 Dify workflow)",
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
        "version": "v0.0.0",
        "status": AgentStatus.draft.value,
        "summary": "给 Spec / 场景 / 工况描述,自动出一版测试方案 + 步骤 + 风险点",
        "use_when": "(规划中) 客户新功能上线前要出测试方案",
        "not_for": "(规划中) 已有 case 模板请用模板库 (后续接入)",
        "tags": ["测试方案", "Spec", "规划中"],
        "engine": AgentEngine.dify.value,
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
        "version": "v0.0.0",
        "status": AgentStatus.draft.value,
        "summary": "指定 Spec + 测试方案,自动展开成可执行的 case 列表 + 预期结果",
        "use_when": "(规划中) QA 拿到方案要快速落 case",
        "not_for": "(规划中) 已有 case 库请用 case 库 (后续接入)",
        "tags": ["用例", "Spec", "规划中"],
        "engine": AgentEngine.dify.value,
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
]


async def seed_agents() -> None:
    """启动时跑一次:
       - SEED_AGENTS 里的 code 已存在 → 跳过
       - 不在 SEED_AGENTS 里的旧 agent → 标记 deprecated (广场不显示, 但 DB 里留痕可回滚)
       - 新增的 code → 插入
       这样切换智能体路线图时, DB 自动收敛到 SEED_AGENTS 的状态.
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
        #          data_sources / tools / status (draft→beta/stable 自动升档;
        #          stable/beta 不降档, 防止误操作把已发布 agent 标记 draft)
        #    不动: call_count / last_called_at / created_by / is_featured / engine
        sync_keys = ("summary", "use_when", "not_for", "version", "icon", "tags",
                     "input_schema", "data_sources", "tools", "engine_config")
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
    featured_only: bool = Query(False),
    _user: User = Depends(get_current_user),
) -> AgentListOut:
    """智能体广场列表。所有人都能调, 但只能看到自己有权访问的。"""
    async with AsyncSessionLocal() as session:
        stmt = select(Agent).where(Agent.status != AgentStatus.deprecated)
        if category:
            stmt = stmt.where(Agent.category == category)
        if status:
            stmt = stmt.where(Agent.status == status)
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
    _user: User = Depends(get_current_user),
) -> AgentOut:
    async with AsyncSessionLocal() as session:
        result = await session.execute(select(Agent).where(Agent.code == code))
        agent = result.scalar_one_or_none()
        if not agent:
            raise HTTPException(status_code=404, detail=f"agent '{code}' not found")
        return AgentOut.model_validate(agent)


@router.post("", response_model=AgentOut)
async def create_agent(
    payload: AgentCreateIn,
    _user: User = Depends(get_current_user),
) -> AgentOut:
    """新建智能体。admin only。"""
    if _user.role.value != "admin":
        raise HTTPException(status_code=403, detail="admin only")
    async with AsyncSessionLocal() as session:
        result = await session.execute(select(Agent).where(Agent.code == payload.code))
        if result.scalar_one_or_none():
            raise HTTPException(status_code=409, detail=f"code '{payload.code}' exists")
        agent = Agent(**payload.model_dump(), created_by=_user.id)
        session.add(agent)
        await session.commit()
        await session.refresh(agent)
        return AgentOut.model_validate(agent)
