"""software_items.icon 改成二进制 collation (2026-10-28)

背景:
    软件库的图标**不许跟别的软件重复** (两张卡长得一样, 用户分不清谁是谁).
    加查重时撞上一个很隐蔽的 MySQL 行为:

    ``software_items.icon`` 原本是 ``varchar(16) COLLATE utf8mb4_unicode_ci``,
    而 MySQL 的 UCA 4.0.0 **不认识 supplementary plane 的字符** ——
    它给**所有 emoji** 套了同一个"通用权重". 结果:

        SELECT '🚀' = '💿';   →  1   (!!)

    也就是说在那一列上, **任何 emoji 都跟任何 emoji 相等**.
    于是 `WHERE icon = '🚀'` 会命中一条存着 💿 的行 ——
    第一个条目 🧰, 第二个条目 📦 就会被判成"图标重复", 直接 409.

    ⚠️ 这个坑不修, 软件库根本没法用 (第二个软件就传不上去).

修法:
    列的 collation 改成 ``utf8mb4_bin`` (按字节比, 一个字节都不差才算相等).
    这样 `WHERE icon = '🚀'` 只命中字面上就是 🚀 的行.

    为什么改列而不是只在代码里加 COLLATE:
      · 改列是**一劳永逸**的 —— 以后谁写 `WHERE icon = ...` 都不会再踩;
      · 后端的查重也已经改成显式 ``collate('utf8mb4_bin')`` (双保险,
        不依赖这一列的 collation 到底是什么).

⚠️ 只动 icon 一列 —— 别的列 (code / name / summary) 是中文和 ASCII,
   utf8mb4_unicode_ci 对它们的行为是对的, 改了反而会让唯一索引变严格.

Revision ID: 0025_sw_icon_bin_collation
Revises: 0024_add_software_library
Create Date: 2026-10-28
"""
from alembic import op


revision = "0025_sw_icon_bin_collation"
down_revision = "0024_add_software_library"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        "ALTER TABLE `software_items` "
        "MODIFY COLUMN `icon` VARCHAR(16) CHARACTER SET utf8mb4 "
        "COLLATE utf8mb4_bin NOT NULL DEFAULT '🧰'"
    )


def downgrade() -> None:
    op.execute(
        "ALTER TABLE `software_items` "
        "MODIFY COLUMN `icon` VARCHAR(16) CHARACTER SET utf8mb4 "
        "COLLATE utf8mb4_unicode_ci NOT NULL DEFAULT '🧰'"
    )
