"""SystemSetting Pydantic schemas."""
from datetime import datetime
from typing import Any
from pydantic import BaseModel, Field


class SettingOut(BaseModel):
    key: str
    value: Any
    category: str
    description: str | None = None
    is_secret: bool
    updated_by: int | None = None
    updated_at: datetime

    class Config:
        from_attributes = True


class SettingGroupOut(BaseModel):
    """前端一次性拉: schema + 当前值 (secret 掩码)."""
    category: str
    label: str
    items: list[dict[str, Any]]  # [{key, value, value_type, description, is_secret, is_default}]


class SettingUpdateIn(BaseModel):
    value: Any
    update_secret: bool = True  # for secret key: 是否要更新 (空字符串代表不改)


class SettingTestOut(BaseModel):
    ok: bool
    status: str  # 'ok' | 'warn' | 'off'
    message: str
    detail: dict[str, Any] | None = None
