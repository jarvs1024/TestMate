"""add pending_action (资产在等什么审核)

背景 (2026-10-30 · 第十二轮):
    资产有三种"要审"的情况, 但 ``publish_status`` 只有一个 ``pending``,
    审核台**分不出来**:
      · 新资产上架        (action = create)
      · 发了新版本        (action = update)
      · **只改了信息**    (action = update_meta)   ← 这次加的

    为什么要分开:
      ① **通知** —— 只改信息的资产, 审核通过后**不该**在市场群发"新资产上架"
         (包没变, 用户装到的东西跟上次一模一样, 群里那条是假消息);
      ② **站内待办** —— 管理员要分得清"这个人在上架新东西"还是"只是在改简介",
         两条待办该给不同的优先级;
      ③ **审核台** —— 审核员得看见这次改的**是信息还是包**.

存量数据**不回填** —— 已有资产没有"在等审"的历史, 字段留空即可.

Revision ID: 0029_add_asset_pending_action
Revises: 0028_kb_ownerships
Create Date: 2026-10-30
"""
from alembic import op
import sqlalchemy as sa


revision = "0029_add_asset_pending_action"
down_revision = "0028_kb_ownerships"
branch_labels = None
depends_on = None


def upgrade() -> None:
    insp = sa.inspect(op.get_bind())
    cols = {c["name"] for c in insp.get_columns("assets")}
    if "pending_action" not in cols:
        op.add_column(
            "assets",
            sa.Column(
                "pending_action",
                sa.String(16),
                nullable=False,
                server_default="",
                index=True,
                comment="在等什么审核: new=新资产 / update=新版本 / meta=只改了信息",
            ),
        )


def downgrade() -> None:
    op.drop_column("assets", "pending_action")
