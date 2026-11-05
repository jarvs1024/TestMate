"""add count_marks (下载/复制计数冷却窗口去重)

背景 (2026-11-05 · 第二十五轮):
    同一个人反复下载/复制 (误触、重试或恶意连点) 会把 download_count 刷虚高.
    加一张去重标记表: 同一 dedup_key (u:{用户id} / ip:{客户端IP}) 在一小时内
    对同一 code 只计一次, 之后照常计数. 匿名下载按 X-Forwarded-For 第一跳的
    IP 去重; 软件库的版本计数用 `code@版本` 当 code, 与条目计数互相独立.

    表只有 (code, dedup_key) 唯一 + 一个时间戳, 一行一对、只翻新不新增,
    量级是 人数×资产数, 永不膨胀.

Revision ID: 0034_count_marks
Revises: 0033_add_software_download_alias
Create Date: 2026-11-05
"""
from alembic import op
import sqlalchemy as sa


revision = "0034_count_marks"
down_revision = "0033_add_software_download_alias"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "count_marks",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column("code", sa.String(200), nullable=False),
        sa.Column("dedup_key", sa.String(120), nullable=False),
        sa.Column(
            "last_counted_at",
            sa.DateTime(),
            nullable=False,
            server_default=sa.text("CURRENT_TIMESTAMP"),
        ),
        sa.UniqueConstraint("code", "dedup_key", name="uq_count_marks_code_key"),
    )


def downgrade() -> None:
    op.drop_table("count_marks")
