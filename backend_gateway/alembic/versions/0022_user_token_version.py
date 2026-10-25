"""登录态版本号: 改密码/改角色/停用账号 → 旧 token 立即作废 (2026-10-26)

背景:
    JWT 一签发就是 7 天有效. 管理员重置了某人的密码 (或把角色降了 / 停用了账号),
    但那个人手上的旧 token **照样能用到过期** —— "改了密码等于没改".

    以前只有"查库看 is_active"这一道, 只能挡住停用, 挡不住改密码.

做法:
    users 表加一列 token_version (默认 0):
      · 登录签发的 token 里带上 tv = 当时的 token_version
      · 每次请求校验 tv == 库里的 token_version, 不等就 401
      · 改密码 / 改角色 / 停用账号 → token_version += 1 → 旧 token 全废

存量兼容:
    老 token 里没有 tv 字段 → 当成 0; 存量用户 token_version 也是 0 → 升级不用重新登录.

Revision ID: 0022_user_token_version
Revises: 0021_user_account_control
Create Date: 2026-10-26
"""
from alembic import op


revision = "0022_user_token_version"
down_revision = "0021_user_account_control"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("ALTER TABLE users ADD COLUMN token_version INTEGER NOT NULL DEFAULT 0")


def downgrade() -> None:
    op.execute("ALTER TABLE users DROP COLUMN token_version")
