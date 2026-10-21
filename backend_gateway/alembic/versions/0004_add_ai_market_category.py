"""add agents.category enum value 'ai_market' + DB MODIFY COLUMN

AI 资产市场入口卡片 (agent-market) 需要独立分类, 否则卡片副标题会显示
"v0.1.0 · 自动化代码", 与 auto_code 下的代码检视语义混淆.

同 0003: SQLAlchemy 用 Enum(AgentCategory) 时 MySQL 列存的是 enum name
(下划线), 不是 value (连字符). Python 侧 ai_market = "ai-market",
DB 侧必须写 'ai_market'.

Revision ID: 0004
Revises: 0003_add_auto_code_category
Create Date: 2026-10-15
"""
from alembic import op


revision = "0004_add_ai_market_category"
down_revision = "0003_add_auto_code_category"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        "ALTER TABLE agents MODIFY COLUMN category "
        "ENUM('ssd_trace','ssd_fw','ssd_fio','ssd_burn','ssd_spec',"
        "'ssd_report','ssd_ops','auto_code','ai_market') NOT NULL"
    )


def downgrade() -> None:
    # 回退前需先把该分类下的行迁走, 否则 ALTER 会因非法 enum 值失败
    op.execute(
        "UPDATE agents SET category = 'auto_code' WHERE category = 'ai_market'"
    )
    op.execute(
        "ALTER TABLE agents MODIFY COLUMN category "
        "ENUM('ssd_trace','ssd_fw','ssd_fio','ssd_burn','ssd_spec',"
        "'ssd_report','ssd_ops','auto_code') NOT NULL"
    )
