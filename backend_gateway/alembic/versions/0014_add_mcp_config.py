"""add mcp_config (连接器的 MCP 配置)

连接器 (mcp) 是**配置型**资产: 以前它也是"包型"(files/.mcp.json + README.md),
现在配置直接写在 manifest.json 里 —— 仓库里一个连接器只有一个 manifest.json.

Revision ID: 0014
Revises: 0013_widen_job_action
Create Date: 2026-10-24
"""
from alembic import op
import sqlalchemy as sa


revision = "0014_add_mcp_config"
down_revision = "0013_widen_job_action"
branch_labels = None
depends_on = None


def upgrade() -> None:
    insp = sa.inspect(op.get_bind())
    cols = {c["name"] for c in insp.get_columns("assets")}
    if "mcp_config" not in cols:
        op.add_column("assets", sa.Column("mcp_config", sa.JSON(), nullable=True))


def downgrade() -> None:
    op.drop_column("assets", "mcp_config")
