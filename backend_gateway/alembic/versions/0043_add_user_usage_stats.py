"""用户使用统计

背景 (2026-11-16):
    设置-用户页需要在线人数、日活曲线与下载排行. 在线靠 users.last_seen_at
    (5 分钟窗口), 日活靠 user_activity_daily 每人每天一行 (按 Asia/Shanghai).

Revision ID: 0043_add_user_usage_stats
Revises: 0042_add_user_notifications
Create Date: 2026-11-16
"""
import sqlalchemy as sa

from alembic import op

revision = "0043_add_user_usage_stats"
down_revision = "0042_add_user_notifications"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "users", sa.Column("last_seen_at", sa.DateTime(), nullable=True)
    )
    op.create_index("ix_users_last_seen_at", "users", ["last_seen_at"])
    op.create_table(
        "user_activity_daily",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column("stat_date", sa.Date(), nullable=False),
        sa.Column("user_id", sa.BigInteger(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.UniqueConstraint(
            "stat_date", "user_id", name="uq_user_activity_daily_date_user"
        ),
    )


def downgrade() -> None:
    op.drop_table("user_activity_daily")
    op.drop_index("ix_users_last_seen_at", table_name="users")
    op.drop_column("users", "last_seen_at")
