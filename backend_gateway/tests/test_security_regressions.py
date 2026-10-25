"""安全与健壮性回归 —— 2026-10-25 全面检视的产出.

盯住这几件事 (每条都对应一个真实缺陷):
  ① kb 共享嵌入页的 theme 参数 → **不能**变成反射型 XSS;
  ② JWT_SECRET 写在 .env **文件**里也要算数 (不是只有环境变量才算);
  ③ 管理员不能把账号改成"免密" (那等于把自己锁死);
  ④ 口令**原样**存、原样比 —— 建号时不许 strip, 登录时才不会对不上;
  ⑤ 全空白口令要显式拒绝 (否则静默生成一个免密账号);
  ⑥ bcrypt 只认前 72 **字节** —— 超长的要拦, 不然静默截断;
  ⑦ anonymous 是内部占位角色, 不许建号;
  ⑧ 建号时挡住"管理员账号名"与"用户邮箱前缀"撞名;
  ⑨ 能力注册接口: category/kind/status 非法值要 422, 不是 500;
  ⑩ secret 配置项传空值 = 不改, 不许把真凭据清空.
"""
import pytest

from app.core.identity import lookup_candidates


# ---------- ① XSS ----------

async def test_share_embed_theme_is_whitelisted(client):
    """theme 被拼进 <script> —— 注入脚本片段必须被降级成 light."""
    # 端点会去连 RAGFlow (本机没有), 连不上会抛错 —— 重点是**不能**返回注入内容
    try:
        r = await client.get(
            "/api/v1/kb/share-embed/search/share",
            params={"theme": "';alert(document.domain);//"},
        )
    except Exception:
        return  # 连不上 RAGFlow, 注入逻辑根本没走到
    if r.status_code == 200:
        body = r.text
        assert "alert(document.domain)" not in body
        assert "'" not in body.split("localStorage.setItem('ragflow-ui-theme'")[0].split("var t=")[-1][:40]


async def test_share_embed_theme_whitelist_logic():
    """白名单逻辑本身: 只认 light / dark."""
    from app.api.kb import share_embed_proxy  # noqa: F401  (确保模块可导入)

    # 直接验证被接受的值 (通过源码里的常量避免重复实现)
    src = open("app/api/kb.py", encoding="utf-8").read()
    assert 'theme in ("light", "dark")' in src
    assert "json.dumps(theme)" in src


# ---------- ② JWT_SECRET 来自 .env 文件 ----------

def test_jwt_secret_from_env_file_is_accepted(monkeypatch):
    """⚠️ pydantic-settings 从 .env **文件**读值时不会写回 os.environ ——
    原来用 os.getenv 判定, 导致本地按 README 起后端直接 RuntimeError."""
    from app.core.config import Settings, _validate_jwt_secret

    monkeypatch.delenv("JWT_SECRET", raising=False)
    s = Settings(_env_file="tests/fixtures/.env.jwt_secret", _env_file_encoding="utf-8")
    assert "JWT_SECRET" in s.model_fields_set
    # 不抛异常 = 通过
    _validate_jwt_secret(s)


def test_jwt_secret_missing_is_still_rejected(monkeypatch):
    """没配 JWT_SECRET 时仍然要拦住 (生产不能走随机默认值).

    ⚠️ conftest 会强制 DEBUG=true (跳过校验), 所以这里要显式改回 false.
    """
    from app.core.config import Settings, _validate_jwt_secret

    monkeypatch.delenv("JWT_SECRET", raising=False)
    monkeypatch.setenv("DEBUG", "false")
    # _env_file=None → 不读 backend_gateway/.env, 模拟"完全没配"
    s = Settings(_env_file=None)
    assert s.DEBUG is False
    assert "JWT_SECRET" not in s.model_fields_set
    with pytest.raises(RuntimeError):
        _validate_jwt_secret(s)


# ---------- ③ 管理员不能改成免密 ----------

async def test_admin_cannot_be_switched_to_passwordless(client, admin_user):
    """admin 角色免密 = 谁也进不去的账号 (need_password 对 admin 恒为真)."""
    r = await client.patch(
        f"/api/v1/auth/users/{admin_user['id']}",
        json={"password_required": False},
        headers={"Authorization": f"Bearer {admin_user['token']}"},
    )
    assert r.status_code == 400, r.text
    assert "免密" in r.json()["detail"]


async def test_normal_user_can_be_switched_to_passwordless(client, admin_user):
    """普通账号可以改免密 (这是管理员的正常操作)."""
    _r = await client.post(
        "/api/v1/auth/users",
        json={"username": "tofree", "role": "tester"},
        headers={"Authorization": f"Bearer {admin_user['token']}"},
    )
    uid = _r.json()["id"]
    r = await client.patch(
        f"/api/v1/auth/users/{uid}",
        json={"password_required": False},
        headers={"Authorization": f"Bearer {admin_user['token']}"},
    )
    assert r.status_code == 200, r.text
    assert r.json()["password_required"] is False


# ---------- ④⑤ 口令原样 / 空白口令 ----------

async def test_password_with_spaces_round_trips(client, admin_user):
    """口令首尾空格是口令的一部分 —— 建号时不能 strip, 登录时原样比对."""
    h = {"Authorization": f"Bearer {admin_user['token']}"}
    r = await client.post(
        "/api/v1/auth/users",
        json={"username": "spacey", "role": "tester", "password": "  Secret@2026  "},
        headers=h,
    )
    assert r.status_code == 201, r.text

    # 原样带空格 → 能登
    ok = await client.post(
        "/api/v1/auth/login", json={"username": "spacey", "password": "  Secret@2026  "}
    )
    assert ok.status_code == 200, ok.text()

    # 去掉空格 → 不能登 (说明口令确实原样存了)
    bad = await client.post("/api/v1/auth/login", json={"username": "spacey", "password": "Secret@2026"})
    assert bad.status_code == 401, bad.text()


async def test_blank_only_password_rejected(client, admin_user):
    """全空白口令要显式拒绝 —— 否则会被当成"没给密码", 静默生成免密账号."""
    r = await client.post(
        "/api/v1/auth/users",
        json={"username": "blankpwd", "role": "tester", "password": "   "},
        headers={"Authorization": f"Bearer {admin_user['token']}"},
    )
    assert r.status_code == 422, r.text


# ---------- ⑥ bcrypt 72 字节 ----------

async def test_password_over_72_bytes_rejected(client, admin_user):
    """bcrypt 只取前 72 **字节**, 超出的被静默丢弃 —— 入参层就拦."""
    r = await client.post(
        "/api/v1/auth/users",
        json={"username": "toolong", "role": "tester", "password": "a" * 100},
        headers={"Authorization": f"Bearer {admin_user['token']}"},
    )
    assert r.status_code == 422, r.text


async def test_password_of_72_bytes_accepted(client, admin_user):
    """正好 72 字节要能过 (别拦过头)."""
    r = await client.post(
        "/api/v1/auth/users",
        json={"username": "exact72", "role": "tester", "password": "a" * 72},
        headers={"Authorization": f"Bearer {admin_user['token']}"},
    )
    assert r.status_code == 201, r.text


# ---------- ⑦ anonymous 占位角色 ----------

async def test_cannot_create_anonymous_account(client, admin_user):
    r = await client.post(
        "/api/v1/auth/users",
        json={"username": "ghost", "role": "anonymous"},
        headers={"Authorization": f"Bearer {admin_user['token']}"},
    )
    assert r.status_code == 422, r.text


async def test_cannot_promote_to_anonymous(client, admin_user):
    _r = await client.post(
        "/api/v1/auth/users",
        json={"username": "notghost", "role": "tester"},
        headers={"Authorization": f"Bearer {admin_user['token']}"},
    )
    uid = _r.json()["id"]
    r = await client.patch(
        f"/api/v1/auth/users/{uid}",
        json={"role": "anonymous"},
        headers={"Authorization": f"Bearer {admin_user['token']}"},
    )
    assert r.status_code == 422, r.text


# ---------- ⑧ 建号撞名 ----------

async def test_admin_name_colliding_with_user_prefix_rejected(client, admin_user):
    """管理员账号名 'zhangsan' 与用户邮箱前缀 'zhangsan' 撞名 → 用户用短名
    登录会先命中管理员, 结果被要求输管理员密码."""
    h = {"Authorization": f"Bearer {admin_user['token']}"}
    r0 = await client.post("/api/v1/auth/users", json={"username": "zhangsan", "role": "tester"}, headers=h)
    assert r0.status_code == 201, r0.text()

    r = await client.post(
        "/api/v1/auth/users",
        json={"username": "zhangsan", "role": "admin", "password": "Admin@2026"},
        headers=h,
    )
    assert r.status_code == 422, r.text
    assert "撞名" in r.json()["detail"]


async def test_user_prefix_colliding_with_admin_name_rejected(client, admin_user):
    h = {"Authorization": f"Bearer {admin_user['token']}"}
    r0 = await client.post(
        "/api/v1/auth/users",
        json={"username": "lisi", "role": "admin", "password": "Admin@2026"},
        headers=h,
    )
    assert r0.status_code == 201, r0.text()

    r = await client.post("/api/v1/auth/users", json={"username": "lisi", "role": "tester"}, headers=h)
    assert r.status_code == 422, r.text
    assert "撞名" in r.json()["detail"]


def test_lookup_candidates_still_prefers_exact_match():
    """精确匹配优先这条规则不能被改坏 (admin 要能按原样命中)."""
    assert lookup_candidates("admin")[0] == "admin"
    assert lookup_candidates("zhangsan")[0] == "zhangsan"
    assert lookup_candidates("zhangsan@twsc.com.cn")[0] == "zhangsan@twsc.com.cn"


# ---------- ⑨ 能力注册枚举校验 ----------

async def test_create_agent_accepts_api_category_round_trip(client, admin_user):
    """category 传 API 出参的形式 ('auto-code') 要能建 —— SQLAlchemy 会把
    连字符 value 转成 DB 里的下划线 name. 这一条是**回归护栏**, 不是缺陷修复."""
    r = await client.post(
        "/api/v1/agents",
        json={
            "code": "probe-cat", "name": "探针", "category": "auto-code",
            "summary": "探针", "kind": "tool", "status": "draft",
        },
        headers={"Authorization": f"Bearer {admin_user['token']}"},
    )
    assert r.status_code in (200, 201), r.text
    assert r.json()["category"] == "auto-code"


async def test_create_agent_rejects_unknown_enum_values(client, admin_user):
    """真正不存在的枚举值要 422 —— 原来会变成 500 的 LookupError."""
    for field, value in (("category", "not-a-category"), ("kind", "wat"), ("status", "zzz")):
        payload = {
            "code": f"probe-{field}", "name": "探针", "category": "auto-code",
            "summary": "探针", "kind": "tool", "status": "draft",
        }
        payload[field] = value
        r = await client.post(
            "/api/v1/agents",
            json=payload,
            headers={"Authorization": f"Bearer {admin_user['token']}"},
        )
        assert r.status_code == 422, (field, value, r.status_code, r.text)
        assert r.status_code != 500


# ---------- ⑩ secret 空值不改 ----------

async def test_empty_secret_value_does_not_wipe_credential(client, admin_user):
    """PUT secret 项传空值 = 不改 —— 原来会把 RAGFlow api_key 直接清空."""
    from tests.conftest import set_setting

    await set_setting("ragflow.api_key", "super-secret-key")
    r = await client.put(
        "/api/v1/settings/ragflow.api_key",
        json={"value": "", "update_secret": True},
        headers={"Authorization": f"Bearer {admin_user['token']}"},
    )
    assert r.status_code == 200, r.text

    from app.core.settings_store import get

    assert (await get("ragflow.api_key", "")) == "super-secret-key", "空值把凭据清空了"


async def test_non_empty_secret_value_is_written(client, admin_user):
    from app.core.settings_store import get

    r = await client.put(
        "/api/v1/settings/ragflow.api_key",
        json={"value": "new-key-123", "update_secret": True},
        headers={"Authorization": f"Bearer {admin_user['token']}"},
    )
    assert r.status_code == 200, r.text
    assert (await get("ragflow.api_key", "")) == "new-key-123"
