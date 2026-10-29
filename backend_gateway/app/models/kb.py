"""知识库 (RAGFlow) 的操作审计 —— 谁在什么时候动了哪个数据集的哪个文档.

## 为什么要有这张表

知识库的内容**存在 RAGFlow 里**, 不在 TestMate 的库里. 所以:

1. **RAGFlow 自己记不了"谁传的"** —— 它的 document 里只有 RAGFlow 用户的
   ``created_by``, 而 TestMate 的所有登录用户共用**同一把 RAGFlow API key**.
   不留痕的话, 有人传了份垃圾文档, 谁传的**没人知道**.
2. 2026-10-29 开放了**普通登录用户上传**的权限 (以前只有 admin 能动知识库)——
   写操作的人变多了, 留痕就更不能少.

⚠️ 删除**仍然只有 admin 能做** —— 这张表只是留痕, 不改变权限边界.
"""
from __future__ import annotations

from datetime import datetime

from sqlalchemy import BigInteger, DateTime, Index, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.db.session import Base

class KbAudit(Base):
    """知识库操作审计流水."""

    __tablename__ = "kb_audits"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    dataset_id: Mapped[str] = mapped_column(String(64), nullable=False, default="", index=True)
    dataset_name: Mapped[str] = mapped_column(String(128), nullable=False, default="")
    document_id: Mapped[str] = mapped_column(String(64), nullable=False, default="", index=True)
    doc_name: Mapped[str] = mapped_column(String(255), nullable=False, default="")
    #: upload / delete / ingest —— 动作名 (中文标签在后端做, 这里存机器可读的值)
    action: Mapped[str] = mapped_column(String(32), nullable=False, default="", index=True)
    actor_id: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    actor_name: Mapped[str] = mapped_column(String(64), nullable=False, default="")
    #: 失败时的原因 (比如 RAGFlow 报错) —— 空串 = 成功
    error: Mapped[str] = mapped_column(Text, nullable=False, default="")
    #: 文档字节数 (上传时记, 便于看谁塞了个大文件进来)
    size: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=datetime.utcnow)

    __table_args__ = (
        # ⚠️ 查"某个数据集最近发生了什么" —— 页面上的审计列表按这个顺序查
        Index("ix_kb_audits_dataset_created", "dataset_id", "created_at"),
    )


class KbDatasetMeta(Base):
    """知识库数据集的**归属** —— 这个库是谁建的.

    ## 为什么必须有这张表

    RAGFlow 的 dataset 里确实有 ``created_by``, 但它记的是 **RAGFlow 用户**,
    而 TestMate 的所有登录用户共用**同一把 RAGFlow API key** ——
    所以 RAGFlow 那边只分得出"RAGFlow 用户", 分不出具体哪个 TestMate 账号建的库.

    这跟 :class:`KbAudit` 的区别:
      · ``KbAudit`` 是**事件流水** (谁什么时候传了东西), 只增不减;
      · 这张表是**当前归属** (这个库/这篇文档归谁), 一个对象一行.

    ⚠️ 历史数据(2026-10-29 之前建的库 / 传的文件)在这张表里**没有记录** ——
       那些是 RAGFlow 侧手工建的, 当时 TestMate 根本没有这个功能.
       详情页会显示「—」, 不瞎猜.
    """

    __tablename__ = "kb_dataset_meta"

    #: RAGFlow 的 dataset id (主键 —— 一个库就一行)
    dataset_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    name: Mapped[str] = mapped_column(String(128), nullable=False, default="")
    description: Mapped[str] = mapped_column(String(500), nullable=False, default="")
    chunk_method: Mapped[str] = mapped_column(String(32), nullable=False, default="")
    embedding_model: Mapped[str] = mapped_column(String(255), nullable=False, default="")
    #: 建库的 TestMate 账号 (可能是后来被删掉的账号, 所以留个名字快照)
    created_by: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    created_by_name: Mapped[str] = mapped_column(String(64), nullable=False, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow
    )


class KbDocumentMeta(Base):
    """知识库文档的**归属** —— 这篇是谁传的.

    ⚠️ 跟 :class:`KbDatasetMeta` 一样的原因: RAGFlow 记不了 TestMate 的账号.

    语义是「**当前这一版**是谁传的」—— 同一个文档被重新上传过, 这里会更新成
    最后一次上传的人 (审计表里则保留全部历史).
    """

    __tablename__ = "kb_document_meta"

    #: RAGFlow 的 document id (主键)
    document_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    dataset_id: Mapped[str] = mapped_column(String(64), nullable=False, default="", index=True)
    doc_name: Mapped[str] = mapped_column(String(255), nullable=False, default="")
    size: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    uploaded_by: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    uploaded_by_name: Mapped[str] = mapped_column(String(64), nullable=False, default="")
    uploaded_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=datetime.utcnow)
