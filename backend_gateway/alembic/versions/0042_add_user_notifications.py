"""站内通知

背景 (2026-11-16):
    扩展库评论/回复的站内提醒. 同一收件人 + dedupe_key 在未读期间聚合为
    一行 (event_count 累加), 已读后新事件另起一行.

Revision ID: 0042_add_user_notifications
Revises: 0041_add_comment_parent
Create Date: 2026-11-16
"""
import sqlalchemy as sa

from alembic import op

revision = "0042_add_user_notifications"
down_revision = "0041_add_comment_parent"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "user_notifications",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column("user_id", sa.BigInteger(), nullable=True),
        sa.Column("username", sa.String(64), nullable=False, server_default=""),
        sa.Column("actor_id", sa.BigInteger(), nullable=True),
        sa.Column("actor_name", sa.String(64), nullable=False, server_default=""),
        sa.Column("kind", sa.String(24), nullable=False),
        sa.Column("dedupe_key", sa.String(160), nullable=False, server_default=""),
        sa.Column("asset_code", sa.String(64), nullable=False, server_default=""),
        sa.Column("asset_name", sa.String(128), nullable=False, server_default=""),
        sa.Column("comment_id", sa.BigInteger(), nullable=True),
        sa.Column("parent_comment_id", sa.BigInteger(), nullable=True),
        sa.Column("title", sa.String(200), nullable=False, server_default=""),
        sa.Column("body", sa.Text(), nullable=False),
        sa.Column("event_count", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("read_at", sa.DateTime(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
    )
    op.create_index("ix_user_notifications_user_id", "user_notifications", ["user_id"])
    op.create_index("ix_user_notifications_kind", "user_notifications", ["kind"])
    op.create_index(
        "ix_user_notifications_dedupe_key", "user_notifications", ["dedupe_key"],
    )
    op.create_index(
        "ix_user_notifications_user_read", "user_notifications", ["user_id", "read_at"],
    )
    op.create_index(
        "ix_user_notifications_name_read", "user_notifications", ["username", "read_at"],
    )
    op.create_index(
        "ix_user_notifications_dedupe",
        "user_notifications",
        ["user_id", "dedupe_key", "read_at"],
    )


def downgrade() -> None:
    for name in (
        "ix_user_notifications_dedupe",
        "ix_user_notifications_name_read",
        "ix_user_notifications_user_read",
        "ix_user_notifications_dedupe_key",
        "ix_user_notifications_kind",
        "ix_user_notifications_user_id",
    ):
        op.drop_index(name, table_name="user_notifications")
    op.drop_table("user_notifications")
