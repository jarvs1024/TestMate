"""add publish_status / asset_audits / asset_installs 安装字段

二期: 完整协作流程
  assets.publish_status   生命周期 (published / unpublished) —— 与 sync_status 解耦
  asset_audits           操作审计 (谁在什么时候上架/下架/更新/安装/冲突解决)
  asset_installs         安装路径 / 包 sha256 / 安装通道

沿用 0006 的做法: 用 inspector 做幂等守卫 —— MySQL DDL 非事务, 迁移中途失败
不会回滚已执行的 ALTER, 但 alembic 版本号会回退. 守卫保证半途失败后重跑能补齐.

Revision ID: 0007
Revises: 0006_asset_sync_status
Create Date: 2026-10-21
"""
from alembic import op
import sqlalchemy as sa


revision = "0007_asset_publish_status"
down_revision = "0006_asset_sync_status"
branch_labels = None
depends_on = None


def _existing_columns(table: str) -> set[str]:
    insp = sa.inspect(op.get_bind())
    return {c["name"] for c in insp.get_columns(table)}


def upgrade() -> None:
    # ---- assets.publish_status ----
    cols = _existing_columns("assets")
    if "publish_status" not in cols:
        op.add_column(
            "assets",
            sa.Column(
                "publish_status", sa.String(length=16), nullable=False,
                server_default="published",
            ),
        )
    insp = sa.inspect(op.get_bind())
    idx = {i["name"] for i in insp.get_indexes("assets")}
    if "ix_assets_publish_status" not in idx:
        op.create_index("ix_assets_publish_status", "assets", ["publish_status"], unique=False)

    # ---- asset_installs 新增字段 ----
    icols = _existing_columns("asset_installs")
    for name, coltype in (
        ("install_path", sa.String(length=512)),
        ("sha256", sa.String(length=64)),
        ("channel", sa.String(length=16)),
    ):
        if name not in icols:
            op.add_column(
                "asset_installs", sa.Column(name, coltype, nullable=False, server_default="")
            )

    # ---- asset_audits ----
    if "asset_audits" not in sa.inspect(op.get_bind()).get_table_names():
        op.create_table(
            "asset_audits",
            sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
            sa.Column("asset_id", sa.BigInteger(), nullable=True),
            sa.Column("code", sa.String(length=64), nullable=False, server_default=""),
            sa.Column("action", sa.String(length=32), nullable=False),
            sa.Column("actor_id", sa.BigInteger(), nullable=True),
            sa.Column("actor_name", sa.String(length=64), nullable=False, server_default=""),
            # ⚠️ TEXT 列不能带 DEFAULT (MySQL errno 1101) —— 默认值走 ORM 侧 default=
            sa.Column("comment", sa.Text(), nullable=False),
            sa.Column("detail", sa.JSON(), nullable=False),
            sa.Column("created_at", sa.DateTime(), nullable=False),
            sa.PrimaryKeyConstraint("id"),
        )
        op.create_index("ix_asset_audits_asset_id", "asset_audits", ["asset_id"], unique=False)
        op.create_index("ix_asset_audits_code", "asset_audits", ["code"], unique=False)
        op.create_index("ix_asset_audits_action", "asset_audits", ["action"], unique=False)


def downgrade() -> None:
    op.drop_index("ix_asset_audits_action", table_name="asset_audits")
    op.drop_index("ix_asset_audits_code", table_name="asset_audits")
    op.drop_index("ix_asset_audits_asset_id", table_name="asset_audits")
    op.drop_table("asset_audits")

    for name in ("channel", "sha256", "install_path"):
        op.drop_column("asset_installs", name)

    op.drop_index("ix_assets_publish_status", table_name="assets")
    op.drop_column("assets", "publish_status")
