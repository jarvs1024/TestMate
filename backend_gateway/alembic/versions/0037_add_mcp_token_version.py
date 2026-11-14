"""静态令牌改短随机串后仍需跟随用户 token_version 失效

Revision ID: 0037_add_mcp_token_version
Revises: 0036_add_integration_credentials
Create Date: 2026-11-14
"""
from alembic import op
import sqlalchemy as sa


revision = "0037_add_mcp_token_version"
down_revision = "0036_add_integration_credentials"
branch_labels = None
depends_on = None


def upgrade() -> None:
    columns = {
        column["name"] for column in sa.inspect(op.get_bind()).get_columns("mcp_api_tokens")
    }
    if "token_version" not in columns:
        op.add_column(
            "mcp_api_tokens",
            sa.Column("token_version", sa.Integer(), nullable=False, server_default="0"),
        )


def downgrade() -> None:
    op.drop_column("mcp_api_tokens", "token_version")
