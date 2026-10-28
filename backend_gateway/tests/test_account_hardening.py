"""账号与运维端点的**加固**回归 (2026-10-26 全面审计).

这一轮审计挖出来的问题, 全在这个文件里钉死:

  · 设置 schema 泄露 git.remote / git.branch / publisher_roles (非管理员也能读到内网仓库地址)
  · 撞名校验漏"老库里存着短名的普通用户" → 一人两号 / 新账号继承老账号资产
  · 改密码后**旧 token 照样能用满 7 天** (JWT 不可撤销)
  · 账号建/改**一个字都不留痕**
  · 登录端点**没有任何失败次数限制** (可在线撞库 + 枚举账号)
  · 运维端点越权: sync 任何发布者都能触发 / 任何人都能重试别人的 job / 任何人都能列出全市场未上架资产
  · /health/ready (无鉴权) 回显 MySQL/Redis 内部报错原文
  · /kb/health (无鉴权) 泄露 RAGFlow 探针信息
"""
from __future__ import annotations

import pytest

API = "/api/v1"
AUTH = f"{API}/auth"
SETTINGS = f"{API}/settings"

# 这些设置项**不能**让非管理员看到 (内网仓库地址 / 发布权限策略)
ADMIN_ONLY_KEYS = (
    "marketplace.git.remote",
    "marketplace.git.branch",
    "marketplace.publisher_roles",
    # ⚠️ 2026-10-28: 软件库的存储根目录 —— **服务端文件路径**,
    #    泄露等于告诉别人服务的目录结构. 显式标了 admin_only.
    "software.storage_path",
)


def _schema_keys(payload: dict) -> set[str]:
    out: set[str] = set()
    for g in payload.get("groups", []):
        for it in g.get("items", []):
            out.add(it["key"])
    return out


# ---------- ① 设置 schema 不泄露内部信息 ----------

async def test_settings_schema_hides_admin_only_keys_for_normal_user(client, stranger_user):
    """非管理员读 schema → 拿不到 SSH 仓库地址 / 分支 / 发布权限策略."""
    r = await client.get(f"{SETTINGS}/schema", headers={
        "Authorization": f"Bearer {stranger_user['token']}"
    })
    assert r.status_code == 200, r.text
    keys = _schema_keys(r.json())
    for k in ADMIN_ONLY_KEYS:
        assert k not in keys, f"{k} 不该出现在非管理员的 schema 里"


async def test_settings_schema_shows_admin_only_keys_for_admin(client, admin_user):
    """管理员照常能看见 (设置页要能编辑它们)."""
    r = await client.get(f"{SETTINGS}/schema", headers={
        "Authorization": f"Bearer {admin_user['token']}"
    })
    assert r.status_code == 200, r.text
    keys = _schema_keys(r.json())
    for k in ADMIN_ONLY_KEYS:
        assert k in keys, f"管理员的 schema 里应该有 {k}"


async def test_settings_schema_still_hides_credentials(client, stranger_user):
    """正则兜底不能被放松 —— 凭据类条目照旧整条不给."""
    r = await client.get(f"{SETTINGS}/schema", headers={
        "Authorization": f"Bearer {stranger_user['token']}"
    })
    assert r.status_code == 200, r.text
    keys = _schema_keys(r.json())
    assert not any("webhook" in k for k in keys), keys
    assert not any("api_key" in k for k in keys), keys


async def test_admin_only_flag_is_used_not_only_regex():
    """新加的敏感项必须标 admin_only —— 别又只靠正则 (正则漏过三项)."""
    from app.core.settings_store import SETTING_SCHEMA

    flagged = {s["key"] for s in SETTING_SCHEMA if s.get("admin_only")}
    for k in ADMIN_ONLY_KEYS:
        assert k in flagged, f"{k} 少了 admin_only 标记"


# ---------- ② 撞名校验: 覆盖所有写法 ----------

async def _make_legacy_shortname_user(username: str) -> int:
    """造一个"老库里存着短名"的普通用户 (迁移 0020 之前的遗留行)."""
    from app.core.security import hash_password
    from app.db.session import AsyncSessionLocal
    from app.models.user import User, UserRole

    async with AsyncSessionLocal() as s:
        u = User(
            username=username,
            password_hash=hash_password("Old@123456"),
            role=UserRole.viewer,
        )
        s.add(u)
        await s.commit()
        await s.refresh(u)
        return u.id


async def test_create_admin_conflicts_with_legacy_shortname_user(client, admin_user):
    """库里有短名普通用户 'zhangsan' 时, 不许再建管理员 'zhangsan'.

    否则老用户用短名登录会**先命中管理员账号** → 老用户被管理员账号劫持.
    ⚠️ 这里用户名**完全相同** → 报 409 (账号已存在) 而不是 422 (撞名) ——
       两者都拒绝, 区别只在提示: 完全同名说"已存在", 不同写法撞上了才说"撞名".
    """
    await _make_legacy_shortname_user("zhangsan")
    r = await client.post(f"{AUTH}/users", headers={
        "Authorization": f"Bearer {admin_user['token']}"
    }, json={"username": "zhangsan", "password": "Admin@12345", "role": "admin"})
    assert r.status_code == 409, r.text
    assert "账号已存在" in r.text, r.text


async def test_create_user_conflicts_with_legacy_shortname_user(client, admin_user):
    """库里有短名普通用户 'zhangsan' 时, 也不许再建 'zhangsan@twsc.com.cn'.

    不挡的话就是**一人两号**, 而且新账号会继承老账号名下的资产所有权
    (作者名比对是容错的 —— 短名和邮箱形式都算命中).
    """
    await _make_legacy_shortname_user("zhangsan")
    r = await client.post(f"{AUTH}/users", headers={
        "Authorization": f"Bearer {admin_user['token']}"
    }, json={"username": "zhangsan", "password": "User@12345", "role": "tester"})
    assert r.status_code == 422, r.text
    assert "撞名" in r.text, r.text


async def test_create_user_with_existing_full_name_returns_409(client, admin_user):
    """完全同名 → 409 (跟老行为一致: 前端靠 409 走"改口令"分支)."""
    r = await client.post(f"{AUTH}/users", headers={
        "Authorization": f"Bearer {admin_user['token']}"
    }, json={"username": "dup_t", "password": "User@12345", "role": "tester"})
    assert r.status_code == 201, r.text
    r2 = await client.post(f"{AUTH}/users", headers={
        "Authorization": f"Bearer {admin_user['token']}"
    }, json={"username": "dup_t", "password": "User@12345", "role": "tester"})
    assert r2.status_code == 409, r2.text


async def test_admin_name_clash_with_email_user_is_blocked(client, admin_user):
    """建管理员 'lisi' 时, 库里已有 'lisi@twsc.com.cn' → 挡住 (老行为别丢)."""
    r = await client.post(f"{AUTH}/users", headers={
        "Authorization": f"Bearer {admin_user['token']}"
    }, json={"username": "lisi", "password": "User@12345", "role": "tester"})
    assert r.status_code == 201, r.text
    r2 = await client.post(f"{AUTH}/users", headers={
        "Authorization": f"Bearer {admin_user['token']}"
    }, json={"username": "lisi", "password": "Admin@12345", "role": "admin"})
    assert r2.status_code == 422, r2.text


# ---------- ③ token_version: 改密码/改角色/停用 → 旧 token 立即作废 ----------

async def _login(client, username: str, password: str) -> dict:
    r = await client.post(f"{AUTH}/login", json={"username": username, "password": password})
    assert r.status_code == 200, r.text
    return r.json()


async def _create_account(client, admin_user, username, password, role="tester") -> dict:
    r = await client.post(f"{AUTH}/users", headers={
        "Authorization": f"Bearer {admin_user['token']}"
    }, json={"username": username, "password": password, "role": role})
    assert r.status_code == 201, r.text
    return r.json()


async def test_password_reset_invalidates_old_token(client, admin_user):
    """管理员重置密码 → 那个账号手上的旧 token **立刻**失效 (不是等 7 天过期)."""
    await _create_account(client, admin_user, "pv_t", "Old@123456")
    tok = (await _login(client, "pv_t", "Old@123456"))["access_token"]
    h = {"Authorization": f"Bearer {tok}"}

    assert (await client.get(f"{AUTH}/me", headers=h)).status_code == 200

    uid = (await client.get(f"{AUTH}/me", headers=h)).json()["id"]
    r = await client.patch(f"{AUTH}/users/{uid}", headers={
        "Authorization": f"Bearer {admin_user['token']}"
    }, json={"password": "New@123456"})
    assert r.status_code == 200, r.text

    # 旧 token → 401
    r2 = await client.get(f"{AUTH}/me", headers=h)
    assert r2.status_code == 401, r2.text
    # 新密码能登, 新 token 能用
    tok2 = (await _login(client, "pv_t", "New@123456"))["access_token"]
    assert (await client.get(f"{AUTH}/me", headers={
        "Authorization": f"Bearer {tok2}"
    })).status_code == 200


async def test_role_change_invalidates_old_token(client, admin_user):
    """角色变更 (降权) → 旧 token 立刻失效 —— 否则手里的 token 还能当管理员用."""
    await _create_account(client, admin_user, "rc_t", "Old@123456")
    tok = (await _login(client, "rc_t", "Old@123456"))["access_token"]
    h = {"Authorization": f"Bearer {tok}"}
    uid = (await client.get(f"{AUTH}/me", headers=h)).json()["id"]

    r = await client.patch(f"{AUTH}/users/{uid}", headers={
        "Authorization": f"Bearer {admin_user['token']}"
    }, json={"role": "viewer"})
    assert r.status_code == 200, r.text

    assert (await client.get(f"{AUTH}/me", headers=h)).status_code == 401


async def test_disable_invalidates_old_token(client, admin_user):
    """停用账号 → 旧 token 立刻失效."""
    await _create_account(client, admin_user, "ds_t", "Old@123456")
    tok = (await _login(client, "ds_t", "Old@123456"))["access_token"]
    h = {"Authorization": f"Bearer {tok}"}
    uid = (await client.get(f"{AUTH}/me", headers=h)).json()["id"]

    r = await client.patch(f"{AUTH}/users/{uid}", headers={
        "Authorization": f"Bearer {admin_user['token']}"
    }, json={"is_active": False})
    assert r.status_code == 200, r.text

    assert (await client.get(f"{AUTH}/me", headers=h)).status_code == 401


async def test_legacy_token_without_tv_still_works(client, stranger_user):
    """升级前签发的 token (没有 tv 字段) 依然能用 —— 不用全员重新登录."""
    r = await client.get(f"{AUTH}/me", headers={
        "Authorization": f"Bearer {stranger_user['token']}"
    })
    assert r.status_code == 200, r.text


async def test_token_with_garbage_sub_is_401_not_500(client):
    """sub 解析失败 → 401 (以前 int() 直接抛 ValueError → 500)."""
    from app.core.security import create_access_token

    tok, _ = create_access_token("not-a-number", {"tv": 0})
    r = await client.get(f"{AUTH}/me", headers={"Authorization": f"Bearer {tok}"})
    assert r.status_code == 401, r.text


# ---------- ④ 账号操作留痕 ----------

async def test_account_operations_are_audited(client, admin_user):
    """建号/改号都要留痕 (管理员在「操作记录」里能查到谁动了哪个账号)."""
    await _create_account(client, admin_user, "au_t", "User@12345")
    r = await client.get(f"{API}/assets/audits?limit=50", headers={
        "Authorization": f"Bearer {admin_user['token']}"
    })
    assert r.status_code == 200, r.text
    items = r.json()["items"]
    creates = [a for a in items if a["action"] == "user.create"]
    assert creates, f"没找到建号留痕: {items}"
    assert any("au_t" in (a.get("code") or "") for a in creates), creates
    assert creates[0]["action_label"] == "创建账号", creates[0]
    # ⚠️ 审计里**不能**出现密码本身
    assert "User@12345" not in r.text, r.text
    # 建号用的就是库里那个邮箱形式的用户名
    assert creates[0]["detail"]["username"] == "au_t@twsc.com.cn", creates[0]

    # 改号 → 也要留痕
    ul = await client.get(f"{AUTH}/users", headers={
        "Authorization": f"Bearer {admin_user['token']}"
    })
    uid = next(u["id"] for u in ul.json() if u["username"] == "au_t@twsc.com.cn")
    r2 = await client.patch(f"{AUTH}/users/{uid}", headers={
        "Authorization": f"Bearer {admin_user['token']}"
    }, json={"role": "viewer"})
    assert r2.status_code == 200, r2.text

    r3 = await client.get(f"{API}/assets/audits?limit=50", headers={
        "Authorization": f"Bearer {admin_user['token']}"
    })
    updates = [a for a in r3.json()["items"] if a["action"] == "user.update"]
    assert updates, f"没找到改号留痕: {r3.json()['items']}"
    assert updates[0]["action_label"] == "修改账号", updates[0]
    assert updates[0]["detail"].get("role") == "viewer", updates[0]


# ---------- ⑤ 登录失败限流 ----------

async def test_login_rate_limit_blocks_bruteforce(client, admin_user):
    """连续登录失败超过阈值 → 429 (在线撞库 + 枚举账号都要有代价)."""
    import app.api.auth as auth_mod

    old_limit = auth_mod._LOGIN_FAIL_LIMIT
    auth_mod._LOGIN_FAIL_LIMIT = 3
    try:
        for i in range(3):
            r = await client.post(f"{AUTH}/login", json={
                "username": "brute_t", "password": "wrong-password",
            })
            assert r.status_code == 401, f"第 {i + 1} 次应该 401, 实际 {r.status_code}"
        # 第 4 次 → 被限流
        r = await client.post(f"{AUTH}/login", json={
            "username": "brute_t", "password": "wrong-password",
        })
        assert r.status_code == 429, r.text
    finally:
        auth_mod._LOGIN_FAIL_LIMIT = old_limit


async def test_login_rate_limit_resets_on_success(client, admin_user):
    """登录成功 → 失败计数清零 (别让一次误输把账号一直挂着"快锁了")."""
    import app.api.auth as auth_mod

    old_limit = auth_mod._LOGIN_FAIL_LIMIT
    auth_mod._LOGIN_FAIL_LIMIT = 3
    try:
        await _create_account(client, admin_user, "ok_t", "Right@123456")
        for _ in range(2):
            await client.post(f"{AUTH}/login", json={"username": "ok_t", "password": "nope"})
        assert (await _login(client, "ok_t", "Right@123456"))["access_token"]
        # 计数清零 → 再错两次也不该 429
        for _ in range(2):
            r = await client.post(f"{AUTH}/login", json={"username": "ok_t", "password": "nope"})
            assert r.status_code == 401, r.text
    finally:
        auth_mod._LOGIN_FAIL_LIMIT = old_limit


# ---------- ⑥ 公开配置端点 ----------

async def test_auth_config_is_public_and_returns_email_domain(client):
    """GET /auth/config 不用登录 → 前端登录页/建号页不用把域名写死."""
    r = await client.get(f"{AUTH}/config")
    assert r.status_code == 200, r.text
    j = r.json()
    assert "email_domain" in j, j
    assert j["email_domain"].startswith("@"), j


# ---------- ⑦ 运维端点越权 ----------

async def test_sync_requires_admin(client, publisher_user):
    """全量同步 = 全市场级别的运维动作 → 只给管理员."""
    r = await client.post(f"{API}/assets/sync", headers={
        "Authorization": f"Bearer {publisher_user['token']}"
    })
    assert r.status_code == 403, r.text


async def test_admin_can_sync(client, admin_user):
    """管理员照常能同步."""
    r = await client.post(f"{API}/assets/sync", headers={
        "Authorization": f"Bearer {admin_user['token']}"
    })
    assert r.status_code == 200, r.text


async def _make_job(created_by: int, code: str = "probe-job") -> int:
    from app.db.session import AsyncSessionLocal
    from app.models.asset import AssetJob

    async with AsyncSessionLocal() as s:
        j = AssetJob(action="create", status="failed", code=code, created_by=created_by)
        s.add(j)
        await s.commit()
        await s.refresh(j)
        return j.id


async def test_job_list_is_scoped_to_owner(client, publisher_user, admin_user):
    """任务列表: 非管理员只看得到自己的 (job 里带未上架资产的 code/git_path)."""
    mine = await _make_job(publisher_user["id"], "my-job")
    theirs = await _make_job(admin_user["id"], "other-job")

    r = await client.get(f"{API}/assets/jobs", headers={
        "Authorization": f"Bearer {publisher_user['token']}"
    })
    assert r.status_code == 200, r.text
    ids = {j["id"] for j in r.json()["items"]}
    assert mine in ids, ids
    assert theirs not in ids, f"不该看到别人的 job: {ids}"

    # 管理员看得到全部
    r2 = await client.get(f"{API}/assets/jobs", headers={
        "Authorization": f"Bearer {admin_user['token']}"
    })
    ids2 = {j["id"] for j in r2.json()["items"]}
    assert mine in ids2 and theirs in ids2, ids2


async def test_cannot_read_other_users_job(client, publisher_user, admin_user):
    """别人的 job 详情 → 403."""
    theirs = await _make_job(admin_user["id"], "other-job")
    r = await client.get(f"{API}/assets/jobs/{theirs}", headers={
        "Authorization": f"Bearer {publisher_user['token']}"
    })
    assert r.status_code == 403, r.text


async def test_cannot_retry_other_users_job(client, publisher_user, admin_user):
    """别人的 job 不能重试 (重试 = 触发执行)."""
    theirs = await _make_job(admin_user["id"], "other-job")
    r = await client.post(f"{API}/assets/jobs/{theirs}/retry", headers={
        "Authorization": f"Bearer {publisher_user['token']}"
    })
    assert r.status_code == 403, r.text


# ---------- ⑧ 健康检查不泄露内部信息 ----------
async def test_health_ready_does_not_leak_raw_error(client, monkeypatch):
    """无鉴权的 /health/ready 不能回显 MySQL/Redis 的原始报错 (带账号/host:port)."""
    import app.api.health as health_mod

    async def _bad_mysql():
        return False, "OperationalError: (1045) Access denied for user 'root'@'10.0.0.9' (using password: YES)"

    async def _bad_redis():
        return False, "ConnectionError: Error connecting to host:6379. Connection refused."

    monkeypatch.setattr(health_mod, "_check_mysql", _bad_mysql)
    monkeypatch.setattr(health_mod, "_check_redis", _bad_redis)

    r = await client.get(f"{API}/health/ready")
    assert r.status_code == 503, r.text
    body = r.text
    assert "root" not in body, body
    assert "6379" not in body, body
    assert "10.0.0.9" not in body, body
    assert "Access denied" not in body, body
    assert "MySQL" in body and "Redis" in body, body


async def test_kb_health_requires_login(client):
    """知识库健康检查要登录 (以前无鉴权, 谁都能探 RAGFlow 的地址/错误详情)."""
    r = await client.get(f"{API}/kb/health")
    assert r.status_code == 401, r.text


# ---------- ⑨ 知识库文档分页的 total 语义 ----------

async def test_kb_documents_total_is_full_count_not_page_count(client, admin_user, monkeypatch):
    """total 必须是**全量**文档数 —— 以前返回本页条数, 前端翻页循环永远不执行."""
    import app.api.kb as kb_mod

    async def _fake_list_documents(**kwargs):
        return {
            "docs": [{"id": f"d{i}", "name": f"doc{i}"} for i in range(100)],
            "total": 250,
        }

    monkeypatch.setattr(kb_mod, "list_documents", _fake_list_documents)
    r = await client.get(f"{API}/kb/datasets/ds1/documents", headers={
        "Authorization": f"Bearer {admin_user['token']}"
    })
    assert r.status_code == 200, r.text
    j = r.json()
    assert len(j["docs"]) == 100
    assert j["total"] == 250, j


# ---------- ⑩ 公开下载开关 (Qoder 原生安装器) ----------

async def _make_published_asset(code: str, status: str = "published") -> int:
    from app.db.session import AsyncSessionLocal
    from app.models.asset import Asset

    async with AsyncSessionLocal() as s:
        a = Asset(code=code, name=code, kind="plugin", publish_status=status, git_path="")
        s.add(a)
        await s.commit()
        await s.refresh(a)
        return a.id


async def test_download_requires_login_by_default(client):
    """默认: 未登录下载 → 401 (marketplace.public_download 默认关)."""
    await _make_published_asset("dml-pub")
    r = await client.get("/api/v1/assets/dml-pub/versions/0.1.0/download")
    assert r.status_code == 401, r.text


async def test_public_download_allows_anonymous_when_enabled(client, admin_user):
    """开关打开: 未登录也能下**已上架**资产的包."""
    await _make_published_asset("dml-pub2")
    from tests.conftest import set_setting

    await set_setting("marketplace.public_download", "true")
    try:
        r = await client.get("/api/v1/assets/dml-pub2/versions/0.1.0/download")
        # 资产没有真实文件 → 404 (而不是 401) = 鉴权已经放过去了
        assert r.status_code == 404, r.text
    finally:
        await set_setting("marketplace.public_download", "false")


async def test_public_download_still_requires_login_for_unpublished(client):
    """开关打开也**只对已上架**的资产生效 —— 待审核的照样 404."""
    await _make_published_asset("dml-pending", status="pending")
    from tests.conftest import set_setting

    await set_setting("marketplace.public_download", "true")
    try:
        r = await client.get("/api/v1/assets/dml-pending/versions/0.1.0/download")
        assert r.status_code == 404, r.text
    finally:
        await set_setting("marketplace.public_download", "false")


async def test_public_download_setting_is_admin_only(client, stranger_user):
    """这是**对外暴露策略** —— 非管理员看不到也改不了."""
    r = await client.get(f"{SETTINGS}/schema", headers={
        "Authorization": f"Bearer {stranger_user['token']}"
    })
    assert "marketplace.public_download" not in _schema_keys(r.json())

    r2 = await client.put(f"{SETTINGS}/marketplace.public_download", headers={
        "Authorization": f"Bearer {stranger_user['token']}"
    }, json={"value": "true"})
    assert r2.status_code == 403, r2.text
