"""下载事件明细

背景 (2026-11-16):
    设置-用户需要「每个用户下载了什么」. 原有 download_count 只是资产级
    累计计数器, count_marks 只保留最近一次去重时间, 无法按用户还原.
    这里新增事件表, 只在计数成功时写一行, 与卡片下载数同口径.

Revision ID: 0044_add_download_events
Revises: 0043_add_user_usage_stats
Create Date: 2026-11-16
"""
import sqlalchemy as sa

from alembic import op

revision = "0044_add_download_events"
down_revision = "0043_add_user_usage_stats"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "download_events",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column("user_id", sa.BigInteger(), nullable=True),
        sa.Column("username", sa.String(64), nullable=False, server_default=""),
        sa.Column("kind", sa.String(16), nullable=False),
        sa.Column("action", sa.String(16), nullable=False, server_default="download"),
        sa.Column("code", sa.String(64), nullable=False),
        sa.Column("name", sa.String(128), nullable=False, server_default=""),
        sa.Column("created_at", sa.DateTime(), nullable=False),
    )
    op.create_index("ix_download_events_created_at", "download_events", ["created_at"])
    op.create_index(
        "ix_download_events_user_created", "download_events", ["user_id", "created_at"]
    )
    op.create_index(
        "ix_download_events_kind_code_created",
        "download_events",
        ["kind", "code", "created_at"],
    )


def downgrade() -> None:
    op.drop_index("ix_download_events_kind_code_created", table_name="download_events")
    op.drop_index("ix_download_events_user_created", table_name="download_events")
    op.drop_index("ix_download_events_created_at", table_name="download_events")
    op.drop_table("download_events")
