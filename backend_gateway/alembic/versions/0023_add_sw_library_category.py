"""add agents.category enum value 'sw_library' (软件库卡片的域标签)

2026-10-27: 新增「软件库」能力 —— 存公司内部的软件 (功能 / 详情 / 适用 / 发布更新说明).
它跟 ai_market (插件·技能·连接) 是两回事: 那是装进 Agent 的扩展, 这是给人用的软件,
所以要独立分类, 否则卡片副标题会跟插件市场混在一起.

⚠️ 同 0017: SQLAlchemy 用 Enum(AgentCategory) 时 MySQL 列存的是 enum **name**
    (下划线), 不是 value (连字符). Python 侧 sw_library = "sw-library",
    DB 侧必须写 'sw_library'.

Revision ID: 0023_add_sw_library_category
Revises: 0022_user_token_version
Create Date: 2026-10-27
"""
from alembic import op


revision = "0023_add_sw_library_category"
down_revision = "0022_user_token_version"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        "ALTER TABLE agents MODIFY COLUMN category "
        "ENUM('ssd_trace','ssd_fw','ssd_fio','ssd_burn','ssd_spec',"
        "'ssd_report','ssd_ops','auto_code','ai_market','ssd_kb',"
        "'sw_library') NOT NULL"
    )


def downgrade() -> None:
    # 回退前需先把该分类下的行迁走, 否则 ALTER 会因非法 enum 值失败
    op.execute(
        "UPDATE agents SET category = 'ai_market' WHERE category = 'sw_library'"
    )
    op.execute(
        "ALTER TABLE agents MODIFY COLUMN category "
        "ENUM('ssd_trace','ssd_fw','ssd_fio','ssd_burn','ssd_spec',"
        "'ssd_report','ssd_ops','auto_code','ai_market','ssd_kb') NOT NULL"
    )
