"""资产市场单测夹具.

三个关键点:
1. **引擎与 git 工作区都是导入期读 env** —— 所以必须在 ``import app.*`` 之前设好,
   否则测试会打到生产库/生产工作区上.
2. 跑在**独立的测试库** ``testmate_test`` 上, 绝不碰生产库.
3. git 工作区用临时目录 —— 每个用例一套, 且绝不连真实远端.
"""
from __future__ import annotations

import os
import shutil
import tempfile
from pathlib import Path

import pytest

# ===== 必须在 import app.* 之前设置 =====
_TEST_DB = os.environ.get("TESTMATE_TEST_DB", "testmate_test")
os.environ["MYSQL_DATABASE"] = _TEST_DB
os.environ["DEBUG"] = "true"
# 测试里绝对不连真实 GitLab —— 用一个一定连不上的地址
os.environ.setdefault("MARKET_GIT_REMOTE", "ssh://git@127.0.0.1:1/nonexistent.git")
os.environ.setdefault("MARKET_GIT_BRANCH", "main")
# 拉取器/worker 在测试里不启动 (ASGITransport 不跑 lifespan), 间隔也调大以防万一
os.environ.setdefault("MARKET_SYNC_INTERVAL_SECONDS", "99999")
# 每个进程一套临时工作区.
# ⚠️ 必须**强制**覆盖: 容器里 MARKET_WORKSPACE 指向真实的 /workspace (市场 git 仓库),
#    用 setdefault 会保留它 —— 测试就会往真实仓库里写文件.
_TEST_WS = tempfile.mkdtemp(prefix="tm-test-ws-")
os.environ["MARKET_WORKSPACE"] = _TEST_WS

from httpx import ASGITransport, AsyncClient  # noqa: E402
from sqlalchemy import text  # noqa: E402

from app.core.config import settings  # noqa: E402
from app.db.session import AsyncSessionLocal, Base, engine  # noqa: E402
import app.models  # noqa: E402,F401  —— 让 Base.metadata 认识所有表

# 需要清空的表 (外键顺序无关, 这里是自关联/无外键)
_TABLES = (
    "asset_audits",
    "asset_notifications",
    "asset_installs",
    "asset_jobs",
    "assets",
    "system_settings",
    "users",
)


def pytest_sessionfinish(session, exitstatus):  # noqa: ARG001
    shutil.rmtree(_TEST_WS, ignore_errors=True)


_DB_READY = False


@pytest.fixture(autouse=True)
async def _clean_tables():
    """每个用例前后都清表 —— 用例之间不许互相污染.

    建库建表在这里做 (函数级): session 级的异步夹具在 pytest-asyncio 里
    不能依赖函数级的 runner, 会 ScopeMismatch.
    """
    global _DB_READY
    import aiomysql

    if not _DB_READY:
        conn = await aiomysql.connect(
            host=settings.MYSQL_HOST,
            port=settings.MYSQL_PORT,
            user=settings.MYSQL_USER,
            password=settings.MYSQL_PASSWORD,
            autocommit=True,
        )
        try:
            async with conn.cursor() as cur:
                await cur.execute(
                    f"CREATE DATABASE IF NOT EXISTS `{_TEST_DB}` "
                    "CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci"
                )
        finally:
            conn.close()
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
        _DB_READY = True

    async with engine.begin() as conn:
        for t in _TABLES:
            await conn.execute(text(f"DELETE FROM {t}"))
    yield
    async with engine.begin() as conn:
        for t in _TABLES:
            await conn.execute(text(f"DELETE FROM {t}"))


@pytest.fixture
def ws(tmp_path, monkeypatch) -> Path:
    """一个**真实的** git 工作区 + 本地裸库当"远端".

    为什么不用假的远端: 上传/审核/上下架都会真的走 commit + push,
    远端不可达时接口会返 502, 测不出状态机. 用本地裸库当远端, 提交流程能真跑通.
    """
    import subprocess

    from app.core import git_sync

    bare = tmp_path / "remote.git"
    work = tmp_path / "ws"
    bare.mkdir(parents=True)
    work.mkdir(parents=True)

    def g(*args: str, cwd: Path = work) -> None:
        subprocess.run(["git", *args], cwd=str(cwd), check=True, capture_output=True)

    subprocess.run(
        ["git", "init", "--bare", str(bare)], check=True, capture_output=True
    )
    g("init", "-b", "main")
    g("config", "user.email", "test@testmate.local")
    g("config", "user.name", "testmate-test")
    g("remote", "add", "origin", str(bare))
    (work / "README.md").write_text("test repo\n", encoding="utf-8")
    g("add", ".")
    g("commit", "-m", "init")
    g("push", "-u", "origin", "main")

    monkeypatch.setattr(git_sync, "WORKSPACE", work)
    monkeypatch.setattr(git_sync, "LOCK_FILE", tmp_path / "ws.lock")
    git_sync.set_git_config(remote=str(bare), branch="main")
    return work


@pytest.fixture
def restore_git_config():
    """用例结束后把 git 配置还原 (别把测试值留给别的用例)."""
    from app.core import git_sync

    before = (git_sync.git_remote(), git_sync.git_branch())
    yield
    git_sync.set_git_config(remote=before[0], branch=before[1])


async def set_setting(key: str, value: str) -> None:
    """直接写设置项 (测试里免得走 HTTP)."""
    from app.core.settings_store import get
    from app.db.session import AsyncSessionLocal
    from app.models.system_setting import SystemSetting

    async with AsyncSessionLocal() as s:
        row = await s.get(SystemSetting, key)
        if row is None:
            row = SystemSetting(key=key, value={"v": value}, category="test", description="", is_secret=False)
            s.add(row)
        else:
            row.value = {"v": value}
        await s.commit()


@pytest.fixture
async def client():
    """ASGI 客户端 (不跑 lifespan → 后台 worker 不会启动)."""
    from app.main import app

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        yield c


@pytest.fixture
async def admin_user():
    """管理员账号 + token."""
    from app.core.security import create_access_token, hash_password
    from app.models.user import User, UserRole

    async with AsyncSessionLocal() as s:
        u = User(
            username="admin_t",
            password_hash=hash_password("Admin@12345"),
            role=UserRole.admin,
        )
        s.add(u)
        await s.commit()
        await s.refresh(u)
        uid, uname = u.id, u.username
    token, _ = create_access_token(uid)
    return {"id": uid, "username": uname, "token": token}


@pytest.fixture
async def publisher_user():
    """普通发布者 (tester 角色) + token."""
    from app.core.security import create_access_token, hash_password
    from app.models.user import User, UserRole

    async with AsyncSessionLocal() as s:
        u = User(
            username="publisher_t",
            password_hash=hash_password("Pub@12345"),
            role=UserRole.tester,
        )
        s.add(u)
        await s.commit()
        await s.refresh(u)
        uid, uname = u.id, u.username
    token, _ = create_access_token(uid)
    return {"id": uid, "username": uname, "token": token}


@pytest.fixture
async def stranger_user():
    """既不是管理员也不在白名单的普通用户."""
    from app.core.security import create_access_token, hash_password
    from app.models.user import User, UserRole

    async with AsyncSessionLocal() as s:
        u = User(
            username="stranger_t",
            password_hash=hash_password("Str@12345"),
            role=UserRole.viewer,
        )
        s.add(u)
        await s.commit()
        await s.refresh(u)
        uid, uname = u.id, u.username
    token, _ = create_access_token(uid)
    return {"id": uid, "username": uname, "token": token}


@pytest.fixture
def auth(admin_user):
    """默认用管理员身份 (多数用例关心的是市场本身, 不是权限)."""
    return {"Authorization": f"Bearer {admin_user['token']}"}


def make_skill_zip(path: Path, name: str = "probe", extra: dict | None = None) -> Path:
    """造一个合规的技能包 (SKILL.md)."""
    import zipfile

    path.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(path, "w") as z:
        z.writestr(
            "SKILL.md",
            f"---\nname: {name}\ndescription: 测试用技能包\n---\n\n# {name}\n\n正文\n",
        )
        for rel, content in (extra or {}).items():
            z.writestr(rel, content)
    return path


def make_plugin_zip(path: Path, name: str = "probe-plugin") -> Path:
    """造一个合规的插件包 (README.md + .qoder-plugin/plugin.json)."""
    import json
    import zipfile

    path.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(path, "w") as z:
        z.writestr("README.md", f"# {name}\n\n插件说明\n")
        z.writestr(
            ".qoder-plugin/plugin.json",
            json.dumps(
                {
                    "name": name,
                    "displayName": name,
                    "version": "1.0.0",
                    "description": "测试用插件",
                    "author": {"name": "test"},
                },
                ensure_ascii=False,
                indent=2,
            ),
        )
    return path
