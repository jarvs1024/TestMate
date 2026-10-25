"""add agents.category enum value 'ssd_kb' (知识库卡片的域标签)

知识库从侧栏顶级项降级成能力墙上的一张卡 (kind=library), 需要一个自己的
域标签, 不能挂在 auto-code / ai-market 下面 —— 那两个说的是代码与资产.

⚠️ 同 0003/0004: SQLAlchemy 用 Enum(AgentCategory) 时 MySQL 列存的是
enum name (下划线), 不是 value (连字符). Python 侧 ssd_kb = "ssd-kb",
DB 侧必须写 'ssd_kb'.

Revision ID: 0017
Revises: 0016_add_capability_kind
Create Date: 2026-10-25
"""
from alembic import op


revision = "0017_add_ssd_kb_category"
down_revision = "0016_add_capability_kind"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        "ALTER TABLE agents MODIFY COLUMN category "
        "ENUM('ssd_trace','ssd_fw','ssd_fio','ssd_burn','ssd_spec',"
        "'ssd_report','ssd_ops','auto_code','ai_market','ssd_kb') NOT NULL"
    )


def downgrade() -> None:
    # 回退前需先把该分类下的行迁走, 否则 ALTER 会因非法 enum 值失败
    op.execute(
        "UPDATE agents SET category = 'ssd_spec' WHERE category = 'ssd_kb'"
    )
    op.execute(
        "ALTER TABLE agents MODIFY COLUMN category "
        "ENUM('ssd_trace','ssd_fw','ssd_fio','ssd_burn','ssd_spec',"
        "'ssd_report','ssd_ops','auto_code','ai_market') NOT NULL"
    )
