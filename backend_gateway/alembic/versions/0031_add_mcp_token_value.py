"""Store MCP static tokens for later display in the personal center.

Revision ID: 0031_add_mcp_token_value
Revises: 0030_add_mcp_tables
Create Date: 2026-11-01
"""
from alembic import op
import sqlalchemy as sa


revision = "0031_add_mcp_token_value"
down_revision = "0030_add_mcp_tables"
branch_labels = None
depends_on = None


def upgrade() -> None:
    columns = {column["name"] for column in sa.inspect(op.get_bind()).get_columns("mcp_api_tokens")}
    if "token_value" not in columns:
        op.add_column(
            "mcp_api_tokens",
            sa.Column("token_value", sa.String(2048), nullable=True),
        )


def downgrade() -> None:
    op.drop_column("mcp_api_tokens", "token_value")
