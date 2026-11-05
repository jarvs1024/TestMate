"""Rename agents.category 'ai_market' → 'ext_library' + entry code 'agent-market' → 'ext-library'

背景 (2026-11-05 · 市场改名扩展的收尾):
    0032 把 settings 键、MCP scope、路由都改成 extensions 了, 但能力墙
    入口卡还留着两个旧名字: category 枚举值 'ai_market' (DB 存的是
    enum **name**, 见 0004) 和卡 code 'agent-market'.

    卡片现在叫「扩展库」, 名字也要对齐 (扩展库/软件库/知识库三个都是
    "-library" 结尾的域名), 否则以后看到 ai_market 会以为还有个独立的市场.

    Python 侧 AgentCategory.ext_library = "ext-library" (连字符), DB 侧
    按惯例写 enum name: 'ext_library'.

⚠️ 为什么是**三步**(而不是先 UPDATE 再 ALTER):
    MySQL 的 enum 列, **写入的值必须在 enum 定义里存在** —— 否则报
    `DataError (1265): Data truncated for column 'category'`。

    所以"把 ai_market 换成 ext_library"**不能**一步做完:
      · 先 UPDATE 成 ext_library → 此时 enum 里还没这个值 → 直接炸
      · 先 ALTER 去掉 ai_market → 此时表里还有 ai_market 的行 → 也炸

    正确顺序是**让新值和旧值在 enum 定义里共存**, 再迁数据, 最后删旧值:

      ① ALTER: enum 里**同时**含 ai_market 和 ext_library
      ② UPDATE: ai_market 的行 → ext_library (此刻 ext_library 合法)
      ③ ALTER: enum 里去掉 ai_market (此刻已没有 ai_market 的行)

    任何一步失败, 数据都还是合法的 enum 值 —— 不会出现"半迁移"的脏状态。

    同 0004 (加值: 先 ALTER 再迁数据) / 0023 (删值: 先迁数据再 ALTER) 的规律。

⚠️ revision id 为什么要短:
    alembic 的 `alembic_version.version_num` 列是 **varchar(32)** —— 存不下
    超过 32 字符的 revision id (会报 `DataError (1406): Data too long`)。
    原 id `0035_rename_ai_market_to_ext_library` 是 **36 字符** → 后端启动时
    alembic 写版本号直接失败 → 服务起不来。
    所以这里用短 id: `0035_rename_market_to_ext_lib` (30 字符)。

Revision ID: 0035_rename_market_to_ext_lib
Revises: 0034_count_marks
Create Date: 2026-11-05
"""
from alembic import op


revision = "0035_rename_market_to_ext_lib"
down_revision = "0034_count_marks"
branch_labels = None
depends_on = None

_ENUM_BEFORE = (
    "ENUM('ssd_trace','ssd_fw','ssd_fio','ssd_burn','ssd_spec',"
    "'ssd_report','ssd_ops','auto_code','ai_market','ssd_kb','sw_library')"
)
# 过渡态: 新旧值共存 —— UPDATE 到 ext_library 时它必须是合法 enum 值
_ENUM_BOTH = (
    "ENUM('ssd_trace','ssd_fw','ssd_fio','ssd_burn','ssd_spec',"
    "'ssd_report','ssd_ops','auto_code','ai_market','ext_library',"
    "'ssd_kb','sw_library')"
)
_ENUM_AFTER = (
    "ENUM('ssd_trace','ssd_fw','ssd_fio','ssd_burn','ssd_spec',"
    "'ssd_report','ssd_ops','auto_code','ext_library','ssd_kb','sw_library')"
)


def upgrade() -> None:
    # ① 先让 enum 定义同时含新旧两个值
    op.execute(f"ALTER TABLE agents MODIFY COLUMN category {_ENUM_BOTH} NOT NULL")
    # ② 再迁数据 (ext_library 此时已合法)
    op.execute(
        "UPDATE agents SET category = 'ext_library' WHERE category = 'ai_market'"
    )
    op.execute(
        "UPDATE agents SET code = 'ext-library' WHERE code = 'agent-market'"
    )
    # ③ 最后把旧值从 enum 定义里摘掉 (此时已无 ai_market 的行)
    op.execute(f"ALTER TABLE agents MODIFY COLUMN category {_ENUM_AFTER} NOT NULL")


def downgrade() -> None:
    # 反向: 先让 ai_market 回到定义里, 再迁数据, 最后摘掉 ext_library
    op.execute(f"ALTER TABLE agents MODIFY COLUMN category {_ENUM_BOTH} NOT NULL")
    op.execute(
        "UPDATE agents SET category = 'ai_market' WHERE category = 'ext_library'"
    )
    op.execute(
        "UPDATE agents SET code = 'agent-market' WHERE code = 'ext-library'"
    )
    op.execute(f"ALTER TABLE agents MODIFY COLUMN category {_ENUM_BEFORE} NOT NULL")
