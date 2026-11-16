"""设置-用户「用户明细」—— 每人活跃天数与下载情况."""
from __future__ import annotations

from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from app.db.session import AsyncSessionLocal
from app.models.download_event import DownloadEvent
from app.models.user import UserActivityDaily

API = "/api/v1"
AUTH = f"{API}/auth"
STATS = f"{AUTH}/stats"


def _auth(u: dict) -> dict[str, str]:
    return {"Authorization": f"Bearer {u['token']}"}


def _today():
    return datetime.now(ZoneInfo("Asia/Shanghai")).date()


async def _seed_activity(user_id: int, days: int) -> None:
    async with AsyncSessionLocal() as s:
        for i in range(days):
            s.add(
                UserActivityDaily(stat_date=_today() - timedelta(days=i), user_id=user_id)
            )
        await s.commit()


async def _seed_event(
    user_id: int | None,
    username: str,
    kind: str,
    code: str,
    name: str,
    *,
    action: str = "download",
    days_ago: int = 0,
) -> None:
    async with AsyncSessionLocal() as s:
        s.add(
            DownloadEvent(
                user_id=user_id,
                username=username,
                kind=kind,
                action=action,
                code=code,
                name=name,
                created_at=datetime.utcnow() - timedelta(days=days_ago),
            )
        )
        await s.commit()


async def test_user_stats_requires_admin(client, stranger_user):
    r = await client.get(f"{STATS}/users", headers=_auth(stranger_user))
    assert r.status_code == 403, r.text
    assert r.json()["detail"] == "仅管理员可以查看用户统计"

    detail = await client.get(
        f"{STATS}/users/{stranger_user['id']}/downloads", headers=_auth(stranger_user)
    )
    assert detail.status_code == 403, detail.text


async def test_user_stats_rejects_unknown_days(client, admin_user):
    r = await client.get(f"{STATS}/users?days=14", headers=_auth(admin_user))

    assert r.status_code == 422, r.text
    assert r.json()["detail"] == "统计周期只能是 7、30 或 90 天"


async def test_user_stats_returns_activity_and_download_counts(
    client, admin_user, stranger_user
):
    await _seed_activity(admin_user["id"], 3)
    await _seed_activity(stranger_user["id"], 1)
    await _seed_event(admin_user["id"], admin_user["username"], "software", "sw-a", "软件 A")
    await _seed_event(admin_user["id"], admin_user["username"], "software", "sw-a", "软件 A")
    await _seed_event(
        admin_user["id"], admin_user["username"], "extension", "ext-a", "扩展 A",
        action="copy",
    )
    await _seed_event(stranger_user["id"], stranger_user["username"], "extension", "ext-b", "扩展 B")
    await _seed_event(None, "", "software", "sw-a", "软件 A")

    r = await client.get(f"{STATS}/users?days=7", headers=_auth(admin_user))

    assert r.status_code == 200, r.text
    body = r.json()
    assert body["days"] == 7
    assert body["since"] == (_today() - timedelta(days=2)).isoformat()
    assert body["anonymous_downloads"] == 1
    rows = {u["username"]: u for u in body["users"]}
    admin = rows[admin_user["username"]]
    stranger = rows[stranger_user["username"]]

    assert admin["active_days"] == 3
    assert len(admin["active_dates"]) == 3
    assert admin["software_downloads"] == 2
    assert admin["extension_downloads"] == 1
    assert admin["total_downloads"] == 3
    assert stranger["active_days"] == 1
    assert stranger["software_downloads"] == 0
    assert stranger["extension_downloads"] == 1
    assert body["users"][0]["username"] == admin_user["username"]


async def test_user_stats_excludes_records_outside_period(
    client, admin_user, stranger_user
):
    await _seed_activity(admin_user["id"], 1)
    await _seed_activity(stranger_user["id"], 1)
    async with AsyncSessionLocal() as s:
        s.add(
            UserActivityDaily(
                stat_date=_today() - timedelta(days=8), user_id=admin_user["id"]
            )
        )
        await s.commit()
    await _seed_event(admin_user["id"], admin_user["username"], "software", "old", "旧软件", days_ago=8)

    r = await client.get(f"{STATS}/users?days=7", headers=_auth(admin_user))

    assert r.status_code == 200, r.text
    rows = {u["username"]: u for u in r.json()["users"]}
    assert rows[admin_user["username"]]["active_days"] == 1
    assert rows[admin_user["username"]]["software_downloads"] == 0


async def test_user_download_detail_groups_by_asset(client, admin_user):
    await _seed_event(admin_user["id"], admin_user["username"], "software", "sw-a", "软件 A")
    await _seed_event(admin_user["id"], admin_user["username"], "software", "sw-a", "软件 A")
    await _seed_event(admin_user["id"], admin_user["username"], "software", "sw-b", "软件 B")
    await _seed_event(admin_user["id"], admin_user["username"], "extension", "ext-a", "扩展 A")
    await _seed_event(admin_user["id"], admin_user["username"], "software", "old", "旧软件", days_ago=8)

    r = await client.get(
        f"{STATS}/users/{admin_user['id']}/downloads?days=7",
        headers=_auth(admin_user),
    )

    assert r.status_code == 200, r.text
    body = r.json()
    assert body["user_id"] == admin_user["id"]
    assert body["days"] == 7
    items = {(i["kind"], i["code"]): i for i in body["items"]}
    assert set(items) == {("software", "sw-a"), ("software", "sw-b"), ("extension", "ext-a")}
    assert items[("software", "sw-a")]["count"] == 2
    assert items[("software", "sw-a")]["name"] == "软件 A"
    assert items[("extension", "ext-a")]["name"] == "扩展 A"
    assert items[("extension", "ext-a")]["action"] == "download"
    assert body["items"][0]["code"] == "sw-a"
    assert body["items"][0]["last_at"]


async def test_user_download_detail_keeps_copy_separate_from_download(client, admin_user):
    """同一个连接器可能既有安装包下载也有配置复制，明细不能合并成一条."""
    await _seed_event(admin_user["id"], admin_user["username"], "extension", "ext-a", "扩展 A")
    await _seed_event(
        admin_user["id"], admin_user["username"], "extension", "ext-a", "扩展 A",
        action="copy",
    )

    r = await client.get(
        f"{STATS}/users/{admin_user['id']}/downloads?days=7",
        headers=_auth(admin_user),
    )

    assert r.status_code == 200, r.text
    items = {(i["kind"], i["action"], i["code"]): i for i in r.json()["items"]}
    assert set(items) == {
        ("extension", "download", "ext-a"),
        ("extension", "copy", "ext-a"),
    }
    assert items[("extension", "download", "ext-a")]["count"] == 1
    assert items[("extension", "copy", "ext-a")]["count"] == 1


async def test_user_download_detail_rejects_unknown_user(client, admin_user):
    r = await client.get(
        f"{STATS}/users/999999/downloads?days=7", headers=_auth(admin_user)
    )

    assert r.status_code == 404, r.text
    assert r.json()["detail"] == "用户不存在"
