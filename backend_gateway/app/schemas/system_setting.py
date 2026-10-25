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
    # ⚠️ secret 项现在**空值一律当"不改"** (与前端"留空 = 不改"的契约一致),
    #    这个开关已经不起作用了 —— 保留字段只是为了不破坏旧调用方的 payload.
    update_secret: bool = True


class SettingTestOut(BaseModel):
    ok: bool
    status: str  # 'ok' | 'warn' | 'off'
    message: str
    detail: dict[str, Any] | None = None
