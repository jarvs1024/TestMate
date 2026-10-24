"""widen asset_jobs.action (16 → 24)

下架改成申请制之后, 任务队列里多几个动作名:
    unpublish_request / unpublish_approve / unpublish_reject / unpublish_cancel
"unpublish_request" 是 17 个字符 —— 老的 String(16) 装不下, MySQL 直接报
"Data too long for column 'action'", 整个申请下架接口 500.

Revision ID: 0013
Revises: 0012_widen_publish_status
Create Date: 2026-10-24
"""
from alembic import op
import sqlalchemy as sa


revision = "0013_widen_job_action"
down_revision = "0012_widen_publish_status"
branch_labels = None
depends_on = None


def upgrade() -> None:
    insp = sa.inspect(op.get_bind())
    cols = {c["name"]: c for c in insp.get_columns("asset_jobs")}
    if "action" not in cols:
        return
    try:
        cur_len = cols["action"]["type"].length
    except AttributeError:  # pragma: no cover - 非 MySQL 方言
        cur_len = None
    if cur_len is not None and int(cur_len) >= 24:
        return
    op.alter_column(
        "asset_jobs",
        "action",
        type_=sa.String(24),
        existing_type=sa.String(16),
        existing_nullable=False,
    )


def downgrade() -> None:
    # ⚠️ 降级会把长动作名截断成 16 字符 —— 降级前先把这类任务清掉.
    op.alter_column(
        "asset_jobs",
        "action",
        type_=sa.String(16),
        existing_type=sa.String(24),
        existing_nullable=False,
    )
