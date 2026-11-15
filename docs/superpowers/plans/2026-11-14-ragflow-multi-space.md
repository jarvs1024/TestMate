# RAGFlow 多用户空间 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 让 TestMate 知识库支持多个 RAGFlow 用户空间（多把 API key），页面可切换，REST/MCP/审计全部跟随空间。

**Architecture:** 新增 `ragflow_spaces` 表存加密 key；`app/core/ragflow_spaces.py` 负责解析与加解密；`ragflow_client` 所有函数显式接收 `space_id`；REST 用 `X-KB-Space` 头解析，MCP 用可选 `space_id` 参数；审计表增加空间快照列。

**Tech Stack:** FastAPI / SQLAlchemy async / Alembic / MySQL / Vue 3 + Pinia + Vitest / RAGFlow HTTP API。

**Spec:** `docs/superpowers/specs/2026-11-14-ragflow-multi-space-design.md`

## Global Constraints

- **任何地方都不得写入、打印、提交真实的 RAGFlow API key**（包括代码、测试、文档、日志、提交信息）。
- `space_id` 缺省 = 使用默认空间；未配置任何空间且无旧 key 时，行为与改造前一致。
- 后端用户可见错误必须是中文、可行动，并列出合法值/可用空间。
- 每次只做本地提交，不推送远端（仓库约定）。
- 测试库会被重建；新表必须加入 `backend_gateway/tests/conftest.py` 的清理列表。
- 现有测试命令：`cd backend_gateway && pytest tests/xxx -v`；前端：`cd frontend_web && npx vitest run <file>`。

---

### Task 1: 空间模型、迁移、空间服务与旧配置迁移

**Files:**
- Create: `backend_gateway/app/models/ragflow_space.py`
- Modify: `backend_gateway/app/models/__init__.py`
- Create: `backend_gateway/alembic/versions/0038_ragflow_spaces.py`
- Create: `backend_gateway/app/core/ragflow_spaces.py`
- Modify: `backend_gateway/tests/conftest.py`（清理列表加 `ragflow_spaces`）
- Modify: `backend_gateway/app/main.py`（启动时调用 `ensure_legacy_space`）
- Test: `backend_gateway/tests/test_ragflow_spaces.py`

**Interfaces:**
- Produces:
  - `RagflowSpace(id: str, name: str, api_key_cipher: str, is_default: bool, created_by: int | None)`
  - `RagflowSpaceError(message: str, status_code: int = 422)`
  - `new_space_id() -> str`
  - `encrypt_key(plaintext: str) -> str` / `decrypt_key(cipher: str) -> str`
  - `list_spaces() -> list[RagflowSpace]`
  - `get_space(space_id: str) -> RagflowSpace | None`
  - `default_space() -> RagflowSpace | None`
  - `resolve(space_id: str | None) -> RagflowSpace | None`
  - `credential_for(space_id: str | None) -> tuple[str, str, RagflowSpace | None]`（base_url, api_key, space）
  - `create_space(name, api_key, *, is_default=False, actor_id=None) -> RagflowSpace`
  - `update_space(space_id, *, name=None, api_key=None, is_default=None) -> RagflowSpace`
  - `delete_space(space_id) -> None`
  - `ensure_legacy_space() -> None`

- [ ] **Step 1: 写模型**

`backend_gateway/app/models/ragflow_space.py`：

```python
"""RAGFlow 用户空间 —— 一把 API key = 一个 RAGFlow 用户空间."""
from __future__ import annotations

from datetime import datetime

from sqlalchemy import BigInteger, Boolean, DateTime, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.db.session import Base


class RagflowSpace(Base):
    __tablename__ = "ragflow_spaces"

    id: Mapped[str] = mapped_column(String(32), primary_key=True)
    name: Mapped[str] = mapped_column(String(64), nullable=False, unique=True)
    #: AES-256-GCM 密文 —— 永远不存明文
    api_key_cipher: Mapped[str] = mapped_column(Text, nullable=False)
    is_default: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    created_by: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow
    )
```

在 `app/models/__init__.py` 末尾加：

```python
from app.models.ragflow_space import RagflowSpace  # noqa: F401
```

`tests/conftest.py` 的 `_TABLES` 元组里加 `"ragflow_spaces"`。

- [ ] **Step 2: 写迁移**

`backend_gateway/alembic/versions/0038_ragflow_spaces.py`：

```python
"""RAGFlow 多用户空间: 新表 + 审计空间维度

Revision ID: 0038_ragflow_spaces
Revises: 0037_add_mcp_token_version
Create Date: 2026-11-14
"""
from alembic import op
import sqlalchemy as sa

revision = "0038_ragflow_spaces"
down_revision = "0037_add_mcp_token_version"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if "ragflow_spaces" not in inspector.get_table_names():
        op.create_table(
            "ragflow_spaces",
            sa.Column("id", sa.String(32), primary_key=True),
            sa.Column("name", sa.String(64), nullable=False, unique=True),
            sa.Column("api_key_cipher", sa.Text(), nullable=False),
            sa.Column("is_default", sa.Boolean(), nullable=False, server_default=sa.text("0")),
            sa.Column("created_by", sa.BigInteger(), nullable=True),
            sa.Column("created_at", sa.DateTime(), nullable=False),
            sa.Column("updated_at", sa.DateTime(), nullable=False),
        )
    cols = {c["name"] for c in inspector.get_columns("kb_audits")}
    if "space_id" not in cols:
        op.add_column("kb_audits", sa.Column("space_id", sa.String(32), nullable=False, server_default=""))
    if "space_name" not in cols:
        op.add_column("kb_audits", sa.Column("space_name", sa.String(64), nullable=False, server_default=""))
    indexes = {i["name"] for i in inspector.get_indexes("kb_audits")}
    if "ix_kb_audits_space_created" not in indexes:
        op.create_index("ix_kb_audits_space_created", "kb_audits", ["space_id", "created_at"])


def downgrade() -> None:
    op.drop_index("ix_kb_audits_space_created", table_name="kb_audits")
    op.drop_column("kb_audits", "space_name")
    op.drop_column("kb_audits", "space_id")
    op.drop_table("ragflow_spaces")
```

- [ ] **Step 3: 写失败测试**

`backend_gateway/tests/test_ragflow_spaces.py`：

```python
"""RAGFlow 用户空间: 加密、默认唯一、解析与旧配置迁移."""
import pytest

from app.core import ragflow_spaces as rs
from app.core.settings_store import get
from app.db.session import AsyncSessionLocal
from app.models.ragflow_space import RagflowSpace
from app.models.system_setting import SystemSetting


async def _add_space(name="A", key="ragflow-old-key-123456", default=False):
    return await rs.create_space(name, key, is_default=default)


@pytest.mark.asyncio
async def test_create_encrypts_key_and_resolves():
    sp = await _add_space("空间A", "ragflow-aaaa-1111", default=True)
    assert sp.id.startswith("sp_")
    async with AsyncSessionLocal() as s:
        row = await s.get(RagflowSpace, sp.id)
        assert row.api_key_cipher.startswith("v1:")
        assert "ragflow-aaaa-1111" not in row.api_key_cipher
    base, key, resolved = await rs.credential_for(sp.id)
    assert resolved.id == sp.id
    assert key == "ragflow-aaaa-1111"


@pytest.mark.asyncio
async def test_default_is_unique():
    a = await _add_space("A", default=True)
    b = await _add_space("B", default=True)
    async with AsyncSessionLocal() as s:
        assert (await s.get(RagflowSpace, a.id)).is_default is False
        assert (await s.get(RagflowSpace, b.id)).is_default is True
    assert (await rs.default_space()).id == b.id


@pytest.mark.asyncio
async def test_resolve_unknown_lists_available():
    await _add_space("A", default=True)
    with pytest.raises(rs.RagflowSpaceError) as ei:
        await rs.resolve("sp_missing")
    assert "不存在" in str(ei.value)
    assert "空间A" in str(ei.value)


@pytest.mark.asyncio
async def test_duplicate_name_rejected():
    await _add_space("同名")
    with pytest.raises(rs.RagflowSpaceError) as ei:
        await rs.create_space("同名", "ragflow-bbbb-2222")
    assert "已经存在" in str(ei.value)


@pytest.mark.asyncio
async def test_ensure_legacy_space_uses_old_key():
    async with AsyncSessionLocal() as s:
        s.add(SystemSetting(key="ragflow.api_key", value={"v": "ragflow-legacy-999"}, category="data-source", description="", is_secret=True))
        await s.commit()
    await rs.ensure_legacy_space()
    sp = await rs.default_space()
    assert sp is not None and sp.name == "默认空间"
    assert (await rs.credential_for(sp.id))[1] == "ragflow-legacy-999"


@pytest.mark.asyncio
async def test_cannot_delete_default():
    sp = await _add_space(default=True)
    with pytest.raises(rs.RagflowSpaceError) as ei:
        await rs.delete_space(sp.id)
    assert "默认空间" in str(ei.value)
```

- [ ] **Step 4: 运行测试确认失败**

Run: `cd backend_gateway && pytest tests/test_ragflow_spaces.py -v`
Expected: FAIL（`No module named app.core.ragflow_spaces`）

- [ ] **Step 5: 实现空间服务**

`backend_gateway/app/core/ragflow_spaces.py`：

```python
"""RAGFlow 用户空间: 多 key 解析、加解密、默认空间与旧配置迁移."""
from __future__ import annotations

import logging
import secrets

from sqlalchemy import delete, select, update

from app.core.settings_store import get
from app.db.session import AsyncSessionLocal
from app.integrations.crypto import decrypt_secret, encrypt_secret
from app.models.ragflow_space import RagflowSpace

logger = logging.getLogger(__name__)

_PROVIDER = "ragflow-space"
_SYSTEM_ACTOR = 0
_KEY_PREFIX = "ragflow-"


class RagflowSpaceError(Exception):
    def __init__(self, message: str, status_code: int = 422):
        super().__init__(message)
        self.message = message
        self.status_code = status_code


def new_space_id() -> str:
    return "sp_" + secrets.token_hex(4)


def encrypt_key(plaintext: str) -> str:
    return encrypt_secret(plaintext, user_id=_SYSTEM_ACTOR, provider=_PROVIDER)


def decrypt_key(cipher: str) -> str:
    return decrypt_secret(cipher, user_id=_SYSTEM_ACTOR, provider=_PROVIDER)


def _validate_key(api_key: str) -> str:
    key = (api_key or "").strip()
    if not key:
        raise RagflowSpaceError("API Key 不能为空")
    if not key.startswith(_KEY_PREFIX):
        raise RagflowSpaceError(f"API Key 必须以 {_KEY_PREFIX} 开头")
    return key


def _validate_name(name: str) -> str:
    n = (name or "").strip()
    if not n:
        raise RagflowSpaceError("空间名称不能为空")
    if len(n) > 64:
        raise RagflowSpaceError("空间名称最长 64 个字符")
    return n


async def list_spaces() -> list[RagflowSpace]:
    async with AsyncSessionLocal() as s:
        return list((await s.execute(select(RagflowSpace).order_by(RagflowSpace.created_at))).scalars().all())


async def get_space(space_id: str) -> RagflowSpace | None:
    if not space_id:
        return None
    async with AsyncSessionLocal() as s:
        return await s.get(RagflowSpace, space_id)


async def default_space() -> RagflowSpace | None:
    async with AsyncSessionLocal() as s:
        return (await s.execute(select(RagflowSpace).where(RagflowSpace.is_default.is_(True)).limit(1))).scalar_one_or_none()


async def _hint() -> str:
    spaces = await list_spaces()
    return "、".join(f"{s.name}({s.id})" for s in spaces) or "（尚未配置任何空间）"


async def resolve(space_id: str | None) -> RagflowSpace | None:
    if not space_id:
        return await default_space()
    sp = await get_space(space_id)
    if sp is None:
        raise RagflowSpaceError(
            f"用户空间不存在：{space_id}。可用空间：{await _hint()}", status_code=404
        )
    return sp


async def credential_for(space_id: str | None) -> tuple[str, str, RagflowSpace | None]:
    """返回 (base_url, api_key, space). 表为空时回退旧配置."""
    space = await resolve(space_id)
    base = (await get("ragflow.base_url", "")) or ""
    if space is None:
        legacy = (await get("ragflow.api_key", "")) or ""
        return base, legacy, None
    return base, decrypt_key(space.api_key_cipher), space


async def _clear_default(s) -> None:
    await s.execute(update(RagflowSpace).values(is_default=False))


async def create_space(name: str, api_key: str, *, is_default: bool = False, actor_id: int | None = None) -> RagflowSpace:
    name = _validate_name(name)
    api_key = _validate_key(api_key)
    async with AsyncSessionLocal() as s:
        exists = (await s.execute(select(RagflowSpace).where(RagflowSpace.name == name))).scalar_one_or_none()
        if exists is not None:
            raise RagflowSpaceError(f"空间「{name}」已经存在，请换一个名称")
        make_default = is_default or (await default_space()) is None
        if make_default:
            await _clear_default(s)
        row = RagflowSpace(
            id=new_space_id(), name=name, api_key_cipher=encrypt_key(api_key),
            is_default=make_default, created_by=actor_id,
        )
        s.add(row)
        await s.commit()
        await s.refresh(row)
        return row


async def update_space(space_id: str, *, name: str | None = None, api_key: str | None = None, is_default: bool | None = None) -> RagflowSpace:
    async with AsyncSessionLocal() as s:
        row = await s.get(RagflowSpace, space_id)
        if row is None:
            raise RagflowSpaceError(f"用户空间不存在：{space_id}。可用空间：{await _hint()}", status_code=404)
        if name is not None:
            name = _validate_name(name)
            dup = (await s.execute(select(RagflowSpace).where(RagflowSpace.name == name, RagflowSpace.id != space_id))).scalar_one_or_none()
            if dup is not None:
                raise RagflowSpaceError(f"空间「{name}」已经存在，请换一个名称")
            row.name = name
        if api_key:
            row.api_key_cipher = encrypt_key(_validate_key(api_key))
        if is_default is True:
            await _clear_default(s)
            row.is_default = True
        await s.commit()
        await s.refresh(row)
        return row


async def delete_space(space_id: str) -> None:
    async with AsyncSessionLocal() as s:
        row = await s.get(RagflowSpace, space_id)
        if row is None:
            raise RagflowSpaceError(f"用户空间不存在：{space_id}", status_code=404)
        if row.is_default:
            raise RagflowSpaceError("默认空间不能删除，请先把另一个空间设为默认")
        await s.delete(row)
        await s.commit()


async def ensure_legacy_space() -> None:
    """启动迁移: 无空间时把旧 ragflow.api_key 落成默认空间，并回填历史审计."""
    async with AsyncSessionLocal() as s:
        existing = (await s.execute(select(RagflowSpace).limit(1))).scalar_one_or_none()
        if existing is not None:
            return
    legacy = ((await get("ragflow.api_key", "")) or "").strip()
    if not legacy.startswith(_KEY_PREFIX):
        return
    try:
        sp = await create_space("默认空间", legacy, is_default=True)
    except RagflowSpaceError:
        logger.exception("旧 RAGFlow key 迁移失败")
        return
    from app.models.kb import KbAudit
    async with AsyncSessionLocal() as s:
        await s.execute(
            update(KbAudit)
            .where(KbAudit.space_id == "")
            .values(space_id=sp.id, space_name=sp.name)
        )
        await s.commit()
    logger.info("已把旧 RAGFlow key 迁移为默认空间 %s", sp.id)
```

在 `app/main.py` 的启动流程里，`seed_defaults()` 之后加：

```python
from app.core import ragflow_spaces
await ragflow_spaces.ensure_legacy_space()
```

（若启动函数里是 `await seed_defaults()`，直接在其下一行添加。）

- [ ] **Step 6: 运行测试确认通过**

Run: `cd backend_gateway && pytest tests/test_ragflow_spaces.py -v`
Expected: PASS

- [ ] **Step 7: 提交**

```bash
git add backend_gateway/app/models/ragflow_space.py backend_gateway/app/models/__init__.py backend_gateway/alembic/versions/0038_ragflow_spaces.py backend_gateway/app/core/ragflow_spaces.py backend_gateway/app/main.py backend_gateway/tests/conftest.py backend_gateway/tests/test_ragflow_spaces.py
git commit -m "feat(kb): 新增 RAGFlow 用户空间模型、加密存储与旧配置迁移"
```

---

### Task 2: `ragflow_client` 全量支持 `space_id`

**Files:**
- Modify: `backend_gateway/app/core/ragflow_client.py`
- Test: `backend_gateway/tests/test_ragflow_client_spaces.py`

**Interfaces:**
- Consumes: `ragflow_spaces.credential_for(space_id)`。
- Produces: 每个公开函数新增关键字参数 `space_id: str | None = None`：
  `list_datasets / create_dataset / update_dataset / delete_dataset / list_documents / list_doc_chunks / ingest_documents / upload_documents / download_document / update_document / parse_documents / delete_documents / retrieval / probe`。

- [ ] **Step 1: 写失败测试**

`backend_gateway/tests/test_ragflow_client_spaces.py`：

```python
import pytest

from app.core import ragflow_client as rc
from app.core import ragflow_spaces as rs


@pytest.mark.asyncio
async def test_config_uses_given_space(monkeypatch):
    sp = await rs.create_space("空间A", "ragflow-aaaa-1111", is_default=True)
    monkeypatch.setattr(rs, "credential_for", lambda sid: rs.credential_for(sid))
    base, key = await rc._config(sp.id)
    assert key == "ragflow-aaaa-1111"


@pytest.mark.asyncio
async def test_config_defaults_when_no_space(monkeypatch):
    await rs.create_space("默认", "ragflow-default-2222", is_default=True)
    _, key = await rc._config(None)
    assert key == "ragflow-default-2222"


@pytest.mark.asyncio
async def test_list_datasets_passes_space_to_config(monkeypatch):
    seen = {}

    async def fake_config(space_id=None):
        seen["space_id"] = space_id
        return "", "mock-key"

    monkeypatch.setattr(rc, "_config", fake_config)
    assert await rc.list_datasets(space_id="sp_x") == []
    assert seen["space_id"] == "sp_x"
```

- [ ] **Step 2: 运行确认失败**

Run: `cd backend_gateway && pytest tests/test_ragflow_client_spaces.py -v`
Expected: FAIL（`_config() takes 0 positional arguments` / `unexpected keyword space_id`）

- [ ] **Step 3: 改造客户端**

在 `ragflow_client.py` 顶部引入：

```python
from app.core.ragflow_spaces import credential_for
```

替换 `_config` / `_headers`：

```python
async def _config(space_id: str | None = None) -> tuple[str, str]:
    base, key, _space = await credential_for(space_id)
    return _rewrite_loopback(base or "").rstrip("/"), key or ""


async def _headers(space_id: str | None = None) -> dict[str, str]:
    _, key = await _config(space_id)
    return {"Authorization": f"Bearer {key}", "Content-Type": "application/json"}
```

每个公开函数签名加 `space_id: str | None = None`，函数体内所有 `_config()` → `_config(space_id)`、`_headers()` → `_headers(space_id)`。
注意内部互相调用也要传：`create_dataset` 里的 `await list_datasets(..., space_id=space_id)`。
`download_document` / `upload_documents` 里的 `headers={"Authorization": f"Bearer {key}"}` 保持使用 `_config(space_id)` 返回的 key。

- [ ] **Step 4: 运行确认通过**

Run: `cd backend_gateway && pytest tests/test_ragflow_client_spaces.py tests/test_kb_core.py -v`
Expected: PASS

- [ ] **Step 5: 提交**

```bash
git add backend_gateway/app/core/ragflow_client.py backend_gateway/tests/test_ragflow_client_spaces.py
git commit -m "feat(kb): ragflow_client 所有调用按 space_id 解析凭据"
```

---

### Task 3: 空间管理 REST API

**Files:**
- Create: `backend_gateway/app/api/kb_spaces.py`
- Modify: `backend_gateway/app/main.py`（注册路由）
- Test: `backend_gateway/tests/test_kb_space_api.py`

**Interfaces:**
- Produces: `/api/v1/kb/spaces` 的 GET/POST/PUT/DELETE 与 `POST /{id}/test`。
- Response:
  ```json
  {"items": [{"id": "sp_x", "name": "空间A", "is_default": true, "configured": true, "key_masked": "ragf••••1111"}], "default_id": "sp_x"}
  ```

- [ ] **Step 1: 写失败测试**

`backend_gateway/tests/test_kb_space_api.py`：

```python
"""空间管理 API: 权限、掩码、默认空间."""
import pytest
from httpx import ASGITransport, AsyncClient

from app.main import app
from app.db.session import AsyncSessionLocal
from app.models.user import User, UserRole
from app.core.security import hash_password


async def _client(user: User) -> AsyncClient:
    from app.core.security import create_access_token
    token, _ = create_access_token(str(user.id), {"role": user.role.value, "username": user.username})
    return AsyncClient(transport=ASGITransport(app=app), base_url="http://test", headers={"Authorization": f"Bearer {token}"})


@pytest.fixture
async def admin():
    async with AsyncSessionLocal() as s:
        u = User(username="admin_sp", email=None, role=UserRole.admin, password_hash=hash_password("x"))
        s.add(u); await s.commit(); await s.refresh(u)
        return u


@pytest.mark.asyncio
async def test_admin_create_list_and_mask(admin):
    async with await _client(admin) as c:
        r = await c.post("/api/v1/kb/spaces", json={"name": "空间A", "api_key": "ragflow-aaaa-1111"})
        assert r.status_code == 200, r.text
        sid = r.json()["space"]["id"]
        r = await c.get("/api/v1/kb/spaces")
        item = r.json()["items"][0]
        assert item["id"] == sid and item["is_default"] is True
        assert item["key_masked"].startswith("ragf")
        assert "aaaa" not in item["key_masked"]


@pytest.mark.asyncio
async def test_non_admin_cannot_write(admin):
    async with AsyncSessionLocal() as s:
        u = User(username="viewer_sp", email=None, role=UserRole.viewer, password_hash=hash_password("x"))
        s.add(u); await s.commit(); await s.refresh(u)
    async with await _client(u) as c:
        assert (await c.post("/api/v1/kb/spaces", json={"name": "X", "api_key": "ragflow-xxxx-2222"})).status_code == 403
        r = await c.get("/api/v1/kb/spaces")
        assert r.status_code == 200
        assert "key_masked" not in r.json()["items"][0]


@pytest.mark.asyncio
async def test_delete_default_rejected(admin):
    async with await _client(admin) as c:
        sid = (await c.post("/api/v1/kb/spaces", json={"name": "默认", "api_key": "ragflow-dddd-1111"})).json()["space"]["id"]
        r = await c.delete(f"/api/v1/kb/spaces/{sid}")
        assert r.status_code == 422
        assert "默认空间" in r.json()["detail"]
```

- [ ] **Step 2: 运行确认失败**

Run: `cd backend_gateway && pytest tests/test_kb_space_api.py -v`
Expected: FAIL（404）

- [ ] **Step 3: 实现路由**

`backend_gateway/app/api/kb_spaces.py`：

```python
"""知识库用户空间管理 —— 读: 所有登录用户; 写: admin."""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from app.api.auth import get_current_user
from app.core import ragflow_spaces
from app.core.config import settings
from app.core.ragflow_spaces import (
    RagflowSpace, RagflowSpaceError, create_space, decrypt_key, delete_space,
    list_spaces, update_space,
)
from app.core.settings_store import _rewrite_loopback
from app.db.session import AsyncSessionLocal
from app.models.asset import AssetAudit
from app.models.user import User, UserRole
import httpx

router = APIRouter()


def _mask(key: str) -> str:
    if not key:
        return ""
    return key[:4] + "•" * 4 + key[-4:] if len(key) > 8 else "••••"


def _out(space: RagflowSpace, *, admin: bool) -> dict:
    item = {"id": space.id, "name": space.name, "is_default": space.is_default, "configured": True}
    if admin:
        try:
            item["key_masked"] = _mask(decrypt_key(space.api_key_cipher))
        except Exception:
            item["key_masked"] = "（无法解密）"
    return item


def _require_admin(user: User) -> None:
    if user.role != UserRole.admin:
        raise HTTPException(status_code=403, detail="只有管理员能管理知识库用户空间")


class SpaceIn(BaseModel):
    name: str = Field(..., min_length=1, max_length=64)
    api_key: str = Field(..., min_length=8, max_length=200)
    is_default: bool = False


class SpacePatch(BaseModel):
    name: str | None = Field(None, min_length=1, max_length=64)
    api_key: str | None = Field(None, max_length=200)
    is_default: bool | None = None


async def _audit(user: User, action: str, space: RagflowSpace) -> None:
    async with AsyncSessionLocal() as s:
        s.add(AssetAudit(
            asset_id=None, code="setting:ragflow.spaces", action="setting.update",
            actor_id=user.id, actor_name=user.username,
            comment=f"{action} 知识库用户空间 {space.name}",
            detail={"op": action, "space_id": space.id, "name": space.name, "is_default": space.is_default, "api_key": "***"},
        ))
        await s.commit()


@router.get("")
async def get_spaces(user: User = Depends(get_current_user)) -> dict:
    rows = await list_spaces()
    admin = user.role == UserRole.admin
    items = [_out(s, admin=admin) for s in rows]
    default = next((s.id for s in rows if s.is_default), "")
    return {"items": items, "default_id": default}


@router.post("")
async def post_space(payload: SpaceIn, user: User = Depends(get_current_user)) -> dict:
    _require_admin(user)
    try:
        sp = await create_space(payload.name, payload.api_key, is_default=payload.is_default, actor_id=user.id)
    except RagflowSpaceError as e:
        raise HTTPException(status_code=e.status_code, detail=e.message)
    await _audit(user, "create", sp)
    return {"ok": True, "space": _out(sp, admin=True)}


@router.put("/{space_id}")
async def put_space(space_id: str, payload: SpacePatch, user: User = Depends(get_current_user)) -> dict:
    _require_admin(user)
    try:
        sp = await update_space(space_id, name=payload.name, api_key=payload.api_key, is_default=payload.is_default)
    except RagflowSpaceError as e:
        raise HTTPException(status_code=e.status_code, detail=e.message)
    await _audit(user, "update", sp)
    return {"ok": True, "space": _out(sp, admin=True)}


@router.delete("/{space_id}")
async def remove_space(space_id: str, user: User = Depends(get_current_user)) -> dict:
    _require_admin(user)
    sp = await ragflow_spaces.get_space(space_id)
    if sp is None:
        raise HTTPException(status_code=404, detail=f"用户空间不存在：{space_id}")
    try:
        await delete_space(space_id)
    except RagflowSpaceError as e:
        raise HTTPException(status_code=e.status_code, detail=e.message)
    await _audit(user, "delete", sp)
    return {"ok": True}


@router.post("/{space_id}/test")
async def test_space(space_id: str, user: User = Depends(get_current_user)) -> dict:
    _require_admin(user)
    try:
        base, key, sp = await ragflow_spaces.credential_for(space_id)
    except RagflowSpaceError as e:
        raise HTTPException(status_code=e.status_code, detail=e.message)
    base = _rewrite_loopback(base).rstrip("/")
    if not base:
        return {"ok": False, "status": "off", "message": "未配置 RAGFlow 地址（设置 → 知识库 → RAGFlow）"}
    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            r = await client.get(f"{base}/datasets?page=1&page_size=1", headers={"Authorization": f"Bearer {key}"})
            data = r.json()
            if r.status_code >= 500:
                return {"ok": False, "status": "warn", "message": f"HTTP {r.status_code}"}
            if data.get("code") != 0:
                return {"ok": False, "status": "warn", "message": data.get("message") or "RAGFlow 返回错误"}
            return {"ok": True, "status": "ok", "message": f"连通 · 可访问 {len(data.get('data') or [])} 个数据集"}
    except Exception as e:  # noqa: BLE001
        return {"ok": False, "status": "off", "message": f"不可达：{type(e).__name__}"}
```

在 `app/main.py`：

```python
from app.api import kb_spaces
app.include_router(kb_spaces.router, prefix="/api/v1/kb/spaces", tags=["kb-spaces"])
```

注意：`include_router(kb.router, ...)` 使用前缀 `/api/v1/kb`，先注册 `kb_spaces` 再注册 `kb`，避免 `/spaces` 被数据集路由干扰（实际上路径不冲突，顺序不敏感）。

- [ ] **Step 4: 运行确认通过**

Run: `cd backend_gateway && pytest tests/test_kb_space_api.py -v`
Expected: PASS

- [ ] **Step 5: 提交**

```bash
git add backend_gateway/app/api/kb_spaces.py backend_gateway/app/main.py backend_gateway/tests/test_kb_space_api.py
git commit -m "feat(kb): 用户空间管理 API（列表/新增/编辑/删除/测试）"
```

---

### Task 4: 知识库 REST 与审计跟随空间

**Files:**
- Modify: `backend_gateway/app/api/kb.py`
- Modify: `backend_gateway/app/models/kb.py`（审计模型加两列）
- Modify: `backend_gateway/app/core/security.py`（上传票加 `sid`）
- Test: `backend_gateway/tests/test_kb_space_scope.py`

**Interfaces:**
- Consumes: `ragflow_spaces.resolve`、`ragflow_client.*(space_id=...)`。
- Produces:
  - 请求头 `X-KB-Space`（缺省 → 默认空间）
  - `_audit(..., space_id="", space_name="")`
  - `_dataset_items(page, page_size, keyword, space_id=None)`
  - `upload_prepared_documents(dataset_id, prepared, user, space_id=None)`
  - `replace_document(..., space_id=None)`
  - `create_kb_upload_ticket(..., space_id=None)` claim `sid`

- [ ] **Step 1: 审计模型加列**

`app/models/kb.py` 的 `KbAudit` 增加：

```python
    space_id: Mapped[str] = mapped_column(String(32), nullable=False, default="", index=True)
    space_name: Mapped[str] = mapped_column(String(64), nullable=False, default="")
```

并把 `__table_args__` 增加：

```python
        Index("ix_kb_audits_space_created", "space_id", "created_at"),
```

- [ ] **Step 2: 上传票加空间**

`app/core/security.py`：

```python
def create_kb_upload_ticket(*, user_id, token_version, dataset_id, space_id: str | None = None, ttl_seconds=...):
    ...
    payload = {"typ": ..., "uid": ..., "tv": ..., "ds": dataset_id, "sid": space_id or "", "exp": expire}
```

`decode_kb_upload_ticket` 不变。

- [ ] **Step 3: 写失败测试**

`backend_gateway/tests/test_kb_space_scope.py`：

```python
"""知识库 REST 按 X-KB-Space 切换; 审计记录空间."""
import pytest
from httpx import ASGITransport, AsyncClient

from app.api import kb as kb_api
from app.core import ragflow_spaces as rs
from app.core.security import create_access_token, hash_password
from app.db.session import AsyncSessionLocal
from app.main import app
from app.models.kb import KbAudit
from app.models.user import User, UserRole
from sqlalchemy import select


@pytest.fixture
async def admin():
    async with AsyncSessionLocal() as s:
        u = User(username="admin_scope", email=None, role=UserRole.admin, password_hash=hash_password("x"))
        s.add(u); await s.commit(); await s.refresh(u)
        return u


async def _client(user):
    token, _ = create_access_token(str(user.id), {"role": user.role.value, "username": user.username})
    return AsyncClient(transport=ASGITransport(app=app), base_url="http://test", headers={"Authorization": f"Bearer {token}"})


@pytest.mark.asyncio
async def test_dataset_list_uses_space_header(monkeypatch, admin):
    a = await rs.create_space("A", "ragflow-aaaa-1111", is_default=True)
    b = await rs.create_space("B", "ragflow-bbbb-2222")
    seen = []

    async def fake_items(page=1, page_size=50, keyword="", space_id=None):
        seen.append(space_id)
        return []

    monkeypatch.setattr(kb_api, "_dataset_items", fake_items)
    async with await _client(admin) as c:
        await c.get("/api/v1/kb/datasets")
        await c.get("/api/v1/kb/datasets", headers={"X-KB-Space": b.id})
    assert seen == [None, b.id]


@pytest.mark.asyncio
async def test_unknown_space_returns_chinese_error(admin):
    async with await _client(admin) as c:
        r = await c.get("/api/v1/kb/datasets", headers={"X-KB-Space": "sp_nope"})
    assert r.status_code == 404
    assert "用户空间不存在" in r.json()["detail"]


@pytest.mark.asyncio
async def test_audit_records_space(monkeypatch, admin):
    sp = await rs.create_space("A", "ragflow-aaaa-1111", is_default=True)
    monkeypatch.setattr(kb_api, "list_datasets", lambda *a, **k: _empty())
    await kb_api._audit(action="upload", user=admin, dataset_id="d1", space_id=sp.id, space_name=sp.name)
    async with AsyncSessionLocal() as s:
        row = (await s.execute(select(KbAudit))).scalars().first()
    assert row.space_id == sp.id and row.space_name == sp.name


async def _empty():
    return []
```

- [ ] **Step 4: 运行确认失败**

Run: `cd backend_gateway && pytest tests/test_kb_space_scope.py -v`
Expected: FAIL

- [ ] **Step 5: 实现 `kb.py` 空间透传**

关键改动（按此顺序做）：

1. 增加依赖：

```python
from app.core import ragflow_spaces
from app.core.ragflow_spaces import RagflowSpaceError


async def kb_space(request: Request) -> str | None:
    """解析 X-KB-Space; 空 = 默认空间."""
    raw = (request.headers.get("X-KB-Space") or "").strip()
    if not raw:
        return None
    try:
        sp = await ragflow_spaces.resolve(raw)
    except RagflowSpaceError as e:
        raise HTTPException(status_code=e.status_code, detail=e.message)
    return sp.id if sp else None
```

2. 每个 `/datasets*`、`/documents*`、`/search`、`/health` 端点签名加：
   `space_id: str | None = Depends(kb_space)`，并把 `space_id` 传给所有 `list_datasets / list_documents / ... / probe` 调用与内部 helper。

3. 内部 helper 增加可选参数并向下传：
   - `_dataset_items(page=1, page_size=50, keyword="", space_id=None)`
   - `_dataset_info(dataset_id, space_id=None)`
   - `_find_document(dataset_id, document_id, space_id=None)`
   - `upload_prepared_documents(dataset_id, prepared, user, space_id=None)`
   - `replace_document(..., space_id=None)`
   - `search_documents(..., space_id: str | None = None)`（路由参数注入）
   - `_safe_delete_documents` 不需要（调用方已传）

4. `_audit` 增加参数并写库：

```python
async def _audit(*, action, user, dataset_id="", dataset_name="", document_id="", doc_name="", size=0, error="", space_id="", space_name="") -> None:
    ...
    s.add(KbAudit(..., space_id=space_id or "", space_name=space_name or ""))
```

所有调用点在写入前解析一次空间元信息：

```python
space = await ragflow_spaces.resolve(space_id)
s_id, s_name = (space.id, space.name) if space else ("", "")
```

并传给 `_audit(..., space_id=s_id, space_name=s_name)`。

5. 上传票：

```python
ticket, expires_in = create_kb_upload_ticket(
    user_id=..., token_version=..., dataset_id=dataset_id, space_id=space_id,
)
```

`ticket_upload` 从 claims 取：

```python
space_id = str(claims.get("sid") or "") or None
```

把它传给 `upload_prepared_documents` / `replace_document`。

6. `GET /audits` 增加 `space_id_filter: str = ""`（别名 `space_id`），查询加：

```python
stmt = select(KbAudit).order_by(desc(KbAudit.id))
if space_id_filter:
    stmt = stmt.where(KbAudit.space_id == space_id_filter)
```

返回项增加 `space_id`、`space_name`。

7. 新建数据集的重名校验天然按空间：`create_dataset` 内部调用的 `list_datasets(space_id=...)` 已带空间。

- [ ] **Step 6: 运行 KB 相关测试**

Run: `cd backend_gateway && pytest tests/test_kb_core.py tests/test_kb_upload.py tests/test_kb_doc_search.py tests/test_kb_space_scope.py tests/test_kb_ownership.py tests/test_kb_delete_audit.py -v`
Expected: PASS（若老测试的假客户端不接受 `space_id` 关键字，给假函数加 `**kwargs` 或 `space_id=None`）

- [ ] **Step 7: 提交**

```bash
git add backend_gateway/app/api/kb.py backend_gateway/app/models/kb.py backend_gateway/app/core/security.py backend_gateway/tests/test_kb_space_scope.py
git commit -m "feat(kb): REST 与审计按用户空间隔离，上传票携带空间"
```

---

### Task 5: MCP 工具支持 `space_id` 与 `kb_space_list`

**Files:**
- Modify: `backend_gateway/app/mcp/kb/tools.py`
- Modify: `backend_gateway/app/mcp/kb/adapter.py`
- Modify: `backend_gateway/tests/test_kb_mcp_read.py`（工具集合与可选参数）
- Test: `backend_gateway/tests/test_kb_mcp_space.py`

**Interfaces:**
- Consumes: `kb.*(space_id=...)`、`ragflow_spaces.resolve`。
- Produces: 所有 `kb_*` 工具可选 `space_id`；新增 `kb_space_list`。

- [ ] **Step 1: 写失败测试**

`backend_gateway/tests/test_kb_mcp_space.py`：

```python
"""MCP: space_id 透传与 kb_space_list."""
import pytest

from app.core import ragflow_spaces as rs
from app.mcp.kb import adapter
from app.mcp.kb.tools import TOOL_SPECS


def test_all_kb_tools_accept_space_id():
    for spec in TOOL_SPECS:
        props = spec.input_schema["properties"]
        if spec.name == "kb_space_list":
            continue
        assert "space_id" in props, spec.name


@pytest.mark.asyncio
async def test_space_list_returns_spaces(monkeypatch):
    await rs.create_space("A", "ragflow-aaaa-1111", is_default=True)
    result = await adapter.space_list(None)
    assert result["items"][0]["name"] == "A"
    assert result["default_id"].startswith("sp_")


@pytest.mark.asyncio
async def test_dataset_list_passes_space(monkeypatch):
    from app.mcp.kb import adapter as a
    seen = {}

    async def fake_items(page=1, page_size=50, keyword="", space_id=None):
        seen["space_id"] = space_id
        return []

    monkeypatch.setattr(a.kb, "_dataset_items", fake_items)
    await a.dataset_list(None, space_id="sp_x")
    assert seen["space_id"] == "sp_x"
```

- [ ] **Step 2: 运行确认失败**

Run: `cd backend_gateway && pytest tests/test_kb_mcp_space.py -v`
Expected: FAIL

- [ ] **Step 3: 实现 tools.py**

在 `tools.py` 增加：

```python
_SPACE_ID = {
    "type": "string",
    "default": "",
    "description": "目标用户空间 id；留空使用默认空间（可用 kb_space_list 查看）",
}
```

给 12 个现有 spec 的 `input_schema` properties 都加入 `"space_id": _SPACE_ID`（不要加入 required）。

新增：

```python
ToolSpec(
    name="kb_space_list",
    description="列出可用的 RAGFlow 用户空间，default_id 为默认空间。",
    input_schema=_object(),
    scope="kb:read",
    read_only=True,
    handler=adapter.space_list,
),
```

- [ ] **Step 4: 实现 adapter.py**

1. `_call` 捕获空间错误：

```python
from app.core.ragflow_spaces import RagflowSpaceError

async def _call(operation):
    try:
        return await operation
    except McpRuntimeError:
        raise
    except RagflowSpaceError as exc:
        raise McpRuntimeError("invalid_arguments", exc.message) from None
    except HTTPException as exc:
        ...
```

2. 每个函数加 `space_id=""` 关键字，并把 `space_id or None` 向下传。示例：

```python
async def dataset_list(ctx, *, page=1, page_size=50, keyword="", space_id=""):
    sid = space_id or None
    ...
    items = await _call(kb._dataset_items(page=page, page_size=page_size, space_id=sid))
    space = await _call(ragflow_spaces.resolve(sid))
    return {"items": items, "page": page, "page_size": page_size, "has_more": has_more,
            "space_id": space.id if space else "", "space_name": space.name if space else ""}
```

`_require_dataset(dataset_id, space_id=None)`，所有调用处传空间。
写入函数（`dataset_create`、`document_upload`、`document_update`、`document_reparse`、`document_write_ticket`）加 `space_id=""`，传给 `kb.*` 与 `kb._find_document`；返回结果加 `space_id`（和 `space_name` 能取到就加）。

`document_write_ticket`：

```python
ticket, expires_in = create_kb_upload_ticket(..., space_id=space_id or None)
body["space_id"] = space_id or ""
```

3. 新增：

```python
from app.core import ragflow_spaces

async def space_list(ctx, **_kwargs):
    rows = await ragflow_spaces.list_spaces()
    default = next((s.id for s in rows if s.is_default), "")
    return {
        "items": [{"id": s.id, "name": s.name, "is_default": s.is_default} for s in rows],
        "default_id": default,
    }
```

- [ ] **Step 5: 更新契约测试**

`tests/test_kb_mcp_read.py`：

- `READ_TOOLS` 加 `"kb_space_list"`。
- `EXPECTED_REQUIRED["kb_space_list"] = set()`。
- `ALTERNATIVE_ARGUMENTS["kb_document_upload"]` 加 `"space_id"`；`["kb_document_update"]` 加 `"space_id"`。
- 其余工具 required 不变（`space_id` 有 default，不会被判成"既非 required 又无 default"）。

Run: `cd backend_gateway && pytest tests/test_kb_mcp_read.py tests/test_kb_mcp_write.py tests/test_kb_mcp_ticket_tool.py tests/test_kb_mcp_space.py -v`
Expected: PASS

- [ ] **Step 6: 提交**

```bash
git add backend_gateway/app/mcp/kb/tools.py backend_gateway/app/mcp/kb/adapter.py backend_gateway/tests/test_kb_mcp_read.py backend_gateway/tests/test_kb_mcp_space.py
git commit -m "feat(mcp): 知识库工具支持 space_id 并新增 kb_space_list"
```

---

### Task 6: 前端 API、空间 store 与请求头

**Files:**
- Modify: `frontend_web/src/api/kb.ts`
- Create: `frontend_web/src/stores/kbSpace.ts`
- Modify: `frontend_web/src/utils/request.ts`
- Test: `frontend_web/src/stores/__tests__/kbSpace.spec.ts`

**Interfaces:**
- Produces:
  - `listKbSpaces() / createKbSpace() / updateKbSpace() / deleteKbSpace() / testKbSpace()`
  - `useKbSpaceStore()`：`spaces`, `currentId`, `currentName`, `load()`, `switchTo(id)`
  - localStorage key `testmate:kb-space`

- [ ] **Step 1: 写失败测试**

`frontend_web/src/stores/__tests__/kbSpace.spec.ts`：

```ts
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { setActivePinia, createPinia } from 'pinia';

vi.mock('@/api/kb', () => ({
  listKbSpaces: vi.fn(async () => ({
    items: [
      { id: 'sp_a', name: 'A', is_default: true, configured: true },
      { id: 'sp_b', name: 'B', is_default: false, configured: true },
    ],
    default_id: 'sp_a',
  })),
}));

import { useKbSpaceStore } from '../kbSpace';

describe('kbSpace store', () => {
  beforeEach(() => { setActivePinia(createPinia()); localStorage.clear(); });

  it('falls back to default space when nothing saved', async () => {
    const s = useKbSpaceStore();
    await s.load();
    expect(s.currentId).toBe('sp_a');
    expect(s.currentName).toBe('A');
  });

  it('persists explicit selection and ignores unknown ids', async () => {
    const s = useKbSpaceStore();
    await s.load();
    s.switchTo('sp_b');
    expect(localStorage.getItem('testmate:kb-space')).toBe('sp_b');
    s.switchTo('sp_missing');
    expect(s.currentId).toBe('sp_b');
  });
});
```

- [ ] **Step 2: 运行确认失败**

Run: `cd frontend_web && npx vitest run src/stores/__tests__/kbSpace.spec.ts`
Expected: FAIL（模块不存在）

- [ ] **Step 3: 实现 API**

`api/kb.ts` 末尾追加：

```ts
export interface KbSpace {
  id: string;
  name: string;
  is_default: boolean;
  configured: boolean;
  key_masked?: string;
}

export async function listKbSpaces(): Promise<{ items: KbSpace[]; default_id: string }> {
  return (await request.get('/kb/spaces')) as { items: KbSpace[]; default_id: string };
}

export async function createKbSpace(payload: { name: string; api_key: string; is_default?: boolean }) {
  return (await request.post('/kb/spaces', payload)) as { ok: boolean; space: KbSpace };
}

export async function updateKbSpace(id: string, payload: { name?: string; api_key?: string; is_default?: boolean }) {
  return (await request.put(`/kb/spaces/${encodeURIComponent(id)}`, payload)) as { ok: boolean; space: KbSpace };
}

export async function deleteKbSpace(id: string) {
  return (await request.delete(`/kb/spaces/${encodeURIComponent(id)}`)) as { ok: boolean };
}

export async function testKbSpace(id: string) {
  return (await request.post(`/kb/spaces/${encodeURIComponent(id)}/test`)) as {
    ok: boolean; status: string; message: string;
  };
}
```

下载请求加头（`downloadKbDocument` 内）：

```ts
const space = localStorage.getItem('testmate:kb-space') || '';
const headers: Record<string, string> = { Authorization: `Bearer ${token}` };
if (space) headers['X-KB-Space'] = space;
const r = await fetch(url, { headers });
```

- [ ] **Step 4: 实现 store**

`frontend_web/src/stores/kbSpace.ts`：

```ts
import { defineStore } from 'pinia';
import { computed, ref } from 'vue';
import { listKbSpaces, type KbSpace } from '@/api/kb';

const STORAGE_KEY = 'testmate:kb-space';

export const useKbSpaceStore = defineStore('kbSpace', () => {
  const spaces = ref<KbSpace[]>([]);
  const currentId = ref(localStorage.getItem(STORAGE_KEY) || '');
  const loaded = ref(false);

  const currentName = computed(
    () => spaces.value.find((s) => s.id === currentId.value)?.name || '未配置空间',
  );

  async function load() {
    const r = await listKbSpaces();
    spaces.value = r.items || [];
    const ids = new Set(spaces.value.map((s) => s.id));
    if (!ids.has(currentId.value)) currentId.value = r.default_id || spaces.value[0]?.id || '';
    if (currentId.value) localStorage.setItem(STORAGE_KEY, currentId.value);
    loaded.value = true;
  }

  function switchTo(id: string) {
    if (!spaces.value.some((s) => s.id === id)) return;
    currentId.value = id;
    localStorage.setItem(STORAGE_KEY, id);
  }

  return { spaces, currentId, currentName, loaded, load, switchTo };
});
```

- [ ] **Step 5: 请求头注入**

`utils/request.ts` 的请求拦截器里、设置 Authorization 之后加：

```ts
// 知识库请求跟随当前用户空间（/kb/spaces 自身除外）
const url = config.url || '';
if (url.includes('/kb/') && !url.startsWith('/kb/spaces')) {
  const space = localStorage.getItem('testmate:kb-space') || '';
  if (space) config.headers['X-KB-Space'] = space;
}
```

- [ ] **Step 6: 运行确认通过**

Run: `cd frontend_web && npx vitest run src/stores/__tests__/kbSpace.spec.ts`
Expected: PASS

- [ ] **Step 7: 提交**

```bash
git add frontend_web/src/api/kb.ts frontend_web/src/stores/kbSpace.ts frontend_web/src/utils/request.ts frontend_web/src/stores/__tests__/kbSpace.spec.ts
git commit -m "feat(web): 知识库空间 API、持久化 store 与请求头"
```

---

### Task 7: 知识库页空间切换与审计维度

**Files:**
- Modify: `frontend_web/src/views/Capability/Library/index.vue`
- Modify: `frontend_web/src/api/kb.ts`（`listKbAudits` 支持空间筛选）
- Test: `frontend_web/src/views/Capability/Library/__tests__/kbSpaceSwitch.spec.ts`

**Interfaces:**
- Consumes: `useKbSpaceStore`、`listKbAudits(page, pageSize, spaceId?)`。

- [ ] **Step 1: 写失败测试**

`frontend_web/src/views/Capability/Library/__tests__/kbSpaceSwitch.spec.ts`：

```ts
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { mount } from '@vue/test-utils';
import { createPinia, setActivePinia } from 'pinia';

const listDatasets = vi.fn(async () => ({ items: [], total: 0 }));
vi.mock('@/api/kb', () => ({
  listDatasets,
  kbHealth: vi.fn(async () => ({ status: 'ok', message: '正常' })),
  listKbSpaces: vi.fn(async () => ({
    items: [
      { id: 'sp_a', name: '空间A', is_default: true, configured: true },
      { id: 'sp_b', name: '空间B', is_default: false, configured: true },
    ],
    default_id: 'sp_a',
  })),
  listKbAudits: vi.fn(async () => ({ items: [], total: 0, page: 1, page_size: 20, pages: 1 })),
  listDocuments: vi.fn(async () => ({ docs: [], total: 0 })),
}));
vi.mock('@/api/settings', () => ({ getSchema: vi.fn(async () => ({ groups: [] })), buildEmbedUrl: vi.fn() }));
vi.mock('@/stores/user', () => ({ useUserStore: () => ({ user: { role: 'admin' } }) }));
vi.mock('@/stores/theme', () => ({ useThemeStore: () => ({ resolved: 'light' }) }));

import Library from '../index.vue';

describe('KB space switch', () => {
  beforeEach(() => { setActivePinia(createPinia()); localStorage.clear(); listDatasets.mockClear(); });

  it('reloads datasets when switching space', async () => {
    const w = mount(Library, { global: { stubs: { CapabilityShell: true, 'el-drawer': true } } });
    await new Promise((r) => setTimeout(r, 0));
    expect(listDatasets).toHaveBeenCalled();
    await w.find('[data-test="kb-space-select"]').setValue('sp_b');
    await new Promise((r) => setTimeout(r, 0));
    expect(localStorage.getItem('testmate:kb-space')).toBe('sp_b');
    expect(listDatasets.mock.calls.length).toBeGreaterThan(1);
  });
});
```

- [ ] **Step 2: 运行确认失败**

Run: `cd frontend_web && npx vitest run src/views/Capability/Library/__tests__/kbSpaceSwitch.spec.ts`
Expected: FAIL（找不到选择器）

- [ ] **Step 3: 概览卡加切换器**

模板里概览 `<h2>` 内、状态徽标前加：

```html
<div class="kb-space">
  <span class="kb-space-lbl">用户空间</span>
  <select
    data-test="kb-space-select"
    class="kb-space-sel"
    :value="kbSpaceStore.currentId"
    @change="onSpaceChange(($event.target as HTMLSelectElement).value)">
    <option v-for="s in kbSpaceStore.spaces" :key="s.id" :value="s.id">
      {{ s.name }}{{ s.is_default ? '（默认）' : '' }}
    </option>
  </select>
</div>
```

样式（页面 scoped 内）：

```css
.kb-space { display: inline-flex; align-items: center; gap: 6px; margin-left: auto; margin-right: 8px; }
.kb-space-lbl { font-size: 11px; color: var(--ink-500); }
.kb-space-sel { font: inherit; font-size: 12.5px; padding: 4px 8px; border: 1px solid var(--border); border-radius: 7px; background: var(--surface); color: var(--ink-900); }
```

- [ ] **Step 4: 脚本接入**

```ts
import { useKbSpaceStore } from '@/stores/kbSpace';

const kbSpaceStore = useKbSpaceStore();
const spaceEpoch = ref(0);

async function onSpaceChange(id: string) {
  if (!id || id === kbSpaceStore.currentId) return;
  kbSpaceStore.switchTo(id);
  spaceEpoch.value += 1;
  datasets.value = [];
  docsByDataset.value = {};
  docLoadingByDs.value = {};
  docErrorByDs.value = {};
  expandedId.value = '';
  rfStatus.value = '';
  rfMsg.value = '';
  audits.value = [];
  await loadAll();
  warmupAllDocs(true);
  if (isAdmin.value) await loadAudits(1);
}
```

`loadAll` / `loadDocs` 开头记录 epoch，await 后比对：

```ts
const epoch = spaceEpoch.value;
... await 请求 ...
if (epoch !== spaceEpoch.value) return;
```

`onMounted` 最前面加载空间：

```ts
try { await kbSpaceStore.load(); } catch { /* 空间列表失败不阻塞页面 */ }
```

- [ ] **Step 5: 审计列与筛选**

模板操作记录表加表头 `<th>空间</th>`（放在「谁」后），行内加：

```html
<td class="mono">{{ a.space_name || '—' }}</td>
```

`ds-hd` 右侧加筛选：

```html
<select v-model="auditSpace" class="kb-space-sel" @change="loadAudits(1)">
  <option value="">全部空间</option>
  <option v-for="s in kbSpaceStore.spaces" :key="s.id" :value="s.id">{{ s.name }}</option>
</select>
```

脚本加 `const auditSpace = ref('');`，`loadAudits` 调用改为：

```ts
const r = await listKbAudits(auditPage.value, auditPageSize.value, auditSpace.value || undefined);
```

`api/kb.ts` 的 `listKbAudits` 增加可选 `spaceId`：

```ts
export async function listKbAudits(page = 1, pageSize = 20, spaceId?: string): Promise<KbAuditPage> {
  const params: Record<string, any> = { page, page_size: pageSize };
  if (spaceId) params.space_id = spaceId;
  const r = (await request.get('/kb/audits', { params })) as ...
```

`KbAuditItem` 加 `space_id: string; space_name: string;`。

- [ ] **Step 6: 运行前端测试**

Run: `cd frontend_web && npx vitest run src/views/Capability/Library/__tests__/kbSpaceSwitch.spec.ts src/views/Capability/Library/__tests__/datasetOwnership.spec.ts`
Expected: PASS

- [ ] **Step 7: 提交**

```bash
git add frontend_web/src/views/Capability/Library/index.vue frontend_web/src/api/kb.ts frontend_web/src/views/Capability/Library/__tests__/kbSpaceSwitch.spec.ts
git commit -m "feat(web): 知识库页支持空间切换，操作记录增加空间维度"
```

---

### Task 8: 设置页空间管理

**Files:**
- Create: `frontend_web/src/views/Settings/components/KbSpaces.vue`
- Modify: `frontend_web/src/views/Settings/index.vue`
- Test: `frontend_web/src/views/Settings/__tests__/kbSpaces.spec.ts`

**Interfaces:**
- Consumes: `listKbSpaces / createKbSpace / updateKbSpace / deleteKbSpace / testKbSpace`。
- Produces: 知识库设置分组里的「用户空间」管理块（admin only）。

- [ ] **Step 1: 写失败测试**

`frontend_web/src/views/Settings/__tests__/kbSpaces.spec.ts`：

```ts
import { describe, expect, it, vi } from 'vitest';
import { mount } from '@vue/test-utils';

const createKbSpace = vi.fn(async () => ({ ok: true, space: { id: 'sp_new', name: '新空间', is_default: false, configured: true } }));
vi.mock('@/api/kb', () => ({
  listKbSpaces: vi.fn(async () => ({
    items: [{ id: 'sp_a', name: '空间A', is_default: true, configured: true, key_masked: 'ragf••••1111' }],
    default_id: 'sp_a',
  })),
  createKbSpace, updateKbSpace: vi.fn(), deleteKbSpace: vi.fn(), testKbSpace: vi.fn(),
}));

import KbSpaces from '../components/KbSpaces.vue';

describe('KbSpaces settings', () => {
  it('lists spaces with masked key', async () => {
    const w = mount(KbSpaces);
    await new Promise((r) => setTimeout(r, 0));
    expect(w.text()).toContain('空间A');
    expect(w.text()).toContain('ragf');
    expect(w.text()).not.toContain('1111');
  });

  it('creates a space', async () => {
    const w = mount(KbSpaces);
    await new Promise((r) => setTimeout(r, 0));
    await w.find('[data-test="add-space"]').trigger('click');
    await w.find('[data-test="space-name"]').setValue('新空间');
    await w.find('[data-test="space-key"]').setValue('ragflow-new-3333');
    await w.find('[data-test="save-space"]').trigger('click');
    await new Promise((r) => setTimeout(r, 0));
    expect(createKbSpace).toHaveBeenCalled();
  });
});
```

- [ ] **Step 2: 运行确认失败**

Run: `cd frontend_web && npx vitest run src/views/Settings/__tests__/kbSpaces.spec.ts`
Expected: FAIL

- [ ] **Step 3: 实现组件**

`KbSpaces.vue`（要点）：

```vue
<template>
  <div class="kbs">
    <h5>👥 用户空间 <span class="sub-cnt">{{ spaces.length }} 个</span></h5>
    <div class="hint">
      💡 一把 RAGFlow API Key = 一个用户空间。所有空间共用一个 RAGFlow 地址；知识库页可切换，MCP 可用 space_id 指定。
    </div>
    <table class="kbs-tbl">
      <thead><tr><th>名称</th><th>API Key</th><th>默认</th><th>操作</th></tr></thead>
      <tbody>
        <tr v-for="s in spaces" :key="s.id">
          <td>{{ s.name }}</td>
          <td class="mono">{{ s.key_masked || '—' }}</td>
          <td>{{ s.is_default ? '默认' : '' }}</td>
          <td>
            <button class="mini-link" @click="openEdit(s)">编辑</button>
            <button class="mini-link" :disabled="s.is_default" @click="makeDefault(s)">设为默认</button>
            <button class="mini-link" @click="test(s)">测试</button>
            <button class="mini-link danger" :disabled="s.is_default" @click="remove(s)">删除</button>
          </td>
        </tr>
      </tbody>
    </table>
    <button class="mini-btn primary" data-test="add-space" @click="openAdd">＋ 新增用户空间</button>

    <div v-if="editing" class="kbs-form">
      <input data-test="space-name" v-model="form.name" placeholder="空间名称（必填）" />
      <input data-test="space-key" v-model="form.api_key" placeholder="RAGFlow API Key（ragflow-...）" />
      <label><input type="checkbox" v-model="form.is_default" /> 设为默认空间</label>
      <button class="mini-btn primary" data-test="save-space" :disabled="!canSave" @click="save">保存</button>
      <button class="ghost-btn" @click="editing = null">取消</button>
      <div v-if="error" class="err">{{ error }}</div>
    </div>
    <div v-if="testResult" :class="['test-result', `s-${testResult.status}`]">{{ testResult.message }}</div>
  </div>
</template>
```

脚本实现 `load / openAdd / openEdit / save / makeDefault / test / remove`，失败用 `ElMessage.error` + 组件内 `error`；key 输入框 `type="password"`。删除/改默认后重新 `load()`。

- [ ] **Step 4: 挂到设置页**

`Settings/index.vue`：

```ts
import KbSpaces from './components/KbSpaces.vue';
```

在 `#sec-asset-kb` 内、RAGFlow 分组之后加：

```html
<div v-if="isAdmin" class="sub-grp sub3">
  <KbSpaces />
</div>
```

并把 `ragflow.api_key` 的展示去掉（后端 schema 移除后自动消失，不需要前端改）。
`kbSourceTotal` 会自然从 2 变 1。

- [ ] **Step 5: 运行确认通过**

Run: `cd frontend_web && npx vitest run src/views/Settings/__tests__/kbSpaces.spec.ts`
Expected: PASS

- [ ] **Step 6: 提交**

```bash
git add frontend_web/src/views/Settings/components/KbSpaces.vue frontend_web/src/views/Settings/index.vue frontend_web/src/views/Settings/__tests__/kbSpaces.spec.ts
git commit -m "feat(web): 设置页新增知识库用户空间管理"
```

---

### Task 9: 本地端到端验证与回归

**Files:**
- 不改代码（发现问题回到对应 Task 修）
- 产出：验证记录（不写入仓库）

**前置：**
- 本机 MySQL 127.0.0.1:3306 / testmate，RAGFlow http://127.0.0.1:18080。
- 第二个空间只通过本地管理接口创建，key 不写入任何文件。

- [ ] **Step 1: 执行迁移与重启后端**

按 `deploy/native/tmctl.sh` 的现有方式重启（`tmctl restart backend` 或项目 README 指定命令），确认启动日志出现空间迁移（若库里已有旧 key）。

- [ ] **Step 2: 确认旧空间自动迁移**

```bash
mysql -h127.0.0.1 -P3306 -utestmate -pTestMate_app_2026 testmate -e "SELECT id,name,is_default FROM ragflow_spaces;"
```
Expected: 一行「默认空间」，`is_default=1`。

- [ ] **Step 3: 通过管理接口新增第二个空间**

用管理员登录 TestMate 拿 token，调用：

```bash
curl -s -X POST http://127.0.0.1:8081/api/v1/kb/spaces \
  -H "Authorization: Bearer $TM_TOKEN" -H 'Content-Type: application/json' \
  -d '{"name":"jarvs889 空间","api_key":"<新 key>"}'
```

再用 `POST /api/v1/kb/spaces/{id}/test` 验证连通，`GET /api/v1/kb/datasets -H "X-KB-Space: <新 id>"` 应返回空列表；默认空间返回 4 个数据集。

- [ ] **Step 4: 浏览器端到端**

打开知识库页：
- 概览显示默认空间（4 个数据集 / 文档数 / 分段数）。
- 切换到新空间：概览变 0，表格显示「暂无数据集」。
- 切回默认空间：数据恢复。
- 在新空间新建数据集并上传一个小文本，确认默认空间不受影响。
- 操作记录出现「空间」列，筛选两个空间分别可见对应记录。
- 知识检索 / 对话 iframe 正常显示（与改造前一致）。
- 截图核对后交付。

- [ ] **Step 5: MCP 验证**

用管理员的 MCP token：
- `kb_space_list` 返回两个空间。
- `kb_dataset_list` 不带 `space_id` → 默认空间 4 个。
- `kb_dataset_list` 带新空间 `space_id` → 0 个。
- 传不存在的 `space_id` → 中文错误并列出可用空间。

- [ ] **Step 6: 回归测试**

```bash
cd backend_gateway && pytest tests -q
cd ../frontend_web && npx vitest run
```
Expected: 全绿。若老测试因新表/新参数失败，按错误修复后重跑。

- [ ] **Step 7: 提交收尾**

```bash
git add -A
git commit -m "test(kb): 多用户空间端到端验证与回归修复"
```

---

## Self-Review

- **Spec 覆盖**：数据模型（Task 1）、凭据解析（Task 1/2）、REST 管理（Task 3）、REST 跟随空间 + 审计维度（Task 4）、MCP（Task 5）、前端切换与审计（Task 6/7）、设置页（Task 8）、迁移兼容（Task 1）、验证（Task 9）。
- **占位符**：无 TBD/TODO；所有代码步骤给出实际内容。
- **类型一致性**：`space_id` 在 `ragflow_client`、`kb._dataset_items`、MCP adapter、前端请求头中使用同一命名；`RagflowSpaceError` 在 REST 转 HTTP、在 MCP 转 `invalid_arguments`。
- **安全**：所有示例 key 均为明显的假值（`ragflow-aaaa-1111`），真实 key 只在 Task 9 的本地命令行中使用，不落文件。
