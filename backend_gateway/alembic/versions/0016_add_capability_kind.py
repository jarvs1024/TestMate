"""add agents.kind (能力形态: tool / board / catalog / library)

2026-10-25: 首页从「智能体广场」改成「能力墙」. 卡片不再都是智能体 ——
代码检视是看板, AI 资产市场是目录, 知识库存是知识. 这四种交互形态
必须显式落到一列, 否则卡片会继续显示引擎/调用次数这些对非工具卡是假信息的字段.

⚠️ 跟 category 正交:
    category = 业务域标签 (ssd-trace / ssd-spec / auto-code …)
    kind     = 交互形态     (tool / board / catalog / library)
    复用 category 会把"看一个看板"和"跑一个 Spec 智能体"混成一类.

存量行统一落成 'tool' (最保守的默认值), 启动时 seed_agents 会按 SEED 配置改写成正确形态.

Revision ID: 0016
Revises: 0015_add_asset_project
Create Date: 2026-10-25
"""
from alembic import op
import sqlalchemy as sa


revision = "0016_add_capability_kind"
down_revision = "0015_add_asset_project"
branch_labels = None
depends_on = None


def upgrade() -> None:
    insp = sa.inspect(op.get_bind())
    cols = {c["name"] for c in insp.get_columns("agents")}
    if "kind" not in cols:
        # AgentKind 的 name 与 value 一致 (都无连字符), 所以这里直接写死字面量.
        op.add_column(
            "agents",
            sa.Column(
                "kind",
                sa.Enum("tool", "board", "catalog", "library", name="agentkind"),
                nullable=False,
                server_default="tool",
            ),
        )


def downgrade() -> None:
    op.drop_column("agents", "kind")
