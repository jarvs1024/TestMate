"""移除 dify 引擎 (平台不再接入 Dify)

2026-10-25: Dify 这个外部依赖被整个拿掉.

为什么:
    Dify 一直是个**假集成** ——
      · deploy/.env 里从来没配过 DIFY_BASE_URL / DIFY_API_KEY, 跑的一直是 DIFY_MOCK
      · 前端从来没调用过 /api/v1/diagnose/stream (只有那个 P0 时期的接口用)
      · 能力卡上的引擎标识写着 "Dify", 但真正能用的 5 张卡全是 builtin
    留着它 = 侧栏显示 "Dify 正常" (其实是 mock 的假象), 设置页还要配一套用不上的
    数据源. 用户已经拍板: "把 dify 数据源去掉, 包括设置中的数据源配置, 以及相关文案".

⚠️ 迁移顺序 (MySQL ENUM 不接受列表外的值, 严格模式下直接报 1265):
    1) 先把指向 dify 的行改掉 —— 这些是**规划中**的能力 (draft), 本来就没跑起来
    2) 再把 ENUM 里的 'dify' 拿掉

⚠️ 同 0003/0004: SQLAlchemy 用 Enum(AgentEngine) 时 MySQL 列存的是 enum name,
   这里 name 与 value 一致 (都无连字符), 所以直接写字面量即可.

Revision ID: 0019_remove_dify_engine
Revises: 0018_capability_roles
Create Date: 2026-10-25
"""
from alembic import op


revision = "0019_remove_dify_engine"
down_revision = "0018_capability_roles"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # 1) 存量行: dify → builtin (这两张卡都是 draft, 还没上线, 改引擎不影响行为)
    op.execute("UPDATE agents SET engine = 'builtin' WHERE engine = 'dify'")
    # 2) ENUM 去掉 dify
    op.execute(
        "ALTER TABLE agents MODIFY COLUMN engine ENUM('n8n','builtin') NOT NULL"
    )


def downgrade() -> None:
    # 1) ENUM 先容下 dify (顺序反了会在有行是 dify 时报 1265)
    op.execute(
        "ALTER TABLE agents MODIFY COLUMN engine ENUM('dify','n8n','builtin') NOT NULL"
    )
    # 2) 存量行回不到 dify —— builtin 和 dify 都可能, 不做数据回填, 保持现状
