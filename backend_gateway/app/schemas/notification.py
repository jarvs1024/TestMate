"""站内通知的请求/响应模型."""
from datetime import datetime

from pydantic import BaseModel

from app.schemas.base import UTCModel


class NotificationOut(UTCModel):
    id: int
    kind: str
    actor_name: str = ""
    asset_code: str = ""
    asset_name: str = ""
    comment_id: int | None = None
    parent_comment_id: int | None = None
    title: str = ""
    body: str = ""
    event_count: int = 1
    read_at: datetime | None = None
    created_at: datetime | None = None
    updated_at: datetime | None = None


class NotificationListOut(BaseModel):
    items: list[NotificationOut]
    total: int
    unread_count: int


class UnreadCountOut(BaseModel):
    count: int


class ReadOut(BaseModel):
    ok: bool = True
    id: int
    read_at: datetime | None = None
