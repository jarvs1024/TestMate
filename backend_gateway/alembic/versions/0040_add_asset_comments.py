"""资产用户评论

背景 (2026-11-15):
    扩展库每个资产详情增加用户评论 —— 平铺, 第一版不支持回复/点赞.
    删除评论用软删 (deleted_at), 审计行留痕; 资产被彻底删除时评论一并清理.

Revision ID: 0040_add_asset_comments
Revises: 0039_drop_space_is_default
Create Date: 2026-11-15
"""
import sqlalchemy as sa

from alembic import op

revision = "0040_add_asset_comments"
down_revision = "0039_drop_space_is_default"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "asset_comments",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        # ⚠️ asset_id 刻意不加外键 —— 历史资产的 id 变过, code 才是稳定身份;
        #    资产删除时由接口按 code 显式清理.
        sa.Column("asset_id", sa.BigInteger(), nullable=True),
        sa.Column("code", sa.String(64), nullable=False),
        sa.Column("user_id", sa.BigInteger(), nullable=True),
        sa.Column("username", sa.String(64), nullable=False, server_default=""),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("deleted_at", sa.DateTime(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False,
                  server_default=sa.text("CURRENT_TIMESTAMP")),
        sa.Column("updated_at", sa.DateTime(), nullable=False,
                  server_default=sa.text("CURRENT_TIMESTAMP")),
    )
    op.create_index("ix_asset_comments_code", "asset_comments", ["code"])
    op.create_index("ix_asset_comments_asset_id", "asset_comments", ["asset_id"])
    op.create_index("ix_asset_comments_user_id", "asset_comments", ["user_id"])
    op.create_index(
        "ix_asset_comments_code_created", "asset_comments", ["code", "created_at"],
    )


def downgrade() -> None:
    op.drop_table("asset_comments")
