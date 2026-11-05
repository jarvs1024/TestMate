"""Rename agents.category 'ai_market' → 'ext_library' + entry code 'agent-market' → 'ext-library'

背景 (2026-11-05 · 市场改名扩展的收尾):
    0032 把 settings 键、MCP scope、路由都改成 extensions 了, 但能力墙
    入口卡还留着两个旧名字: category 枚举值 'ai_market' (DB 存的是
    enum **name**, 见 0004) 和卡 code 'agent-market'.

    卡片现在叫「扩展库」, 名字也要对齐 (扩展库/软件库/知识库三个都是
    "-library" 结尾的域名), 否则以后看到 ai_market 会以为还有个独立的市场.

    Python 侧 AgentCategory.ext_library = "ext-library" (连字符), DB 侧
    按惯例写 enum name: 'ext_library'.

Revision ID: 0035_rename_ai_market_to_ext_library
Revises: 0034_count_marks
Create Date: 2026-11-05
"""
from alembic import op


revision = "0035_rename_ai_market_to_ext_library"
down_revision = "0034_count_marks"
branch_labels = None
depends_on = None

_ENUM_BEFORE = (
    "ENUM('ssd_trace','ssd_fw','ssd_fio','ssd_burn','ssd_spec',"
    "'ssd_report','ssd_ops','auto_code','ai_market','ssd_kb','sw_library')"
)
_ENUM_AFTER = (
    "ENUM('ssd_trace','ssd_fw','ssd_fio','ssd_burn','ssd_spec',"
    "'ssd_report','ssd_ops','auto_code','ext_library','ssd_kb','sw_library')"
)


def upgrade() -> None:
    # 先迁数据再改列定义, 否则 ALTER 会因非法 enum 值失败 (同 0004/0023)
    op.execute(
        "UPDATE agents SET category = 'ext_library' WHERE category = 'ai_market'"
    )
    op.execute(
        "UPDATE agents SET code = 'ext-library' WHERE code = 'agent-market'"
    )
    op.execute(f"ALTER TABLE agents MODIFY COLUMN category {_ENUM_AFTER} NOT NULL")


def downgrade() -> None:
    op.execute(
        "UPDATE agents SET category = 'ai_market' WHERE category = 'ext_library'"
    )
    op.execute(
        "UPDATE agents SET code = 'agent-market' WHERE code = 'ext-library'"
    )
    op.execute(f"ALTER TABLE agents MODIFY COLUMN category {_ENUM_BEFORE} NOT NULL")
