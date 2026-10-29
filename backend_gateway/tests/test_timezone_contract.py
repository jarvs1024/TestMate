"""时间字段的时区契约 —— **后端一律输出 UTC(带 `Z`)**.

## 为什么锁这个

库里存的是 **naive UTC**(`datetime.utcnow()`, MySQL 的 DATETIME 没时区概念)。
以前 API 直接把它原样吐出去:

```
"updated_at": "2026-10-28T16:09:01"      ← 没有时区后缀
```

前端 `new Date(str)` 会按**本地时区**解析(本机 UTC+8)→ 显示出来比真实时间
**晚 8 小时**。通知记录、审计记录、资产更新时间、"X 分钟前" 全错。

修法在 `app/schemas/base.py`: 响应模型统一继承 `UTCModel`,
naive datetime 一律当 UTC, 输出带 `Z` 的 ISO 串。

⚠️ 这些用例锁的是**接口契约** —— 将来谁把 `UTCModel` 去掉, 这里立刻红。
"""
from __future__ import annotations

import re
from datetime import datetime

from app.schemas.base import UTCModel, to_utc_iso

API = "/api/v1/assets"

# ISO 串 + 结尾的 Z (或 ±HH:MM)
ISO_Z = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(\.\d+)?Z$")


# ---------- 单元: 序列化器本身 ----------

def test_naive_datetime_is_treated_as_utc():
    """naive datetime → 当 UTC, 不是当本地时间."""
    s = to_utc_iso(datetime(2026, 10, 28, 16, 9, 1))
    assert s == "2026-10-28T16:09:01Z", s


def test_aware_datetime_is_converted_to_utc():
    """带时区的 → 换算成 UTC 再输出 (不是硬贴 Z)."""
    from datetime import timezone, timedelta
    tz8 = timezone(timedelta(hours=8))
    s = to_utc_iso(datetime(2026, 10, 29, 0, 9, 1, tzinfo=tz8))
    assert s == "2026-10-28T16:09:01Z", s


def test_utc_model_serializes_datetime_with_z():
    """UTCModel 的 JSON 输出必须带 Z."""

    class M(UTCModel):
        when: datetime | None = None

    j = M(when=datetime(2026, 10, 28, 16, 9, 1)).model_dump(mode="json")
    assert j["when"] == "2026-10-28T16:09:01Z", j
    assert ISO_Z.match(j["when"]), j


def test_utc_model_leaves_other_fields_alone():
    """通配序列化器**只动 datetime** —— 别的字段原样输出."""
    from typing import Any

    class Child(UTCModel):
        when: datetime | None = None

    class M(UTCModel):
        name: str
        n: int
        flag: bool
        child: Child | None = None
        items: list[Child] = []
        meta: dict[str, Any] = {}

    j = M(
        name="x", n=3, flag=True,
        child=Child(when=datetime(2026, 10, 28, 16, 9, 2)),
        items=[Child(when=datetime(2026, 10, 28, 16, 9, 3))],
        meta={"k": 1},
    ).model_dump(mode="json")
    assert j["name"] == "x" and j["n"] == 3 and j["flag"] is True
    assert j["meta"] == {"k": 1}
    # 嵌套模型也要带上 Z
    assert j["child"]["when"].endswith("Z"), j
    assert j["items"][0]["when"].endswith("Z"), j


def test_utc_model_python_mode_keeps_datetime():
    """python 模式 (model_dump()) 不受影响 —— 内部逻辑拿到的还是 datetime."""
    class M(UTCModel):
        when: datetime | None = None

    m = M(when=datetime(2026, 10, 28, 16, 9, 1))
    assert isinstance(m.model_dump()["when"], datetime)


# ---------- 接口层: 每个带时间的响应都要带 Z ----------

async def _all_datetime_values(payload) -> list[str]:
    """把响应里所有**看起来像时间**的字符串值挑出来."""
    out: list[str] = []

    def walk(x):
        if isinstance(x, dict):
            for v in x.values():
                walk(v)
        elif isinstance(x, list):
            for v in x:
                walk(v)
        elif isinstance(x, str):
            if re.match(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}", x):
                out.append(x)

    walk(payload)
    return out


async def test_assets_api_timestamps_have_z(client, auth):
    """资产列表 / 详情里的时间戳要带 Z."""
    from app.db.session import AsyncSessionLocal
    from app.models.asset import Asset

    async with AsyncSessionLocal() as s:
        s.add(Asset(
            code="tz-demo", name="时区用例", icon="🧩", kind="skill",
            version="1.0.0", category="效率工具", publish_status="published",
            author="admin_t", git_path="assets/skills/demo/tz-demo",
        ))
        await s.commit()

    r = await client.get(f"{API}?limit=5", headers=auth)
    assert r.status_code == 200, r.text
    stamps = await _all_datetime_values(r.json())
    assert stamps, "响应里应该有更新时间戳"
    for s in stamps:
        assert s.endswith("Z"), f"时间戳缺时区后缀: {s}"


async def test_notifications_api_timestamps_have_z(client, auth):
    """通知回执里的时间戳要带 Z —— 这正是用户看到的"差 8 小时"的地方."""
    r = await client.get(f"{API}/notifications?limit=20", headers=auth)
    assert r.status_code == 200, r.text
    stamps = await _all_datetime_values(r.json())
    for s in stamps:
        assert s.endswith("Z"), f"时间戳缺时区后缀: {s}"


async def test_audits_api_timestamps_have_z(client, auth):
    """审计记录里的时间戳要带 Z."""
    r = await client.get(f"{API}/audits?limit=20", headers=auth)
    assert r.status_code == 200, r.text
    stamps = await _all_datetime_values(r.json())
    for s in stamps:
        assert s.endswith("Z"), f"时间戳缺时区后缀: {s}"


async def test_sync_status_api_timestamp_has_z(client, auth):
    """同步状态里的 last_sync_at 要带 Z."""
    r = await client.get(f"{API}/sync-status", headers=auth)
    assert r.status_code == 200, r.text
    stamps = await _all_datetime_values(r.json())
    for s in stamps:
        assert s.endswith("Z"), f"时间戳缺时区后缀: {s}"


async def test_software_api_timestamps_have_z(client, auth):
    """软件库里的时间戳也要带 Z."""
    r = await client.get("/api/v1/software?limit=5", headers=auth)
    assert r.status_code == 200, r.text
    stamps = await _all_datetime_values(r.json())
    for s in stamps:
        assert s.endswith("Z"), f"时间戳缺时区后缀: {s}"
