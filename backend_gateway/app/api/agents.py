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


# ===== 种子: 4 个 SSD 域智能体 =====
# 跟现有 4 个前端页面 1:1 对应,等新布局跑起来,旧页面 302 到对应 agent
SEED_AGENTS: list[dict] = [
    {
        "code": "trace-doctor",
        "name": "Trace 医生",
        "icon": "🩺",
        "category": AgentCategory.ssd_trace.value,
        "version": "v1.2.0",
        "status": AgentStatus.stable.value,
        "summary": "上传 NVMe/SATA trace,自动定位完成符异常/重传/Credit 耗尽,关联历史同类 case",
        "use_when": "• 跑完 case 拿到 pcap/log\n• 需要快速判断\"是不是 FW 问题\"",
        "not_for": "kernel ring buffer 日志(用 LogLog 智能体)\nFIO 报告对比(用 FIO 判官)\n纯人工解读",
        "tags": ["NVMe", "PCIe", "trace", "诊断"],
        "engine": AgentEngine.dify.value,
        "engine_config": {"workflow_id": "trace_diagnose_v1"},
        "input_schema": [
            {"key": "trace_file", "label": "trace 文件", "type": "file", "required": True,
             "accept": ".pcap,.log,.txt,.bin"},
            {"key": "machine_id", "label": "机台", "type": "machine_select", "required": True},
            {"key": "fw_version", "label": "FW 版本", "type": "text", "required": False,
             "placeholder": "例: 2.1.5-rc3"},
            {"key": "mode", "label": "解析模式", "type": "select",
             "options": ["rule+rag", "rule", "llm"], "default": "rule+rag",
             "required": True},
        ],
        "data_sources": ["machines:SMART", "machines:last_fw", "ragflow:trace_history"],
        "tools": ["dingtalk_send"],
        "is_featured": True,
    },
    {
        "code": "fio-judge",
        "name": "FIO 判官",
        "icon": "📊",
        "category": AgentCategory.ssd_fio.value,
        "version": "v2.0.1",
        "status": AgentStatus.stable.value,
        "summary": "上传 2 份 fio JSON,自动画回归图 + 标红恶化指标 + 关联历史 FW 回归",
        "use_when": "• FW 升级前后, 跑 4K 随机读写要对比\n• 性能抖动要找原因",
        "not_for": "trace/PCIe 行为(用 Trace 医生)\n长期老化数据(用 Aging 守望)",
        "tags": ["FIO", "性能", "回归", "对比"],
        "engine": AgentEngine.dify.value,
        "engine_config": {"workflow_id": "fio_compare_v2"},
        "input_schema": [
            {"key": "baseline", "label": "基线 fio JSON", "type": "file", "required": True,
             "accept": ".json"},
            {"key": "candidate", "label": "新版本 fio JSON", "type": "file", "required": True,
             "accept": ".json"},
            {"key": "regression_pct", "label": "恶化阈值 (%)", "type": "number",
             "default": 5, "min": 1, "max": 50, "required": True},
        ],
        "data_sources": ["ragflow:fio_regression_history"],
        "tools": ["dingtalk_send", "report_save"],
        "is_featured": True,
    },
    {
        "code": "fw-scout",
        "name": "FW 侦察兵",
        "icon": "🧬",
        "category": AgentCategory.ssd_fw.value,
        "version": "v0.3.0",
        "status": AgentStatus.beta.value,
        "summary": "上传两份 FW 镜像,自动 diff + 标出改了哪些模块 + 建议回归 case 清单",
        "use_when": "• 新 FW release 前要评估影响面\n• QA 拿到 changelog 不知道测啥",
        "not_for": "已上机跑的 FW(用 Trace 医生)\n生产事故根因(用 Trace 医生)",
        "tags": ["FW", "diff", "风险", "回归"],
        "engine": AgentEngine.dify.value,
        "engine_config": {"workflow_id": "fw_diff_v0_3"},
        "input_schema": [
            {"key": "fw_base", "label": "基线 FW", "type": "file", "required": True,
             "accept": ".bin,.fw,.zip"},
            {"key": "fw_target", "label": "新 FW", "type": "file", "required": True,
             "accept": ".bin,.fw,.zip"},
            {"key": "scope", "label": "影响范围", "type": "select",
             "options": ["仅 GC", "仅 Trim", "仅 Wear-leveling", "全部", "智能推断"],
             "default": "智能推断", "required": True},
        ],
        "data_sources": ["fw_library", "ragflow:fw_bug_history"],
        "tools": ["dingtalk_send", "case_pool_read"],
        "is_featured": True,
    },
    {
        "code": "aging-watch",
        "name": "老化守望",
        "icon": "⏱",
        "category": AgentCategory.ssd_burn.value,
        "version": "v1.0.0",
        "status": AgentStatus.stable.value,
        "summary": "7×24h 老化/高低温/断电恢复任务派发,实时回传机台状态 + 异常推钉钉",
        "use_when": "• FW 出了一版, 要跑长时老化\n• 客户要求做可靠性验证",
        "not_for": "单次短测试(用其他 agent)\nCI 代码测试(走 Jenkins)",
        "tags": ["老化", "长时任务", "可靠性"],
        "engine": AgentEngine.n8n.value,
        "engine_config": {"workflow_id": "aging_dispatch_v1"},
        "input_schema": [
            {"key": "machine_ids", "label": "机台 (多选)", "type": "machine_multi_select",
             "required": True},
            {"key": "fw_version", "label": "FW 版本", "type": "text", "required": True},
            {"key": "duration_hours", "label": "运行时长 (小时)", "type": "number",
             "default": 168, "min": 1, "required": True},
            {"key": "workload", "label": "工况", "type": "select",
             "options": ["4K 随机写", "128K 顺序写", "混合 70/30", "高低温循环"],
             "default": "4K 随机写", "required": True},
            {"key": "temp_profile", "label": "温箱曲线", "type": "text",
             "placeholder": "例: 25℃→70℃→-10℃, 8h 循环"},
        ],
        "data_sources": ["machines:all", "fw_library"],
        "tools": ["machine_ssh", "dingtalk_send", "job_dispatch"],
        "is_featured": True,
    },
    {
        "code": "kb-query-bot",
        "name": "分类查询知识机器助手",
        "icon": "🤖",
        "category": AgentCategory.ssd_spec.value,  # 协议 / 知识类
        "version": "v1.0.0",
        "status": AgentStatus.stable.value,
        "summary": "基于 Dify Chatbot 的知识库对话入口,直接在 TestMate 里聊,免开新窗口",
        "use_when": "• 随手查 Spec / 协议 / 内部知识库\n• 想在 TestMate 内闭环, 不用切浏览器标签",
        "not_for": "需要 FW diff / FIO 比对 / 老化派发等专业流程 (用对应专业智能体)",
        "tags": ["Dify", "知识库", "对话", "RAG"],
        "engine": AgentEngine.dify.value,
        "engine_config": {"mode": "embed"},
        "input_schema": [],
        "data_sources": ["dify:chatbot:1yidcQMo2wcZJH9B"],
        "tools": [],
        "is_featured": True,
        "embed_url": "http://localhost:35001/chatbot/1yidcQMo2wcZJH9B",
    },
]


async def seed_agents() -> None:
    """启动时跑一次: 4 个种子智能体, 已有就跳过。"""
    async with AsyncSessionLocal() as session:
        for cfg in SEED_AGENTS:
            result = await session.execute(
                select(Agent).where(Agent.code == cfg["code"])
            )
            if result.scalar_one_or_none():
                continue
            agent = Agent(**cfg, created_by=None)
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
