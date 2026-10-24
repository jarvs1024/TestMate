"""add download_count (下载次数)

安装语义下线后, 「安装次数」是**猜不出来的** —— 后端只知道用户点了下载,
不知道人家到底解压没有. 但**下载次数**是准确的: 下载端点自己就知道.

所以恢复一个**语义正确**的计数: download_count (不是 install_count).

它是热门度指标 (排序 hot 用), 任何人都能下 —— 计数增长是正常的.

沿用之前迁移的做法: 用 inspector 做幂等守卫 —— MySQL DDL 非事务,
迁移中途失败不会回滚已执行的 ALTER, 但 alembic 版本号会回退.
守卫保证半途失败后重跑能补齐.

Revision ID: 0011
Revises: 0010_drop_install_tracking
Create Date: 2026-10-24
"""
from alembic import op
import sqlalchemy as sa


revision = "0011_asset_download_count"
down_revision = "0010_drop_install_tracking"
branch_labels = None
depends_on = None


def upgrade() -> None:
    insp = sa.inspect(op.get_bind())
    cols = {c["name"] for c in insp.get_columns("assets")}
    if "download_count" not in cols:
        op.add_column(
            "assets",
            sa.Column("download_count", sa.Integer(), nullable=False, server_default="0"),
        )


def downgrade() -> None:
    op.drop_column("assets", "download_count")
