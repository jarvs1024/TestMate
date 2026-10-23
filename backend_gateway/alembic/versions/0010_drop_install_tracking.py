"""下线「安装」语义: 删 asset_installs 表与 assets.install_count 列

安装方式简化成**只有下载** —— 用户拿一份 zip 自己解压.
后端既不写盘, 也就**不知道**用户到底装没装:
  - 记录下载行为然后标「已安装」是虚假语义 (下载 ≠ 解压安装)
  - 「可更新」同理
  - install_count 更是虚的 (下载次数 ≠ 安装次数)

所以整套"本地安装态"直接下线:
  - asset_installs 表          —— 本机安装记录, 没人再产生
  - assets.install_count 列   —— 下载次数, 不再统计
  - 审计里的 install/uninstall 动作 —— 不会再发生

列表可见性随之简化: 在架 ∪ 我提交的 (以前还有"我已安装的",
那是为了让已装用户能去更新/卸载 —— 现在这两件事都没了, 这条规则也没意义).

沿用 0006/0007/0008/0009 的做法: 用 inspector 做幂等守卫 —— MySQL DDL 非事务,
迁移中途失败不会回滚已执行的 ALTER, 但 alembic 版本号会回退.
守卫保证半途失败后重跑能补齐.

Revision ID: 0010
Revises: 0009_asset_review_note
Create Date: 2026-10-24
"""
from alembic import op
import sqlalchemy as sa


revision = "0010_drop_install_tracking"
down_revision = "0009_asset_review_note"
branch_labels = None
depends_on = None


def upgrade() -> None:
    insp = sa.inspect(op.get_bind())
    tables = set(insp.get_table_names())

    # 1) 清掉历史审计里的 install / uninstall 动作
    #    (代码不再产生这两种动作, 留着只是历史噪音)
    if "asset_audits" in tables:
        op.execute(
            "DELETE FROM asset_audits WHERE action IN ('install', 'uninstall')"
        )

    # 2) 删 assets.install_count 列
    cols = {c["name"] for c in insp.get_columns("assets")}
    if "install_count" in cols:
        op.drop_column("assets", "install_count")

    # 3) 删 asset_installs 表 (最后做 —— 前面两步不依赖它)
    if "asset_installs" in tables:
        op.drop_table("asset_installs")


def downgrade() -> None:
    # 恢复需要原来那张表的数据 —— 已经没了, 只能建空表
    op.create_table(
        "asset_installs",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column("code", sa.String(64), nullable=False, index=True),
        sa.Column("version", sa.String(32), nullable=False, default=""),
        sa.Column("user_id", sa.BigInteger(), nullable=False, default=0),
        sa.Column("client_id", sa.String(64), nullable=False, default="local", index=True),
        sa.Column("client_kind", sa.String(32), nullable=False, default="web"),
        sa.Column("status", sa.String(16), nullable=False, default="installed"),
        sa.Column("install_path", sa.String(512), nullable=False, default=""),
        sa.Column("sha256", sa.String(64), nullable=False, default=""),
        sa.Column("channel", sa.String(16), nullable=False, default="server"),
        sa.Column("installed_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
    )
    op.add_column(
        "assets", sa.Column("install_count", sa.Integer(), nullable=False, default=0)
    )
