"""系统设置表 — DB 优先, .env 兜底。

存"运营/业务"配置: RAGFlow/Dify 连接、钉钉 webhook、平台名、mock 开关等。
不属于: 部署层的 host/port/credentials(mysql password / jwt secret) — 这些还在 .env。
"""
from datetime import datetime
from sqlalchemy import String, DateTime, JSON, Boolean, BigInteger, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.db.session import Base


class SystemSetting(Base):
    __tablename__ = "system_settings"

    key: Mapped[str] = mapped_column(String(96), primary_key=True)
    value: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    category: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    is_secret: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    updated_by: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow
    )
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=datetime.utcnow)
