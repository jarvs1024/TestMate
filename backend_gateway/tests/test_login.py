"""登录 —— 2026-10-25 账号管理重构.

新规则:
  · 账号**必须管理员先建过**才能登录 —— 填了没开通的账号一律 401;
  · 普通用户 = 公司邮箱 (后缀固定 @twsc.com.cn), 建号时没设密码 → 免密登录;
  · 管理员 = 账号名 (不含 @), **必须密码**登录.

盯住这几件事:
  ① 普通用户: 管理员建过的号, 只填用户名 (前缀或完整邮箱) 就能进;
  ② 管理员: 缺密码 → password_required (前端据此展开密码框);
     密码错 → 401; 密码对 → 进;
  ③ **账号不存在 → 401, 而且绝不在库里自动建号** (免的是密码, 不是身份);
  ④ 账号被停用 → 401;
  ⑤ 建号时设了密码的普通账号 → 登录必须输密码;
  ⑥ 非法输入 (别的域名 / 垃圾字符) → 401, **不会**在库里堆垃圾账号;
  ⑦ 白名单容错: publisher/reviewer 名单填短名或全邮箱都能命中.
"""
import pytest
from sqlalchemy import select

from app.core.identity import email_domain, local_part, lookup_candidates, name_matches, to_email
from app.db.session import AsyncSessionLocal
from app.models.user import User, UserRole


# ---------- 纯逻辑: 身份口径 ----------

def test_to_email_normalizes():
    assert to_email("zhangsan") == "zhangsan@twsc.com.cn"
    assert to_email("ZhangSan") == "zhangsan@twsc.com.cn"
    assert to_email("zhangsan@twsc.com.cn") == "zhangsan@twsc.com.cn"
    assert to_email("zhangsan@other.com") is None
    assert to_email("") is None
    assert to_email("   ") is None
    assert to_email("a b") is None          # 空格不是合法本地部分
    assert to_email("rm -rf /") is None


def test_lookup_candidates_order():
    """⚠️ 顺序不能乱: 'admin' 必须先按原样命中, 否则会被当成
    'admin@twsc.com.cn' 命中另一个普通账号."""
    assert lookup_candidates("admin")[0] == "admin"
    assert "admin@twsc.com.cn" in lookup_candidates("admin")
    cands = lookup_candidates("zhangsan")
    assert cands[0] == "zhangsan"
    assert "zhangsan@twsc.com.cn" in cands
    # 老库里存短名时也能命中
    assert "zhangsan" in lookup_candidates("zhangsan@twsc.com.cn")


def test_local_part_and_domain():
    assert local_part("zhangsan@twsc.com.cn") == "zhangsan"
    assert local_part("admin") == "admin"
    assert email_domain() == "@twsc.com.cn"


def test_name_matches_tolerates_both_forms():
    """白名单填短名或全邮箱都算命中."""
    assert name_matches({"zhangsan"}, "zhangsan@twsc.com.cn")
    assert name_matches({"zhangsan@twsc.com.cn"}, "zhangsan@twsc.com.cn")
    assert name_matches({"zhangsan@twsc.com.cn"}, "zhangsan")
    assert not name_matches({"lisi"}, "zhangsan@twsc.com.cn")
    assert not name_matches(set(), "zhangsan")


# ---------- 登录端点 ----------

async def _make_user(
    username: str,
    password: str | None,
    role: UserRole = UserRole.tester,
    *,
    is_active: bool = True,
    password_required: bool | None = None,
) -> int:
    """造一个账号 (模拟管理员建好的号).

    ⚠️ password_required 默认按"有没有给密码"推 —— 建号时给了密码就是
    必须密码账号, 没给就是免密账号.
    """
    from app.core.security import hash_password

    if password_required is None:
        password_required = bool(password)
    async with AsyncSessionLocal() as s:
        u = User(
            username=username,
            password_hash=hash_password(password) if password else hash_password("x" * 40),
            role=role,
            is_active=is_active,
            password_required=password_required,
        )
        s.add(u)
        await s.commit()
        await s.refresh(u)
        return u.id


async def test_ordinary_user_login_without_password(client):
    """普通用户: 管理员建过的号, 只填用户名就能进 (前缀 / 完整邮箱都认)."""
    await _make_user("zhangsan@twsc.com.cn", None)
    r = await client.post("/api/v1/auth/login", json={"username": "zhangsan"})
    assert r.status_code == 200, r.text()
    assert r.json()["access_token"]

    r2 = await client.post("/api/v1/auth/login", json={"username": "zhangsan@twsc.com.cn"})
    assert r2.status_code == 200, r2.text()


async def test_unknown_account_is_rejected_and_not_created(client):
    """⚠️ 核心: 账号不存在 → 401, 而且**绝不在库里自动建号**.

    免密免的是**密码**, 不是身份 —— 知道同事邮箱不等于能进他的号.
    """
    r = await client.post("/api/v1/auth/login", json={"username": "newbie"})
    assert r.status_code == 401, r.text()
    detail = r.json()["detail"]
    assert detail["code"] == "account_not_found"
    assert "开通" in detail["message"]

    async with AsyncSessionLocal() as s:
        rows = (await s.execute(select(User))).scalars().all()
        assert not rows, "未知账号不该被自动开通"


async def test_disabled_account_cannot_login(client):
    """管理员停用的账号 → 401."""
    await _make_user("leaver@twsc.com.cn", None, is_active=False)
    r = await client.post("/api/v1/auth/login", json={"username": "leaver"})
    assert r.status_code == 401, r.text()
    assert r.json()["detail"]["code"] == "account_disabled"


async def test_admin_must_provide_password(client):
    """管理员: 缺密码 → password_required (前端据此展开密码框)."""
    await _make_user("admin2", "Admin@123", UserRole.admin)
    r = await client.post("/api/v1/auth/login", json={"username": "admin2"})
    assert r.status_code == 401, r.text()
    detail = r.json()["detail"]
    assert detail["code"] == "password_required"
    assert "密码" in detail["message"]


async def test_admin_wrong_password_rejected(client):
    """管理员: 密码错 → 普通 401 (不是 password_required)."""
    await _make_user("admin3", "Admin@123", UserRole.admin)
    r = await client.post("/api/v1/auth/login", json={"username": "admin3", "password": "wrong"})
    assert r.status_code == 401, r.text()
    assert r.json()["detail"] == "用户名或密码错误"


async def test_admin_with_right_password_ok(client):
    await _make_user("admin4", "Admin@123", UserRole.admin)
    r = await client.post("/api/v1/auth/login", json={"username": "admin4", "password": "Admin@123"})
    assert r.status_code == 200, r.text()


async def test_password_account_requires_password(client):
    """建号时设了密码的普通账号 → 登录必须输密码."""
    await _make_user("secure@twsc.com.cn", "MyPwd@2026")
    r = await client.post("/api/v1/auth/login", json={"username": "secure"})
    assert r.status_code == 401, r.text()
    assert r.json()["detail"]["code"] == "password_required"

    r2 = await client.post("/api/v1/auth/login", json={"username": "secure", "password": "MyPwd@2026"})
    assert r2.status_code == 200, r2.text()

    r3 = await client.post("/api/v1/auth/login", json={"username": "secure", "password": "wrong"})
    assert r3.status_code == 401, r3.text()
    assert r3.json()["detail"] == "用户名或密码错误"


async def test_passwordless_account_ignores_typed_password(client):
    """免密账号: 用户手滑多输了密码 —— 照样放行.

    这个账号压根没有密码, 输什么都对不上, 报"密码错误"只会让人以为自己记错了.
    """
    await _make_user("free@twsc.com.cn", None)
    r = await client.post("/api/v1/auth/login", json={"username": "free", "password": "随便打的"})
    assert r.status_code == 200, r.text()


async def test_foreign_domain_is_rejected(client):
    """别的域名 → 401, 而且**不会**在库里留下垃圾账号."""
    r = await client.post("/api/v1/auth/login", json={"username": "someone@other.com"})
    assert r.status_code == 401, r.text()
    async with AsyncSessionLocal() as s:
        rows = (await s.execute(select(User).where(User.username.like("%other.com")))).scalars().all()
        assert not rows, "非本公司域名不该被开通"


async def test_garbage_input_is_rejected(client):
    r = await client.post("/api/v1/auth/login", json={"username": "rm -rf /"})
    assert r.status_code == 401, r.text()


async def test_unknown_user_not_in_company_domain_rejected(client):
    """不是公司邮箱的输入 (比如乱打的名字) → 401."""
    r = await client.post("/api/v1/auth/login", json={"username": "不存在的人"})
    assert r.status_code == 401, r.text()


async def test_login_response_carries_username(client):
    """token 里带的 username 是邮箱形式 —— 前端顶栏显示的就是它."""
    await _make_user("lisi@twsc.com.cn", None)
    r = await client.post("/api/v1/auth/login", json={"username": "lisi"})
    assert r.status_code == 200, r.text()
    me = await client.get(
        "/api/v1/auth/me", headers={"Authorization": f"Bearer {r.json()['access_token']}"}
    )
    assert me.status_code == 200, me.text()
    assert me.json()["username"] == "lisi@twsc.com.cn"


# ---------- 白名单容错 ----------

@pytest.mark.parametrize("whitelist", ["zhangsan", "zhangsan@twsc.com.cn"])
async def test_publisher_whitelist_accepts_both_forms(client, whitelist):
    """设置页里手填的白名单, 短名和全邮箱都得认."""
    from tests.conftest import set_setting

    await set_setting("marketplace.publisher_usernames", whitelist)
    await _make_user("zhangsan@twsc.com.cn", None)
    r = await client.post("/api/v1/auth/login", json={"username": "zhangsan"})
    token = r.json()["access_token"]
    h = {"Authorization": f"Bearer {token}"}

    from app.core.market_policy import can_publish
    async with AsyncSessionLocal() as s:
        user = (await s.execute(select(User).where(User.username == "zhangsan@twsc.com.cn"))).scalar_one()
        assert await can_publish(user) is True
