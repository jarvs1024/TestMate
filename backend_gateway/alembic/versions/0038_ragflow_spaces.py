"""RAGFlow 多用户空间: 新表 + 审计空间维度

Revision ID: 0038_ragflow_spaces
Revises: 0037_add_mcp_token_version
Create Date: 2026-11-14
"""
import sqlalchemy as sa

from alembic import op

revision = "0038_ragflow_spaces"
down_revision = "0037_add_mcp_token_version"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if "ragflow_spaces" not in inspector.get_table_names():
        op.create_table(
            "ragflow_spaces",
            sa.Column("id", sa.String(32), primary_key=True),
            sa.Column("name", sa.String(64), nullable=False, unique=True),
            sa.Column("api_key_cipher", sa.Text(), nullable=False),
            sa.Column("is_default", sa.Boolean(), nullable=False, server_default=sa.text("0")),
            sa.Column("created_by", sa.BigInteger(), nullable=True),
            sa.Column("created_at", sa.DateTime(), nullable=False),
            sa.Column("updated_at", sa.DateTime(), nullable=False),
        )
    cols = {c["name"] for c in inspector.get_columns("kb_audits")}
    if "space_id" not in cols:
        op.add_column(
            "kb_audits",
            sa.Column("space_id", sa.String(32), nullable=False, server_default=""),
        )
    if "space_name" not in cols:
        op.add_column(
            "kb_audits",
            sa.Column("space_name", sa.String(64), nullable=False, server_default=""),
        )
    indexes = {i["name"] for i in inspector.get_indexes("kb_audits")}
    if "ix_kb_audits_space_created" not in indexes:
        op.create_index("ix_kb_audits_space_created", "kb_audits", ["space_id", "created_at"])


def downgrade() -> None:
    op.drop_index("ix_kb_audits_space_created", table_name="kb_audits")
    op.drop_column("kb_audits", "space_name")
    op.drop_column("kb_audits", "space_id")
    op.drop_table("ragflow_spaces")
