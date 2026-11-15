"""RAGFlow 用户空间 —— 一把 API key 对应一个 RAGFlow 用户空间."""
from __future__ import annotations

from datetime import datetime

from sqlalchemy import BigInteger, DateTime, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.db.session import Base


class RagflowSpace(Base):
    """知识库用户空间.

    RAGFlow 的 API key 绑死在用户上：换一把 key 就换了一整个租户空间
    (数据集 / 文档 / 分段全都不一样)。这张表把多把 key 存下来，页面和 MCP
    才能按空间切换。

    ⚠️ key 永远只存 AES-256-GCM 密文，明文不落库、不出接口。
    """

    __tablename__ = "ragflow_spaces"

    id: Mapped[str] = mapped_column(String(32), primary_key=True)
    name: Mapped[str] = mapped_column(String(64), nullable=False, unique=True)
    #: AES-256-GCM 密文
    api_key_cipher: Mapped[str] = mapped_column(Text, nullable=False)
    created_by: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, default=datetime.utcnow
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow
    )
