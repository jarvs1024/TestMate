"""智能体/工作流注册表 —— 现在叫「能力注册表」。

每个 Agent = 平台上的一项**能力**. 能力有四种形态 (AgentKind):
工具 / 看板 / 目录 / 知识 —— 只有 tool 形态才是真正的"智能体"(有引擎、有输入 schema).

平台所有能力都挂在这张表上, 新增一项能力 = 首页多一张卡, 不动主框架.
"""
from datetime import datetime
import enum

from sqlalchemy import String, DateTime, Enum, BigInteger, Integer, Text, JSON, Boolean
from sqlalchemy.orm import Mapped, mapped_column

from app.db.session import Base


class AgentStatus(str, enum.Enum):
    """上架状态 / 灰度等级。"""

    draft = "draft"           # 草稿, 仅创建者可见
    alpha = "alpha"           # 内测, 指定人可见
    beta = "beta"             # 公开测试, 可灰度比例
    stable = "stable"         # 正式
    deprecated = "deprecated" # 弃用


class AgentCategory(str, enum.Enum):
    """域标签 (物理上限制 agent 的数据/工具/使用范围)。"""

    ssd_trace = "ssd-trace"           # NVMe/SATA trace 诊断
    ssd_fw = "ssd-fw"                 # FW 版本比对 / 风险
    ssd_fio = "ssd-fio"               # fio 报告对比
    ssd_burn = "ssd-burn"             # 老化/长时任务
    ssd_spec = "ssd-spec"             # 协议 / spec 问答
    ssd_report = "ssd-report"         # 测试报告 / 周报
    ssd_ops = "ssd-ops"               # 机台/环境运维
    auto_code = "auto-code"           # 自动化代码 (代码检视 / PR-Agent / 静态分析等)
    ai_market = "ai-market"           # AI 资产市场入口 (插件 / 技能 / 连接器集市, 跳 /market 页)
    ssd_kb = "ssd-kb"                 # 知识库存 (RAGFlow 数据集 / 文档 / 检索)


class AgentKind(str, enum.Enum):
    """能力形态 —— 这张卡**怎么用**, 跟 category (业务域) 正交.

    2026-10-25 起前端首页是「能力墙」而不是「智能体广场」:
    卡片不再都是智能体 —— 代码检视是看板, 资产市场是目录, 知识库存是知识.
    这四种交互形态必须显式建模, 否则卡片会继续顶着智能体的皮
    (引擎 / 调用次数 / 最近调用 这些字段对看板和目录全是假信息).

    · tool     填参数 → 出结果 (日志分析 / 用例生成)
    · board    只读指标看板 (代码检视)
    · catalog  可浏览的共享资产目录 (AI 资产市场)
    · library  知识库存 + 检索 (知识库)

    ⚠️ 名字与值故意一致 (都无连字符): MySQL ENUM 存的是 enum **name**,
       name 与 value 一致时不会有 0003/0004 踩过的那个坑.
    """

    tool = "tool"
    board = "board"
    catalog = "catalog"
    library = "library"


class AgentEngine(str, enum.Enum):
    """后端执行引擎。"""

    dify = "dify"                     # Dify workflow (主)
    n8n = "n8n"                       # n8n flow
    builtin = "builtin"               # 平台内置 (不依赖外部 AI)


class Agent(Base):
    __tablename__ = "agents"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)

    # ===== 基础元信息 =====
    code: Mapped[str] = mapped_column(String(64), nullable=False, unique=True, index=True)
    name: Mapped[str] = mapped_column(String(64), nullable=False)
    icon: Mapped[str] = mapped_column(String(16), nullable=False, default="🩺")
    category: Mapped[AgentCategory] = mapped_column(Enum(AgentCategory), nullable=False)
    # ===== 能力形态 (2026-10-25) =====
    # 跟 category 正交: category 说的是"管哪块业务", kind 说的是"这张卡怎么用".
    # 默认 tool —— 老数据在 seed_agents 启动同步里会被改写成正确的形态.
    kind: Mapped[AgentKind] = mapped_column(Enum(AgentKind), nullable=False, default=AgentKind.tool)
    version: Mapped[str] = mapped_column(String(16), nullable=False, default="v0.1.0")
    status: Mapped[AgentStatus] = mapped_column(
        Enum(AgentStatus), nullable=False, default=AgentStatus.draft
    )

    # ===== 描述 (强制: 新人只看这段就知道干嘛的/什么场景用/不该用啥场景) =====
    summary: Mapped[str] = mapped_column(String(255), nullable=False)
    use_when: Mapped[str] = mapped_column(Text, nullable=False, default="")
    not_for: Mapped[str] = mapped_column(Text, nullable=False, default="")
    tags: Mapped[list] = mapped_column(JSON, nullable=False, default=list)

    # ===== 后端执行 =====
    engine: Mapped[AgentEngine] = mapped_column(
        Enum(AgentEngine), nullable=False, default=AgentEngine.dify
    )
    engine_config: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)

    # ===== 输入参数 schema (前端动态渲染表单) =====
    # 形如:
    # [
    #   {"key":"trace_file", "label":"trace 文件", "type":"file", "required":True},
    #   {"key":"machine_id", "label":"机台", "type":"machine_select", "required":True},
    #   {"key":"fw_version", "label":"FW 版本", "type":"text", "required":False},
    #   {"key":"mode", "label":"解析模式", "type":"select",
    #    "options":["rule+rag","rule","llm"], "default":"rule+rag"},
    # ]
    input_schema: Mapped[list] = mapped_column(JSON, nullable=False, default=list)

    # ===== 数据源 / 工具白名单 (避免变通用 AI) =====
    data_sources: Mapped[list] = mapped_column(JSON, nullable=False, default=list)
    tools: Mapped[list] = mapped_column(JSON, nullable=False, default=list)

    # ===== 灰度/权限 =====
    visibility: Mapped[str] = mapped_column(String(16), nullable=False, default="all")
    allowed_roles: Mapped[list] = mapped_column(JSON, nullable=False, default=list)
    allowed_user_ids: Mapped[list] = mapped_column(JSON, nullable=False, default=list)
    beta_ratio: Mapped[int] = mapped_column(Integer, nullable=False, default=100)

    # ===== 统计 =====
    call_count: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0)
    last_called_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    is_featured: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)

    # ===== 嵌入模式 =====
    # 有值时, AgentRunner 跳过表单+流程, 直接全屏渲染该 URL 的 iframe (内嵌第三方 chatbot/页面)
    embed_url: Mapped[str | None] = mapped_column(String(512), nullable=True)

    # ===== 自定义路由 =====
    # 默认空 = 走 AgentRunner (表单+流程).
    # 有值时, AgentCard 点击跳到指定路由, 而不是 Runner.
    # 格式: "page:<name>" 跳前端路由 name (例: "page:code-review" → /code-review)
    route: Mapped[str | None] = mapped_column(String(64), nullable=True)

    # ===== 时间戳 =====
    created_by: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow
    )
