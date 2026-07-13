"""add agents.category enum value 'auto_code' + DB MODIFY COLUMN

SQLAlchemy 用 Enum(AgentCategory) 时 MySQL 列存的是 enum name (下划线),
不是 value (连字符). Python 加新 enum 成员 auto_code = 'auto-code' 后,
需要同步 DB enum 列允许新值.

修订时间: 2026-07-13
"""
from alembic import op


revision = "0003_add_auto_code_category"
down_revision = "0002_add_agents_route"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # MySQL ALTER ENUM: 在末尾加 'auto_code'
    op.execute(
        "ALTER TABLE agents MODIFY COLUMN category "
        "ENUM('ssd_trace','ssd_fw','ssd_fio','ssd_burn','ssd_spec',"
        "'ssd_report','ssd_ops','auto_code') NOT NULL"
    )


def downgrade() -> None:
    op.execute(
        "ALTER TABLE agents MODIFY COLUMN category "
        "ENUM('ssd_trace','ssd_fw','ssd_fio','ssd_burn','ssd_spec',"
        "'ssd_report','ssd_ops') NOT NULL"
    )
