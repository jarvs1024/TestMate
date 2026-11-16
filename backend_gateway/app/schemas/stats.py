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
