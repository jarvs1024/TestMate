"""评论一级回复

背景 (2026-11-15):
    资产作者 / 管理员可以回复用户评论. 只支持一级 ——
    `parent_id` 指向主评论, 回复的 parent_id 恒为空, 不能套娃.

Revision ID: 0041_add_comment_parent
Revises: 0040_add_asset_comments
Create Date: 2026-11-15
"""
import sqlalchemy as sa

from alembic import op

revision = "0041_add_comment_parent"
down_revision = "0040_add_asset_comments"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "asset_comments", sa.Column("parent_id", sa.BigInteger(), nullable=True),
    )
    op.create_index("ix_asset_comments_parent_id", "asset_comments", ["parent_id"])


def downgrade() -> None:
    op.drop_index("ix_asset_comments_parent_id", table_name="asset_comments")
    op.drop_column("asset_comments", "parent_id")
