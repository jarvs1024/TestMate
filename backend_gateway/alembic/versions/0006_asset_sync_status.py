"""add 资产市场的同步状态字段 (方案 A: staged → syncing → pushed/failed)

assets:
  sync_status   该资产当前同步状态 (staged / pushed / failed)
  last_error    最近一次同步失败的错误摘要
asset_jobs:
  staged_at     写本地工作区完成的时间
  pushed_at     push 到 GitLab 成功的时间
  next_retry_at 下次自动重试的时间 (可重试错误才有)

⚠️ 两个坑 (都踩过):
1. MySQL 不允许 TEXT 列带 DEFAULT (errno 1101) —— last_error 不能写 server_default.
2. MySQL 的 DDL 非事务: 迁移中途失败时, 已执行的 ALTER 不会回滚, 但 alembic 版本号会回退.
   下次重跑就会撞 "Duplicate column". 所以本迁移用 inspector 做幂等守卫 —— 已经建过的列跳过,
   缺的补上. 这样即使上次只跑了一半, 这次也能干净地补齐.

Revision ID: 0006
Revises: 0005_marketplace_assets
Create Date: 2026-10-20
"""
from alembic import op
import sqlalchemy as sa


revision = "0006_asset_sync_status"
down_revision = "0005_marketplace_assets"
branch_labels = None
depends_on = None


def _existing_columns(table: str) -> set[str]:
    insp = sa.inspect(op.get_bind())
    return {c["name"] for c in insp.get_columns(table)}


def _add_text_column(table: str, name: str) -> None:
    """安全地加一个 NOT NULL 的 TEXT 列:
       先加 nullable → 回填空串 → 再改成 NOT NULL.
    (直接 ADD COLUMN NOT NULL TEXT 在有数据的表上会失败)"""
    op.add_column(table, sa.Column(name, sa.Text(), nullable=True))
    op.execute(sa.text(f"UPDATE {table} SET {name} = '' WHERE {name} IS NULL"))
    op.alter_column(
        table, name, existing_type=sa.Text(), nullable=False, existing_nullable=True
    )


def upgrade() -> None:
    # ---- assets ----
    cols = _existing_columns("assets")
    if "sync_status" not in cols:
        op.add_column(
            "assets",
            sa.Column(
                "sync_status", sa.String(length=16), nullable=False, server_default="staged"
            ),
        )
    if "last_error" not in cols:
        _add_text_column("assets", "last_error")

    insp = sa.inspect(op.get_bind())
    idx = {i["name"] for i in insp.get_indexes("assets")}
    if "ix_assets_sync_status" not in idx:
        op.create_index("ix_assets_sync_status", "assets", ["sync_status"], unique=False)

    # ---- asset_jobs ----
    jcols = _existing_columns("asset_jobs")
    for c in ("staged_at", "pushed_at", "next_retry_at"):
        if c not in jcols:
            op.add_column("asset_jobs", sa.Column(c, sa.DateTime(), nullable=True))


def downgrade() -> None:
    for c in ("next_retry_at", "pushed_at", "staged_at"):
        op.drop_column("asset_jobs", c)
    op.drop_index("ix_assets_sync_status", table_name="assets")
    op.drop_column("assets", "last_error")
    op.drop_column("assets", "sync_status")
