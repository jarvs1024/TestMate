"""add asset_notifications (钉钉通知送达回执)

二期收尾: 通知从 fire-and-forget 变成"可观测 + 可重试"
  asset_notifications   每次通知尝试的记录: 状态 / 重试次数 / 错误原因 / 消息正文
                        (正文存下来是为了重试时能原样重发, 不用重新拼)

沿用 0006/0007 的做法: 用 inspector 做幂等守卫 —— MySQL DDL 非事务, 迁移中途失败
不会回滚已执行的 DDL, 但 alembic 版本号会回退. 守卫保证半途失败后重跑能补齐.

Revision ID: 0008
Revises: 0007_asset_publish_status
Create Date: 2026-10-22
"""
from alembic import op
import sqlalchemy as sa


revision = "0008_asset_notifications"
down_revision = "0007_asset_publish_status"
branch_labels = None
depends_on = None


def upgrade() -> None:
    if "asset_notifications" in sa.inspect(op.get_bind()).get_table_names():
        return
    op.create_table(
        "asset_notifications",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("event", sa.String(length=32), nullable=False, server_default=""),
        sa.Column("code", sa.String(length=64), nullable=False, server_default=""),
        sa.Column("asset_name", sa.String(length=128), nullable=False, server_default=""),
        sa.Column("status", sa.String(length=16), nullable=False, server_default="pending"),
        sa.Column("attempts", sa.Integer(), nullable=False, server_default="0"),
        # ⚠️ TEXT 列不能带 DEFAULT (MySQL errno 1101) —— 默认值走 ORM 侧 default=
        sa.Column("error", sa.Text(), nullable=False),
        sa.Column("title", sa.String(length=256), nullable=False, server_default=""),
        sa.Column("text", sa.Text(), nullable=False),
        sa.Column("last_attempt_at", sa.DateTime(), nullable=True),
        sa.Column("next_retry_at", sa.DateTime(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_asset_notifications_event", "asset_notifications", ["event"], unique=False
    )
    op.create_index(
        "ix_asset_notifications_code", "asset_notifications", ["code"], unique=False
    )
    op.create_index(
        "ix_asset_notifications_status", "asset_notifications", ["status"], unique=False
    )


def downgrade() -> None:
    op.drop_index("ix_asset_notifications_status", table_name="asset_notifications")
    op.drop_index("ix_asset_notifications_code", table_name="asset_notifications")
    op.drop_index("ix_asset_notifications_event", table_name="asset_notifications")
    op.drop_table("asset_notifications")
