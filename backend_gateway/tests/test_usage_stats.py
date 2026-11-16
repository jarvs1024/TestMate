"""设置-用户「使用统计」回归 —— 在线人数 / 日活 / 下载排行."""
from __future__ import annotations

from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from sqlalchemy import func, select

from app.db.session import AsyncSessionLocal
from app.models.asset import Asset
from app.models.software import SoftwareItem
from app.models.user import User, UserActivityDaily

API = "/api/v1"
AUTH = f"{API}/auth"
STATS = f"{AUTH}/stats"


def _auth(u: dict) -> dict[str, str]:
    return {"Authorization": f"Bearer {u['token']}"}


def _today() -> str:
    return datetime.now(ZoneInfo("Asia/Shanghai")).date().isoformat()


async def _seed_downloads() -> None:
    async with AsyncSessionLocal() as s:
        s.add_all(
            [
                SoftwareItem(
                    code="soft-low", name="低下载", download_count=2,
                    publish_status="published",
                ),
                SoftwareItem(
                    code="soft-high", name="高下载", download_count=9,
                    publish_status="published",
                ),
                SoftwareItem(
                    code="soft-mid", name="中下载", download_count=5,
                    publish_status="published",
                ),
                SoftwareItem(
                    code="soft-hidden", name="隐藏软件", download_count=100,
                    publish_status="hidden",
                ),
                SoftwareItem(
                    code="soft-deleted", name="已删软件", download_count=200,
                    publish_status="published", deleted_at=datetime.utcnow(),
                ),
            ]
        )
        for i in range(1, 10):
            s.add(
                Asset(
                    code=f"ext-{i}", name=f"扩展{i}", kind="skill",
                    download_count=i, publish_status="published",
                )
            )
        await s.commit()


async def test_summary_requires_admin(client, stranger_user):
    r = await client.get(f"{STATS}/summary", headers=_auth(stranger_user))

    assert r.status_code == 403, r.text
    assert r.json()["detail"] == "仅管理员可以查看用户统计"


async def test_summary_rejects_unknown_days(client, admin_user):
    r = await client.get(f"{STATS}/summary?days=14", headers=_auth(admin_user))

    assert r.status_code == 422, r.text
    assert r.json()["detail"] == "统计周期只能是 7、30 或 90 天"


async def test_summary_returns_zero_filled_series_and_library_rankings(
    client, admin_user
):
    await _seed_downloads()
    me = await client.get(f"{AUTH}/me", headers=_auth(admin_user))
    assert me.status_code == 200, me.text

    r = await client.get(f"{STATS}/summary?days=7", headers=_auth(admin_user))

    assert r.status_code == 200, r.text
    body = r.json()
    assert len(body["active"]["series"]) == 7
    assert body["active"]["series"][-1]["date"] == _today()
    assert body["active"]["series"][0]["count"] == 0
    assert body["active"]["today"] >= 1

    software = body["downloads"]["software"]
    assert software["total"] == 16
    assert [i["code"] for i in software["items"]] == [
        "soft-high", "soft-mid", "soft-low",
    ]

    extensions = body["downloads"]["extensions"]
    assert extensions["total"] == 45
    assert len(extensions["items"]) == 8
    assert extensions["items"][0]["code"] == "ext-9"
    assert [i["count"] for i in extensions["items"]] == [9, 8, 7, 6, 5, 4, 3, 2]


async def test_authenticated_web_request_marks_user_online(
    client, admin_user, stranger_user
):
    me = await client.get(f"{AUTH}/me", headers=_auth(stranger_user))
    assert me.status_code == 200, me.text

    r = await client.get(f"{STATS}/summary", headers=_auth(admin_user))

    assert r.status_code == 200, r.text
    online = r.json()["online"]
    names = {u["username"] for u in online["users"]}
    assert stranger_user["username"] in names
    assert online["count"] == len(online["users"])
    assert online["window_minutes"] == 5


async def test_background_poll_only_keeps_online_but_does_not_count_active(
    client, stranger_user
):
    poll = await client.get(
        f"{API}/notifications/unread-count", headers=_auth(stranger_user)
    )
    assert poll.status_code == 200, poll.text

    async with AsyncSessionLocal() as s:
        active_rows = await s.scalar(
            select(func.count())
            .select_from(UserActivityDaily)
            .where(UserActivityDaily.user_id == stranger_user["id"])
        )
        last_seen = await s.scalar(
            select(User.last_seen_at).where(User.id == stranger_user["id"])
        )
    assert active_rows == 0
    assert last_seen is not None


async def test_stats_poll_only_keeps_online_but_does_not_count_active(
    client, admin_user
):
    """设置页每 60 秒轮询在线名单 —— 这是后台轮询, 不能把管理员一直算成日活."""
    r = await client.get(f"{STATS}/online", headers=_auth(admin_user))
    assert r.status_code == 200, r.text

    async with AsyncSessionLocal() as s:
        active_rows = await s.scalar(
            select(func.count())
            .select_from(UserActivityDaily)
            .where(UserActivityDaily.user_id == admin_user["id"])
        )
        last_seen = await s.scalar(
            select(User.last_seen_at).where(User.id == admin_user["id"])
        )
    assert active_rows == 0
    assert last_seen is not None


async def test_daily_activity_is_deduplicated_per_user_per_day(
    client, stranger_user
):
    first = await client.get(f"{AUTH}/me", headers=_auth(stranger_user))
    second = await client.get(f"{AUTH}/me", headers=_auth(stranger_user))
    assert first.status_code == 200 and second.status_code == 200

    async with AsyncSessionLocal() as s:
        rows = await s.scalar(
            select(func.count())
            .select_from(UserActivityDaily)
            .where(
                UserActivityDaily.user_id == stranger_user["id"],
                UserActivityDaily.stat_date == datetime.now(
                    ZoneInfo("Asia/Shanghai")
                ).date(),
            )
        )
    assert rows == 1


async def test_last_seen_update_does_not_bump_user_updated_at(
    client, stranger_user
):
    async with AsyncSessionLocal() as s:
        before = await s.scalar(
            select(User.updated_at).where(User.id == stranger_user["id"])
        )

    r = await client.get(f"{AUTH}/me", headers=_auth(stranger_user))
    assert r.status_code == 200, r.text

    async with AsyncSessionLocal() as s:
        row = await s.get(User, stranger_user["id"])
        assert row is not None
        assert row.last_seen_at is not None
        assert row.updated_at == before


async def test_successful_login_marks_user_active_and_online(client):
    from app.core.security import hash_password

    async with AsyncSessionLocal() as s:
        u = User(
            username="login_stats_t",
            password_hash=hash_password("Login@12345"),
            role="tester",
            password_required=True,
        )
        s.add(u)
        await s.commit()
        await s.refresh(u)
        uid = u.id

    login = await client.post(
        f"{AUTH}/login",
        json={"username": "login_stats_t", "password": "Login@12345"},
    )
    assert login.status_code == 200, login.text

    async with AsyncSessionLocal() as s:
        rows = await s.scalar(
            select(func.count())
            .select_from(UserActivityDaily)
            .where(UserActivityDaily.user_id == uid)
        )
        last_seen = await s.scalar(select(User.last_seen_at).where(User.id == uid))
    assert rows == 1
    assert last_seen is not None


async def test_user_list_exposes_online_flag(client, admin_user, stranger_user):
    """账号列表要能直接告诉前端「谁在线」—— 不让前端自己拿时钟算边界."""
    await client.get(f"{AUTH}/me", headers=_auth(stranger_user))
    async with AsyncSessionLocal() as s:
        s.add(
            User(
                username="stale_list_t",
                password_hash="",
                role="viewer",
                last_seen_at=datetime.utcnow() - timedelta(minutes=6),
            )
        )
        await s.commit()

    r = await client.get(f"{AUTH}/users", headers=_auth(admin_user))

    assert r.status_code == 200, r.text
    rows = {u["username"]: u for u in r.json()}
    assert rows[stranger_user["username"]]["is_online"] is True
    assert rows["stale_list_t"]["is_online"] is False
    assert rows[stranger_user["username"]]["last_seen_at"] is not None


async def test_online_endpoint_returns_recent_users_only(
    client, admin_user, stranger_user
):
    await client.get(f"{AUTH}/me", headers=_auth(stranger_user))
    await client.get(f"{AUTH}/me", headers=_auth(admin_user))
    async with AsyncSessionLocal() as s:
        s.add(
            User(
                username="stale_stats_t",
                password_hash="",
                role="viewer",
                last_seen_at=datetime.utcnow() - timedelta(minutes=6),
            )
        )
        await s.commit()

    denied = await client.get(f"{STATS}/online", headers=_auth(stranger_user))
    assert denied.status_code == 403, denied.text

    r = await client.get(f"{STATS}/online", headers=_auth(admin_user))

    assert r.status_code == 200, r.text
    body = r.json()
    names = {u["username"] for u in body["users"]}
    assert stranger_user["username"] in names
    assert admin_user["username"] in names
    assert "stale_stats_t" not in names
    assert body["count"] == len(body["users"])
