"""下载/配置复制事件 —— 按用户统计的原始明细.

只在 count_dedup 判定「这次要计数」时写一行, 与卡片上的 download_count
同口径 (2 小时内重复下载只计一次). 不做外键: 账号删除后历史下载仍应保留.
"""
from datetime import datetime

from sqlalchemy import BigInteger, DateTime, Index, String
from sqlalchemy.orm import Mapped, mapped_column

from app.db.session import Base


class DownloadEvent(Base):
    __tablename__ = "download_events"
    __table_args__ = (
        Index("ix_download_events_created_at", "created_at"),
        Index("ix_download_events_user_created", "user_id", "created_at"),
        Index("ix_download_events_kind_code_created", "kind", "code", "created_at"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    # 匿名下载 (固定链接 / 公开下载) 没有用户, 但事件仍保留, 用于单独统计
    user_id: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    # 用户名快照 —— 账号改名/删除后仍能还原当时是谁
    username: Mapped[str] = mapped_column(String(64), nullable=False, default="")
    # software / extension
    kind: Mapped[str] = mapped_column(String(16), nullable=False)
    # download / copy (MCP 连接器的「配置复制」)
    action: Mapped[str] = mapped_column(String(16), nullable=False, default="download")
    code: Mapped[str] = mapped_column(String(64), nullable=False)
    name: Mapped[str] = mapped_column(String(128), nullable=False, default="")
    created_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, default=datetime.utcnow
    )
