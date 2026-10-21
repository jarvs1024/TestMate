"""add assets / asset_jobs / asset_installs — AI 资产市场

GitLab 是资产的唯一真实来源; 这三张表是**查询镜像 + 本地态**:
  - assets          index.json 的投影, 供列表/搜索/详情
  - asset_jobs      上传/更新的异步任务, 支持后台执行与断点重试
  - asset_installs  本机安装记录 (本地态, 不进 GitLab)

status 字段一律 String 而非 MySQL ENUM —— ENUM 的 ALTER 必须写裸 SQL (见 0003/0004),
既不可组合也会被 `alembic check` 判成漂移.

Revision ID: 0005
Revises: 0004_add_ai_market_category
Create Date: 2026-10-16
"""
from alembic import op
import sqlalchemy as sa


revision = "0005_marketplace_assets"
down_revision = "0004_add_ai_market_category"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "assets",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("code", sa.String(length=64), nullable=False),
        sa.Column("name", sa.String(length=128), nullable=False),
        sa.Column("icon", sa.String(length=16), nullable=False, server_default="🧩"),
        sa.Column("kind", sa.String(length=16), nullable=False),
        sa.Column("version", sa.String(length=32), nullable=False, server_default="0.1.0"),
        sa.Column("summary", sa.String(length=500), nullable=False, server_default=""),
        # ⚠️ TEXT/JSON 列在 MySQL 不允许 DEFAULT (errno 1101), 默认值走 ORM 侧 default=
        sa.Column("description", sa.Text(), nullable=False),
        sa.Column("use_when", sa.Text(), nullable=False),
        sa.Column("not_for", sa.Text(), nullable=False),
        sa.Column("category", sa.String(length=64), nullable=False, server_default=""),
        sa.Column("tags", sa.JSON(), nullable=False),
        sa.Column("keywords", sa.JSON(), nullable=False),
        sa.Column("permissions", sa.JSON(), nullable=False),
        sa.Column("install_steps", sa.JSON(), nullable=False),
        sa.Column("bindings", sa.JSON(), nullable=False),
        sa.Column("author", sa.String(length=64), nullable=False, server_default=""),
        sa.Column("featured", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("homepage", sa.String(length=512), nullable=True),
        sa.Column("git_path", sa.String(length=512), nullable=False, server_default=""),
        sa.Column("git_commit_sha", sa.String(length=64), nullable=False, server_default=""),
        sa.Column("git_web_url", sa.String(length=512), nullable=False, server_default=""),
        sa.Column("install_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("code", name="uq_assets_code"),
    )
    op.create_index("ix_assets_code", "assets", ["code"], unique=False)
    op.create_index("ix_assets_kind", "assets", ["kind"], unique=False)
    op.create_index("ix_assets_category", "assets", ["category"], unique=False)

    op.create_table(
        "asset_jobs",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("action", sa.String(length=16), nullable=False),
        sa.Column("status", sa.String(length=16), nullable=False, server_default="pending"),
        sa.Column("code", sa.String(length=64), nullable=False),
        sa.Column("asset_name", sa.String(length=128), nullable=False, server_default=""),
        sa.Column("kind", sa.String(length=16), nullable=False, server_default="skill"),
        sa.Column("payload", sa.JSON(), nullable=False),
        sa.Column("git_path", sa.String(length=512), nullable=False, server_default=""),
        sa.Column("commit_sha", sa.String(length=64), nullable=False, server_default=""),
        sa.Column("error", sa.Text(), nullable=False),
        sa.Column("attempts", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("created_by", sa.BigInteger(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_asset_jobs_status", "asset_jobs", ["status"], unique=False)
    op.create_index("ix_asset_jobs_code", "asset_jobs", ["code"], unique=False)

    op.create_table(
        "asset_installs",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("code", sa.String(length=64), nullable=False),
        sa.Column("version", sa.String(length=32), nullable=False, server_default=""),
        sa.Column("user_id", sa.BigInteger(), nullable=False, server_default="0"),
        sa.Column("client_id", sa.String(length=64), nullable=False, server_default="local"),
        sa.Column("client_kind", sa.String(length=32), nullable=False, server_default="web"),
        sa.Column("status", sa.String(length=16), nullable=False, server_default="installed"),
        sa.Column("installed_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_asset_installs_code", "asset_installs", ["code"], unique=False)
    op.create_index(
        "ix_asset_installs_client_id", "asset_installs", ["client_id"], unique=False
    )


def downgrade() -> None:
    op.drop_index("ix_asset_installs_client_id", table_name="asset_installs")
    op.drop_index("ix_asset_installs_code", table_name="asset_installs")
    op.drop_table("asset_installs")

    op.drop_index("ix_asset_jobs_code", table_name="asset_jobs")
    op.drop_index("ix_asset_jobs_status", table_name="asset_jobs")
    op.drop_table("asset_jobs")

    op.drop_index("ix_assets_category", table_name="assets")
    op.drop_index("ix_assets_kind", table_name="assets")
    op.drop_index("ix_assets_code", table_name="assets")
    op.drop_table("assets")
