"""智能体/工作流注册表 —— 现在叫「能力注册表」。

每个 Agent = 平台上的一项**能力**. 能力有三种角色 (AgentKind):
工具 (干活) / 看板 (看数) / 底座 (供料) —— 只有 tool 才是真正的"智能体"(有引擎、有输入 schema).

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
    ssd_kb = "ssd-kb"                 # 知识库 (RAGFlow 数据集 / 文档 / 检索)


class AgentKind(str, enum.Enum):
    """能力**角色** —— 这张卡在平台里扮演什么角色, 不是它长什么样.

    2026-10-25 定稿 (第二版): 原来是四种"形态" (tool / board / catalog / library),
    但那两个名字都在**泄漏实现** —— "目录"说的是目录结构, "知识"说的是内容形态,
    跟用户脑子里的"这东西能干嘛"对不上. 实际资产市场里三种资产形态的官方说明
    写得很清楚: "一段可复用的方法与知识, 装进 Agent 后直接照着做" /
    "让 Agent 连到外部服务" —— 资产本来就是**装进 Agent 的扩展**;
    知识库则是 RAGFlow 的数据集/分段, 是**检索语料**.

    所以角色只回答三件事: 干活 / 看数 / 供料.

    · tool      干活: 填参数 → 出结果 (日志分析 / 用例生成 / 测试方案生成)
    · board     看数: 只读指标看板 (代码检视)
    · platform  供料: 给上面两类提供弹药 ——
                 技能沉淀 (插件 / 技能 / 连接器) + RAG 语料 (规范 / 缺陷 / 报告)

    ⚠️ 底座里的两类怎么区分? 靠 **category** (业务域): ai-market / ssd-kb.
       细分信息没丢, 只是不该由角色徽标来背.

    ⚠️ 名字与值故意一致 (都无连字符): MySQL ENUM 存的是 enum **name**,
       name 与 value 一致时不会有 0003/0004 踩过的那个坑.
    """

    tool = "tool"
    board = "board"
    platform = "platform"


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
    # ===== 能力角色 (2026-10-25) =====
    # 跟 category 正交: category 说的是"管哪块业务", kind 说的是"扮演什么角色".
    # 默认 tool —— 老数据在 seed_agents 启动同步里会被改写成正确的角色.
    kind: Mapped[AgentKind] = mapped_column(Enum(AgentKind), nullable=False, default=AgentKind.tool)
    # ===== 卡片自己的动作词 (2026-10-25) =====
    # 同一角色下的卡动法不同 (底座里的"浏览技能包" vs "检索语料"),
    # 所以 CTA 不能由角色决定, 得每张卡自带 —— admin 以后加卡也能自己写按钮词.
    # 空 = 前端按角色给默认词.
    cta: Mapped[str] = mapped_column(String(32), nullable=False, default="")
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
