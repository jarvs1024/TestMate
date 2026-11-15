"""用户空间不再有「默认」—— 未指定 space_id 时用最早创建的空间

Revision ID: 0039_drop_space_is_default
Revises: 0038_ragflow_spaces
Create Date: 2026-11-15
"""
import sqlalchemy as sa

from alembic import op

revision = "0039_drop_space_is_default"
down_revision = "0038_ragflow_spaces"
branch_labels = None
depends_on = None


def upgrade() -> None:
    cols = {c["name"] for c in sa.inspect(op.get_bind()).get_columns("ragflow_spaces")}
    if "is_default" in cols:
        op.drop_column("ragflow_spaces", "is_default")


def downgrade() -> None:
    cols = {c["name"] for c in sa.inspect(op.get_bind()).get_columns("ragflow_spaces")}
    if "is_default" not in cols:
        op.add_column(
            "ragflow_spaces",
            sa.Column("is_default", sa.Boolean(), nullable=False, server_default=sa.text("0")),
        )
