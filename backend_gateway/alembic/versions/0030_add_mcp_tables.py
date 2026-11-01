"""Add MCP OAuth, token, and tool-call persistence tables.

Revision ID: 0030_add_mcp_tables
Revises: 0029_add_asset_pending_action
Create Date: 2026-10-31
"""
from alembic import op
import sqlalchemy as sa


revision = "0030_add_mcp_tables"
down_revision = "0029_add_asset_pending_action"
branch_labels = None
depends_on = None


def upgrade() -> None:
    tables = set(sa.inspect(op.get_bind()).get_table_names())

    if "mcp_oauth_clients" not in tables:
        op.create_table(
            "mcp_oauth_clients",
            sa.Column("client_id", sa.String(128), nullable=False),
            sa.Column("client_name", sa.String(255), nullable=False),
            sa.Column("redirect_uris", sa.JSON(), nullable=False),
            sa.Column("scopes", sa.JSON(), nullable=False),
            sa.Column("created_at", sa.DateTime(), nullable=False),
            sa.PrimaryKeyConstraint("client_id"),
        )

    if "mcp_oauth_grants" not in tables:
        op.create_table(
            "mcp_oauth_grants",
            sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
            sa.Column("user_id", sa.BigInteger(), nullable=False),
            sa.Column("client_id", sa.String(128), nullable=False),
            sa.Column("scopes", sa.JSON(), nullable=False),
            sa.Column("version", sa.Integer(), nullable=False),
            sa.Column("revoked_at", sa.DateTime(), nullable=True),
            sa.Column("created_at", sa.DateTime(), nullable=False),
            sa.Column("updated_at", sa.DateTime(), nullable=False),
            sa.PrimaryKeyConstraint("id"),
            sa.UniqueConstraint("user_id", "client_id", name="uk_mcp_grant_user_client"),
        )
        op.create_index("ix_mcp_oauth_grants_user_id", "mcp_oauth_grants", ["user_id"])

    if "mcp_api_tokens" not in tables:
        op.create_table(
            "mcp_api_tokens",
            sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
            sa.Column("name", sa.String(128), nullable=False),
            sa.Column("token_hash", sa.String(64), nullable=False),
            sa.Column("user_id", sa.BigInteger(), nullable=False),
            sa.Column("scopes", sa.JSON(), nullable=False),
            sa.Column("expires_at", sa.DateTime(), nullable=True),
            sa.Column("revoked_at", sa.DateTime(), nullable=True),
            sa.Column("last_used_at", sa.DateTime(), nullable=True),
            sa.Column("created_at", sa.DateTime(), nullable=False),
            sa.PrimaryKeyConstraint("id"),
        )
        op.create_index(
            "ix_mcp_api_tokens_token_hash", "mcp_api_tokens", ["token_hash"], unique=True
        )
        op.create_index("ix_mcp_api_tokens_user_id", "mcp_api_tokens", ["user_id"])

    if "mcp_tool_calls" not in tables:
        op.create_table(
            "mcp_tool_calls",
            sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
            sa.Column("user_id", sa.BigInteger(), nullable=False),
            sa.Column("client_id", sa.String(128), nullable=False),
            sa.Column("domain", sa.String(32), nullable=False),
            sa.Column("tool", sa.String(128), nullable=False),
            sa.Column("read_only", sa.Boolean(), nullable=False),
            sa.Column("success", sa.Boolean(), nullable=False),
            sa.Column("error", sa.Text(), nullable=True),
            sa.Column("args_summary", sa.JSON(), nullable=False),
            sa.Column("duration", sa.Integer(), nullable=False),
            sa.Column("created_at", sa.DateTime(), nullable=False),
            sa.PrimaryKeyConstraint("id"),
        )
        op.create_index("ix_mcp_tool_calls_user_id", "mcp_tool_calls", ["user_id"])
        op.create_index("ix_mcp_tool_calls_client_id", "mcp_tool_calls", ["client_id"])


def downgrade() -> None:
    op.drop_index("ix_mcp_tool_calls_client_id", table_name="mcp_tool_calls")
    op.drop_index("ix_mcp_tool_calls_user_id", table_name="mcp_tool_calls")
    op.drop_table("mcp_tool_calls")
    op.drop_index("ix_mcp_api_tokens_user_id", table_name="mcp_api_tokens")
    op.drop_index("ix_mcp_api_tokens_token_hash", table_name="mcp_api_tokens")
    op.drop_table("mcp_api_tokens")
    op.drop_index("ix_mcp_oauth_grants_user_id", table_name="mcp_oauth_grants")
    op.drop_table("mcp_oauth_grants")
    op.drop_table("mcp_oauth_clients")
