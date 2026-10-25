"""能力角色收敛为三种 + 新增 agents.cta

2026-10-25 第二版: 角色从四种 (tool / board / catalog / library) 收成三种
(tool / board / platform).

为什么收敛:
    "目录" 和 "知识" 都在**泄漏实现** —— 前者说的是目录结构, 后者说的是内容形态,
    跟用户脑子里的"这东西能干嘛"对不上.
    实际上资产市场里三种资产的官方说明写得很清楚:
    "一段可复用的方法与知识, 装进 Agent 后直接照着做" / "让 Agent 连到外部服务"
    —— 资产本来就是装进 Agent 的扩展; 知识库则是 RAGFlow 的数据集/分段, 是检索语料.
    两者同属一类: **给上面两类能力供料的底座**.

    细分信息没丢 —— 靠 category 区分 (ai-market / ssd-kb), 不该由角色徽标来背.

为什么加 cta 列:
    同一角色下的卡动法不同 (底座里的"浏览技能包" vs "检索语料"),
    所以 CTA 不能由角色决定, 得每张卡自带 —— admin 以后加卡也能自己写按钮词.

⚠️ 同 0003/0004: SQLAlchemy 用 Enum(AgentKind) 时 MySQL 列存的是 enum name,
   这里 name 与 value 一致 (都无连字符), 所以直接写字面量即可.

Revision ID: 0018
Revises: 0017_add_ssd_kb_category
Create Date: 2026-10-25
"""
from alembic import op
import sqlalchemy as sa


revision = "0018_capability_roles"
down_revision = "0017_add_ssd_kb_category"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # ⚠️ 顺序很要紧: MySQL ENUM 列**不接受列表外的值** (严格模式下报 1265
    #    "Data truncated for column 'kind'"), 所以必须先把 ENUM 撑开,
    #    再改数据, 最后收紧 —— 反过来做会在有数据时直接炸掉.
    # 1) 撑开 ENUM: 先容下 platform
    op.execute(
        "ALTER TABLE agents MODIFY COLUMN kind "
        "ENUM('tool','board','catalog','library','platform') NOT NULL DEFAULT 'tool'"
    )
    # 2) 数据迁移: 目录 / 知识 → 底座
    op.execute(
        "UPDATE agents SET kind = 'platform' WHERE kind IN ('catalog', 'library')"
    )
    # 3) 收紧 ENUM: 只留三种角色
    op.execute(
        "ALTER TABLE agents MODIFY COLUMN kind "
        "ENUM('tool','board','platform') NOT NULL DEFAULT 'tool'"
    )
    # 4) 加 cta 列 (每张卡自己的动作词; 空 = 前端按角色给默认)
    insp = sa.inspect(op.get_bind())
    cols = {c["name"] for c in insp.get_columns("agents")}
    if "cta" not in cols:
        op.add_column(
            "agents",
            sa.Column("cta", sa.String(32), nullable=False, server_default=""),
        )


def downgrade() -> None:
    # 同样先撑开 ENUM, 再改数据, 最后收紧.
    op.execute(
        "ALTER TABLE agents MODIFY COLUMN kind "
        "ENUM('tool','board','catalog','library','platform') NOT NULL DEFAULT 'tool'"
    )
    # 1) 先把 platform 拆回 catalog / library —— 靠 category 还原:
    #    ai_market 是资产市场 (目录), ssd_kb 是知识库存 (知识)
    #    ⚠️ category 也是 Enum 列, MySQL 存的是 enum **name** (下划线), 不是 value.
    op.execute(
        "UPDATE agents SET kind = 'catalog' WHERE kind = 'platform' AND category = 'ai_market'"
    )
    op.execute(
        "UPDATE agents SET kind = 'library' WHERE kind = 'platform' AND category = 'ssd_kb'"
    )
    # 其余 platform 的行归回 tool (最保守: 有引擎有参数, 能跑)
    op.execute("UPDATE agents SET kind = 'tool' WHERE kind = 'platform'")
    op.execute(
        "ALTER TABLE agents MODIFY COLUMN kind "
        "ENUM('tool','board','catalog','library') NOT NULL DEFAULT 'tool'"
    )
    op.drop_column("agents", "cta")
