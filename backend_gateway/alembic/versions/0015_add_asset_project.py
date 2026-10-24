"""add project (资产的适用范围: 通用 / 某个项目特有)

资产是团队共有的, 但团队同时跑多个项目 (6100 / 3361 / …), 项目会增减:
    · 有的资产**通用** —— 所有项目都能用 (project = "")
    · 有的是**某个项目特有** —— 只有那个项目用得上 (project = "6100")

存量资产默认 project = "" (通用) —— 不用改数据, 也不用动 GitLab 目录.

Revision ID: 0015
Revises: 0014_add_mcp_config
Create Date: 2026-10-24
"""
from alembic import op
import sqlalchemy as sa


revision = "0015_add_asset_project"
down_revision = "0014_add_mcp_config"
branch_labels = None
depends_on = None


def upgrade() -> None:
    insp = sa.inspect(op.get_bind())
    cols = {c["name"] for c in insp.get_columns("assets")}
    if "project" not in cols:
        op.add_column(
            "assets",
            sa.Column("project", sa.String(32), nullable=False, server_default="", index=True),
        )


def downgrade() -> None:
    op.drop_column("assets", "project")
