"""普通用户用户名统一成公司邮箱形式 (2026-10-25 登录重构)

背景:
    登录重构后"普通用户的用户名"就是公司邮箱 (zhangsan@twsc.com.cn) ——
    输入框可以只填前缀, 后端自动补后缀. 库里存的用户名也就跟着统一成
    邮箱形式, 免得出现"库里是短名、登录要邮箱"这种对不上的情况.

谁改:
    · users.username        —— 非 admin 的账号
    · assets.author         —— 资产的作者名 (字符串, 存的是用户名)
    · asset_audits.actor_name —— 审计流水里的操作人名

⚠️ admin (及其他不含 @ 的管理员账号名) 不动 —— 管理员是**账号名**不是邮箱,
   登录时按原样匹配, 不该被补上域名.

⚠️ 就算这次迁移漏了某个环境, 登录也不会挂: identity.lookup_candidates
   会依次试 原样 → 邮箱形式 → 本地部分, 老库里的 'zhangsan' 照样能登录.

Revision ID: 0020_email_usernames
Revises: 0019_remove_dify_engine
Create Date: 2026-10-25
"""
from alembic import op


revision = "0020_email_usernames"
down_revision = "0019_remove_dify_engine"
branch_labels = None
depends_on = None

DOMAIN = "@twsc.com.cn"


def upgrade() -> None:
    # users.username —— 只改不含 @ 且不是 admin 的行
    op.execute(
        f"UPDATE users SET username = CONCAT(username, '{DOMAIN}') "
        "WHERE username NOT LIKE '%@%' AND role <> 'admin'"
    )
    # assets.author —— 跟用户名的改法保持一致 (否则作者认领不上自己的资产)
    op.execute(
        f"UPDATE assets SET author = CONCAT(author, '{DOMAIN}') "
        "WHERE author IS NOT NULL AND author NOT LIKE '%@%' AND author <> 'admin'"
    )
    # asset_audits.actor_name —— 审计流水同理
    op.execute(
        f"UPDATE asset_audits SET actor_name = CONCAT(actor_name, '{DOMAIN}') "
        "WHERE actor_name IS NOT NULL AND actor_name NOT LIKE '%@%' AND actor_name <> 'admin'"
    )


def downgrade() -> None:
    op.execute(
        f"UPDATE users SET username = SUBSTRING_INDEX(username, '@', 1) "
        "WHERE username LIKE '%@%'"
    )
    op.execute(
        f"UPDATE assets SET author = SUBSTRING_INDEX(author, '@', 1) "
        "WHERE author LIKE '%@%'"
    )
    op.execute(
        f"UPDATE asset_audits SET actor_name = SUBSTRING_INDEX(actor_name, '@', 1) "
        "WHERE actor_name LIKE '%@%'"
    )
