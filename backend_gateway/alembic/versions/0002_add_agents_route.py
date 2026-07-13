"""add agents.route (custom route override for non-Runner agents)

广场里部分智能体(代码检视等看板型)不通过 AgentRunner,
而是跳自定义路由. 给 agents 表加 route 列 (nullable).

Revision ID: 0002
Revises: 0001
Create Date: 2026-07-13
"""
from alembic import op
import sqlalchemy as sa


revision = "0002"
down_revision = "0001_initial"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "agents",
        sa.Column("route", sa.String(length=64), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("agents", "route")
