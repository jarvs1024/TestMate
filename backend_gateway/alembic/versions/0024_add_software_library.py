"""add software_items / software_versions —— 软件库 (2026-10-27)

背景:
    能力墙上的「软件库」卡要真能用: 传任意格式的软件包 (≤5G) → 服务端磁盘 →
    卡片浏览 → 下载 / 发新版本.

    它跟「插件·技能·连接」(assets 那几张表) 是**两个东西**:
      · 插件·技能·连接 → 装进 Agent 的文本包, 真身在 GitLab, assets 只是镜像
      · 软件库        → 给人用的内部软件 (任意格式二进制), 真身在**服务端磁盘**

    所以独立建两张表:
      · software_items     —— 条目 (卡片门面): 名称/功能/详情/适用场景/分类/作者…
      · software_versions  —— 版本 (文件本体): 相对路径/大小/sha256/更新说明…

⚠️ status 一律 String 而非 MySQL ENUM (理由同 0005).
⚠️ file_path 存**相对**路径 —— 绝对路径换机器/改设置项就失效了.

Revision ID: 0024_add_software_library
Revises: 0023_add_sw_library_category
Create Date: 2026-10-27
"""
from alembic import op
import sqlalchemy as sa


revision = "0024_add_software_library"
down_revision = "0023_add_sw_library_category"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "software_items",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("code", sa.String(length=64), nullable=False),
        sa.Column("name", sa.String(length=128), nullable=False),
        sa.Column("icon", sa.String(length=16), nullable=False, server_default="🧰"),
        sa.Column("version", sa.String(length=32), nullable=False, server_default=""),
        sa.Column("summary", sa.String(length=500), nullable=False, server_default=""),
        # ⚠️ TEXT/JSON 列在 MySQL 不允许 DEFAULT (errno 1101), 默认值走 ORM 侧 default=
        sa.Column("description", sa.Text(), nullable=False),
        sa.Column("features", sa.JSON(), nullable=False),
        sa.Column("use_when", sa.Text(), nullable=False),
        sa.Column("not_for", sa.Text(), nullable=False),
        sa.Column("platform", sa.String(length=32), nullable=False, server_default=""),
        sa.Column("category", sa.String(length=64), nullable=False, server_default=""),
        sa.Column("tags", sa.JSON(), nullable=False),
        sa.Column("keywords", sa.JSON(), nullable=False),
        sa.Column("author", sa.String(length=64), nullable=False, server_default=""),
        sa.Column("download_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column(
            "publish_status",
            sa.String(length=16),
            nullable=False,
            server_default="awaiting_file",
        ),
        sa.Column("deleted_at", sa.DateTime(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("code", name="uq_software_items_code"),
    )
    op.create_index("ix_software_items_code", "software_items", ["code"], unique=False)
    op.create_index(
        "ix_software_items_platform", "software_items", ["platform"], unique=False
    )
    op.create_index(
        "ix_software_items_category", "software_items", ["category"], unique=False
    )
    op.create_index(
        "ix_software_items_publish_status",
        "software_items",
        ["publish_status"],
        unique=False,
    )

    op.create_table(
        "software_versions",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("item_id", sa.BigInteger(), nullable=False),
        sa.Column("version", sa.String(length=32), nullable=False),
        sa.Column("release_notes", sa.Text(), nullable=False),
        sa.Column("file_name", sa.String(length=255), nullable=False, server_default=""),
        sa.Column("file_path", sa.String(length=512), nullable=False, server_default=""),
        sa.Column("file_size", sa.BigInteger(), nullable=False, server_default="0"),
        sa.Column("sha256", sa.String(length=64), nullable=False, server_default=""),
        sa.Column(
            "status",
            sa.String(length=16),
            nullable=False,
            server_default="awaiting_file",
        ),
        sa.Column("declared_size", sa.BigInteger(), nullable=False, server_default="0"),
        sa.Column("last_error", sa.Text(), nullable=False),
        sa.Column("author", sa.String(length=64), nullable=False, server_default=""),
        sa.Column("download_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_software_versions_item_id", "software_versions", ["item_id"], unique=False
    )
    op.create_index(
        "ix_software_versions_version", "software_versions", ["version"], unique=False
    )
    op.create_index(
        "ix_software_versions_status", "software_versions", ["status"], unique=False
    )


def downgrade() -> None:
    op.drop_index("ix_software_versions_status", table_name="software_versions")
    op.drop_index("ix_software_versions_version", table_name="software_versions")
    op.drop_index("ix_software_versions_item_id", table_name="software_versions")
    op.drop_table("software_versions")

    op.drop_index("ix_software_items_publish_status", table_name="software_items")
    op.drop_index("ix_software_items_category", table_name="software_items")
    op.drop_index("ix_software_items_platform", table_name="software_items")
    op.drop_index("ix_software_items_code", table_name="software_items")
    op.drop_table("software_items")
