"""响应模型共用的基类 —— 时间一律按 **UTC** 输出.

## 为什么要有这个

库里存的时间是 **naive UTC**(`datetime.utcnow()`, MySQL 的 DATETIME 没时区概念),
但**以前 API 直接把它原样吐出去**:

```
"updated_at": "2026-10-28T16:09:01"     ← 没有时区后缀, 语义不明
```

前端拿到这种串, `new Date(str)` 会按**浏览器本地时区**去解析(本机是 UTC+8),
于是显示出来的时间**比真实时间晚 8 小时** —— 通知记录、审计记录、资产更新时间、
"X 分钟前" 全是错的。

## 怎么修

在响应模型上补一个通配字段序列化器: **naive datetime 一律当成 UTC**, 输出带 `Z`:

```
"updated_at": "2026-10-28T16:09:01Z"    ← 明确是 UTC
```

这样 API 的语义就确定了("这是 UTC"), 前端 `new Date(str)` 不用改就对,
外部脚本 / 别的客户端也不会再踩同一个坑。

⚠️ **只影响 JSON 输出**(`when_used='json'`)—— `model_dump()`(python 模式)
还是拿到 datetime 对象, 内部逻辑(DB 比较、排序)一点都不受影响。

⚠️ 只给**响应模型**(`*Out`)用 —— 请求模型不需要。
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from pydantic import BaseModel, field_serializer


def to_utc_iso(value: datetime) -> str:
    """naive datetime (库里存的是 UTC) → 带 Z 的 ISO 串."""
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


class UTCModel(BaseModel):
    """所有**响应**模型的基类 —— 时间按 UTC 输出(带 `Z`)."""

    @field_serializer("*", when_used="json", check_fields=False)
    def _serialize_utc_datetime(self, value: Any) -> Any:
        # ⚠️ 通配序列化器对**所有字段**生效 —— 所以这里必须只动 datetime,
        #    别的类型原样返回 (嵌套模型也靠它自动带上 Z).
        if isinstance(value, datetime):
            return to_utc_iso(value)
        return value
