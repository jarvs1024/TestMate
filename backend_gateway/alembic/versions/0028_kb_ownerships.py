"""知识库归属表 (2026-10-29)

背景:
    开放了「新建数据集」(tester 及以上) 之后, 知识库里出现了两个新问题:

      ① **建了库不知道是谁建的** —— RAGFlow 的 dataset 里有 ``created_by``,
         但它记的是 **RAGFlow 用户**; 而 TestMate 的所有登录用户共用
         **同一把 API key**, 所以 RAGFlow 那边分不出具体哪个账号建的库.
      ② **传了文档不知道是谁传的** —— 同理.

    这跟第一阶段的 ``kb_audits``(0027) 是**两回事**:
      · ``kb_audits`` 是**事件流水** —— 谁什么时候动了什么, 只增不减;
      · 这两张表是**当前归属** —— 这个库/这篇文档归谁, 一个对象就一行.

改动:
    新建 ``kb_dataset_meta``:
      · dataset_id (主键) / name / description / chunk_method / embedding_model
      · created_by / created_by_name —— 建库的人
      · created_at / updated_at

    新建 ``kb_document_meta``:
      · document_id (主键) / dataset_id / doc_name / size
      · uploaded_by / uploaded_by_name —— 最后一次上传的人
      · uploaded_at

⚠️ 历史数据**不回填** —— 2026-10-29 之前建的库和传的文件, 当时 TestMate
   根本没有建库/上传功能, 没人知道是谁干的. 详情页显示「—」, 不瞎猜.
   (协议文档那 5 篇是 2026-10-29 事故恢复时重传的, 审计表里有记录.)

⚠️ 迁移用 inspector 做幂等守卫 (沿用 0006~0010 的做法) —— MySQL DDL 非事务,
   迁移中途失败不会回滚已执行的 DDL, 但 alembic 版本号会回退.
   守卫保证半途失败后重跑能补齐.

Revision ID: 0028_kb_ownerships
Revises: 0027_kb_audits
Create Date: 2026-10-29
"""
from alembic import op
import sqlalchemy as sa


revision = "0028_kb_ownerships"
down_revision = "0027_kb_audits"
branch_labels = None
depends_on = None


def upgrade() -> None:
    insp = sa.inspect(op.get_bind())
    tables = set(insp.get_table_names())

    if "kb_dataset_meta" not in tables:
        op.execute(
            """
            CREATE TABLE `kb_dataset_meta` (
                `dataset_id` VARCHAR(64) NOT NULL COMMENT 'RAGFlow 数据集 ID',
                `name` VARCHAR(128) NOT NULL DEFAULT '' COMMENT '数据集名称',
                `description` VARCHAR(500) NOT NULL DEFAULT '' COMMENT '数据集说明',
                `chunk_method` VARCHAR(32) NOT NULL DEFAULT '' COMMENT '切片方式 (naive/manual)',
                `embedding_model` VARCHAR(255) NOT NULL DEFAULT '' COMMENT '嵌入模型',
                `created_by` BIGINT NULL COMMENT '建库的 TestMate 账号 ID',
                `created_by_name` VARCHAR(64) NOT NULL DEFAULT '' COMMENT '建库人账号 (名字快照)',
                `created_at` DATETIME NOT NULL COMMENT '创建时间 (UTC)',
                `updated_at` DATETIME NOT NULL COMMENT '更新时间 (UTC)',
                PRIMARY KEY (`dataset_id`)
            ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
            """
        )

    if "kb_document_meta" not in tables:
        op.execute(
            """
            CREATE TABLE `kb_document_meta` (
                `document_id` VARCHAR(64) NOT NULL COMMENT 'RAGFlow 文档 ID',
                `dataset_id` VARCHAR(64) NOT NULL DEFAULT '' COMMENT '所属数据集 ID',
                `doc_name` VARCHAR(255) NOT NULL DEFAULT '' COMMENT '文档名',
                `size` INTEGER NOT NULL DEFAULT 0 COMMENT '文档字节数',
                `uploaded_by` BIGINT NULL COMMENT '上传者的 TestMate 账号 ID',
                `uploaded_by_name` VARCHAR(64) NOT NULL DEFAULT '' COMMENT '上传者账号 (名字快照)',
                `uploaded_at` DATETIME NOT NULL COMMENT '上传时间 (UTC)',
                PRIMARY KEY (`document_id`),
                KEY `ix_kb_document_meta_dataset_id` (`dataset_id`)
            ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
            """
        )


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS `kb_document_meta`")
    op.execute("DROP TABLE IF EXISTS `kb_dataset_meta`")
