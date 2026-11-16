"""设置-用户「使用统计」响应模型."""
from datetime import datetime

from pydantic import BaseModel, ConfigDict

from app.models.user import UserRole
from app.schemas.base import UTCModel


class StatsOnlineUser(UTCModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    username: str
    role: UserRole
    last_seen_at: datetime


class StatsOnline(BaseModel):
    count: int
    window_minutes: int
    users: list[StatsOnlineUser]


class StatsSeriesPoint(BaseModel):
    date: str
    count: int


class StatsActive(BaseModel):
    today: int
    series: list[StatsSeriesPoint]


class StatsDownloadItem(BaseModel):
    code: str
    name: str
    icon: str = ""
    count: int
    # 扩展的细分类型 (plugin/skill/mcp); mcp 的数字是「配置复制」而非安装包下载
    kind: str = ""


class StatsDownloadLibrary(BaseModel):
    total: int
    items: list[StatsDownloadItem]


class StatsDownloads(BaseModel):
    software: StatsDownloadLibrary
    extensions: StatsDownloadLibrary


class StatsSummary(BaseModel):
    online: StatsOnline
    active: StatsActive
    downloads: StatsDownloads


class StatsUserRow(UTCModel):
    id: int
    username: str
    role: UserRole
    is_active: bool
    is_online: bool
    active_days: int
    active_dates: list[str]
    last_seen_at: datetime | None = None
    software_downloads: int = 0
    extension_downloads: int = 0
    total_downloads: int = 0


class StatsUsers(BaseModel):
    days: int
    # 用户维度数据从哪天开始记 —— 用户明细是事件表上线后才有的
    since: str
    anonymous_downloads: int = 0
    users: list[StatsUserRow]


class StatsUserDownloadItem(UTCModel):
    kind: str
    action: str = "download"
    code: str
    name: str
    count: int
    last_at: datetime


class StatsUserDownloads(BaseModel):
    user_id: int
    days: int
    items: list[StatsUserDownloadItem]
