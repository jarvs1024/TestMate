"""widen publish_status (16 → 24) —— 装得下第五态 unpublish_pending

下架改成**申请 + 审核**之后, 生命周期多了第五态:

    published → unpublish_pending → (管理员通过) 彻底删除
                               ↘ (管理员驳回 / 作者撤销) published

"unpublish_pending" 是 17 个字符, 老的 String(16) 装不下 —— MySQL 严格模式下
会直接报错 (Data too long), 非严格模式则**悄悄截断**成 "unpublish_pendin",
然后所有按状态判断的代码全都不匹配 (资产卡在"申请下架"里谁也看不到)。

顺带把长度放到 24, 以后再加状态不用再改列。

Revision ID: 0012
Revises: 0011_asset_download_count
Create Date: 2026-10-24
"""
from alembic import op
import sqlalchemy as sa


revision = "0012_widen_publish_status"
down_revision = "0011_asset_download_count"
branch_labels = None
depends_on = None


def upgrade() -> None:
    insp = sa.inspect(op.get_bind())
    cols = {c["name"]: c for c in insp.get_columns("assets")}
    if "publish_status" in cols:
        # 已经是 24+ 就别动 (幂等)
        try:
            cur_len = cols["publish_status"]["type"].length
        except AttributeError:  # pragma: no cover - 非 MySQL 方言
            cur_len = None
        if cur_len is None or int(cur_len) < 24:
            op.alter_column(
                "assets",
                "publish_status",
                type_=sa.String(24),
                existing_type=sa.String(16),
                existing_nullable=False,
            )


def downgrade() -> None:
    # ⚠️ 降级会把 "unpublish_pending" 截断成 16 字符 —— 降级前请先把这些资产
    #    处理掉 (审核通过/撤销), 否则状态会认不出来.
    op.alter_column(
        "assets",
        "publish_status",
        type_=sa.String(16),
        existing_type=sa.String(24),
        existing_nullable=False,
    )
