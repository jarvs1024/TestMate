"""add review_note (上架审核意见)

二期: 上架需要审核 (审核人是管理员)
  assets.review_note  最近一次审核意见 (驳回理由 / 审核备注)

沿用 0006/0007/0008 的做法: 用 inspector 做幂等守卫 —— MySQL DDL 非事务,
迁移中途失败不会回滚已执行的 ALTER, 但 alembic 版本号会回退.
守卫保证半途失败后重跑能补齐.

Revision ID: 0009
Revises: 0008_asset_notifications
Create Date: 2026-10-22
"""
from alembic import op
import sqlalchemy as sa


revision = "0009_asset_review_note"
down_revision = "0008_asset_notifications"
branch_labels = None
depends_on = None


def upgrade() -> None:
    insp = sa.inspect(op.get_bind())
    cols = {c["name"] for c in insp.get_columns("assets")}
    if "review_note" not in cols:
        # ⚠️ TEXT 列不能带 DEFAULT (MySQL errno 1101) —— 默认值走 ORM 侧 default=
        op.add_column(
            "assets", sa.Column("review_note", sa.Text(), nullable=False)
        )


def downgrade() -> None:
    op.drop_column("assets", "review_note")
