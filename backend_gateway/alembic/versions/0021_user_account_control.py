"""账号可控: 停用开关 + 是否必须密码 (2026-10-25 账号管理)

背景:
    登录改成"**必须管理员先建号**"之后, 管理员需要能管账号:
      · 离职/转岗的人 → **停用** (别删号 —— 资产归属还在他名下)
      · 有人要密码   → 建号时给密码, 登录必须输
      · 有人要免密   → 建号时不给密码, 填用户名就进

所以 users 表加两列:
    · is_active          —— 停用后不能登录
    · password_required  —— 这个账号登录是否必须输密码

存量数据怎么定:
    · role='admin' → password_required=1  (管理员本来就必须密码)
    · 其余         → password_required=0  (普通用户免密)
    · is_active 全部 = 1 (存量账号都还能用)

Revision ID: 0021_user_account_control
Revises: 0020_email_usernames
Create Date: 2026-10-25
"""
from alembic import op


revision = "0021_user_account_control"
down_revision = "0020_email_usernames"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("ALTER TABLE users ADD COLUMN is_active BOOLEAN NOT NULL DEFAULT 1")
    op.execute("ALTER TABLE users ADD COLUMN password_required BOOLEAN NOT NULL DEFAULT 0")
    # 管理员账号本来就是"必须密码"的, 补上 (否则 admin 会被当成免密账号)
    op.execute("UPDATE users SET password_required = 1 WHERE role = 'admin'")


def downgrade() -> None:
    op.execute("ALTER TABLE users DROP COLUMN password_required")
    op.execute("ALTER TABLE users DROP COLUMN is_active")
