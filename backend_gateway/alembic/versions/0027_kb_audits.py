"""知识库 (RAGFlow) 操作审计表 (2026-10-29)

背景:
    知识库的内容**存在 RAGFlow 里**, 不在 TestMate 的库里. 2026-10-29 开放了
    **普通登录用户上传**的权限 (以前只有 admin 能动知识库), 于是缺一个"谁干的"的地方:

      · RAGFlow 自己记不了 —— 它的 document 里只有 RAGFlow 用户的 ``created_by``,
        而 TestMate 的所有登录用户共用**同一把 RAGFlow API key**;
      · 不留痕的话, 有人传了份垃圾文档, 谁传的**没人知道**.

改动:
    新建 ``kb_audits`` 表:
      · dataset_id / dataset_name —— 动了哪个数据集
      · document_id / doc_name    —— 动了哪个文档
      · action                    —— upload / delete / ingest
      · actor_id / actor_name     —— 谁干的 (TestMate 账号)
      · error                     —— 失败原因 (空串 = 成功)
      · size                      —— 文档字节数
      · created_at                —— 什么时候

⚠️ 这张表**只是留痕**, 不改变权限边界 —— 删除仍然只有 admin 能做.

⚠️ 迁移用 inspector 做幂等守卫 (沿用 0006~0010 的做法) —— MySQL DDL 非事务,
   迁移中途失败不会回滚已执行的 DDL, 但 alembic 版本号会回退.
   守卫保证半途失败后重跑能补齐.

Revision ID: 0027_kb_audits
Revises: 0026_sw_install_notes
Create Date: 2026-10-29
"""
from alembic import op
import sqlalchemy as sa


revision = "0027_kb_audits"
down_revision = "0026_sw_install_notes"
branch_labels = None
depends_on = None


def upgrade() -> None:
    insp = sa.inspect(op.get_bind())
    tables = set(insp.get_table_names())
    if "kb_audits" in tables:
        return

    op.execute(
        """
        CREATE TABLE `kb_audits` (
            `id` BIGINT NOT NULL AUTO_INCREMENT,
            `dataset_id` VARCHAR(64) NOT NULL DEFAULT '' COMMENT 'RAGFlow 数据集 ID',
            `dataset_name` VARCHAR(128) NOT NULL DEFAULT '' COMMENT '数据集名称',
            `document_id` VARCHAR(64) NOT NULL DEFAULT '' COMMENT 'RAGFlow 文档 ID',
            `doc_name` VARCHAR(255) NOT NULL DEFAULT '' COMMENT '文档名',
            `action` VARCHAR(32) NOT NULL DEFAULT '' COMMENT 'upload / delete / ingest',
            `actor_id` BIGINT NULL COMMENT '操作人 ID',
            `actor_name` VARCHAR(64) NOT NULL DEFAULT '' COMMENT '操作人账号',
            `error` TEXT NOT NULL COMMENT '失败原因 (空串 = 成功)',
            `size` INTEGER NOT NULL DEFAULT 0 COMMENT '文档字节数',
            `created_at` DATETIME NOT NULL COMMENT '操作时间 (UTC)',
            PRIMARY KEY (`id`),
            KEY `ix_kb_audits_dataset_id` (`dataset_id`),
            KEY `ix_kb_audits_document_id` (`document_id`),
            KEY `ix_kb_audits_action` (`action`),
            KEY `ix_kb_audits_dataset_created` (`dataset_id`, `created_at`)
        ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
        """
    )


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS `kb_audits`")
