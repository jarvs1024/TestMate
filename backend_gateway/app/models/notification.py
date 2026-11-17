"""站内通知 —— 用户自己的消息箱 (与钉钉送达回执 AssetNotification 无关)."""
from datetime import datetime

from sqlalchemy import BigInteger, DateTime, Index, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.db.session import Base


class UserNotification(Base):
    """收件人的站内通知.

    聚合规则: 同一收件人 + 同一个 dedupe_key 在**未读**期间合并成一行
    (event_count 累加, body/comment_id 取最新); 已读之后再来的事件另起一行.
    所以 dedupe_key 的解释权在写入方 (见 app/core/inbox.py):
      · asset_comment:{code}      同一资产的评论
      · comment_reply:{root_id}   同一条主评论下的回复
    """

    __tablename__ = "user_notifications"
    __table_args__ = (
        Index("ix_user_notifications_user_read", "user_id", "read_at"),
        Index("ix_user_notifications_name_read", "username", "read_at"),
        Index("ix_user_notifications_dedupe", "user_id", "dedupe_key", "read_at"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    # 收件人 —— 能解析到账号就填 id; username 同时留快照 (账号改名/停用不影响历史)
    user_id: Mapped[int | None] = mapped_column(BigInteger, nullable=True, index=True)
    username: Mapped[str] = mapped_column(String(64), nullable=False, default="")

    actor_id: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    actor_name: Mapped[str] = mapped_column(String(64), nullable=False, default="")

    # asset_comment(评论了你的资产) / comment_reply(回复了你的评论)
    kind: Mapped[str] = mapped_column(String(24), nullable=False, index=True)
    dedupe_key: Mapped[str] = mapped_column(String(160), nullable=False, default="", index=True)

    asset_code: Mapped[str] = mapped_column(String(64), nullable=False, default="")
    asset_name: Mapped[str] = mapped_column(String(128), nullable=False, default="")

    # 跳转定位 —— 最新一条事件 (回复则指向回复本身, 主评论指向主评论)
    comment_id: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    parent_comment_id: Mapped[int | None] = mapped_column(BigInteger, nullable=True)

    title: Mapped[str] = mapped_column(String(200), nullable=False, default="")
    body: Mapped[str] = mapped_column(Text, nullable=False, default="")
    event_count: Mapped[int] = mapped_column(Integer, nullable=False, default=1)

    read_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow
    )
