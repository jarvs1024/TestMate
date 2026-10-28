"""软件库: 安装说明/注意事项 + 版本变体标签/推荐版本 (2026-10-28)

背景:
    用户提了两件事:
      ① 软件上架和详情要能展示「安装说明」「注意事项」这类**可选**信息栏;
      ② 一个软件要挂两个不同的版本, **两个都有用** —— 光有版本号分不清谁是谁.

改动:
    software_items:
      · install_steps  Text     安装说明 (怎么装、怎么跑起来) —— 选填
      · caveats       Text     注意事项 (坑、副作用) —— 选填
    software_versions:
      · variant       String(32)  变体标签 (如「Windows版」「LTS版」) —— 选填
      · is_default    Boolean     是否是推荐下载的版本

⚠️ 为什么 is_default 存在**版本行**上而不是条目上:
    「推荐哪个版本」这件事, 天然是**版本的属性** —— 一个条目同时只能有一个推荐版本,
    但换推荐只是把某一行的标记挪走, 不该动条目本身.
    条目上的 `version` 字段是"当前版本指针"(发新版本时自动切),
    它回答的是"最新的是哪个", 而 is_default 回答的是"该下哪个" —— 两回事.

⚠️ 迁移**只加列**, 不动已有数据:
    · install_steps / caveats / variant 默认空串 —— 老条目照旧显示, 只是没这两栏;
    · is_default 默认 false —— 老条目的行为不变 (仍然取时间上最新的 ready 版本),
      直到有人手动把某个版本标成推荐.

Revision ID: 0026_sw_install_notes
Revises: 0025_sw_icon_bin_collation
Create Date: 2026-10-28
"""
from alembic import op


revision = "0026_sw_install_notes"
down_revision = "0025_sw_icon_bin_collation"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # ---- software_items: 安装说明 + 注意事项 ----
    # ⚠️ TEXT 列**不能带 DEFAULT** (MySQL 1101: BLOB/TEXT can't have a default value)
    #    → 先加成可空列, 再回填空串, 最后收紧成 NOT NULL.
    op.execute("ALTER TABLE `software_items` ADD COLUMN `install_steps` TEXT NULL")
    op.execute("ALTER TABLE `software_items` ADD COLUMN `caveats` TEXT NULL")
    op.execute("UPDATE `software_items` SET `install_steps` = '', `caveats` = '' "
               "WHERE `install_steps` IS NULL OR `caveats` IS NULL")
    op.execute(
        "ALTER TABLE `software_items` "
        "MODIFY COLUMN `install_steps` TEXT NOT NULL COMMENT '安装说明 (选填)'"
    )
    op.execute(
        "ALTER TABLE `software_items` "
        "MODIFY COLUMN `caveats` TEXT NOT NULL COMMENT '注意事项 (选填)'"
    )

    # ---- software_versions: 变体标签 + 推荐版本 ----
    op.execute(
        "ALTER TABLE `software_versions` "
        "ADD COLUMN `variant` VARCHAR(32) NOT NULL DEFAULT '' "
        "COMMENT '变体标签, 如 Windows版 (选填)'"
    )
    op.execute(
        "ALTER TABLE `software_versions` "
        "ADD COLUMN `is_default` BOOLEAN NOT NULL DEFAULT 0 "
        "COMMENT '是否推荐下载的版本'"
    )
    op.execute(
        "CREATE INDEX `ix_software_versions_is_default` "
        "ON `software_versions` (`is_default`)"
    )


def downgrade() -> None:
    op.execute("DROP INDEX `ix_software_versions_is_default` ON `software_versions`")
    op.execute("ALTER TABLE `software_versions` DROP COLUMN `is_default`")
    op.execute("ALTER TABLE `software_versions` DROP COLUMN `variant`")
    op.execute("ALTER TABLE `software_items` DROP COLUMN `caveats`")
    op.execute("ALTER TABLE `software_items` DROP COLUMN `install_steps`")
