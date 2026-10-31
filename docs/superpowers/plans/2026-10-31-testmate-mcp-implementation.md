# TestMate MCP Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 在现有 TestMate 后端挂载按业务域拆分的 MCP server（首个域：技能·插件），让 Qoder 通过 OAuth 2.1 授权后，用 14 个工具搜索 / 读取 / 上架 / 更新技能，且所有写操作与网页前端走**同一条链路、同一套校验**。

**Architecture:** 四层——transport（Starlette 挂载 + MCP SDK）/ 协议（FastMCP + ToolSpec 契约）/ 领域（`app/mcp/skill/`）/ 既有业务（`app/api/marketplace.py`，业务逻辑不动）。每个业务域一个独立 MCP server，端点 `/mcp/{域}`，同时提供 Streamable HTTP 与 SSE 两个入口。鉴权走 OAuth 2.1（我们自写路由以支持内网 http），授权不过期但可撤销。一致性由三层防线保证：规则单一真源 + 契约测试（REST vs MCP）+ 参数反射检查。

**Tech Stack:** Python 3.11+ / FastAPI / Starlette / SQLAlchemy(async) / MySQL / `mcp==1.29.1`(官方 SDK, FastMCP) / PyJWT / Vue 3 + TS + Element Plus

**设计文档：** `docs/specs/2026-10-31-testmate-mcp-design.md`（v11，本计划的唯一事实来源）

---

## Global Constraints

以下约束**对每个任务都生效**，不再逐条重复：

- **依赖锁定**：`mcp==1.29.1`（`requirements.txt` 写 `mcp>=1.29,<2`，`requirements.lock` 锁 `mcp==1.29.1`）。2.x 有 breaking change，本轮不碰。
- **后端启动**：`uvicorn app.main:app`，工作目录 `backend_gateway/`。
- **⚠️ 禁止**在 `backend_gateway/` 下新建顶层 `mcp/` 目录，禁止把 `app/` 加入 `sys.path` —— 否则 `import mcp` 会解析到 `app/mcp/`，官方 SDK 导入失败。
- **OAuth issuer 允许 http**（内网 `http://10.0.0.5:8081`）：因此**绝不能调用 SDK 的 `create_auth_routes`**（它强制 HTTPS），也**绝不能给 FastMCP 传 `auth_server_provider`**（传了它内部就会调 `create_auth_routes`）。只传 `token_verifier` + `AuthSettings`。
- **MCP access token 不带 `exp`**（授权不过期），但**必须带 `aud="mcp"`** —— 平台登录 JWT 没有 `aud`，绝不能让登录 token 当 MCP token 用（越权）。
- **MCP access token 用 PyJWT 签发**（`import jwt as pyjwt`）；平台登录 token 用 jose（`from jose import jwt`）—— 两者模块名不同，不要在同一个文件里用同名 `jwt`。
- **MCP 端点路径**：`POST /mcp/skill`（Streamable HTTP，**不带尾斜杠**）、`GET /mcp/skill/sse`、`POST /mcp/skill/messages/?session_id=…`。
- **OAuth 端点路径**：`POST /oauth/register`、`GET|POST /oauth/authorize`、`POST /oauth/token`、`POST /oauth/revoke`；元数据 `GET /.well-known/oauth-authorization-server`、`GET /.well-known/oauth-protected-resource/mcp/skill`。**issuer = 站点根**（不带路径）。
- **前端 SPA 同意页路由 = `/connect/authorize`**（**不能**放在 `/mcp` 下：nginx `location /mcp` 是前缀匹配会劫持它）。
- **DCR `redirect_uris` 只允许回环地址**：`http://127.0.0.1:*` 与 `http://localhost:*`。
- **DCR 强制三件套**：`token_endpoint_auth_method="none"`（不发 client_secret）、`scope` 写入全部支持 scope、`grant_types=["authorization_code"]`（不发 refresh token）。
- **不替用户做主**：写工具遇「必填缺失 / 枚举越界 / 有多候选 / 可选项未确认」→ **拒绝执行**并返回 `needs_confirmation`，**不产生任何副作用**。
- **既有业务零改动原则**：`app/api/marketplace.py` 只允许 (a) 新增 1 个只读端点 `GET /assets/rules`；(b) 在 3 个函数顶部加内置资产守卫（共约 9 行）。**其余一律不动。**
- **单进程约束**：SSE + 内存态授权码要求 `BACKEND_WORKERS=1`（现有 `tmctl` 已告警）。
- **测试库**：`testmate_test`，测试夹具已自动清表（`tests/conftest.py`）。新增测试文件放进 `backend_gateway/tests/`。
- **语言**：代码注释与提交信息用中文（与既有仓库一致）。

---

## 阶段总览

| 阶段 | 任务 | 产出 |
|---|---|---|
| S0 探针 | Task 1 | Qoder 是否会自动走 OAuth 的**结论**（决定后续路线） |
| S1 OAuth 后端 | Task 2 – 6 | 能用 code 换到 token；发现链路全通 |
| S2 同意页 | Task 7 – 9 | 浏览器里走完「登录→同意→回客户端」；可撤销 |
| S3 内置资产 | Task 10 – 11 | 市场里出现「TestMate 平台能力」连接器卡片 |
| S4 MCP 公共层 | Task 12 – 13 | 能握手、能 `tools/list`、路径与鉴权全对 |
| S5 技能域 | Task 14 – 17 | 14 个工具 + 不猜协议 + 规则单一真源 |
| S5.5 一致性 | Task 18 – 20 | 契约测试全绿；前端与 MCP 规则同源 |
| S6 部署分发 | Task 21 – 23 | 全链路打通 + 真机验收 |

---

# Stage S0 — Qoder OAuth 探针（独立 spike）

> **这个阶段不写任何生产代码。** 目的只有一个：确认 Qoder 会不会自动走
> 「401 → PR metadata → AS metadata → /oauth/register → /oauth/authorize」这条发现链路。
> 探针**不依赖本项目任何代码**，避免循环依赖。

### Task 1: 最小 OAuth 探针 + Qoder 真机验证

**Files:**
- Create: `docs/spikes/2026-10-31-qoder-oauth-probe/probe.py`
- Create: `docs/spikes/2026-10-31-qoder-oauth-probe/README.md`

**Interfaces:**
- Consumes: 无（独立脚本，只用标准库 + `pyjwt`）
- Produces: `docs/spikes/2026-10-31-qoder-oauth-probe/README.md` 里的「结论」一节（**二选一**：`走 OAuth` / `不走 OAuth`），后续任务据此决定路线

- [ ] **Step 1: 写探针脚本**

创建 `docs/spikes/2026-10-31-qoder-oauth-probe/probe.py`：

```python
"""Qoder OAuth 发现探针 —— 最小可跑, 不依赖 TestMate 任何代码.

目的: 确认 Qoder 遇到 401 + WWW-Authenticate(resource_metadata=…) 时,
会不会自动去发现授权服务器并弹出「授权」按钮.

跑法:  python3 probe.py 8899
然后在 Qoder 里新增自定义 MCP 服务器:
    类型: HTTP
    URL:  http://127.0.0.1:8899/mcp/skill
"""
from __future__ import annotations

import base64
import hashlib
import json
import secrets
import sys
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlparse

PORT = int(sys.argv[1]) if len(sys.argv) > 1 else 8899
BASE = f"http://127.0.0.1:{PORT}"

CLIENTS: dict[str, dict] = {}
CODES: dict[str, dict] = {}


def b64u(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).decode().rstrip("=")


class Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def log_message(self, fmt, *args):  # 安静一点, 只打关键行
        pass

    def _send(self, code: int, body: dict, extra: dict | None = None) -> None:
        raw = json.dumps(body).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(raw)))
        for k, v in (extra or {}).items():
            self.send_header(k, v)
        self.end_headers()
        self.wfile.write(raw)

    def do_GET(self):  # noqa: N802
        path = urlparse(self.path).path
        if path == "/.well-known/oauth-protected-resource/mcp/skill":
            return self._send(200, {
                "resource": f"{BASE}/mcp/skill",
                "authorization_servers": [BASE],
                "scopes_supported": ["market:read"],
                "bearer_methods_supported": ["header"],
            })
        if path == "/.well-known/oauth-authorization-server":
            return self._send(200, {
                "issuer": BASE,
                "authorization_endpoint": f"{BASE}/oauth/authorize",
                "token_endpoint": f"{BASE}/oauth/token",
                "registration_endpoint": f"{BASE}/oauth/register",
                "response_types_supported": ["code"],
                "grant_types_supported": ["authorization_code"],
                "code_challenge_methods_supported": ["S256"],
                "token_endpoint_auth_methods_supported": ["none"],
                "scopes_supported": ["market:read"],
            })
        if path == "/mcp/skill":
            return self._send(401, {"error": "invalid_token"},
                              {"WWW-Authenticate":
                               f'Bearer resource_metadata="{BASE}/.well-known/oauth-protected-resource/mcp/skill"'})
        if path == "/callback":
            q = parse_qs(urlparse(self.path).query)
            html = f"<h1>探针回调成功</h1><pre>{json.dumps(q, ensure_ascii=False, indent=2)}</pre>"
            raw = html.encode()
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(raw)))
            self.end_headers()
            self.wfile.write(raw)
            return
        return self._send(404, {"error": "not_found"})

    def do_POST(self):  # noqa: N802
        path = urlparse(self.path).path
        length = int(self.headers.get("Content-Length") or 0)
        raw = self.rfile.read(length) if length else b""
        if path == "/oauth/register":
            body = json.loads(raw or b"{}")
            cid = "probe-" + secrets.token_hex(6)
            CLIENTS[cid] = body
            print(f"[register] client_id={cid} redirect_uris={body.get('redirect_uris')}")
            return self._send(201, {
                "client_id": cid,
                "redirect_uris": body.get("redirect_uris", []),
                "token_endpoint_auth_method": "none",
                "grant_types": ["authorization_code"],
                "scope": "market:read",
                "client_name": body.get("client_name") or "Qoder 探针",
            })
        if path == "/oauth/authorize":
            q = parse_qs(urlparse(self.path).query)
            cid = (q.get("client_id") or [""])[0]
            redirect = (q.get("redirect_uri") or [""])[0]
            challenge = (q.get("code_challenge") or [""])[0]
            state = (q.get("state") or [""])[0]
            code = "code-" + secrets.token_hex(8)
            CODES[code] = {"client_id": cid, "challenge": challenge, "redirect": redirect}
            print(f"[authorize] client_id={cid} -> {redirect}")
            sep = "&" if "?" in redirect else "?"
            self.send_response(302)
            self.send_header("Location", f"{redirect}{sep}code={code}&state={state}")
            self.send_header("Content-Length", "0")
            self.end_headers()
            return
        if path == "/oauth/token":
            form = parse_qs(raw.decode())
            code = (form.get("code") or [""])[0]
            verifier = (form.get("code_verifier") or [""])[0]
            rec = CODES.pop(code, None)
            if not rec:
                return self._send(400, {"error": "invalid_grant"})
            digest = hashlib.sha256(verifier.encode()).digest()
            if b64u(digest) != rec["challenge"]:
                return self._send(400, {"error": "invalid_grant", "error_description": "PKCE mismatch"})
            return self._send(200, {
                "access_token": "probe-token-" + secrets.token_hex(8),
                "token_type": "Bearer",
                "expires_in": 3600,
                "scope": "market:read",
            })
        return self._send(404, {"error": "not_found"})


if __name__ == "__main__":
    srv = ThreadingHTTPServer(("127.0.0.1", PORT), Handler)
    print(f"探针已启动: {BASE}")
    print(f"  MCP 端点   : {BASE}/mcp/skill")
    print(f"  AS 元数据  : {BASE}/.well-known/oauth-authorization-server")
    print("Ctrl-C 退出")
    srv.serve_forever()
```

- [ ] **Step 2: 跑起来并自测端点**

Run: `python3 docs/spikes/2026-10-31-qoder-oauth-probe/probe.py 8899`

另开一个终端自测：

```bash
curl -i http://127.0.0.1:8899/mcp/skill
curl -s http://127.0.0.1:8899/.well-known/oauth-authorization-server
curl -s http://127.0.0.1:8899/.well-known/oauth-protected-resource/mcp/skill
```

Expected: 第一个返回 **401** 且响应头含 `WWW-Authenticate: Bearer resource_metadata="…"`；后两个返回 JSON。

- [ ] **Step 3: 在 Qoder 里配置并观察**

在 Qoder（CN 版）设置 → 连接器与 MCP → 新增 → 类型选 **HTTP** → URL 填 `http://127.0.0.1:8899/mcp/skill` → 保存。

然后记录：

| 观察项 | 结果（勾选） |
|---|---|
| Qoder 是否显示「授权」/「需要授权」按钮 | ☐ 是 ☐ 否 |
| 点击后是否自动打开浏览器到 `/oauth/authorize` | ☐ 是 ☐ 否 |
| 浏览器是否自动跳到 `/callback?code=…&state=…` | ☐ 是 ☐ 否 |
| 之后调用 `/mcp/skill` 是否带上了 `Authorization` 头 | ☐ 是 ☐ 否 |
| Qoder 侧是否出现「工具」列表 | ☐ 是 ☐ 否 |

> ⚠️ 若 Qoder 要求「Headers」手动填 `Authorization: Bearer xxx` 才肯发请求，
> 或根本不做 401 发现 → **结论 = 不走 OAuth**，S1/S2 降级为静态令牌路线（需额外约 1 天工作量：个人令牌页 + 引导用户手填 header）。

- [ ] **Step 4: 写结论**

在 `docs/spikes/2026-10-31-qoder-oauth-probe/README.md` 写入：

```markdown
# Qoder OAuth 发现探针

- 探针脚本：`probe.py`（标准库，无外部依赖）
- 跑法：`python3 probe.py 8899`，Qoder 里配 `http://127.0.0.1:8899/mcp/skill`（类型 HTTP）

## 观察记录（YYYY-MM-DD，Qoder 版本 x.y.z）

（把 Task 1 Step 3 的表格填进来）

## 结论

**走 OAuth** / **不走 OAuth**（二选一，删掉另一个）

- 若「走 OAuth」：S1/S2 按本计划执行。
- 若「不走 OAuth」：S1/S2 降级为「个人令牌页 + Qoder 手填 `Authorization: Bearer <token>`」，
  需要额外约 1 天工作量，且 D9 决策要改。
```

- [ ] **Step 5: 提交**

```bash
git add docs/spikes/2026-10-31-qoder-oauth-probe/
git commit -m "spike(MCP): Qoder OAuth 发现探针 —— 确认 401 发现链路是否成立"
```

---

# Stage S1 — OAuth 后端骨架

### Task 2: 依赖 + 数据模型 + 迁移

**Files:**
- Modify: `backend_gateway/requirements.txt`
- Modify: `backend_gateway/requirements.lock`
- Create: `backend_gateway/app/models/mcp.py`
- Modify: `backend_gateway/app/models/__init__.py`
- Create: `backend_gateway/alembic/versions/0030_add_mcp_tables.py`
- Test: `backend_gateway/tests/test_mcp_models.py`

**Interfaces:**
- Consumes: `app.db.session.Base`、`app.core.config.settings`
- Produces:
  - `app.models.mcp.McpOAuthClient`（表 `mcp_oauth_clients`）
  - `app.models.mcp.McpOAuthGrant`（表 `mcp_oauth_grants`）
  - `app.models.mcp.McpApiToken`（表 `mcp_api_tokens`）
  - `app.models.mcp.McpToolCall`（表 `mcp_tool_calls`）
  - 全部模型在 `app/models/__init__.py` 导出（`Base.metadata` 认识它们，测试建表才有）

- [ ] **Step 1: 写失败的测试**

创建 `backend_gateway/tests/test_mcp_models.py`：

```python
"""MCP 相关 ORM 模型 —— 建表 + 字段约束."""

from __future__ import annotations

import pytest
from sqlalchemy import text

from app.db.session import AsyncSessionLocal


@pytest.mark.asyncio
async def test_mcp_tables_exist():
    async with AsyncSessionLocal() as s:
        for table in ("mcp_oauth_clients", "mcp_oauth_grants", "mcp_api_tokens", "mcp_tool_calls"):
            r = await s.execute(text("SHOW TABLES LIKE :t"), {"t": table})
            assert r.first() is not None, f"表 {table} 不存在"


@pytest.mark.asyncio
async def test_grant_unique_index():
    """(user_id, client_id) 必须唯一 —— 吊销链依赖它定位单行."""
    async with AsyncSessionLocal() as s:
        r = await s.execute(text("SHOW INDEX FROM mcp_oauth_grants"))
        idx = [row[2] for row in r.fetchall()]
        assert "uk_mcp_grant" in idx, f"缺唯一索引 uk_mcp_grant, 现有: {idx}"
```

- [ ] **Step 2: 跑测试确认失败**

Run: `cd backend_gateway && pytest tests/test_mcp_models.py -v`
Expected: FAIL —— `表 mcp_oauth_clients 不存在`

- [ ] **Step 3: 写 ORM 模型**

创建 `backend_gateway/app/models/mcp.py`：

```python
"""MCP 相关数据模型：OAuth 客户端 / 授权 / 平台接入令牌 / 工具调用审计.

设计文档：docs/specs/2026-10-31-testmate-mcp-design.md
  · §4.2 数据模型
  · §4.7 吊销模型（授权 = 一条 grant）
  · §4.8 配额（计数来源 = mcp_tool_calls）
  · §8   审计
"""

from datetime import datetime

from sqlalchemy import BigInteger, DateTime, Index, Integer, JSON, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.db.session import Base


class McpOAuthClient(Base):
    """DCR 动态注册的 OAuth 客户端（公开客户端 + PKCE，不发 secret）."""

    __tablename__ = "mcp_oauth_clients"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    client_id: Mapped[str] = mapped_column(String(128), nullable=False, unique=True, index=True)
    client_name: Mapped[str] = mapped_column(String(128), nullable=False, default="")
    redirect_uris: Mapped[list] = mapped_column(JSON, nullable=False, default=list)
    scopes: Mapped[str] = mapped_column(String(512), nullable=False, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    last_used_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)


class McpOAuthGrant(Base):
    """一条授权（用户 × 客户端）—— **不过期**，靠 revoked_at 撤销."""

    __tablename__ = "mcp_oauth_grants"
    __table_args__ = (
        UniqueConstraint("user_id", "client_id", name="uk_mcp_grant"),
        Index("ix_mcp_grant_user", "user_id"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    client_id: Mapped[str] = mapped_column(String(128), nullable=False)
    client_name: Mapped[str] = mapped_column(String(128), nullable=False, default="")
    scopes: Mapped[list] = mapped_column(JSON, nullable=False, default=list)
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    last_used_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)


class McpApiToken(Base):
    """平台接入令牌（adminOnly，CI / 脚本 / 兜底通道）."""

    __tablename__ = "mcp_api_tokens"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    token_prefix: Mapped[str] = mapped_column(String(16), nullable=False, index=True)
    token_hash: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    label: Mapped[str] = mapped_column(String(128), nullable=False, default="")
    scopes: Mapped[list] = mapped_column(JSON, nullable=False, default=list)
    created_by: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    expires_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    last_used_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)


class McpToolCall(Base):
    """工具调用审计（同时是配额的计数来源）."""

    __tablename__ = "mcp_tool_calls"
    __table_args__ = (
        Index("ix_mcp_calls_user", "user_id", "client_id", "created_at"),
        Index("ix_mcp_calls_user_only", "user_id", "created_at"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    client_id: Mapped[str] = mapped_column(String(128), nullable=False, default="")
    client_name: Mapped[str] = mapped_column(String(128), nullable=False, default="")
    tool: Mapped[str] = mapped_column(String(64), nullable=False)
    domain: Mapped[str] = mapped_column(String(32), nullable=False)
    args_summary: Mapped[str] = mapped_column(Text, nullable=False, default="")
    ok: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    error_code: Mapped[str] = mapped_column(String(32), nullable=False, default="")
    duration_ms: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
```

- [ ] **Step 4: 导出模型**

修改 `backend_gateway/app/models/__init__.py`，在既有导出行之后追加：

```python
from app.models.mcp import McpApiToken, McpOAuthClient, McpOAuthGrant, McpToolCall  # noqa: F401
```

- [ ] **Step 5: 写迁移**

创建 `backend_gateway/alembic/versions/0030_add_mcp_tables.py`（**down_revision 指向 `0029_add_asset_pending_action` 的 revision id**——先 `grep -n "revision\|down_revision" alembic/versions/0029_add_asset_pending_action.py` 确认）：

```python
"""add mcp oauth clients / grants / api tokens / tool calls

Revision ID: 0030_add_mcp_tables
Revises: 0029_add_asset_pending_action
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0030_add_mcp_tables"
down_revision = "0029_add_asset_pending_action"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "mcp_oauth_clients",
        sa.Column("id", sa.BigInteger, primary_key=True, autoincrement=True),
        sa.Column("client_id", sa.String(128), nullable=False),
        sa.Column("client_name", sa.String(128), nullable=False, server_default=""),
        sa.Column("redirect_uris", sa.JSON, nullable=False),
        sa.Column("scopes", sa.String(512), nullable=False, server_default=""),
        sa.Column("created_at", sa.DateTime, nullable=False),
        sa.Column("last_used_at", sa.DateTime, nullable=True),
    )
    op.create_index("ix_mcp_oauth_clients_client_id", "mcp_oauth_clients", ["client_id"], unique=True)

    op.create_table(
        "mcp_oauth_grants",
        sa.Column("id", sa.BigInteger, primary_key=True, autoincrement=True),
        sa.Column("user_id", sa.BigInteger, nullable=False),
        sa.Column("client_id", sa.String(128), nullable=False),
        sa.Column("client_name", sa.String(128), nullable=False, server_default=""),
        sa.Column("scopes", sa.JSON, nullable=False),
        sa.Column("created_at", sa.DateTime, nullable=False),
        sa.Column("last_used_at", sa.DateTime, nullable=True),
        sa.Column("revoked_at", sa.DateTime, nullable=True),
        sa.UniqueConstraint("user_id", "client_id", name="uk_mcp_grant"),
    )
    op.create_index("ix_mcp_grant_user", "mcp_oauth_grants", ["user_id"])

    op.create_table(
        "mcp_api_tokens",
        sa.Column("id", sa.BigInteger, primary_key=True, autoincrement=True),
        sa.Column("token_prefix", sa.String(16), nullable=False),
        sa.Column("token_hash", sa.String(64), nullable=False),
        sa.Column("label", sa.String(128), nullable=False, server_default=""),
        sa.Column("scopes", sa.JSON, nullable=False),
        sa.Column("created_by", sa.BigInteger, nullable=True),
        sa.Column("created_at", sa.DateTime, nullable=False),
        sa.Column("expires_at", sa.DateTime, nullable=True),
        sa.Column("revoked_at", sa.DateTime, nullable=True),
        sa.Column("last_used_at", sa.DateTime, nullable=True),
    )
    op.create_index("ix_mcp_api_tokens_token_hash", "mcp_api_tokens", ["token_hash"])
    op.create_index("ix_mcp_api_tokens_token_prefix", "mcp_api_tokens", ["token_prefix"])

    op.create_table(
        "mcp_tool_calls",
        sa.Column("id", sa.BigInteger, primary_key=True, autoincrement=True),
        sa.Column("user_id", sa.BigInteger, nullable=False),
        sa.Column("client_id", sa.String(128), nullable=False, server_default=""),
        sa.Column("client_name", sa.String(128), nullable=False, server_default=""),
        sa.Column("tool", sa.String(64), nullable=False),
        sa.Column("domain", sa.String(32), nullable=False),
        sa.Column("args_summary", sa.Text, nullable=False, server_default=""),
        sa.Column("ok", sa.Integer, nullable=False, server_default="0"),
        sa.Column("error_code", sa.String(32), nullable=False, server_default=""),
        sa.Column("duration_ms", sa.Integer, nullable=False, server_default="0"),
        sa.Column("created_at", sa.DateTime, nullable=False),
    )
    op.create_index("ix_mcp_calls_user", "mcp_tool_calls", ["user_id", "client_id", "created_at"])
    op.create_index("ix_mcp_calls_user_only", "mcp_tool_calls", ["user_id", "created_at"])


def downgrade() -> None:
    op.drop_table("mcp_tool_calls")
    op.drop_table("mcp_api_tokens")
    op.drop_table("mcp_oauth_grants")
    op.drop_table("mcp_oauth_clients")
```

- [ ] **Step 6: 加依赖**

`backend_gateway/requirements.txt` 追加：

```
mcp>=1.29,<2
```

`backend_gateway/requirements.lock` 追加（锁到实测版本，并补齐传递依赖）：

```
mcp==1.29.1
httpx-sse==0.4.3
sse-starlette==2.4.1
jsonschema==4.25.1
referencing==0.37.0
rpds-py==0.28.0
pyjwt==2.10.1
```

> ⚠️ 锁文件的精确版本用 `pip index versions <pkg>` 或在有网机器上 `pip install mcp==1.29.1 && pip freeze` 核对后填入；
> `pydantic`/`starlette`/`httpx`/`anyio`/`uvicorn`/`pydantic-settings` 现有版本**已满足** `mcp==1.29.1` 的下限，不要动。

- [ ] **Step 7: 跑测试确认通过**

Run: `cd backend_gateway && pytest tests/test_mcp_models.py -v`
Expected: PASS（2 passed）

> 若报「表不存在」，说明测试库没建表 —— `tests/conftest.py` 的 `_clean_tables` 夹具会在首次使用时
> `Base.metadata.create_all`，确认 `app/models/__init__.py` 已导出新模型（Step 4）。

- [ ] **Step 8: 提交**

```bash
git add backend_gateway/requirements.txt backend_gateway/requirements.lock \
        backend_gateway/app/models/ backend_gateway/alembic/versions/0030_add_mcp_tables.py \
        backend_gateway/tests/test_mcp_models.py
git commit -m "feat(MCP): 数据模型 —— oauth 客户端/授权/接入令牌/调用审计 4 张表"
```

---

### Task 3: OAuth provider（客户端注册表 + 授权码 + token 签发）

**Files:**
- Create: `backend_gateway/app/mcp/__init__.py`
- Create: `backend_gateway/app/mcp/common/__init__.py`
- Create: `backend_gateway/app/mcp/common/oauth_provider.py`
- Test: `backend_gateway/tests/test_mcp_oauth_provider.py`

**Interfaces:**
- Consumes: `app.models.mcp.McpOAuthClient` / `McpOAuthGrant`、`app.db.session.AsyncSessionLocal`、`app.core.security.settings`
- Produces:
  - `SUPPORTED_SCOPES: frozenset[str] = frozenset({"market:read", "market:write"})`
  - `class TestMateOAuthProvider(OAuthAuthorizationServerProvider)` —— 实现 SDK 协议 10 个方法
  - `provider.pending_requests: PendingRequestStore` —— 同意页 ticket 存储（Task 7 用）
  - `issue_mcp_access_token(...) -> str` / `decode_mcp_access_token(...) -> dict | None`（**放 `common/auth.py`，本任务只声明、由 Task 5 实现**；本任务用 stub 调用 `self._issue_token()` 内部方法）

> ⚠️ **本任务的 provider 不依赖 HTTP 层**（不 import starlette），只做协议语义 ——
> 这样 Task 4 的路由层可以薄薄地包一层。

- [ ] **Step 1: 写失败的测试**

创建 `backend_gateway/tests/test_mcp_oauth_provider.py`：

```python
"""OAuth provider 语义 —— 客户端注册 / 授权码 / PKCE / scope."""

from __future__ import annotations

import base64
import hashlib

import pytest

from app.mcp.common.oauth_provider import (
    SUPPORTED_SCOPES,
    TestMateOAuthProvider,
    b64u_sha256,
    is_loopback_redirect,
)


def _s256(verifier: str) -> str:
    return base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).decode().rstrip("=")


@pytest.mark.asyncio
async def test_register_client_forces_public_client_shape():
    p = TestMateOAuthProvider()
    from mcp.shared.auth import OAuthClientInformationFull

    await p.register_client(OAuthClientInformationFull(
        client_id="c1",
        client_name="Qoder",
        redirect_uris=["http://127.0.0.1:51234/cb"],
        token_endpoint_auth_method=None,   # 客户端没填 —— 我们必须兜住
        grant_types=["authorization_code", "refresh_token"],
        scope=None,                        # 客户端没填 —— 我们必须兜住
    ))
    got = await p.get_client("c1")
    assert got is not None
    assert got.token_endpoint_auth_method == "none"
    assert got.client_secret is None
    assert set(got.scope.split()) == set(SUPPORTED_SCOPES)
    assert "refresh_token" not in got.grant_types


@pytest.mark.asyncio
async def test_get_client_unknown_returns_none():
    p = TestMateOAuthProvider()
    assert await p.get_client("nope") is None


@pytest.mark.asyncio
async def test_authorize_requires_pkce_and_known_client():
    from mcp.server.auth.provider import AuthorizationParams, AuthorizeError
    from mcp.shared.auth import OAuthClientInformationFull

    p = TestMateOAuthProvider()
    await p.register_client(OAuthClientInformationFull(
        client_id="c1", redirect_uris=["http://127.0.0.1:51234/cb"],
        token_endpoint_auth_method="none", grant_types=["authorization_code"],
        scope="market:read market:write",
    ))
    client = await p.get_client("c1")
    params = AuthorizationParams(
        state="st", scopes=["market:read"], code_challenge=_s256("verifier-123"),
        redirect_uri="http://127.0.0.1:51234/cb", redirect_uri_provided_explicitly=True,
    )
    url = await p.authorize(client, params)
    assert url.startswith("/connect/authorize?ticket=")

    with pytest.raises(AuthorizeError):
        await p.authorize(client, params.model_copy(update={"code_challenge": ""}))


@pytest.mark.asyncio
async def test_exchange_code_checks_pkce_and_single_use():
    from mcp.server.auth.provider import AuthorizationParams, TokenError
    from mcp.shared.auth import OAuthClientInformationFull

    p = TestMateOAuthProvider()
    await p.register_client(OAuthClientInformationFull(
        client_id="c1", redirect_uris=["http://127.0.0.1:51234/cb"],
        token_endpoint_auth_method="none", grant_types=["authorization_code"],
        scope="market:read market:write",
    ))
    client = await p.get_client("c1")
    params = AuthorizationParams(
        state="st", scopes=["market:read"], code_challenge=_s256("verifier-123"),
        redirect_uri="http://127.0.0.1:51234/cb", redirect_uri_provided_explicitly=True,
    )
    url = await p.authorize(client, params)
    ticket = url.split("ticket=", 1)[1]

    # 同意页还没提交 —— 不该有码
    assert await p.load_authorization_code(client, "not-exist") is None

    code = await p.approve_pending(ticket, user_id=42, username="u@x.com", scopes=["market:read"])
    loaded = await p.load_authorization_code(client, code)
    assert loaded is not None and loaded.client_id == "c1"

    # PKCE 错 → 拒
    with pytest.raises(TokenError):
        await p.exchange_authorization_code(client, loaded.model_copy(update={"code_challenge": _s256("wrong")}))

    # 正确 → 拿到 token（无 exp）
    token = await p.exchange_authorization_code(client, loaded)
    assert token.access_token
    assert token.refresh_token is None


def test_loopback_redirect_only():
    assert is_loopback_redirect("http://127.0.0.1:51234/cb")
    assert is_loopback_redirect("http://localhost:1234/cb")
    assert not is_loopback_redirect("https://evil.example.com/cb")
    assert not is_loopback_redirect("http://10.0.0.5:8080/cb")


def test_b64u_sha256_matches_pkce_spec():
    assert b64u_sha256("abc") == _s256("abc")
```

- [ ] **Step 2: 跑测试确认失败**

Run: `cd backend_gateway && pytest tests/test_mcp_oauth_provider.py -v`
Expected: FAIL —— `ModuleNotFoundError: No module named 'app.mcp'`

- [ ] **Step 3: 写 provider**

创建 `backend_gateway/app/mcp/common/oauth_provider.py`：

```python
"""OAuth 2.1 授权服务器 provider（协议语义层，不碰 HTTP）.

设计文档 §4.3 / §4.4 / §4.5。

⚠️ 三条强制规则（§4.3.3），少一条 Qoder 就连不上：
  1. token_endpoint_auth_method = "none"（公开客户端 + PKCE，不发 client_secret）
  2. scope 强制写入全部支持 scope（SDK 的 validate_scope 在 scope 为 None 时会拒绝一切）
  3. grant_types = ["authorization_code"]（不发 refresh token —— 授权不过期）

⚠️ 授权码与「待处理授权请求」都放**进程内内存**：
  SSE 已要求后端单进程（BACKEND_WORKERS=1），进程重启 → 用户重新点一次「同意」即可。
"""

from __future__ import annotations

import base64
import hashlib
import secrets
import time
from dataclasses import dataclass, field
from typing import Any
from urllib.parse import urlparse

from mcp.server.auth.provider import (
    AccessToken,
    AuthorizationCode,
    AuthorizationParams,
    AuthorizeError,
    OAuthAuthorizationServerProvider,
    OAuthToken,
    RefreshToken,
    TokenError,
)
from mcp.shared.auth import OAuthClientInformationFull

#: 本服务支持的全部 scope —— DCR 时无条件写进 client.scope（§4.3.3 规则 2）
SUPPORTED_SCOPES: frozenset[str] = frozenset({"market:read", "market:write"})

#: 授权码有效期（秒）
AUTH_CODE_TTL = 300
#: 待处理授权请求（同意页 ticket）有效期（秒）
PENDING_TTL = 600


def b64u_sha256(verifier: str) -> str:
    """PKCE S256: base64url(sha256(verifier))，去掉 padding."""
    return base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).decode().rstrip("=")


def is_loopback_redirect(uri: str) -> bool:
    """DCR 只允许回环回调地址（§4.3.5）—— 否则授权码可能被送到外部站点."""
    try:
        p = urlparse(uri)
    except Exception:
        return False
    if p.scheme != "http":
        return False
    host = (p.hostname or "").lower()
    return host in ("127.0.0.1", "localhost", "::1")


@dataclass
class PendingRequest:
    """一次待用户确认的授权请求（后端保管，前端只拿 ticket）."""

    ticket: str
    client_id: str
    client_name: str
    redirect_uri: str
    code_challenge: str
    scopes: list[str]
    state: str | None
    resource: str | None
    created_at: float = field(default_factory=time.time)


@dataclass
class _Grant:
    user_id: int
    client_id: str
    scopes: list[str]
    revoked: bool = False


class TestMateOAuthProvider(OAuthAuthorizationServerProvider):
    """协议语义实现 —— 状态在内存，落库的只有 client 与 grant."""

    def __init__(self) -> None:
        self._clients: dict[str, OAuthClientInformationFull] = {}
        self._codes: dict[str, AuthorizationCode] = {}
        self._pending: dict[str, PendingRequest] = {}
        self._grants: dict[tuple[int, str], _Grant] = {}

    # ---------- 客户端 ----------

    async def get_client(self, client_id: str) -> OAuthClientInformationFull | None:
        return self._clients.get(client_id)

    async def register_client(self, client_info: OAuthClientInformationFull) -> None:
        """强制 §4.3.3 三条规则 —— 客户端说什么不算."""
        uris = [str(u) for u in (client_info.redirect_uris or [])]
        bad = [u for u in uris if not is_loopback_redirect(u)]
        if bad:
            from mcp.server.auth.provider import RegistrationError

            raise RegistrationError(
                error="invalid_redirect_uri",
                error_description=f"只允许回环地址（http://127.0.0.1:* / http://localhost:*），收到: {bad}",
            )
        client_info.token_endpoint_auth_method = "none"
        client_info.client_secret = None
        client_info.client_secret_expires_at = None
        client_info.grant_types = ["authorization_code"]
        client_info.scope = " ".join(sorted(SUPPORTED_SCOPES))
        client_info.redirect_uris = uris
        self._clients[str(client_info.client_id)] = client_info

    # ---------- 授权 ----------

    async def authorize(self, client: OAuthClientInformationFull, params: AuthorizationParams) -> str:
        """返回**同意页地址**（相对路径，同源，跳 SPA）."""
        if not params.code_challenge:
            raise AuthorizeError(error="invalid_request", error_description="缺少 PKCE code_challenge")
        ticket = secrets.token_urlsafe(24)
        self._pending[ticket] = PendingRequest(
            ticket=ticket,
            client_id=str(client.client_id),
            client_name=client.client_name or "未命名客户端",
            redirect_uri=str(params.redirect_uri),
            code_challenge=params.code_challenge,
            scopes=list(params.scopes or []),
            state=params.state,
            resource=params.resource,
        )
        self._gc()
        return f"/connect/authorize?ticket={ticket}"

    def get_pending(self, ticket: str) -> PendingRequest | None:
        return self._pending.get(ticket)

    async def approve_pending(
        self, ticket: str, *, user_id: int, username: str, scopes: list[str]
    ) -> str:
        """同意页点了「同意」→ 建授权码，返回 code."""
        req = self._pending.pop(ticket, None)
        if req is None:
            raise TokenError(error="invalid_request", error_description="授权请求已失效或已被使用")
        granted = [s for s in scopes if s in SUPPORTED_SCOPES]
        if not granted:
            raise TokenError(error="invalid_scope", error_description="至少要授予一个 scope")
        code = secrets.token_urlsafe(32)
        self._codes[code] = AuthorizationCode(
            code=code,
            scopes=granted,
            expires_at=time.time() + AUTH_CODE_TTL,
            client_id=req.client_id,
            code_challenge=req.code_challenge,
            redirect_uri=req.redirect_uri,  # type: ignore[arg-type]
            redirect_uri_provided_explicitly=True,
            resource=req.resource,
            subject=str(user_id),
        )
        key = (user_id, req.client_id)
        self._grants[key] = _Grant(user_id=user_id, client_id=req.client_id, scopes=granted)
        return code

    async def deny_pending(self, ticket: str) -> None:
        """点了「拒绝」→ 丢弃请求（由路由层负责回 redirect_uri 带 error）."""
        self._pending.pop(ticket, None)

    # ---------- 授权码 ----------

    async def load_authorization_code(
        self, client: OAuthClientInformationFull, authorization_code: str
    ) -> AuthorizationCode | None:
        code = self._codes.get(authorization_code)
        if code is None:
            return None
        if code.expires_at < time.time():
            self._codes.pop(authorization_code, None)
            return None
        return code

    async def exchange_authorization_code(
        self, client: OAuthClientInformationFull, authorization_code: AuthorizationCode
    ) -> OAuthToken:
        if authorization_code.code_challenge != b64u_sha256(authorization_code.code):  # pragma: no cover
            pass  # 真校验在 token 端点（SDK 的 TokenHandler）做
        self._codes.pop(authorization_code.code, None)
        subject = authorization_code.subject or "0"
        token = _issue_access_token(
            user_id=int(subject),
            client_id=authorization_code.client_id,
            scopes=authorization_code.scopes,
            grant_id=None,
        )
        return OAuthToken(access_token=token, token_type="Bearer", scope=" ".join(authorization_code.scopes))

    # ---------- 其余协议方法（本轮不用，但要实现） ----------

    async def load_refresh_token(
        self, client: OAuthClientInformationFull, refresh_token: str
    ) -> RefreshToken | None:
        return None

    async def exchange_refresh_token(
        self, client: OAuthClientInformationFull, refresh_token: RefreshToken, scopes: list[str]
    ) -> OAuthToken:
        raise TokenError(error="unsupported_grant_type", error_description="不发 refresh token")

    async def load_access_token(self, token: str) -> AccessToken | None:
        return None

    async def revoke_token(self, token: AccessToken | RefreshToken) -> None:
        return None

    # ---------- 内部 ----------

    def _gc(self) -> None:
        now = time.time()
        for t in [k for k, v in self._pending.items() if now - v.created_at > PENDING_TTL]:
            self._pending.pop(t, None)
        for c in [k for k, v in self._codes.items() if v.expires_at < now]:
            self._codes.pop(c, None)

    def grant_for(self, user_id: int, client_id: str) -> _Grant | None:
        return self._grants.get((user_id, client_id))


def _issue_access_token(*, user_id: int, client_id: str, scopes: list[str], grant_id: int | None) -> str:
    """签发 MCP access token —— **不带 exp**（授权不过期），但带 aud='mcp'."""
    import jwt as pyjwt

    from app.core.config import settings

    now = int(time.time())
    payload = {
        "sub": str(user_id),
        "client_id": client_id,
        "scopes": scopes,
        "grant_id": grant_id,
        "aud": "mcp",           # ⚠️ 平台登录 JWT 没有 aud —— 绝不能互相通用
        "iat": now,
    }
    return pyjwt.encode(payload, settings.JWT_SECRET, algorithm=settings.JWT_ALGORITHM)
```

> ⚠️ `exchange_authorization_code` 里那段 `if ... pass` 是**占位**，Task 4 的 token 端点会做真正的
> PKCE 校验（SDK 的 `TokenHandler` 已经做：`hashed_code_verifier != auth_code.code_challenge` → `invalid_grant`）。
> 保留这段是为了让 provider 在**没有 HTTP 层**时也能单测；Task 4 完成后可删。

- [ ] **Step 4: 跑测试确认通过**

Run: `cd backend_gateway && pytest tests/test_mcp_oauth_provider.py -v`
Expected: PASS（5 passed）

- [ ] **Step 5: 提交**

```bash
git add backend_gateway/app/mcp/ backend_gateway/tests/test_mcp_oauth_provider.py
git commit -m "feat(MCP): OAuth provider —— DCR 三条强制规则 + 授权码 + PKCE + 同意页 ticket"
```

---

### Task 4: OAuth 路由 + 元数据 + 自写 DCR 处理器

**Files:**
- Create: `backend_gateway/app/mcp/common/oauth_routes.py`
- Test: `backend_gateway/tests/test_mcp_oauth_routes.py`

**Interfaces:**
- Consumes: `app.mcp.common.oauth_provider.TestMateOAuthProvider`、`app.core.config.settings`
- Produces:
  - `build_oauth_router(provider, *, issuer_url: str, resource_server_url: str, scopes: list[str]) -> APIRouter`
  - 路由：`GET /.well-known/oauth-authorization-server`、`GET /.well-known/oauth-protected-resource/{resource_path:path}`、`POST /oauth/register`、`GET /oauth/authorize`、`POST /oauth/token`
  - `POST /oauth/token` 返回 `{"access_token", "token_type": "Bearer", "scope"}` —— **无 expires_in**（不过期）

- [ ] **Step 1: 写失败的测试**

创建 `backend_gateway/tests/test_mcp_oauth_routes.py`：

```python
"""OAuth 路由 —— 元数据 / DCR / authorize / token.

⚠️ 关键回归点（v11 自审发现的三个致命坑）：
  · issuer 必须是 http（内网）—— 不能调 SDK 的 create_auth_routes（它强制 HTTPS）
  · DCR 必须强制 scope，否则 validate_scope 拒绝一切带 scope 的授权请求
  · token_endpoint_auth_method 必须是 none，否则 token 端点抛 Unsupported auth method
"""

from __future__ import annotations

import base64
import hashlib

import pytest
from httpx import ASGITransport, AsyncClient

from app.mcp.common.oauth_routes import build_oauth_router
from app.mcp.common.oauth_provider import TestMateOAuthProvider


def _s256(verifier: str) -> str:
    return base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).decode().rstrip("=")


@pytest.fixture()
def provider() -> TestMateOAuthProvider:
    return TestMateOAuthProvider()


def _client(app):
    return AsyncClient(transport=ASGITransport(app=app), base_url="http://testserver")


@pytest.mark.asyncio
async def test_authorization_server_metadata_is_http(provider):
    app = build_oauth_router(
        provider, issuer_url="http://10.0.0.5:8081",
        resource_server_url="http://10.0.0.5:8081/mcp/skill",
        scopes=["market:read", "market:write"],
    )
    async with _client(app) as c:
        r = await c.get("/.well-known/oauth-authorization-server")
    assert r.status_code == 200
    d = r.json()
    assert d["issuer"] == "http://10.0.0.5:8081"
    assert d["authorization_endpoint"] == "http://10.0.0.5:8081/oauth/authorize"
    assert d["token_endpoint"] == "http://10.0.0.5:8081/oauth/token"
    assert d["registration_endpoint"] == "http://10.0.0.5:8081/oauth/register"
    assert d["code_challenge_methods_supported"] == ["S256"]
    assert d["token_endpoint_auth_methods_supported"] == ["none"]


@pytest.mark.asyncio
async def test_protected_resource_metadata(provider):
    app = build_oauth_router(
        provider, issuer_url="http://10.0.0.5:8081",
        resource_server_url="http://10.0.0.5:8081/mcp/skill",
        scopes=["market:read"],
    )
    async with _client(app) as c:
        r = await c.get("/.well-known/oauth-protected-resource/mcp/skill")
    assert r.status_code == 200
    d = r.json()
    assert d["resource"] == "http://10.0.0.5:8081/mcp/skill"
    assert d["authorization_servers"] == ["http://10.0.0.5:8081"]


@pytest.mark.asyncio
async def test_register_forces_public_client_and_scope(provider):
    app = build_oauth_router(
        provider, issuer_url="http://h", resource_server_url="http://h/mcp/skill",
        scopes=["market:read", "market:write"],
    )
    async with _client(app) as c:
        r = await c.post("/oauth/register", json={
            "redirect_uris": ["http://127.0.0.1:51234/cb"],
            "client_name": "Qoder",
        })
    assert r.status_code == 201
    d = r.json()
    assert d["token_endpoint_auth_method"] == "none"
    assert "client_secret" not in d or d["client_secret"] is None
    assert set(d["scope"].split()) == {"market:read", "market:write"}


@pytest.mark.asyncio
async def test_register_rejects_non_loopback_redirect(provider):
    app = build_oauth_router(
        provider, issuer_url="http://h", resource_server_url="http://h/mcp/skill",
        scopes=["market:read"],
    )
    async with _client(app) as c:
        r = await c.post("/oauth/register", json={
            "redirect_uris": ["https://evil.example.com/cb"],
        })
    assert r.status_code == 400
    assert r.json()["error"] == "invalid_redirect_uri"


@pytest.mark.asyncio
async def test_authorize_redirects_to_consent_page(provider):
    app = build_oauth_router(
        provider, issuer_url="http://h", resource_server_url="http://h/mcp/skill",
        scopes=["market:read"],
    )
    async with _client(app) as c:
        reg = await c.post("/oauth/register", json={"redirect_uris": ["http://127.0.0.1:51234/cb"]})
        cid = reg.json()["client_id"]
        r = await c.get("/oauth/authorize", params={
            "client_id": cid,
            "redirect_uri": "http://127.0.0.1:51234/cb",
            "response_type": "code",
            "code_challenge": _s256("v123"),
            "code_challenge_method": "S256",
            "state": "st",
            "scope": "market:read",
        }, follow_redirects=False)
    assert r.status_code == 302
    assert r.headers["location"].startswith("/connect/authorize?ticket=")
```

- [ ] **Step 2: 跑测试确认失败**

Run: `cd backend_gateway && pytest tests/test_mcp_oauth_routes.py -v`
Expected: FAIL —— `ModuleNotFoundError: No module named 'app.mcp.common.oauth_routes'`

- [ ] **Step 3: 写路由层**

创建 `backend_gateway/app/mcp/common/oauth_routes.py`：

```python
"""OAuth 路由与元数据 —— **自写**（不用 SDK 的 create_auth_routes）.

⚠️ 为什么不用 SDK 的（v11 自审发现，设计文档 §4.3.1）：
   SDK 的 `create_auth_routes()` 第一行调 `validate_issuer_url()`，强制 issuer 必须 HTTPS
   （localhost 除外）。TestMate 是内网 http://10.0.0.5:8081 → 装配时直接 ValueError。

   本模块的做法：**复制 SDK 的路由拼装，跳过 issuer 校验**，复用 SDK 的 handler
   （AuthorizationHandler / TokenHandler / MetadataHandler）与 build_metadata。

⚠️ 本模块**不 import 任何业务模块**（common 层纪律）。
"""

from __future__ import annotations

import base64
import hashlib
import json
import secrets
import time
from typing import Any

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse, RedirectResponse
from mcp.server.auth.handlers.authorize import AuthorizationHandler
from mcp.server.auth.handlers.metadata import MetadataHandler
from mcp.server.auth.handlers.token import TokenHandler
from mcp.server.auth.middleware.client_auth import ClientAuthenticator
from mcp.server.auth.provider import AuthorizationCode, AuthorizationParams, TokenError
from mcp.shared.auth import OAuthClientInformationFull, OAuthClientMetadata
from starlette.responses import Response

from app.mcp.common.oauth_provider import SUPPORTED_SCOPES, TestMateOAuthProvider


def _b64u(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).decode().rstrip("=")


def build_oauth_router(
    provider: TestMateOAuthProvider,
    *,
    issuer_url: str,
    resource_server_url: str,
    scopes: list[str] | None = None,
) -> APIRouter:
    """拼出 OAuth 路由（返回 APIRouter，便于 include_router）."""
    scopes = scopes or sorted(SUPPORTED_SCOPES)
    issuer = issuer_url.rstrip("/")
    resource = resource_server_url.rstrip("/")

    router = APIRouter()

    # ---------- 元数据（RFC 8414 / RFC 9728） ----------

    @router.get("/.well-known/oauth-authorization-server")
    async def authorization_server_metadata() -> Response:
        body = {
            "issuer": issuer,
            "authorization_endpoint": f"{issuer}/oauth/authorize",
            "token_endpoint": f"{issuer}/oauth/token",
            "registration_endpoint": f"{issuer}/oauth/register",
            "response_types_supported": ["code"],
            "grant_types_supported": ["authorization_code"],
            "code_challenge_methods_supported": ["S256"],
            "token_endpoint_auth_methods_supported": ["none"],
            "scopes_supported": scopes,
        }
        return JSONResponse(body, headers={"Cache-Control": "public, max-age=3600"})

    @router.get("/.well-known/oauth-protected-resource/{resource_path:path}")
    async def protected_resource_metadata(resource_path: str) -> Response:
        body = {
            "resource": resource,
            "authorization_servers": [issuer],
            "scopes_supported": scopes,
            "bearer_methods_supported": ["header"],
        }
        return JSONResponse(body, headers={"Cache-Control": "public, max-age=3600"})

    # ---------- DCR（自写：强制三条规则） ----------

    @router.post("/oauth/register")
    async def register(request: Request) -> Response:
        try:
            body = await request.json()
        except Exception:
            return JSONResponse({"error": "invalid_client_metadata"}, status_code=400)
        try:
            meta = OAuthClientMetadata.model_validate(body)
        except Exception as exc:
            return JSONResponse(
                {"error": "invalid_client_metadata", "error_description": str(exc)}, status_code=400
            )
        client_id = "mcp-" + secrets.token_hex(12)
        info = OAuthClientInformationFull(
            client_id=client_id,
            client_id_issued_at=int(time.time()),
            client_secret=None,                      # 规则 1：公开客户端，不发 secret
            token_endpoint_auth_method="none",       # 规则 1
            grant_types=["authorization_code"],      # 规则 3
            response_types=["code"],
            redirect_uris=[str(u) for u in (meta.redirect_uris or [])],
            scope=" ".join(scopes),                  # 规则 2：强制写全
            client_name=meta.client_name,
            client_uri=meta.client_uri,
            logo_uri=meta.logo_uri,
        )
        try:
            await provider.register_client(info)
        except Exception as exc:
            code = getattr(exc, "error", "invalid_client_metadata")
            desc = getattr(exc, "error_description", str(exc))
            return JSONResponse({"error": code, "error_description": desc}, status_code=400)
        return JSONResponse(info.model_dump(mode="json", exclude_none=True), status_code=201)

    # ---------- authorize（SDK handler + 我们的 provider） ----------

    @router.get("/oauth/authorize")
    @router.post("/oauth/authorize")
    async def authorize(request: Request) -> Response:
        handler = AuthorizationHandler(provider)  # type: ignore[arg-type]
        return await handler.handle(request)

    # ---------- token（SDK handler + 我们的 provider） ----------

    @router.post("/oauth/token")
    async def token(request: Request) -> Response:
        authenticator = ClientAuthenticator(provider)  # type: ignore[arg-type]
        handler = TokenHandler(provider, authenticator)  # type: ignore[arg-type]
        return await handler.handle(request)

    return router
```

- [ ] **Step 4: 跑测试确认通过**

Run: `cd backend_gateway && pytest tests/test_mcp_oauth_routes.py -v`
Expected: PASS（5 passed）

- [ ] **Step 5: 提交**

```bash
git add backend_gateway/app/mcp/common/oauth_routes.py backend_gateway/tests/test_mcp_oauth_routes.py
git commit -m "feat(MCP): OAuth 路由与元数据 —— 自写绕开 SDK 的 HTTPS 校验 + 自写 DCR"
```

---

### Task 5: TokenVerifier + Principal（鉴权层）

**Files:**
- Create: `backend_gateway/app/mcp/common/auth.py`
- Test: `backend_gateway/tests/test_mcp_auth.py`

**Interfaces:**
- Consumes: `app.models.mcp.McpOAuthGrant` / `McpApiToken`、`app.db.session.AsyncSessionLocal`、`app.core.config.settings`
- Produces:
  - `@dataclass(frozen=True) class Principal`：`user_id: int`、`username: str`、`role: str`、`client_id: str`、`client_name: str`、`scopes: frozenset[str]`、`grant_id: int | None`
  - `issue_mcp_access_token(*, user_id, client_id, scopes, grant_id) -> str`（**无 exp**，带 `aud="mcp"`）
  - `decode_mcp_access_token(token: str) -> dict | None`
  - `class OAuthTokenVerifier`：实现 SDK `TokenVerifier.verify_token(token) -> AccessToken | None`
  - `class StaticTokenVerifier`：查 `mcp_api_tokens`
  - `VERIFIERS: list[TokenVerifier]`
  - `async def resolve_principal(request: Request) -> Principal | None` —— 从请求里取 Principal（含 User 现查）

- [ ] **Step 1: 写失败的测试**

创建 `backend_gateway/tests/test_mcp_auth.py`：

```python
"""MCP 鉴权 —— access token 签发/校验 + 吊销立即生效."""

from __future__ import annotations

from datetime import datetime

import pytest
from sqlalchemy import select

from app.db.session import AsyncSessionLocal
from app.mcp.common.auth import (
    decode_mcp_access_token,
    issue_mcp_access_token,
)
from app.models.mcp import McpOAuthGrant


def test_access_token_has_no_exp_and_has_aud():
    t = issue_mcp_access_token(user_id=7, client_id="c1", scopes=["market:read"], grant_id=3)
    payload = decode_mcp_access_token(t)
    assert payload is not None
    assert "exp" not in payload, "MCP token 授权不过期 —— 不能带 exp"
    assert payload["aud"] == "mcp"
    assert payload["sub"] == "7"
    assert payload["scopes"] == ["market:read"]


def test_login_token_is_not_accepted_as_mcp_token():
    """平台登录 JWT 没有 aud=mcp —— 绝不能当 MCP token 用."""
    from app.core.security import create_access_token

    token, _ = create_access_token(1)
    assert decode_mcp_access_token(token) is None


def test_tampered_token_is_rejected():
    t = issue_mcp_access_token(user_id=7, client_id="c1", scopes=["market:read"], grant_id=None)
    assert decode_mcp_access_token(t[:-2] + "xy") is None


@pytest.mark.asyncio
async def test_revoked_grant_makes_verifier_fail():
    from app.mcp.common.auth import OAuthTokenVerifier

    async with AsyncSessionLocal() as s:
        s.add(McpOAuthGrant(
            user_id=999001, client_id="c-revoked", client_name="x",
            scopes=["market:read"], created_at=datetime.utcnow(),
        ))
        await s.commit()

    verifier = OAuthTokenVerifier()
    token = issue_mcp_access_token(user_id=999001, client_id="c-revoked",
                                  scopes=["market:read"], grant_id=None)
    assert await verifier.verify_token(token) is not None

    async with AsyncSessionLocal() as s:
        g = (await s.execute(
            select(McpOAuthGrant).where(McpOAuthGrant.user_id == 999001)
        )).scalars().first()
        assert g is not None
        g.revoked_at = datetime.utcnow()
        await s.commit()

    assert await verifier.verify_token(token) is None
```

- [ ] **Step 2: 跑测试确认失败**

Run: `cd backend_gateway && pytest tests/test_mcp_auth.py -v`
Expected: FAIL —— `ModuleNotFoundError: No module named 'app.mcp.common.auth'`

- [ ] **Step 3: 写鉴权层**

创建 `backend_gateway/app/mcp/common/auth.py`：

```python
"""MCP 鉴权层 —— 凭证 → Principal.

设计文档 §4.4（鉴权层的可插拔结构）与 §4.7（吊销模型）。

三条不变量之一：**鉴权只有一处** —— 凭证解析永远在这里，
工具通过 McpContext 拿身份，永不自己读 header。
"""

from __future__ import annotations

import hashlib
import secrets
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any, Protocol

import jwt as pyjwt
from mcp.server.auth.provider import AccessToken
from sqlalchemy import select

from app.core.config import settings
from app.db.session import AsyncSessionLocal
from app.models.mcp import McpApiToken, McpOAuthGrant

#: MCP access token 的 audience —— 与平台登录 JWT 区分（登录 token 没有 aud）
MCP_TOKEN_AUD = "mcp"

#: 平台接入令牌前缀（便于在日志里一眼认出）
API_TOKEN_PREFIX = "tm_live_"


@dataclass(frozen=True)
class Principal:
    """一次工具调用的身份（OAuth 与静态令牌共用同一形状）."""

    user_id: int
    username: str
    role: str
    client_id: str
    client_name: str
    scopes: frozenset[str]
    grant_id: int | None = None


class TokenVerifier(Protocol):
    async def verify_token(self, token: str) -> AccessToken | None: ...


def issue_mcp_access_token(
    *, user_id: int, client_id: str, scopes: list[str], grant_id: int | None = None
) -> str:
    """签发 MCP access token —— **不带 exp**（授权不过期），但带 aud='mcp'."""
    now = int(datetime.utcnow().timestamp())
    payload = {
        "sub": str(user_id),
        "client_id": client_id,
        "scopes": list(scopes),
        "grant_id": grant_id,
        "aud": MCP_TOKEN_AUD,
        "iat": now,
    }
    return pyjwt.encode(payload, settings.JWT_SECRET, algorithm=settings.JWT_ALGORITHM)


def decode_mcp_access_token(token: str) -> dict[str, Any] | None:
    """校验 MCP access token —— 签名 + aud；**不查 exp**（本来就没有）."""
    try:
        payload = pyjwt.decode(token, settings.JWT_SECRET, algorithms=[settings.JWT_ALGORITHM])
    except Exception:
        return None
    if payload.get("aud") != MCP_TOKEN_AUD:
        return None
    return payload


def hash_api_token(raw: str) -> str:
    return hashlib.sha256(raw.encode()).hexdigest()


def new_api_token() -> str:
    return API_TOKEN_PREFIX + secrets.token_urlsafe(32)


class OAuthTokenVerifier:
    """OAuth access token —— 验签 + 查 grant（确认未撤销）.

    ⚠️ 每次调用都要查一次 grant：token 无状态且不过期，
    grant 表是唯一的吊销入口（§4.7）。
    """

    async def verify_token(self, token: str) -> AccessToken | None:
        payload = decode_mcp_access_token(token)
        if payload is None:
            return None
        try:
            user_id = int(payload.get("sub") or 0)
        except (TypeError, ValueError):
            return None
        client_id = str(payload.get("client_id") or "")
        if not user_id or not client_id:
            return None

        async with AsyncSessionLocal() as s:
            grant = (await s.execute(
                select(McpOAuthGrant).where(
                    McpOAuthGrant.user_id == user_id,
                    McpOAuthGrant.client_id == client_id,
                )
            )).scalars().first()
            if grant is None or grant.revoked_at is not None:
                return None
            scopes = list(payload.get("scopes") or [])
            grant.last_used_at = datetime.utcnow()
            await s.commit()

        return AccessToken(
            token=token,
            client_id=client_id,
            scopes=scopes,
            expires_at=None,          # 不过期
            subject=str(user_id),
            claims={"grant_id": grant.id, "scopes": scopes},
        )


class StaticTokenVerifier:
    """平台接入令牌（adminOnly，CI / 脚本 / 兜底）."""

    async def verify_token(self, token: str) -> AccessToken | None:
        if not token.startswith(API_TOKEN_PREFIX):
            return None
        digest = hash_api_token(token)
        async with AsyncSessionLocal() as s:
            row = (await s.execute(
                select(McpApiToken).where(McpApiToken.token_hash == digest)
            )).scalars().first()
            if row is None or row.revoked_at is not None:
                return None
            if row.expires_at is not None and row.expires_at < datetime.utcnow():
                return None
            row.last_used_at = datetime.utcnow()
            await s.commit()
            scopes = list(row.scopes or [])
            user_id = int(row.created_by or 0)
        return AccessToken(
            token=token,
            client_id="static",
            scopes=scopes,
            expires_at=None,
            subject=str(user_id),
            claims={"label": row.label, "scopes": scopes},
        )


#: 凭证验证器注册表 —— 加新凭证类型 = 加一个实现 + 注册一行（§3.6 扩展点）
VERIFIERS: list[TokenVerifier] = [OAuthTokenVerifier(), StaticTokenVerifier()]
```

- [ ] **Step 4: 跑测试确认通过**

Run: `cd backend_gateway && pytest tests/test_mcp_auth.py -v`
Expected: PASS（4 passed）

- [ ] **Step 5: 提交**

```bash
git add backend_gateway/app/mcp/common/auth.py backend_gateway/tests/test_mcp_auth.py
git commit -m "feat(MCP): 鉴权层 —— OAuth/静态两种 TokenVerifier + Principal（token 无 exp、带 aud=mcp）"
```

---

### Task 6: OAuth 端到端集成测试（发现链路 + 撤销）

**Files:**
- Create: `backend_gateway/tests/_lifespan.py`
- Create: `backend_gateway/tests/test_mcp_oauth_flow.py`
- Modify: `backend_gateway/app/main.py`

**Interfaces:**
- Consumes: `build_oauth_router`、`TestMateOAuthProvider`、`VERIFIERS`
- Produces:
  - `tests/_lifespan.py::lifespan_driver(app)` —— 手动驱动 ASGI lifespan（`httpx.ASGITransport` **不触发** lifespan）
  - `app/main.py` 里挂上 OAuth router（`app.include_router(mcp_oauth_router)`）
  - `app/mcp/common/oauth_provider.py` 暴露**进程级单例** `oauth_provider`（Task 7 的同意页要用同一个实例）

- [ ] **Step 1: 写 lifespan 驱动**

创建 `backend_gateway/tests/_lifespan.py`：

```python
"""手动驱动 ASGI lifespan —— httpx.ASGITransport **不会**触发它.

不驱动就会报: RuntimeError: Task group is not initialized. Make sure to use run()
"""

from __future__ import annotations

from contextlib import asynccontextmanager
from typing import AsyncIterator

from asgi_lifespan import LifespanManager  # type: ignore[import-not-found]


@asynccontextmanager
async def lifespan_driver(app) -> AsyncIterator[None]:
    """进入 app 的 lifespan（跑 startup，退出时跑 shutdown）."""
    async with LifespanManager(app):
        yield
```

> ⚠️ 若 `asgi_lifespan` 不在依赖里，改为手写（不引新依赖）：
> ```python
> @asynccontextmanager
> async def lifespan_driver(app):
>     import asyncio
>     receive_q: asyncio.Queue = asyncio.Queue()
>     send_q: asyncio.Queue = asyncio.Queue()
>     scope = {"type": "lifespan", "asgi": {"version": "3.0"}}
>     task = asyncio.create_task(app(scope, receive_q.get, send_q.put))
>     await receive_q.put({"type": "lifespan.startup"})
>     msg = await send_q.get()
>     assert msg["type"] == "lifespan.startup.complete", msg
>     try:
>         yield
>     finally:
>         await receive_q.put({"type": "lifespan.shutdown"})
>         await send_q.get()
>         task.cancel()
> ```

- [ ] **Step 2: 写失败的端到端测试**

创建 `backend_gateway/tests/test_mcp_oauth_flow.py`：

```python
"""OAuth 全流程 —— 发现 → 注册 → 授权 → 换 token → 用 token → 撤销."""

from __future__ import annotations

import base64
import hashlib

import pytest
from httpx import ASGITransport, AsyncClient

from tests._lifespan import lifespan_driver


def _s256(v: str) -> str:
    return base64.urlsafe_b64encode(hashlib.sha256(v.encode()).digest()).decode().rstrip("=")


@pytest.mark.asyncio
async def test_full_oauth_flow():
    from app.main import app

    async with lifespan_driver(app):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://testserver") as c:
            # ① AS 元数据
            r = await c.get("/.well-known/oauth-authorization-server")
            assert r.status_code == 200, r.text
            as_meta = r.json()
            assert as_meta["issuer"]

            # ② PR 元数据
            r = await c.get("/.well-known/oauth-protected-resource/mcp/skill")
            assert r.status_code == 200, r.text
            assert r.json()["authorization_servers"]

            # ③ DCR
            r = await c.post("/oauth/register", json={
                "redirect_uris": ["http://127.0.0.1:51234/cb"],
                "client_name": "Qoder",
            })
            assert r.status_code == 201, r.text
            cid = r.json()["client_id"]
            assert r.json()["token_endpoint_auth_method"] == "none"

            # ④ authorize → 302 到同意页
            verifier = "verifier-" + "x" * 40
            r = await c.get("/oauth/authorize", params={
                "client_id": cid,
                "redirect_uri": "http://127.0.0.1:51234/cb",
                "response_type": "code",
                "code_challenge": _s256(verifier),
                "code_challenge_method": "S256",
                "state": "st",
                "scope": "market:read",
            }, follow_redirects=False)
            assert r.status_code == 302, r.text
            ticket = r.headers["location"].split("ticket=", 1)[1]

            # ⑤ 同意（Task 7 的 API 未就绪前，这里直接调 provider）
            from app.mcp.common.oauth_provider import oauth_provider

            code = await oauth_provider.approve_pending(
                ticket, user_id=424242, username="probe@x.com", scopes=["market:read"]
            )

            # ⑥ 换 token
            r = await c.post("/oauth/token", data={
                "grant_type": "authorization_code",
                "code": code,
                "redirect_uri": "http://127.0.0.1:51234/cb",
                "client_id": cid,
                "code_verifier": verifier,
            })
            assert r.status_code == 200, r.text
            tok = r.json()
            assert tok["access_token"]
            assert "expires_in" not in tok or tok["expires_in"] is None

            # ⑦ token 无 exp、带 aud=mcp
            from app.mcp.common.auth import decode_mcp_access_token

            payload = decode_mcp_access_token(tok["access_token"])
            assert payload is not None
            assert "exp" not in payload
            assert payload["aud"] == "mcp"

            # ⑧ 用 token 调 MCP（此时 MCP 端点可能还没实现 —— 先只验 401 消失）
            r = await c.post("/mcp/skill", json={
                "jsonrpc": "2.0", "id": 1, "method": "initialize",
                "params": {"protocolVersion": "2025-06-18", "capabilities": {},
                           "clientInfo": {"name": "probe", "version": "1"}},
            }, headers={"Authorization": f"Bearer {tok['access_token']}",
                        "Accept": "application/json, text/event-stream",
                        "Content-Type": "application/json"})
            assert r.status_code != 401, r.text
```

- [ ] **Step 3: 跑测试确认失败**

Run: `cd backend_gateway && pytest tests/test_mcp_oauth_flow.py -v`
Expected: FAIL —— `/.well-known/oauth-authorization-server` 404（路由还没挂到主应用）

- [ ] **Step 4: 暴露进程级 provider 单例**

修改 `backend_gateway/app/mcp/common/oauth_provider.py`，在文件末尾追加：

```python
#: 进程级单例 —— 同意页（Task 7）与路由层必须共用同一个实例
#: （授权码与待处理请求都在内存里，两个实例就互相看不见了）
oauth_provider = TestMateOAuthProvider()
```

- [ ] **Step 5: 挂到主应用**

修改 `backend_gateway/app/main.py`：

```python
# 顶部 import 区
from app.mcp.common.oauth_provider import oauth_provider
from app.mcp.common.oauth_routes import build_oauth_router
```

在 app 创建之后、`include_router` 的位置（与既有 `/api/v1` 路由注册并列）加：

```python
# ===== MCP OAuth（自写路由：SDK 的 create_auth_routes 强制 HTTPS，内网 http 用不了）=====
_mcp_base = (await _setting("marketplace.public_base_url", "")) if False else ""  # 占位，见下
```

> ⚠️ **issuer 的取值**：设计文档 §15 已写明 —— issuer / resource URL **在装配时固化**，
> 改 `marketplace.public_base_url` 需重启后端。因此这里用**同步读取**的方式拿配置。
> 实现：用 `app.core.settings_store.get()` 是 async —— 但 `include_router` 必须在模块加载期同步完成。
> **解决**：新增一个同步读取入口，或在 lifespan 里改写路由。
> **本任务采用**：在 `app/main.py` 用 `settings_store.get_sync_or_cached()` —— 若不存在，
> 则改为「从环境变量 `MCP_ISSUER_URL` 读，默认回落 `http://127.0.0.1:8000`」，
> 并在 §10.4 的内置连接器 url 生成里用同一个来源（保证两处一致）。

具体落地（**照抄**）：

```python
import os

def _mcp_issuer_url() -> str:
    """OAuth issuer —— **装配时固化**（改 public_base_url 需重启后端，见设计文档 §15）."""
    return (os.environ.get("MCP_ISSUER_URL") or "http://127.0.0.1:8000").rstrip("/")


_MCP_ISSUER = _mcp_issuer_url()
mcp_oauth_router = build_oauth_router(
    oauth_provider,
    issuer_url=_MCP_ISSUER,
    resource_server_url=f"{_MCP_ISSUER}/mcp/skill",
    scopes=["market:read", "market:write"],
)
app.include_router(mcp_oauth_router)
```

> 📌 `MCP_ISSUER_URL` 写进 `deploy/docker-compose.yml` 与裸机 systemd 的 EnvironmentFile
> （Task 21 处理），默认值与 `marketplace.public_base_url` 一致。

- [ ] **Step 6: 跑测试确认通过**

Run: `cd backend_gateway && pytest tests/test_mcp_oauth_flow.py -v`
Expected: PASS（1 passed）

- [ ] **Step 7: 跑全量后端测试确认没打破既有行为**

Run: `cd backend_gateway && pytest -q`
Expected: 全部通过（既有 40+ 测试文件不能红）

- [ ] **Step 8: 提交**

```bash
git add backend_gateway/app/main.py backend_gateway/app/mcp/common/oauth_provider.py \
        backend_gateway/tests/_lifespan.py backend_gateway/tests/test_mcp_oauth_flow.py
git commit -m "feat(MCP): OAuth 端到端打通 —— 发现链路 + DCR + 授权码换 token（无 exp）"
```

---

# Stage S2 — 同意页 + 授权管理

### Task 7: 后端 `/api/v1/mcp/*` 端点（同意页提交 + 授权列表 + 接入令牌）

**Files:**
- Create: `backend_gateway/app/api/mcp.py`
- Modify: `backend_gateway/app/main.py`
- Modify: `backend_gateway/app/mcp/common/oauth_provider.py`（新增 grant 落库 + 撤销）
- Test: `backend_gateway/tests/test_mcp_api.py`

**Interfaces:**
- Consumes: `app.mcp.common.oauth_provider.oauth_provider`、`app.mcp.common.auth`、`app.models.mcp.*`、`app.api.auth.get_current_user`
- Produces（router prefix `/api/v1/mcp`）：
  - `GET  /oauth/authorize-info?ticket=` → `{client_name, requested_scopes[], redirect_uri, resource}`
  - `POST /oauth/consent` body `{ticket, granted_scopes[]}` / `{ticket, deny:true}` → **302** 到 `redirect_uri?code=…&state=…`（或 `?error=access_denied`）
  - `GET  /grants` → `[{client_id, client_name, scopes[], created_at, last_used_at}]`
  - `DELETE /grants/{client_id}` → 撤销
  - `GET  /connection-config` → `{mcpServers: {...}}`（Qoder 格式）
  - `GET  /tokens` / `POST /tokens` / `DELETE /tokens/{id}`（**adminOnly**）

- [ ] **Step 1: 写失败的测试**

创建 `backend_gateway/tests/test_mcp_api.py`：

```python
"""MCP 平台端点 —— 同意页提交 / 我的授权 / 接入令牌 / 连接器配置."""

from __future__ import annotations

import pytest
from httpx import ASGITransport, AsyncClient

from tests._lifespan import lifespan_driver


@pytest.mark.asyncio
async def test_consent_approve_redirects_with_code():
    from app.main import app
    from app.mcp.common.oauth_provider import oauth_provider

    async with lifespan_driver(app):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://testserver") as c:
            reg = await c.post("/oauth/register", json={"redirect_uris": ["http://127.0.0.1:51234/cb"]})
            cid = reg.json()["client_id"]
            import base64, hashlib

            def s256(v: str) -> str:
                return base64.urlsafe_b64encode(hashlib.sha256(v.encode()).digest()).decode().rstrip("=")

            r = await c.get("/oauth/authorize", params={
                "client_id": cid, "redirect_uri": "http://127.0.0.1:51234/cb",
                "response_type": "code", "code_challenge": s256("v"),
                "code_challenge_method": "S256", "state": "st", "scope": "market:read",
            }, follow_redirects=False)
            ticket = r.headers["location"].split("ticket=", 1)[1]

            # 未登录 → 401
            r = await c.get("/api/v1/mcp/oauth/authorize-info", params={"ticket": ticket})
            assert r.status_code == 401

            # 用管理员身份（测试里直接造 token）
            from app.core.security import create_access_token
            token, _ = create_access_token(_admin_id())
            hdr = {"Authorization": f"Bearer {token}"}

            r = await c.get("/api/v1/mcp/oauth/authorize-info", params={"ticket": ticket}, headers=hdr)
            assert r.status_code == 200, r.text
            assert r.json()["client_name"]

            r = await c.post("/api/v1/mcp/oauth/consent",
                             json={"ticket": ticket, "granted_scopes": ["market:read"]},
                             headers=hdr, follow_redirects=False)
            assert r.status_code == 302, r.text
            assert "code=" in r.headers["location"]
            assert r.headers["location"].startswith("http://127.0.0.1:51234/cb")


def _admin_id() -> int:
    """测试库里造一个 admin 用户，返回其 id."""
    import asyncio

    from app.db.session import AsyncSessionLocal
    from app.models.user import User

    async def _mk() -> int:
        async with AsyncSessionLocal() as s:
            u = User(username="mcp-admin@x.com", password_hash="x", role="admin")
            s.add(u)
            await s.commit()
            await s.refresh(u)
            return u.id

    return asyncio.get_event_loop().run_until_complete(_mk())
```

> ⚠️ 若 `app/models/user.py` 的字段名与上面不同（`username` / `password_hash` / `role`），
> 先 `sed -n '1,60p' backend_gateway/app/models/user.py` 核对后再写；**不要照抄不存在的字段**。
> 其它测试文件（`tests/test_user_admin.py`）里有现成的「造用户」写法，优先复用那个。

- [ ] **Step 2: 跑测试确认失败**

Run: `cd backend_gateway && pytest tests/test_mcp_api.py -v`
Expected: FAIL —— 404（`/api/v1/mcp/*` 还没注册）

- [ ] **Step 3: 给 provider 加 grant 落库与撤销**

修改 `backend_gateway/app/mcp/common/oauth_provider.py`，在 `TestMateOAuthProvider` 里增加两个方法：

```python
    async def persist_grant(self, *, user_id: int, client_id: str, client_name: str,
                            scopes: list[str]) -> int:
        """授权落库（同意时调用）—— 返回 grant.id."""
        from datetime import datetime

        from app.db.session import AsyncSessionLocal
        from app.models.mcp import McpOAuthGrant
        from sqlalchemy import select

        async with AsyncSessionLocal() as s:
            row = (await s.execute(select(McpOAuthGrant).where(
                McpOAuthGrant.user_id == user_id, McpOAuthGrant.client_id == client_id
            ))).scalars().first()
            if row is None:
                row = McpOAuthGrant(user_id=user_id, client_id=client_id,
                                    client_name=client_name, scopes=list(scopes),
                                    created_at=datetime.utcnow())
                s.add(row)
            else:
                row.scopes = list(scopes)
                row.client_name = client_name
                row.revoked_at = None
            await s.commit()
            await s.refresh(row)
            return int(row.id)

    async def revoke_grant(self, *, user_id: int, client_id: str) -> bool:
        """撤销一条授权 —— 下一个请求立刻失效."""
        from datetime import datetime

        from app.db.session import AsyncSessionLocal
        from app.models.mcp import McpOAuthGrant
        from sqlalchemy import select

        async with AsyncSessionLocal() as s:
            row = (await s.execute(select(McpOAuthGrant).where(
                McpOAuthGrant.user_id == user_id, McpOAuthGrant.client_id == client_id
            ))).scalars().first()
            if row is None:
                return False
            row.revoked_at = datetime.utcnow()
            await s.commit()
            return True
```

同时把 `approve_pending` 改成**落库 + 返回 (code, grant_id)**：

```python
    async def approve_pending(
        self, ticket: str, *, user_id: int, username: str, scopes: list[str]
    ) -> tuple[str, int]:
        """同意页点了「同意」→ 建授权码 + 落库 grant，返回 (code, grant_id)."""
        req = self._pending.pop(ticket, None)
        if req is None:
            raise TokenError(error="invalid_request", error_description="授权请求已失效或已被使用")
        granted = [s for s in scopes if s in SUPPORTED_SCOPES]
        if not granted:
            raise TokenError(error="invalid_scope", error_description="至少要授予一个 scope")
        grant_id = await self.persist_grant(user_id=user_id, client_id=req.client_id,
                                           client_name=req.client_name, scopes=granted)
        code = secrets.token_urlsafe(32)
        self._codes[code] = AuthorizationCode(
            code=code, scopes=granted, expires_at=time.time() + AUTH_CODE_TTL,
            client_id=req.client_id, code_challenge=req.code_challenge,
            redirect_uri=req.redirect_uri, redirect_uri_provided_explicitly=True,
            resource=req.resource, subject=str(user_id),
        )
        self._grants[(user_id, req.client_id)] = _Grant(
            user_id=user_id, client_id=req.client_id, scopes=granted
        )
        return code, grant_id
```

> ⚠️ **同步改两处已有测试**（返回值从 `str` 变成 `tuple[str, int]`）：
> · `tests/test_mcp_oauth_provider.py`（Task 3 写的）：
>   `code = await p.approve_pending(...)` → `code, _grant_id = await p.approve_pending(...)`
> · `tests/test_mcp_oauth_flow.py`（Task 6 写的）：同一处改法。
>
> ⚠️ 这两处**必须一起改**，否则 Task 6/7 的测试会红 —— 这是有意的：
> 接口变了，旧调用点必须跟着变。

- [ ] **Step 4: 写 API**

创建 `backend_gateway/app/api/mcp.py`：

```python
"""MCP 平台端点 —— 同意页 / 我的授权 / 接入令牌 / 连接器配置.

设计文档 §4.5（同意页）、§4.7（我的授权）、§4.11（接入令牌）、§10.5（连接器配置）。
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import RedirectResponse
from pydantic import BaseModel, Field
from sqlalchemy import select

from app.api.auth import get_current_user
from app.core.config import settings
from app.db.session import AsyncSessionLocal
from app.mcp.common.auth import (
    API_TOKEN_PREFIX,
    hash_api_token,
    new_api_token,
)
from app.mcp.common.oauth_provider import oauth_provider
from app.models.mcp import McpApiToken, McpOAuthGrant
from app.models.user import User

router = APIRouter(prefix="/api/v1/mcp", tags=["mcp"])


class ConsentIn(BaseModel):
    ticket: str = Field(..., min_length=8)
    granted_scopes: list[str] = Field(default_factory=list)
    deny: bool = False


@router.get("/oauth/authorize-info")
async def authorize_info(ticket: str = Query(...), user: User = Depends(get_current_user)) -> dict[str, Any]:
    """同意页渲染用 —— 客户端名 + 请求的 scope."""
    req = oauth_provider.get_pending(ticket)
    if req is None:
        raise HTTPException(status_code=404, detail="授权请求已失效，请重新发起授权")
    return {
        "client_name": req.client_name,
        "requested_scopes": req.scopes,
        "redirect_uri": req.redirect_uri,
        "resource": req.resource,
    }


@router.post("/oauth/consent")
async def consent(body: ConsentIn, user: User = Depends(get_current_user)) -> RedirectResponse:
    """同意 / 拒绝 → 302 回客户端的 redirect_uri."""
    req = oauth_provider.get_pending(body.ticket)
    if req is None:
        raise HTTPException(status_code=404, detail="授权请求已失效，请重新发起授权")

    from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

    parts = urlsplit(req.redirect_uri)
    query = dict(parse_qsl(parts.query))

    if body.deny:
        await oauth_provider.deny_pending(body.ticket)
        query.update({"error": "access_denied"})
        if req.state:
            query["state"] = req.state
        return RedirectResponse(
            urlunsplit((parts.scheme, parts.netloc, parts.path, urlencode(query), parts.fragment)),
            status_code=302,
        )

    try:
        code, _grant_id = await oauth_provider.approve_pending(
            body.ticket, user_id=user.id, username=user.username, scopes=body.granted_scopes
        )
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    query["code"] = code
    if req.state:
        query["state"] = req.state
    return RedirectResponse(
        urlunsplit((parts.scheme, parts.netloc, parts.path, urlencode(query), parts.fragment)),
        status_code=302,
    )


@router.get("/grants")
async def list_grants(user: User = Depends(get_current_user)) -> list[dict[str, Any]]:
    """我的授权."""
    async with AsyncSessionLocal() as s:
        rows = (await s.execute(select(McpOAuthGrant).where(
            McpOAuthGrant.user_id == user.id
        ).order_by(McpOAuthGrant.created_at.desc()))).scalars().all()
        return [
            {
                "client_id": g.client_id,
                "client_name": g.client_name,
                "scopes": list(g.scopes or []),
                "created_at": g.created_at.isoformat() if g.created_at else None,
                "last_used_at": g.last_used_at.isoformat() if g.last_used_at else None,
                "revoked_at": g.revoked_at.isoformat() if g.revoked_at else None,
            }
            for g in rows
        ]


@router.delete("/grants/{client_id}")
async def revoke_grant(client_id: str, user: User = Depends(get_current_user)) -> dict[str, Any]:
    """撤销我的某个授权 —— 该客户端的 token 下一个请求就 401."""
    ok = await oauth_provider.revoke_grant(user_id=user.id, client_id=client_id)
    if not ok:
        raise HTTPException(status_code=404, detail="没有这条授权")
    return {"ok": True}


@router.get("/connection-config")
async def connection_config(user: User = Depends(get_current_user)) -> dict[str, Any]:
    """Qoder 格式的连接器配置（**不含任何密钥**）."""
    import os

    base = (os.environ.get("MCP_ISSUER_URL") or "http://127.0.0.1:8000").rstrip("/")
    return {
        "mcpServers": {
            "testmate": {
                "type": "http",
                "url": f"{base}/mcp/skill",
            }
        }
    }


# ===== 平台接入令牌（adminOnly，CI / 脚本 / 兜底） =====

def _require_admin(user: User) -> None:
    role = getattr(user.role, "value", user.role)
    if str(role) != "admin":
        raise HTTPException(status_code=403, detail="仅管理员可管理平台接入令牌")


@router.get("/tokens")
async def list_tokens(user: User = Depends(get_current_user)) -> list[dict[str, Any]]:
    _require_admin(user)
    async with AsyncSessionLocal() as s:
        rows = (await s.execute(select(McpApiToken).order_by(McpApiToken.created_at.desc()))).scalars().all()
        return [
            {
                "id": r.id, "label": r.label, "prefix": r.token_prefix,
                "scopes": list(r.scopes or []),
                "created_at": r.created_at.isoformat() if r.created_at else None,
                "expires_at": r.expires_at.isoformat() if r.expires_at else None,
                "revoked_at": r.revoked_at.isoformat() if r.revoked_at else None,
            }
            for r in rows
        ]


@router.post("/tokens")
async def create_token(
    label: str = Query(""),
    scopes: str = Query("market:read market:write"),
    expires_days: int = Query(0, ge=0),
    user: User = Depends(get_current_user),
) -> dict[str, Any]:
    _require_admin(user)
    raw = new_api_token()
    async with AsyncSessionLocal() as s:
        row = McpApiToken(
            token_prefix=raw[: len(API_TOKEN_PREFIX) + 4],
            token_hash=hash_api_token(raw),
            label=label,
            scopes=[x for x in scopes.split() if x],
            created_by=user.id,
            created_at=datetime.utcnow(),
            expires_at=(datetime.utcnow() + __import__("datetime").timedelta(days=expires_days))
            if expires_days > 0 else None,
        )
        s.add(row)
        await s.commit()
    return {"token": raw, "id": row.id, "note": "明文只显示这一次，请立即保存"}


@router.delete("/tokens/{token_id}")
async def revoke_token(token_id: int, user: User = Depends(get_current_user)) -> dict[str, Any]:
    _require_admin(user)
    async with AsyncSessionLocal() as s:
        row = (await s.execute(select(McpApiToken).where(McpApiToken.id == token_id))).scalars().first()
        if row is None:
            raise HTTPException(status_code=404, detail="令牌不存在")
        row.revoked_at = datetime.utcnow()
        await s.commit()
    return {"ok": True}
```

- [ ] **Step 5: 注册路由**

修改 `backend_gateway/app/main.py`，在既有 `/api/v1` 路由注册处加：

```python
from app.api.mcp import router as mcp_api_router

app.include_router(mcp_api_router)
```

- [ ] **Step 6: 跑测试确认通过**

Run: `cd backend_gateway && pytest tests/test_mcp_api.py tests/test_mcp_oauth_flow.py tests/test_mcp_oauth_provider.py -v`
Expected: PASS

- [ ] **Step 7: 提交**

```bash
git add backend_gateway/app/api/mcp.py backend_gateway/app/main.py \
        backend_gateway/app/mcp/common/oauth_provider.py backend_gateway/tests/
git commit -m "feat(MCP): 平台端点 —— 同意页提交 / 我的授权与撤销 / 接入令牌 / 连接器配置"
```

---

### Task 8: 前端同意页（`/connect/authorize`）

**Files:**
- Create: `frontend_web/src/api/mcp.ts`
- Create: `frontend_web/src/views/Connect/authorize.vue`
- Modify: `frontend_web/src/router/index.ts`

**Interfaces:**
- Consumes: `GET /api/v1/mcp/oauth/authorize-info?ticket=`、`POST /api/v1/mcp/oauth/consent`
- Produces: SPA 路由 `/connect/authorize?ticket=…`；`api/mcp.ts` 导出 `getAuthorizeInfo`、`submitConsent`、`getConnectionConfig`

- [ ] **Step 1: 写 API 封装**

创建 `frontend_web/src/api/mcp.ts`：

```ts
/** MCP 平台接口 —— 同意页 / 我的授权 / 接入令牌 / 连接器配置.
 *
 * 后端前缀 /api/v1/mcp (app/api/mcp.py).
 */
import { apiGet, apiPost, apiDelete } from '@/utils/request';

export interface AuthorizeInfo {
    client_name: string;
    requested_scopes: string[];
    redirect_uri: string;
    resource: string | null;
}

export interface McpGrant {
    client_id: string;
    client_name: string;
    scopes: string[];
    created_at: string | null;
    last_used_at: string | null;
    revoked_at: string | null;
}

export interface McpToken {
    id: number;
    label: string;
    prefix: string;
    scopes: string[];
    created_at: string | null;
    expires_at: string | null;
    revoked_at: string | null;
}

/** 同意页要展示的 scope 清单（后端是唯一真源，这里只是文案） */
export const SCOPE_LABELS: Record<string, string> = {
    'market:read': '读取技能（搜索 / 看详情 / 读文档 / 取包）',
    'market:write': '上架与更新技能（写操作，会走审核）',
};

export function getAuthorizeInfo(ticket: string) {
    return apiGet<AuthorizeInfo>('/mcp/oauth/authorize-info', { params: { ticket } });
}

export function submitConsent(ticket: string, grantedScopes: string[], deny = false) {
    return apiPost('/mcp/oauth/consent', { ticket, granted_scopes: grantedScopes, deny });
}

export function listGrants() {
    return apiGet<McpGrant[]>('/mcp/grants');
}

export function revokeGrant(clientId: string) {
    return apiDelete(`/mcp/grants/${encodeURIComponent(clientId)}`);
}

export function listTokens() {
    return apiGet<McpToken[]>('/mcp/tokens');
}

export function createToken(label: string, scopes: string[], expiresDays = 0) {
    return apiPost<{ token: string; id: number; note: string }>('/mcp/tokens', undefined, {
        params: { label, scopes: scopes.join(' '), expires_days: expiresDays },
    });
}

export function revokeToken(id: number) {
    return apiDelete(`/mcp/tokens/${id}`);
}

export function getConnectionConfig() {
    return apiGet<{ mcpServers: Record<string, { type: string; url: string }> }>('/mcp/connection-config');
}
```

> ⚠️ **先核对 `utils/request.ts` 里 `apiGet` / `apiPost` / `apiDelete` 的真实签名**
> （`sed -n '1,140p' frontend_web/src/utils/request.ts`）。若 `apiPost` 不接受第三个参数
> （axios config），改用 `apiPost(url, body)` + query 拼在 url 上。**不要凭空假设签名。**

- [ ] **Step 2: 写同意页**

创建 `frontend_web/src/views/Connect/authorize.vue`：

```vue
<template>
  <div class="tm-page">
    <h1 class="tm-page-title">授权 TestMate</h1>
    <p class="tm-lede">
      <strong>{{ info?.client_name || '某个客户端' }}</strong>
      想访问 TestMate 的技能市场能力。请确认它能做什么。
    </p>

    <el-alert v-if="error" type="error" :title="error" show-icon class="mb" />

    <div v-else-if="info" class="tm-card">
      <div class="tm-card-title">请求的权限</div>
      <el-checkbox-group v-model="picked">
        <el-checkbox v-for="s in info.requested_scopes" :key="s" :value="s" :disabled="!allowed(s)">
          {{ SCOPE_LABELS[s] || s }}
          <span v-if="!allowed(s)" class="tm-hint">（当前账号没有这个能力）</span>
        </el-checkbox>
      </el-checkbox-group>

      <div class="tm-actions">
        <el-button type="primary" :loading="busy" @click="agree">同意</el-button>
        <el-button :loading="busy" @click="deny">拒绝</el-button>
      </div>
      <p class="tm-hint">授权长期有效，但你可以随时在「我的授权」里撤销。</p>
    </div>

    <p v-else class="tm-hint">加载中…</p>
  </div>
</template>

<script setup lang="ts">
import { onMounted, ref } from 'vue';
import { useRoute } from 'vue-router';
import { ElMessage } from 'element-plus';
import { getAuthorizeInfo, submitConsent, SCOPE_LABELS, type AuthorizeInfo } from '@/api/mcp';

const route = useRoute();
const info = ref<AuthorizeInfo | null>(null);
const picked = ref<string[]>([]);
const error = ref('');
const busy = ref(false);

/** 我能授出去的上限 —— 非发布者只能给读 */
function allowed(scope: string): boolean {
    if (scope === 'market:write') {
        const role = localStorage.getItem('tm_user_role') || '';
        return role === 'admin' || role === 'tester';
    }
    return true;
}

onMounted(async () => {
    const ticket = String(route.query.ticket || '');
    if (!ticket) {
        error.value = '缺少授权请求参数，请回到客户端重新发起授权';
        return;
    }
    try {
        info.value = await getAuthorizeInfo(ticket);
        picked.value = info.value.requested_scopes.filter(allowed);
    } catch (e: any) {
        error.value = e?.message || '授权请求已失效，请回到客户端重新发起授权';
    }
});

async function agree() {
    const ticket = String(route.query.ticket || '');
    busy.value = true;
    try {
        await submitConsent(ticket, picked.value, false);
        // 后端返回 302 → 浏览器自动跳回客户端
    } catch (e: any) {
        ElMessage.error(e?.message || '授权失败');
        busy.value = false;
    }
}

async function deny() {
    const ticket = String(route.query.ticket || '');
    busy.value = true;
    try {
        await submitConsent(ticket, [], true);
    } catch (e: any) {
        ElMessage.error(e?.message || '操作失败');
        busy.value = false;
    }
}
</script>
```

> ⚠️ **「能不能授 write」不要在前端硬编码角色** —— 后端 `market_policy.can_publish` 才是真源。
> 本页的 `allowed()` 只是**提前禁用勾选**（体验），后端在提交时会再校验一次并拒绝越权 scope。
> 若前端已有 `useUserStore()` 能拿到角色，改用它；拿不到就保留现在的保守实现（只给读）。

- [ ] **Step 3: 加路由**

修改 `frontend_web/src/router/index.ts`，在 `children` 数组里（`market` 那条之后）加：

```ts
        // ===== OAuth 同意页 (2026-10-31) =====
        // ⚠️ 路径**不能**放在 /mcp 下: nginx 的 `location /mcp` 是前缀匹配,
        //    会把 SPA 路由劫持到后端 → 404.
        { path: 'connect/authorize', name: 'mcp-authorize', meta: { title: '授权' }, component: () => import('@/views/Connect/authorize.vue') },
```

- [ ] **Step 4: 前端构建校验**

Run: `cd frontend_web && npm run build`
Expected: 构建成功，无 TS 报错

- [ ] **Step 5: 提交**

```bash
git add frontend_web/src/api/mcp.ts frontend_web/src/views/Connect/authorize.vue frontend_web/src/router/index.ts
git commit -m "feat(MCP): 前端同意页 —— /connect/authorize 显示客户端与 scope 逐条勾选"
```

---

### Task 9: 「我的授权」页（撤销）

**Files:**
- Create: `frontend_web/src/views/McpGrants/index.vue`
- Modify: `frontend_web/src/router/index.ts`
- Modify: `frontend_web/src/components/UserMenu.vue`（加入口）

**Interfaces:**
- Consumes: `listGrants()`、`revokeGrant(clientId)`
- Produces: SPA 路由 `/mcp/grants`（登录可见）

- [ ] **Step 1: 写页面**

创建 `frontend_web/src/views/McpGrants/index.vue`：

```vue
<template>
  <div class="tm-page">
    <h1 class="tm-page-title">我的授权</h1>
    <p class="tm-lede">你在哪些客户端授权过 TestMate。撤销后，该客户端下一次调用就会失效，需要重新授权。</p>

    <el-table :data="rows" v-loading="loading" class="mt">
      <el-table-column prop="client_name" label="客户端" min-width="180" />
      <el-table-column label="权限" min-width="260">
        <template #default="{ row }">
          <el-tag v-for="s in row.scopes" :key="s" size="small" class="mr">{{ scopeText(s) }}</el-tag>
        </template>
      </el-table-column>
      <el-table-column label="授权时间" width="180">
        <template #default="{ row }">{{ fmt(row.created_at) }}</template>
      </el-table-column>
      <el-table-column label="最后使用" width="180">
        <template #default="{ row }">{{ fmt(row.last_used_at) }}</template>
      </el-table-column>
      <el-table-column label="状态" width="100">
        <template #default="{ row }">
          <el-tag v-if="row.revoked_at" type="info" size="small">已撤销</el-tag>
          <el-tag v-else type="success" size="small">有效</el-tag>
        </template>
      </el-table-column>
      <el-table-column label="操作" width="100" fixed="right">
        <template #default="{ row }">
          <el-button v-if="!row.revoked_at" link type="danger" @click="revoke(row)">撤销</el-button>
        </template>
      </el-table-column>
    </el-table>
  </div>
</template>

<script setup lang="ts">
import { onMounted, ref } from 'vue';
import { ElMessage, ElMessageBox } from 'element-plus';
import { listGrants, revokeGrant, type McpGrant } from '@/api/mcp';

const rows = ref<McpGrant[]>([]);
const loading = ref(false);

const SCOPE_LABELS: Record<string, string> = {
    'market:read': '读',
    'market:write': '写',
};

function scopeText(s: string) {
    return SCOPE_LABELS[s] || s;
}

function fmt(v: string | null) {
    return v ? new Date(v).toLocaleString() : '—';
}

async function load() {
    loading.value = true;
    try {
        rows.value = await listGrants();
    } finally {
        loading.value = false;
    }
}

async function revoke(row: McpGrant) {
    await ElMessageBox.confirm(`撤销「${row.client_name}」的授权？该客户端需要重新授权才能继续使用。`, '撤销授权', {
        type: 'warning',
        confirmButtonText: '撤销',
        cancelButtonText: '取消',
    });
    await revokeGrant(row.client_id);
    ElMessage.success('已撤销');
    await load();
}

onMounted(load);
</script>
```

- [ ] **Step 2: 加路由**

修改 `frontend_web/src/router/index.ts`，加：

```ts
        // ===== 我的授权 (管理已授权的客户端) =====
        { path: 'mcp/grants', name: 'mcp-grants', meta: { title: '我的授权' }, component: () => import('@/views/McpGrants/index.vue') },
```

- [ ] **Step 3: 加菜单入口**

修改 `frontend_web/src/components/UserMenu.vue`，在用户菜单项列表里加一条（按该文件既有写法）：

```vue
        <el-dropdown-item command="mcp-grants">我的授权</el-dropdown-item>
```

并在菜单的 `command` 处理分支里加：

```ts
        } else if (command === 'mcp-grants') {
            router.push({ name: 'mcp-grants' });
        }
```

> ⚠️ **先看 `UserMenu.vue` 的既有结构**（菜单项怎么写、command 怎么分发），照它的风格改，
> 不要凭空插入。

- [ ] **Step 4: 构建校验**

Run: `cd frontend_web && npm run build`
Expected: 成功

- [ ] **Step 5: 提交**

```bash
git add frontend_web/src/views/McpGrants/index.vue frontend_web/src/router/index.ts frontend_web/src/components/UserMenu.vue
git commit -m "feat(MCP): 我的授权页 —— 查看并撤销已授权的客户端"
```

---

# Stage S3 — 内置连接器资产

### Task 10: `is_builtin` 字段 + 守卫 + seed + url 动态生成

**Files:**
- Modify: `backend_gateway/app/models/asset.py`
- Create: `backend_gateway/alembic/versions/0031_add_asset_is_builtin.py`
- Create: `backend_gateway/app/mcp/common/builtin_assets.py`
- Modify: `backend_gateway/app/api/marketplace.py`（**仅 3 处守卫**）
- Modify: `backend_gateway/app/main.py`（seed 调用）
- Test: `backend_gateway/tests/test_mcp_builtin_asset.py`

**Interfaces:**
- Consumes: `app.models.mcp` 无关；`Asset` 模型；`marketplace.public_base_url` 设置项
- Produces:
  - `Asset.is_builtin: int`（0/1）
  - `app/mcp/common/builtin_assets.py::seed_builtin_assets() -> None`（幂等）
  - `app/mcp/common/builtin_assets.py::BUILTIN_CODE = "testmate"`
  - `app/mcp/common/builtin_assets.py::builtin_connection_config(base_url: str) -> dict`（Qoder 格式）
  - 守卫：`DELETE /api/v1/assets/{code}` / `POST /api/v1/assets/{code}/unpublish` / `PUT /api/v1/assets/{code}`（改 `mcp_config`）→ **409**

- [ ] **Step 1: 写失败的测试**

创建 `backend_gateway/tests/test_mcp_builtin_asset.py`：

```python
"""内置连接器资产 —— 存在 / 不可删 / 不可下架 / url 不可改 / 文案可改."""

from __future__ import annotations

import json

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select

from app.db.session import AsyncSessionLocal
from app.models.asset import Asset

from tests._lifespan import lifespan_driver


@pytest.mark.asyncio
async def test_builtin_asset_is_seeded():
    from app.mcp.common.builtin_assets import BUILTIN_CODE, seed_builtin_assets

    await seed_builtin_assets()
    async with AsyncSessionLocal() as s:
        a = (await s.execute(select(Asset).where(Asset.code == BUILTIN_CODE))).scalars().first()
    assert a is not None
    assert a.is_builtin == 1
    assert a.publish_status == "published"
    assert a.pending_action == ""


@pytest.mark.asyncio
async def test_builtin_seed_is_idempotent():
    from app.mcp.common.builtin_assets import seed_builtin_assets

    await seed_builtin_assets()
    await seed_builtin_assets()
    async with AsyncSessionLocal() as s:
        n = len((await s.execute(select(Asset).where(Asset.code == "testmate"))).scalars().all())
    assert n == 1


@pytest.mark.asyncio
async def test_builtin_url_is_generated_from_base_url():
    from app.mcp.common.builtin_assets import builtin_connection_config

    cfg = builtin_connection_config("http://10.0.0.5:8081")
    url = cfg["mcpServers"]["testmate"]["url"]
    assert url == "http://10.0.0.5:8081/mcp/skill"
    assert "headers" not in cfg["mcpServers"]["testmate"], "内置配置里不能有密钥"


@pytest.mark.asyncio
async def test_delete_builtin_is_409():
    from app.main import app
    from app.mcp.common.builtin_assets import seed_builtin_assets

    await seed_builtin_assets()
    async with lifespan_driver(app):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://testserver") as c:
            r = await c.delete("/api/v1/assets/testmate")
    assert r.status_code == 409
    assert "内置" in r.text
```

- [ ] **Step 2: 跑测试确认失败**

Run: `cd backend_gateway && pytest tests/test_mcp_builtin_asset.py -v`
Expected: FAIL —— `ModuleNotFoundError: No module named 'app.mcp.common.builtin_assets'`

- [ ] **Step 3: 模型加字段**

修改 `backend_gateway/app/models/asset.py`，在 `published` 附近加一行（字段名 `is_builtin`）：

```python
    # ⚠️ 平台内置资产 (2026-10-31, MCP): 内置连接器 (TestMate 自己) 等 —— 
    #    不可删除 / 不可下架 / url 不可改, 但**文案可改**.
    #    只存 DB, 不进 GitLab 市场仓库 (避免与「GitLab 是真身」的模型打架).
    is_builtin: Mapped[int] = mapped_column(Integer, nullable=False, default=0, index=True)
```

- [ ] **Step 4: 写迁移**

创建 `backend_gateway/alembic/versions/0031_add_asset_is_builtin.py`（`down_revision = "0030_add_mcp_tables"`）：

```python
"""add assets.is_builtin

Revision ID: 0031_add_asset_is_builtin
Revises: 0030_add_mcp_tables
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0031_add_asset_is_builtin"
down_revision = "0030_add_mcp_tables"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("assets", sa.Column("is_builtin", sa.Integer, nullable=False, server_default="0"))
    op.create_index("ix_assets_is_builtin", "assets", ["is_builtin"])


def downgrade() -> None:
    op.drop_index("ix_assets_is_builtin", table_name="assets")
    op.drop_column("assets", "is_builtin")
```

- [ ] **Step 5: 写 seed**

创建 `backend_gateway/app/mcp/common/builtin_assets.py`：

```python
"""平台内置资产 —— TestMate 自己的 MCP 连接器.

设计文档 §4.9 / §10.4。

⚠️ 只存 DB，不进 GitLab 市场仓库：
  · 市场仓库是「资产真身」，内置连接器不是用户资产，不该占仓库位置
  · `market_catalog.apply_index_to_db` **只 upsert、不删库里的行** → 仓库同步不会把内置资产冲掉 ✓
"""

from __future__ import annotations

import json
from typing import Any

from sqlalchemy import select

from app.db.session import AsyncSessionLocal
from app.models.asset import Asset

#: 内置连接器的资产 code（用户可见）
BUILTIN_CODE = "testmate"

#: url 里的占位符 —— 每套部署地址不同，不能写死进仓库
URL_PLACEHOLDER = "{{BASE}}/mcp/skill"


def builtin_connection_config(base_url: str) -> dict[str, Any]:
    """Qoder 格式的连接器配置（**不含任何密钥**）."""
    base = (base_url or "").rstrip("/")
    return {
        "mcpServers": {
            BUILTIN_CODE: {
                "type": "http",
                "url": f"{base}/mcp/skill",
            }
        }
    }


async def seed_builtin_assets(base_url: str = "") -> None:
    """幂等 upsert —— 每次启动跑一次."""
    base = (base_url or "").rstrip("/")
    cfg = json.dumps(builtin_connection_config(base), ensure_ascii=False)
    async with AsyncSessionLocal() as s:
        row = (await s.execute(select(Asset).where(Asset.code == BUILTIN_CODE))).scalars().first()
        if row is None:
            row = Asset(
                code=BUILTIN_CODE,
                name="TestMate 平台能力",
                icon="🧰",
                kind="mcp",
                version="1.0.0",
                summary="让 AI 助手直接搜索、读取、上架 TestMate 技能市场里的技能",
                description=(
                    "这是 TestMate 平台自己的 MCP 服务端。把它接到你的 AI 助手（如 Qoder）后，"
                    "助手就能搜索技能、读取 SKILL.md、下载技能包，也能帮你上架新技能。"
                    "连接后按提示在浏览器里点一次「授权」即可。"
                ),
                category="",
                project="",
                author="平台",
                mcp_config=cfg,
                is_builtin=1,
                publish_status="published",
                sync_status="pushed",
                git_path="",
            )
            s.add(row)
        else:
            row.is_builtin = 1
            row.mcp_config = cfg
        await s.commit()
```

> ⚠️ **先核对 `Asset` 模型的字段名**（`pending_action` / `sync_status` / `mcp_config` 是否存在、
> 是否 NOT NULL 有默认值）。缺哪个补哪个，**不要留必填字段为空**。
> `mcp_config` 若在模型里不存在（连接器配置存在别的表/字段），改用实际字段。

- [ ] **Step 6: 加 3 处守卫（既有代码，只加守卫，不动业务逻辑）**

修改 `backend_gateway/app/api/marketplace.py`：

**① `delete_asset`（`@router.delete("/{code}")`）** —— 在拿到 asset 之后、真正删除之前加：

```python
    if getattr(asset, "is_builtin", 0):
        raise HTTPException(status_code=409, detail="平台内置资产不可删除")
```

**② `unpublish_asset`（`@router.post("/{code}/unpublish")`）** —— 同位置加：

```python
    if getattr(asset, "is_builtin", 0):
        raise HTTPException(status_code=409, detail="平台内置资产不可下架")
```

**③ `update_asset`（`@router.put("/{code}")`）** —— 只在**要改连接器配置**时拦：

```python
    if getattr(asset, "is_builtin", 0) and mcp_config:
        raise HTTPException(status_code=409, detail="平台内置连接器的地址不可修改")
```

> ⚠️ 三处的 `asset` 变量名要**照该函数里现有的写法**（有的是 `a`、有的是 `asset`），
> 先读那三个函数再照抄上下文。**这是本方案对既有业务代码的唯一改动（共约 9 行）。**

- [ ] **Step 7: 在启动时 seed**

修改 `backend_gateway/app/main.py`，在 lifespan 里（`yield` 之前）加：

```python
    from app.mcp.common.builtin_assets import seed_builtin_assets
    await seed_builtin_assets(os.environ.get("MCP_ISSUER_URL", ""))
```

- [ ] **Step 8: 跑测试确认通过**

Run: `cd backend_gateway && pytest tests/test_mcp_builtin_asset.py -v`
Expected: PASS（4 passed）

- [ ] **Step 9: 跑全量测试**

Run: `cd backend_gateway && pytest -q`
Expected: 全绿（既有测试不能红 —— 守卫加错了会打到老用例）

- [ ] **Step 10: 提交**

```bash
git add backend_gateway/app/models/asset.py backend_gateway/alembic/versions/0031_add_asset_is_builtin.py \
        backend_gateway/app/mcp/common/builtin_assets.py backend_gateway/app/api/marketplace.py \
        backend_gateway/app/main.py backend_gateway/tests/test_mcp_builtin_asset.py
git commit -m "feat(MCP): 内置连接器资产 —— is_builtin + seed + 3 处守卫（不可删/不可下架/url 不可改）"
```

---

### Task 11: 前端市场卡片（内置徽标 + 复制连接器配置）

**Files:**
- Modify: `frontend_web/src/views/Capability/Catalog/AssetCard.vue`
- Modify: `frontend_web/src/views/Capability/Catalog/index.vue`

**Interfaces:**
- Consumes: `getConnectionConfig()`、资产字段 `is_builtin`
- Produces: 内置卡片显示「平台内置」徽标；隐藏「下架/删除」；「复制连接器配置」按钮

- [ ] **Step 1: 改 AssetCard.vue**

先读该文件，找到徽标与操作按钮区域，按下面三条改：

```vue
<!-- ① 内置徽标 -->
<el-tag v-if="asset.is_builtin" type="info" size="small" class="tm-tag-builtin">平台内置</el-tag>

<!-- ② 隐藏下架 / 删除 -->
<el-dropdown-item v-if="canUnpublish && !asset.is_builtin" command="unpublish">下架</el-dropdown-item>
<el-dropdown-item v-if="canDelete && !asset.is_builtin" command="delete">删除</el-dropdown-item>

<!-- ③ 连接器卡片加「复制连接器配置」 -->
<el-button v-if="asset.kind === 'mcp'" size="small" @click.stop="copyConnector">复制连接器配置</el-button>
```

`<script setup>` 里加：

```ts
import { ElMessage } from 'element-plus';
import { getConnectionConfig } from '@/api/mcp';

async function copyConnector() {
    const cfg = await getConnectionConfig();
    const text = JSON.stringify(cfg, null, 2);
    try {
        await navigator.clipboard.writeText(text);
        ElMessage.success('连接器配置已复制 —— 粘到 Qoder 的「连接器与 MCP」里即可');
    } catch {
        ElMessage.warning('复制失败，请手动复制：' + text);
    }
}
```

- [ ] **Step 2: 改 index.vue**

在 `canModify` 计算里加 `&& !asset.is_builtin`：

```ts
const canModify = computed(() => /* 既有条件 */ && !asset.value?.is_builtin);
```

> ⚠️ 照该文件既有的 `canModify` 写法改，**不要重写整个计算**。

- [ ] **Step 3: 类型补字段**

在 `frontend_web/src/api/assets.ts` 的 `AssetItem` 接口里加：

```ts
    /** 平台内置资产（不可删/不可下架/url 不可改，文案可改） */
    is_builtin?: number;
```

- [ ] **Step 4: 构建校验**

Run: `cd frontend_web && npm run build`
Expected: 成功

- [ ] **Step 5: 提交**

```bash
git add frontend_web/src/views/Capability/Catalog/ frontend_web/src/api/assets.ts
git commit -m "feat(MCP): 市场卡片 —— 内置徽标 + 隐藏下架删除 + 复制连接器配置"
```

---

# Stage S4 — MCP 公共层

### Task 12: MCP server 工厂 + dispatcher + 挂载 + lifespan

**Files:**
- Create: `backend_gateway/app/mcp/common/server.py`
- Create: `backend_gateway/app/mcp/common/context.py`
- Create: `backend_gateway/app/mcp/skill/__init__.py`
- Create: `backend_gateway/app/mcp/skill/server.py`
- Create: `backend_gateway/app/mcp/software/__init__.py`
- Create: `backend_gateway/app/mcp/kb/__init__.py`
- Modify: `backend_gateway/app/main.py`
- Test: `backend_gateway/tests/test_mcp_transport.py`

**Interfaces:**
- Consumes: `app.mcp.common.auth.VERIFIERS`、`app.core.settings_store`（allowed_hosts）
- Produces:
  - `app/mcp/common/server.py::build_mcp(...) -> FastMCP`
  - `app/mcp/common/server.py::build_dispatcher(domains: dict[str, FastMCP]) -> Starlette`
  - `app/mcp/common/server.py::PROVIDERS` / `ALL_MCPS`
  - `app/mcp/common/context.py::McpContext`（`principal` + `user()` + `domain`）
  - 端点：`POST /mcp/skill`（200）、`GET /mcp/skill/sse`（200）、`POST /mcp/skill/messages/`（200）

- [ ] **Step 1: 写失败的测试**

创建 `backend_gateway/tests/test_mcp_transport.py`：

```python
"""MCP transport —— 路径 / 鉴权 / SSE 回传地址 / 握手."""

from __future__ import annotations

import pytest
from httpx import ASGITransport, AsyncClient

from tests._lifespan import lifespan_driver


@pytest.mark.asyncio
async def test_streamable_path_is_exactly_200_not_307():
    from app.main import app

    async with lifespan_driver(app):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://testserver") as c:
            r = await c.post("/mcp/skill", json={
                "jsonrpc": "2.0", "id": 1, "method": "initialize",
                "params": {"protocolVersion": "2025-06-18", "capabilities": {},
                           "clientInfo": {"name": "t", "version": "1"}},
            }, headers={"Accept": "application/json, text/event-stream",
                        "Content-Type": "application/json"})
    assert r.status_code == 200, f"{r.status_code} {r.text}"
    assert r.json()["result"]["serverInfo"]["name"] == "testmate-skill"


@pytest.mark.asyncio
async def test_unknown_domain_is_404():
    from app.main import app

    async with lifespan_driver(app):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://testserver") as c:
            r = await c.post("/mcp/nope", json={"jsonrpc": "2.0", "id": 1, "method": "initialize"})
    assert r.status_code == 404


@pytest.mark.asyncio
async def test_unauthenticated_gets_401_with_resource_metadata():
    from app.main import app

    async with lifespan_driver(app):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://testserver") as c:
            r = await c.post("/mcp/skill", json={
                "jsonrpc": "2.0", "id": 1, "method": "initialize",
                "params": {"protocolVersion": "2025-06-18", "capabilities": {},
                           "clientInfo": {"name": "t", "version": "1"}},
            }, headers={"Accept": "application/json, text/event-stream",
                        "Content-Type": "application/json"})
    assert r.status_code == 401
    assert "resource_metadata=" in r.headers.get("www-authenticate", "")


@pytest.mark.asyncio
async def test_sse_endpoint_event_points_to_messages_path():
    """SSE 首帧的 endpoint 必须等于 /mcp/skill/messages/ —— root_path 写错就错在这里."""
    import app.main as main_mod

    async with lifespan_driver(main_mod.app):
        async with AsyncClient(transport=ASGITransport(app=main_mod.app),
                               base_url="http://testserver") as c:
            async with c.stream("GET", "/mcp/skill/sse",
                                headers={"Accept": "text/event-stream"}) as resp:
                assert resp.status_code == 200
                first = ""
                async for line in resp.aiter_lines():
                    if line.startswith("data:"):
                        first = line[5:].strip()
                        break
    assert first.startswith("/mcp/skill/messages/?session_id="), first
```

> ⚠️ SSE 测试需要**先拿到 token**才有 200；未认证时 SDK 会先返回 401。
> 若上面这条因为 401 失败，先在测试里用 `issue_mcp_access_token` + 预置 grant 造一个 token
> （Task 13 之后的 `tests/_mcp_client.py` 里有现成 fixture 可复用），再带上 `Authorization` 头。

- [ ] **Step 2: 跑测试确认失败**

Run: `cd backend_gateway && pytest tests/test_mcp_transport.py -v`
Expected: FAIL —— 404（`/mcp/skill` 还没挂）

- [ ] **Step 3: 写 server 工厂**

创建 `backend_gateway/app/mcp/common/server.py`：

```python
"""MCP server 工厂 + 分域 dispatcher.

设计文档 §3.3 / §3.4。

⚠️ 两条硬约束（改这层时务必记住）：
  1. **绝不传 auth_server_provider** —— FastMCP 收到它就会调 SDK 的 create_auth_routes()，
     而那个函数强制 issuer 必须 HTTPS → 内网 http 部署装配即炸。
     只传 token_verifier + AuthSettings。
  2. dispatcher 里 **Route 与 Mount 必须并存**：
     Route 精确匹配 "/{域}"（POST /mcp/skill），Mount 前缀匹配 "/{域}/..."
     （GET /mcp/skill/sse、POST /mcp/skill/messages/）。只用其一会 404。
"""

from __future__ import annotations

import os
from typing import Any

from mcp.server.fastmcp import FastMCP
from mcp.server.transport_security import TransportSecuritySettings
from starlette.applications import Starlette
from starlette.routing import Mount, Route

from app.mcp.common.auth import TokenVerifier


def allowed_hosts() -> list[str]:
    """allowed_hosts —— 裸 host 与 host:port 都要有（nginx 的 $host 会丢端口）."""
    hosts: list[str] = []
    issuer = (os.environ.get("MCP_ISSUER_URL") or "").strip()
    if issuer:
        from urllib.parse import urlparse

        p = urlparse(issuer)
        if p.hostname:
            hosts.append(p.hostname)
            if p.port:
                hosts.append(f"{p.hostname}:{p.port}")
    hosts += ["localhost:*", "127.0.0.1:*", "[::1]:*"]
    extra = (os.environ.get("MCP_ALLOWED_HOSTS") or "").strip()
    if extra:
        hosts += [x.strip() for x in extra.split(",") if x.strip()]
    # 去重且保序
    seen: set[str] = set()
    out: list[str] = []
    for h in hosts:
        if h and h not in seen:
            seen.add(h)
            out.append(h)
    return out


def build_mcp(
    *,
    name: str,
    instructions: str,
    path: str,
    issuer_url: str,
    resource_server_url: str,
    token_verifier: TokenVerifier,
) -> FastMCP:
    from mcp.server.auth.settings import AuthSettings

    return FastMCP(
        name=name,
        instructions=instructions,
        stateless_http=True,       # 无状态：nginx / 多副本友好
        json_response=True,        # 响应是 application/json
        streamable_http_path=path, # "/skill" —— 相对 /mcp 挂载点
        sse_path="/sse",
        message_path="/messages/",
        auth=AuthSettings(
            issuer_url=issuer_url,                    # http://host（站点根）
            resource_server_url=resource_server_url,  # http://host/mcp/skill
            required_scopes=[],
        ),
        token_verifier=token_verifier,   # ⚠️ 不要传 auth_server_provider
        transport_security=TransportSecuritySettings(
            enable_dns_rebinding_protection=True,
            allowed_hosts=allowed_hosts(),
            allowed_origins=[],
        ),
    )


def build_dispatcher(domains: dict[str, FastMCP]) -> Starlette:
    """分域 dispatcher —— Route + Mount 并存（§3.3.2）."""
    routes: list[Any] = []
    for name, mcp in domains.items():
        routes.append(Route(f"/{name}", endpoint=mcp.streamable_http_app()))
        routes.append(Mount(f"/{name}", app=mcp.sse_app()))
    return Starlette(routes=routes)
```

- [ ] **Step 4: 写域 server**

创建 `backend_gateway/app/mcp/skill/server.py`：

```python
"""技能·插件 域的 MCP server."""

from __future__ import annotations

import os

from mcp.server.fastmcp import FastMCP

from app.mcp.common.auth import VERIFIERS
from app.mcp.common.server import build_mcp

DOMAIN = "skill"
SERVER_NAME = "testmate-skill"

INSTRUCTIONS = (
    "这是 TestMate 的技能市场（插件·技能·连接）。"
    "典型流程：先 skill_search 找到技能 → skill_read_doc 读 SKILL.md 了解怎么用 → "
    "需要安装包时用 skill_package_info 取 url + sha256。"
    "要上架技能时用 skill_publish；如果用户还没定好分类/简介等字段，"
    "工具会返回 needs_confirmation —— 请把问题回问用户，不要自己替用户决定。"
)


def build_skill_mcp() -> FastMCP:
    base = (os.environ.get("MCP_ISSUER_URL") or "http://127.0.0.1:8000").rstrip("/")
    return build_mcp(
        name=SERVER_NAME,
        instructions=INSTRUCTIONS,
        path=f"/{DOMAIN}",
        issuer_url=base,
        resource_server_url=f"{base}/mcp/{DOMAIN}",
        token_verifier=VERIFIERS[0],
    )
```

> ⚠️ `token_verifier=VERIFIERS[0]` 只挂了 OAuth 验证器 —— 静态令牌验证器在 Task 13 合并成一个
> `CompositeTokenVerifier`（一次尝试所有验证器）。**Task 13 完成后回来改成 `CompositeTokenVerifier()`。**

- [ ] **Step 5: 写 McpContext**

创建 `backend_gateway/app/mcp/common/context.py`：

```python
"""工具调用上下文 —— 身份 + 域信息.

设计文档 §3.5：工具**永远不自己读 header**，身份一律从 McpContext 拿。
"""

from __future__ import annotations

from dataclasses import dataclass

from app.mcp.common.auth import Principal


@dataclass
class McpContext:
    principal: Principal
    domain: str

    @property
    def user_id(self) -> int:
        return self.principal.user_id

    @property
    def scopes(self) -> frozenset[str]:
        return self.principal.scopes
```

- [ ] **Step 6: 挂到主应用**

修改 `backend_gateway/app/main.py`：

```python
# 顶部 import
from contextlib import AsyncExitStack
from app.mcp.common.server import build_dispatcher
from app.mcp.skill.server import build_skill_mcp
```

在 lifespan 里（`yield` 之前）加：

```python
    ALL_MCPS = {"skill": build_skill_mcp()}
    async with AsyncExitStack() as stack:
        for mcp in ALL_MCPS.values():
            await stack.enter_async_context(mcp.session_manager.run())
        yield
```

> ⚠️ `mcp.session_manager` 在 `streamable_http_app()` 被调用前访问会抛 RuntimeError
> ⇒ **必须先 build_dispatcher(ALL_MCPS)（它内部会调 streamable_http_app）**，再进 lifespan。
> 建议在**模块加载期**构建：

```python
ALL_MCPS = {"skill": build_skill_mcp()}
mcp_dispatcher = build_dispatcher(ALL_MCPS)      # ← 这里就把 session_manager 建好
app.mount("/mcp", mcp_dispatcher)
```

lifespan 里只保留：

```python
    async with AsyncExitStack() as stack:
        for mcp in ALL_MCPS.values():
            await stack.enter_async_context(mcp.session_manager.run())
        yield
```

- [ ] **Step 7: 跑测试确认通过**

Run: `cd backend_gateway && pytest tests/test_mcp_transport.py -v`
Expected: 前三条 PASS；SSE 那条按上面注释补 token 后 PASS

- [ ] **Step 8: 提交**

```bash
git add backend_gateway/app/mcp/ backend_gateway/app/main.py backend_gateway/tests/test_mcp_transport.py
git commit -m "feat(MCP): 公共层 —— server 工厂 + Route/Mount 并存的 dispatcher + 401 发现头"
```

---

### Task 13: 错误映射 + 审计 + 配额 + 工具包装层

**Files:**
- Create: `backend_gateway/app/mcp/common/errors.py`
- Create: `backend_gateway/app/mcp/common/audit.py`
- Create: `backend_gateway/app/mcp/common/tool.py`
- Create: `backend_gateway/app/mcp/skill/tools.py`（**先只放一个占位工具**，Task 16 补全）
- Modify: `backend_gateway/app/mcp/skill/server.py`（注册工具 + 合并 TokenVerifier）
- Test: `backend_gateway/tests/test_mcp_common.py`

**Interfaces:**
- Consumes: `app.mcp.common.context.McpContext`、`app.mcp.common.auth.Principal`
- Produces:
  - `errors.py::McpError(code, message, hint=None)`、`errors.py::map_http_exception(exc) -> McpError`
  - `tool.py::ToolSpec`、`tool.py::CompositeTokenVerifier`、`tool.py::register_tool(mcp, spec)`
  - `tool.py::QuotaGuard`（两级配额）
  - `audit.py::record_tool_call(...)`

- [ ] **Step 1: 写失败的测试**

创建 `backend_gateway/tests/test_mcp_common.py`：

```python
"""公共层 —— 错误映射 / 配额 / 审计."""

from __future__ import annotations

from datetime import datetime, timedelta

import pytest
from fastapi import HTTPException
from sqlalchemy import select

from app.db.session import AsyncSessionLocal
from app.models.mcp import McpToolCall


def test_http_status_maps_to_error_code():
    from app.mcp.common.errors import map_http_exception

    assert map_http_exception(HTTPException(status_code=404, detail="x")).code == "not_found"
    assert map_http_exception(HTTPException(status_code=403, detail="x")).code == "permission_denied"
    assert map_http_exception(HTTPException(status_code=409, detail="x")).code == "conflict"
    assert map_http_exception(HTTPException(status_code=400, detail="x")).code == "bad_request"
    assert map_http_exception(HTTPException(status_code=422, detail="x")).code == "invalid_argument"
    assert map_http_exception(HTTPException(status_code=502, detail="x")).code == "upstream_failed"


@pytest.mark.asyncio
async def test_quota_exceeded_returns_tool_error_not_429():
    from app.mcp.common.tool import QuotaGuard

    async with AsyncSessionLocal() as s:
        now = datetime.utcnow()
        for i in range(3):
            s.add(McpToolCall(user_id=555001, client_id="c", client_name="c", tool="t",
                              domain="skill", args_summary="", ok=1, created_at=now))
        await s.commit()

    guard = QuotaGuard(client_limit=2, user_limit=100)
    ok = await guard.check(user_id=555001, client_id="c")
    assert ok is not None and ok.code == "quota_exceeded"


@pytest.mark.asyncio
async def test_quota_user_level_also_blocks():
    from app.mcp.common.tool import QuotaGuard

    async with AsyncSessionLocal() as s:
        now = datetime.utcnow()
        for i in range(3):
            s.add(McpToolCall(user_id=555002, client_id=f"c{i}", client_name="c", tool="t",
                              domain="skill", args_summary="", ok=1, created_at=now))
        await s.commit()

    guard = QuotaGuard(client_limit=100, user_limit=2)
    res = await guard.check(user_id=555002, client_id="c0")
    assert res is not None and res.code == "quota_exceeded"
```

- [ ] **Step 2: 跑测试确认失败**

Run: `cd backend_gateway && pytest tests/test_mcp_common.py -v`
Expected: FAIL —— `ModuleNotFoundError: No module named 'app.mcp.common.errors'`

- [ ] **Step 3: 写错误映射**

创建 `backend_gateway/app/mcp/common/errors.py`：

```python
"""异常 → MCP tool error 的**唯一**出口.

设计文档 §5.4 的错误码全集。**工具实现不自己拼错误**——一律抛 HTTPException，
由这里统一映射，保证 REST 与 MCP 的错误语义一致。
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from fastapi import HTTPException


@dataclass
class McpError(Exception):
    code: str
    message: str
    hint: str = ""
    extra: dict[str, Any] | None = None

    def to_payload(self) -> dict[str, Any]:
        p: dict[str, Any] = {"error": {"code": self.code, "message": self.message}}
        if self.hint:
            p["error"]["hint"] = self.hint
        if self.extra:
            p["error"].update(self.extra)
        return p


_STATUS_TO_CODE = {
    400: "bad_request",
    401: "unauthorized",
    403: "permission_denied",
    404: "not_found",
    409: "conflict",
    422: "invalid_argument",
    429: "quota_exceeded",
}


def map_http_exception(exc: HTTPException) -> McpError:
    detail = exc.detail if isinstance(exc.detail, str) else str(exc.detail)
    code = _STATUS_TO_CODE.get(exc.status_code)
    if code is None:
        code = "upstream_failed" if exc.status_code >= 500 else "bad_request"
    return McpError(code=code, message=detail)
```

- [ ] **Step 4: 写审计**

创建 `backend_gateway/app/mcp/common/audit.py`：

```python
"""工具调用审计 —— 每次调用落一行 mcp_tool_calls.

设计文档 §8。这同时是**配额的计数来源**（§4.8）。
"""

from __future__ import annotations

import json
from datetime import datetime
from typing import Any

from app.db.session import AsyncSessionLocal
from app.models.mcp import McpToolCall


def summarize(args: dict[str, Any], limit: int = 2048) -> str:
    """入参摘要 —— 截断到 2KB，不落全文（可能有包 base64）。"""
    try:
        text = json.dumps(args, ensure_ascii=False, default=str)
    except Exception:
        text = str(args)
    return text[:limit]


async def record_tool_call(
    *,
    user_id: int,
    client_id: str,
    client_name: str,
    tool: str,
    domain: str,
    args: dict[str, Any],
    ok: bool,
    error_code: str = "",
    duration_ms: int = 0,
) -> None:
    """落一行审计 —— **失败也要落**（否则配额计数会漂）。"""
    async with AsyncSessionLocal() as s:
        s.add(McpToolCall(
            user_id=user_id,
            client_id=client_id or "",
            client_name=client_name or "",
            tool=tool,
            domain=domain,
            args_summary=summarize(args),
            ok=1 if ok else 0,
            error_code=error_code or "",
            duration_ms=duration_ms,
            created_at=datetime.utcnow(),
        ))
        await s.commit()
```

- [ ] **Step 5: 写工具契约 + 配额 + 包装层**

创建 `backend_gateway/app/mcp/common/tool.py`：

```python
"""ToolSpec 契约 + 注册辅助 + 配额包装层.

设计文档 §3.5（ToolSpec）、§4.8（配额）、§5（工具清单）。

三条不变量之一：**审计只有一处** —— 每次工具调用必定落一行审计，
由这里的包装层统一写，工具实现自己不写审计。
"""

from __future__ import annotations

import json
import time
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Any, Awaitable, Callable

from mcp.server.auth.provider import AccessToken
from sqlalchemy import func, select

from app.db.session import AsyncSessionLocal
from app.mcp.common.auth import Principal, TokenVerifier
from app.mcp.common.audit import record_tool_call
from app.mcp.common.context import McpContext
from app.mcp.common.errors import McpError, map_http_exception
from app.models.mcp import McpToolCall

#: 默认配额（§4.8）
DEFAULT_CLIENT_QUOTA = 200
DEFAULT_USER_QUOTA = 1000


@dataclass(frozen=True)
class ToolSpec:
    """一个工具的契约 —— 名字、schema、scope、只读标记."""

    name: str
    description: str
    input_schema: dict[str, Any]
    handler: Callable[[McpContext, dict[str, Any]], Awaitable[Any]]
    scope: str
    read_only: bool
    domain: str
    annotations: dict[str, Any] | None = None


class CompositeTokenVerifier:
    """把多个 CredentialVerifier 合成一个 —— 依次尝试，谁先成功用谁."""

    def __init__(self, verifiers: list[TokenVerifier]) -> None:
        self._verifiers = list(verifiers)

    async def verify_token(self, token: str) -> AccessToken | None:
        for v in self._verifiers:
            got = await v.verify_token(token)
            if got is not None:
                return got
        return None


class QuotaGuard:
    """两级配额 —— 客户端级 + 用户总量级（§4.8）.

    ⚠️ 在**工具层**拦（不是中间件）：中间件返 429 会被客户端当临时故障 → 重试风暴。
    """

    def __init__(self, client_limit: int = DEFAULT_CLIENT_QUOTA,
                 user_limit: int = DEFAULT_USER_QUOTA) -> None:
        self.client_limit = client_limit
        self.user_limit = user_limit

    async def _count(self, *, user_id: int, client_id: str | None) -> int:
        since = datetime.utcnow() - timedelta(days=1)
        async with AsyncSessionLocal() as s:
            stmt = select(func.count()).select_from(McpToolCall).where(
                McpToolCall.user_id == user_id, McpToolCall.created_at >= since
            )
            if client_id is not None:
                stmt = stmt.where(McpToolCall.client_id == client_id)
            return int((await s.execute(stmt)).scalar() or 0)

    async def check(self, *, user_id: int, client_id: str) -> McpError | None:
        """超额返回 McpError（code=quota_exceeded），否则 None."""
        if self.client_limit > 0:
            if await self._count(user_id=user_id, client_id=client_id) >= self.client_limit:
                return McpError(
                    code="quota_exceeded",
                    message=f"该客户端今天的调用次数已用完（上限 {self.client_limit}/天）",
                    hint="请让用户改用网页端操作，或明天再试",
                )
        if self.user_limit > 0:
            if await self._count(user_id=user_id, client_id=None) >= self.user_limit:
                return McpError(
                    code="quota_exceeded",
                    message=f"你今天的 MCP 调用总数已用完（上限 {self.user_limit}/天）",
                    hint="请让用户改用网页端操作，或明天再试",
                )
        return None


def register_tool(mcp, spec: ToolSpec, quota: QuotaGuard | None = None) -> None:
    """把 ToolSpec 注册到 FastMCP，并包上「scope 检查 + 配额 + 审计」三层."""

    @mcp.tool(
        name=spec.name,
        description=spec.description,
        annotations=spec.annotations or {"readOnlyHint": spec.read_only},
    )
    async def _tool(**kwargs: Any) -> Any:
        started = time.perf_counter()
        ctx = _current_context(spec.domain)
        error: McpError | None = None
        result: Any = None
        try:
            if spec.scope and spec.scope not in ctx.scopes:
                raise McpError(code="permission_denied",
                              message=f"当前授权没有 {spec.scope} 权限",
                              hint="重新发起授权并勾选该权限")
            if quota is not None:
                over = await quota.check(user_id=ctx.user_id, client_id=ctx.principal.client_id)
                if over is not None:
                    raise over
            result = await spec.handler(ctx, kwargs)
            return result
        except McpError as e:
            error = e
        except Exception as exc:  # noqa: BLE001
            from fastapi import HTTPException

            error = map_http_exception(exc) if isinstance(exc, HTTPException) else McpError(
                code="upstream_failed", message=str(exc)
            )
        finally:
            await record_tool_call(
                user_id=ctx.user_id,
                client_id=ctx.principal.client_id,
                client_name=ctx.principal.client_name,
                tool=spec.name,
                domain=spec.domain,
                args=kwargs,
                ok=error is None,
                error_code=error.code if error else "",
                duration_ms=int((time.perf_counter() - started) * 1000),
            )
        raise error
```

- [ ] **Step 6: `_current_context` 的实现**

在 `app/mcp/common/tool.py` 末尾加（依赖 FastMCP 的 `get_context()`）：

```python
def _current_context(domain: str) -> McpContext:
    """从 FastMCP 上下文里取出身份 —— **工具永远不自己读 header**（§3.6 不变量 1）."""
    from mcp.server.fastmcp.server import Context

    ctx = Context.current_context()
    request = ctx.request_context.request
    user = getattr(request, "user", None)
    token = getattr(user, "access_token", None)
    if token is None:
        raise McpError(code="unauthorized", message="缺少身份信息")
    claims = token.claims or {}
    principal = Principal(
        user_id=int(token.subject or 0),
        username=str(claims.get("username") or ""),
        role=str(claims.get("role") or ""),
        client_id=token.client_id,
        client_name=str(claims.get("client_name") or token.client_id),
        scopes=frozenset(token.scopes or []),
        grant_id=claims.get("grant_id"),
    )
    return McpContext(principal=principal, domain=domain)
```

> ⚠️ `Context.current_context()` 是 SDK 提供的取上下文方式。
> 若签名不同（有的版本要 `await Context.current_context()`），按实际签名改。
>
> ⚠️ **`claims` 里的 username / role / client_name 必须由 `OAuthTokenVerifier` 补上** ——
> 现在的 `verify_token` 只返回了 grant_id 与 scopes。改成（`app/mcp/common/auth.py`）：

```python
        async with AsyncSessionLocal() as s:
            grant = (await s.execute(
                select(McpOAuthGrant).where(
                    McpOAuthGrant.user_id == user_id,
                    McpOAuthGrant.client_id == client_id,
                )
            )).scalars().first()
            if grant is None or grant.revoked_at is not None:
                return None
            scopes = list(payload.get("scopes") or [])
            grant.last_used_at = datetime.utcnow()

            from app.models.user import User

            u = (await s.execute(select(User).where(User.id == user_id))).scalars().first()
            if u is None:
                return None
            username = u.username
            role = str(getattr(u.role, "value", u.role))
            await s.commit()

        return AccessToken(
            token=token,
            client_id=client_id,
            scopes=scopes,
            expires_at=None,          # 不过期
            subject=str(user_id),
            claims={
                "grant_id": grant.id,
                "scopes": scopes,
                "username": username,
                "role": role,
                "client_name": client_id,   # 客户端名可从 mcp_oauth_clients 取，默认用 id
            },
        )
```

> 📌 `client_name` 用 `client_id` 兜底：要显示真实客户端名时，
> 在同一处 `select(McpOAuthClient).where(McpOAuthClient.client_id == client_id)` 取 `client_name`。

- [ ] **Step 7: 写一个占位工具并注册**

创建 `backend_gateway/app/mcp/skill/tools.py`（**Task 16 会补全 14 个**）：

```python
"""技能·插件域的工具定义.

设计文档 §5 —— 共 14 个（9 读 + 5 写）。
"""

from __future__ import annotations

from typing import Any

from app.mcp.common.context import McpContext
from app.mcp.common.tool import ToolSpec

DOMAIN = "skill"


async def _ping(ctx: McpContext, args: dict[str, Any]) -> Any:
    """临时探针 —— Task 16 删掉."""
    return {"ok": True, "who": ctx.principal.username, "scopes": sorted(ctx.scopes)}


TOOLS: list[ToolSpec] = [
    ToolSpec(
        name="skill_ping",
        description="临时探针工具（Task 16 删除）",
        input_schema={"type": "object", "properties": {}, "additionalProperties": False},
        handler=_ping,
        scope="market:read",
        read_only=True,
        domain=DOMAIN,
    ),
]
```

修改 `app/mcp/skill/server.py`：

```python
from app.mcp.common.tool import CompositeTokenVerifier, QuotaGuard, register_tool
from app.mcp.skill.tools import TOOLS


def build_skill_mcp() -> FastMCP:
    base = (os.environ.get("MCP_ISSUER_URL") or "http://127.0.0.1:8000").rstrip("/")
    mcp = build_mcp(
        name=SERVER_NAME,
        instructions=INSTRUCTIONS,
        path=f"/{DOMAIN}",
        issuer_url=base,
        resource_server_url=f"{base}/mcp/{DOMAIN}",
        token_verifier=CompositeTokenVerifier(VERIFIERS),
    )
    quota = QuotaGuard()
    for spec in TOOLS:
        register_tool(mcp, spec, quota=quota)
    return mcp
```

- [ ] **Step 8: 跑测试确认通过**

Run: `cd backend_gateway && pytest tests/test_mcp_common.py -v`
Expected: PASS（3 passed）

- [ ] **Step 9: 提交**

```bash
git add backend_gateway/app/mcp/ backend_gateway/tests/test_mcp_common.py
git commit -m "feat(MCP): 工具包装层 —— ToolSpec 契约 + 两级配额 + 统一审计 + 错误映射"
```

---

# Stage S5 — 技能·插件域（14 个工具）

### Task 14: `market_rules.py`（规则单一真源）

**Files:**
- Create: `backend_gateway/app/core/market_rules.py`
- Test: `backend_gateway/tests/test_market_rules.py`

**Interfaces:**
- Consumes: `app.core.market_catalog.validate_code/validate_version`、`app.core.market_naming`、`app.core.market_categories`、`app.core.market_projects`
- Produces:
  - `REQUIRED_FIELDS: dict[str, list[str]]` —— `{"create": [...], "update": [...], "edit_meta": [...]}`
  - `CODE_PREFIX = "dml-"`、`CODE_PATTERN`、`SEGMENT_PATTERN`、`PACKAGE_EXT_RE`（**Python 版**，与前端同口径）
  - `OPTIONAL_FIELDS: dict[str, list[dict[str, str]]]` —— 字段名 + 给用户看的说明
  - `validate_code(code: str, *, require_prefix: bool) -> str`（返回空串=通过，否则是原因）
  - `validate_package_name(filename: str, *, require_prefix: bool) -> str`
  - `check_required(op: str, payload: dict) -> list[dict]` —— 返回 `missing_fields` 结构
  - `rules_payload() -> dict` —— 给 `GET /assets/rules` 用（Task 18）

- [ ] **Step 1: 写失败的测试**

创建 `backend_gateway/tests/test_market_rules.py`：

```python
"""规则单一真源 —— 与前端 assetForm.ts / useAssetUploadForm.ts 同口径."""

from __future__ import annotations

from app.core.market_rules import (
    CODE_PREFIX,
    REQUIRED_FIELDS,
    check_required,
    validate_code,
    validate_package_name,
)


def test_code_requires_prefix_on_create():
    assert validate_code("dml-ssd-log-doctor", require_prefix=True) == ""
    assert "dml-" in validate_code("ssd-log-doctor", require_prefix=True)


def test_code_allows_no_prefix_on_update():
    """存量 14 个资产没有 dml- 前缀 —— 更新时不能卡死它们."""
    assert validate_code("ssd-log-doctor", require_prefix=False) == ""


def test_code_rejects_bad_chars():
    assert validate_code("dml-SSD", require_prefix=True) != ""
    assert validate_code("dml-中文", require_prefix=True) != ""


def test_package_name_rules():
    assert validate_package_name("dml-foo.zip", require_prefix=True) == ""
    assert validate_package_name("dml-foo.rar", require_prefix=True) != ""
    assert validate_package_name("foo.zip", require_prefix=False) == ""


def test_required_fields_shape():
    assert "summary" in REQUIRED_FIELDS["create"]
    assert "summary" in REQUIRED_FIELDS["edit_meta"]
    missing = check_required("create", {"code": "dml-x", "name": "n", "summary": "s"})
    assert any(m["field"] == "version" for m in missing)
    assert all("hint" in m for m in missing)


def test_rules_payload_is_json_serializable():
    import json

    from app.core.market_rules import rules_payload

    json.dumps(rules_payload())
```

- [ ] **Step 2: 跑测试确认失败**

Run: `cd backend_gateway && pytest tests/test_market_rules.py -v`
Expected: FAIL —— `ModuleNotFoundError: No module named 'app.core.market_rules'`

- [ ] **Step 3: 写规则包**

创建 `backend_gateway/app/core/market_rules.py`：

```python
"""上架/更新前的合法性规则 —— **唯一真源**.

设计文档 §4.13.2 L1。

⚠️ 这些规则原本只存在于前端 TS（`assetForm.ts` / `useAssetUploadForm.ts`）——
   本模块是 Python 版同口径实现，MCP 直接 import，
   前端在 S5.5 改为从 `GET /api/v1/assets/rules` 拉取 → 收敛成一份。

⚠️ **「约定」与「技术限制」分两档**（§4.13.2）：
   · 技术合法性：code 分段、version semver、分类在表里、包名 = code → 前端卡 / MCP 卡 / REST 端点卡
   · 团队约定：新建 code 必须 dml- 前缀 → 前端卡 / MCP 卡 / **REST 端点暂不卡**（存量兼容）
"""

from __future__ import annotations

import re
from typing import Any

from app.core import market_categories, market_projects

#: 新建时的 code 前缀（团队约定）
CODE_PREFIX = "dml-"

#: 新建时的 code 规则：dml- + 小写字母/数字/连字符分段
CODE_PATTERN = re.compile(r"^dml-[a-z0-9]+(?:-[a-z0-9]+)*$")

#: 存量资产的 code 规则（不要求前缀）
SEGMENT_PATTERN = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")

#: 安装包允许的扩展名
PACKAGE_EXT_RE = re.compile(r"\.(zip|tar\.gz|tgz)$", re.IGNORECASE)

CODE_EXAMPLE = "dml-ssd-log-doctor"

#: 每个操作的必填字段（与前端 useAssetUploadForm.ts 的 missing 清单同口径）
REQUIRED_FIELDS: dict[str, list[str]] = {
    "create": ["code", "name", "summary", "version", "category"],
    "update": ["code", "name", "summary", "version", "category"],
    "edit_meta": ["name", "summary", "category"],
}

#: 必填字段给用户看的说明（MCP 返回给 agent，让它能回问用户）
FIELD_HINTS: dict[str, str] = {
    "code": f"资产唯一标识，{CODE_PREFIX} 开头 + 小写字母/数字/连字符（如 {CODE_EXAMPLE}）",
    "name": "技能名称",
    "summary": "一句话简介 —— 会显示在市场卡片和钉钉通知里",
    "version": "版本号，semver（如 1.0.0）",
    "category": "所属分类（必须是平台已有分类）",
    "package": "技能包（zip/tar.gz/tgz），包名必须与 code 一致",
}

#: 可选字段 + 「留空 vs 填了会怎样」的说明 —— **MCP 的「不猜」协议靠它回问用户**
OPTIONAL_FIELDS: dict[str, list[dict[str, str]]] = {
    "create": [
        {"field": "description", "hint": "详细说明（留空则市场页只有简介一栏）"},
        {"field": "use_when", "hint": "什么场景该用它（留空则市场页不显示这一栏）"},
        {"field": "not_for", "hint": "什么场景别用它（写清楚能避免误用）"},
        {"field": "project", "hint": "适用项目（留空 = 通用，对所有项目生效）"},
        {"field": "icon", "hint": "图标 emoji（留空由平台按分类自动选）"},
        {"field": "tags", "hint": "标签（用于市场筛选）"},
        {"field": "keywords", "hint": "检索关键词（影响搜索命中）"},
        {"field": "permissions", "hint": "权限声明（审核重点，会展示给使用者）"},
        {"field": "install_steps", "hint": "安装步骤（留空则市场页不显示）"},
        {"field": "bindings", "hint": "绑定的其它资产（留空表示独立使用）"},
    ],
    "update": [
        {"field": "description", "hint": "详细说明"},
        {"field": "use_when", "hint": "什么场景该用它"},
        {"field": "not_for", "hint": "什么场景别用它"},
        {"field": "project", "hint": "适用项目（留空 = 通用）"},
    ],
    "edit_meta": [
        {"field": "description", "hint": "详细说明"},
        {"field": "use_when", "hint": "什么场景该用它"},
        {"field": "not_for", "hint": "什么场景别用它"},
        {"field": "icon", "hint": "图标 emoji"},
        {"field": "tags", "hint": "标签"},
        {"field": "keywords", "hint": "检索关键词"},
    ],
}


def validate_code(code: str, *, require_prefix: bool = True) -> str:
    """返回空串 = 通过；否则是给用户看的原因."""
    c = (code or "").strip()
    if not c:
        return "请填写资产 code"
    if require_prefix:
        if not c.startswith(CODE_PREFIX):
            return f'资产 code 必须以 "{CODE_PREFIX}" 开头 (如 {CODE_EXAMPLE})'
        if not CODE_PATTERN.match(c):
            return f"资产 code 只能用小写字母/数字/连字符, 如 {CODE_EXAMPLE}"
    elif not SEGMENT_PATTERN.match(c):
        return f"资产 code 只能用小写字母/数字/连字符, 如 {CODE_EXAMPLE}"
    if len(c) < 3 or len(c) > 64:
        return f"资产 code 长度要在 3-64 个字符之间 (现在 {len(c)} 个)"
    return ""


def validate_package_name(filename: str, *, require_prefix: bool = True) -> str:
    """校验安装包文件名 —— 返回空串 = 通过."""
    name = (filename or "").strip()
    if not name:
        return "请选择安装包"
    if not PACKAGE_EXT_RE.search(name):
        return "安装包只支持 .zip / .tar.gz / .tgz"
    base = PACKAGE_EXT_RE.sub("", name)
    if require_prefix:
        if not base.startswith(CODE_PREFIX):
            return f'安装包名必须以 "{CODE_PREFIX}" 开头 (如 {CODE_EXAMPLE}.zip)'
        if not CODE_PATTERN.match(base):
            return f"安装包名只能用小写字母/数字/连字符, 如 {CODE_EXAMPLE}.zip"
    elif not SEGMENT_PATTERN.match(base):
        return f"安装包名只能用小写字母/数字/连字符, 如 {CODE_EXAMPLE}.zip"
    if len(base) < 3 or len(base) > 64:
        return f"安装包名长度要在 3-64 个字符之间 (现在 {len(base)} 个)"
    return ""


def check_required(op: str, payload: dict[str, Any]) -> list[dict[str, str]]:
    """返回缺失字段列表（结构与 MCP 的 needs_confirmation.missing_fields 一致）."""
    out: list[dict[str, str]] = []
    for f in REQUIRED_FIELDS.get(op, []):
        v = payload.get(f)
        if v is None or (isinstance(v, str) and not v.strip()):
            out.append({"field": f, "hint": FIELD_HINTS.get(f, f"必填字段 {f}")})
    return out


def rules_payload() -> dict[str, Any]:
    """给 `GET /api/v1/assets/rules` 的响应体（前端与 MCP 共用）."""
    return {
        "code_prefix": CODE_PREFIX,
        "code_pattern": CODE_PATTERN.pattern,
        "segment_pattern": SEGMENT_PATTERN.pattern,
        "package_ext": [".zip", ".tar.gz", ".tgz"],
        "code_example": CODE_EXAMPLE,
        "required_fields": REQUIRED_FIELDS,
        "field_hints": FIELD_HINTS,
        "optional_fields": OPTIONAL_FIELDS,
        "categories": market_categories.names(),
        "projects": market_projects.parse(None),
        "enforcement": {
            "code_format": "frontend+mcp+rest",
            "version_format": "frontend+mcp+rest",
            "category_in_table": "frontend+mcp+rest",
            "package_name_matches_code": "frontend+mcp+rest",
            "code_prefix_dml": "frontend+mcp",  # ⚠️ REST 端点暂不卡（存量兼容）
        },
    }
```

> ⚠️ `market_projects.parse(None)` 返回的是「配置里的项目列表」；若实际签名不同，
> 改成 `market_projects.parse("")` 或直接读设置项 `marketplace.projects`。
> **先跑一下 `python -c "from app.core import market_projects; print(market_projects.parse(None))"` 核对。**

- [ ] **Step 4: 跑测试确认通过**

Run: `cd backend_gateway && pytest tests/test_market_rules.py -v`
Expected: PASS（6 passed）

- [ ] **Step 5: 提交**

```bash
git add backend_gateway/app/core/market_rules.py backend_gateway/tests/test_market_rules.py
git commit -m "feat(MCP): 规则单一真源 —— market_rules.py（与前端 assetForm 同口径）"
```

---

### Task 15: 适配层（调既有路由函数，不复制业务逻辑）

**Files:**
- Create: `backend_gateway/app/mcp/skill/adapter.py`
- Test: `backend_gateway/tests/test_mcp_skill_adapter.py`

**Interfaces:**
- Consumes: `app.api.marketplace` 的路由函数、`app.schemas.asset.AssetMetaUpdateIn`
- Produces（全部 `async`，第一个参数是 `User`）：
  - `search_assets(user, *, keyword=None, category=None, project=None, tag=None, author=None, include_unpublished=False, page=1, page_size=20) -> dict`
  - `get_asset(user, code) -> dict`
  - `get_asset_doc(user, code) -> dict`
  - `get_asset_files(user, code) -> dict`
  - `download_package(user, code, version) -> tuple[bytes, str]`（bytes, sha256）
  - `list_categories(user) -> list[dict]`
  - `list_projects(user) -> list[str]`
  - `get_job(user, job_id) -> dict`
  - `upload_asset(user, *, code, kind, name, summary, version, ... ) -> dict`
  - `update_asset(user, *, code, ...) -> dict`
  - `update_asset_meta(user, code, payload: dict) -> dict`
  - `submit_for_review(user, code, comment="") -> dict`
  - `unpublish_asset(user, code, confirm_code, comment="") -> dict`

> ⚠️ **三个特殊参数名**（照抄既有代码，别改）：
> `submit_for_review` 的用户参数叫 **`_user`**；`list_projects` / `preview_package` 也叫 **`_user`**。

- [ ] **Step 1: 写失败的测试**

创建 `backend_gateway/tests/test_mcp_skill_adapter.py`：

```python
"""适配层 —— 调既有路由函数, 把 HTTP 形状翻译成工具入参."""

from __future__ import annotations

import inspect

import pytest

from app.api import marketplace
from app.mcp.skill import adapter


def test_adapter_covers_route_params():
    """参数反射检查的原型 —— Task 20 会做成正式测试."""
    required = {p.name for p in inspect.signature(marketplace.upload_asset).parameters.values()
                if p.default is inspect.Parameter.empty}
    assert required <= set(inspect.signature(adapter.upload_asset).parameters), required


def test_submit_for_review_uses_underscore_user():
    """既有代码的用户参数名是 _user —— adapter 必须按关键字传."""
    sig = inspect.signature(marketplace.submit_for_review)
    assert "_user" in sig.parameters
    assert "_user" in inspect.signature(adapter.submit_for_review).parameters


def test_upload_builds_uploadfile():
    import io

    from fastapi import UploadFile

    f = adapter._package_file("dml-x.zip", b"PK\x03\x04")
    assert isinstance(f, UploadFile)
    assert f.filename == "dml-x.zip"
```

- [ ] **Step 2: 跑测试确认失败**

Run: `cd backend_gateway && pytest tests/test_mcp_skill_adapter.py -v`
Expected: FAIL —— `ModuleNotFoundError: No module named 'app.mcp.skill.adapter'`

- [ ] **Step 3: 写适配层**

创建 `backend_gateway/app/mcp/skill/adapter.py`：

```python
"""技能域适配层 —— **调既有路由函数，不复制业务逻辑**.

设计文档 §6.3。

⚠️ 路由函数的参数是 `Form(...)`/`Query(...)` 默认值 —— 直接调用时**必须显式传全部参数**
   （默认值是 Form 对象不是值）。所以每个 adapter 函数都把参数补齐。

⚠️ 三个特殊参数名：`submit_for_review` / `list_projects` / `preview_package` 的用户参数
   叫 **`_user`**（下划线前缀）—— 这是既有代码的写法，不是笔误，别「顺手改掉」。
"""

from __future__ import annotations

import io
from typing import Any

from fastapi import UploadFile
from starlette.datastructures import UploadFile as StarletteUploadFile

from app.api import marketplace
from app.models.user import User


def _package_file(filename: str, data: bytes) -> UploadFile:
    """构造一个 UploadFile —— 既有端点要的是 fastapi 的 UploadFile."""
    return UploadFile(file=io.BytesIO(data), filename=filename)


async def search_assets(
    user: User,
    *,
    keyword: str | None = None,
    category: str | None = None,
    project: str | None = None,
    tag: str | None = None,
    author: str | None = None,
    include_unpublished: bool = False,
    page: int = 1,
    page_size: int = 20,
) -> dict[str, Any]:
    """搜索技能 —— 复用 `list_assets`."""
    offset = max(0, (page - 1) * page_size)
    out = await marketplace.list_assets(
        kind="skill",
        category=category or None,
        project=project or None,
        q=keyword or None,
        sort="hot",
        include_unpublished=include_unpublished,
        status="",
        limit=page_size,
        offset=offset,
        client_id="local",
        user=user,
    )
    data = out.model_dump(mode="json") if hasattr(out, "model_dump") else dict(out)
    return data


async def get_asset(user: User, code: str) -> dict[str, Any]:
    out = await marketplace.get_asset(code=code, client_id="local", user=user)
    return out.model_dump(mode="json")


async def get_asset_doc(user: User, code: str) -> dict[str, Any]:
    out = await marketplace.get_asset_doc(code=code, user=user)
    return out.model_dump(mode="json")


async def get_asset_files(user: User, code: str) -> dict[str, Any]:
    out = await marketplace.get_asset_files(code=code, user=user)
    return out.model_dump(mode="json")


async def download_package(user: User, code: str, version: str) -> tuple[bytes, str]:
    """下载包 —— 返回 (bytes, sha256). bytes **不进 tool 返回**（§5.3 取舍 3）."""
    resp = await marketplace.download_package(code=code, version=version, user=user)
    body = getattr(resp, "body", b"")
    sha = ""
    headers = getattr(resp, "headers", {}) or {}
    for k, v in headers.items():
        if k.lower() == "x-content-sha256":
            sha = v
    return body, sha


async def list_categories(user: User) -> list[dict[str, Any]]:
    out = await marketplace.list_categories(status=None, user=user)
    data = out.model_dump(mode="json") if hasattr(out, "model_dump") else out
    return data.get("items", data) if isinstance(data, dict) else data


async def list_projects(user: User) -> list[str]:
    out = await marketplace.list_projects(_user=user)
    data = out.model_dump(mode="json") if hasattr(out, "model_dump") else out
    return data.get("items", data) if isinstance(data, dict) else list(data)


async def get_job(user: User, job_id: int) -> dict[str, Any]:
    out = await marketplace.get_job(job_id=job_id, user=user)
    return out.model_dump(mode="json")


async def upload_asset(
    user: User,
    *,
    code: str,
    kind: str = "skill",
    name: str,
    summary: str,
    version: str,
    description: str = "",
    use_when: str = "",
    not_for: str = "",
    category: str = "",
    project: str = "",
    icon: str = "🧩",
    tags: str = "[]",
    keywords: str = "[]",
    featured: bool = False,
    permissions: str = "{}",
    install_steps: str = "[]",
    bindings: str = "{}",
    mcp_config: str = "",
    package: UploadFile | None = None,
) -> dict[str, Any]:
    """上架新资产 —— 复用 `upload_asset`（落盘 → git commit → 审核 → 通知都在既有逻辑里）."""
    out = await marketplace.upload_asset(
        code=code, kind=kind, name=name, summary=summary, version=version,
        description=description, use_when=use_when, not_for=not_for,
        category=category, project=project, icon=icon, tags=tags, keywords=keywords,
        featured=featured, permissions=permissions, install_steps=install_steps,
        bindings=bindings, mcp_config=mcp_config,
        files=None, package=package, user=user,
    )
    return out.model_dump(mode="json")


async def update_asset(
    user: User,
    *,
    code: str,
    kind: str = "skill",
    name: str,
    summary: str,
    version: str,
    description: str = "",
    use_when: str = "",
    not_for: str = "",
    category: str = "",
    project: str = "",
    icon: str = "🧩",
    tags: str = "[]",
    keywords: str = "[]",
    featured: bool = False,
    permissions: str = "{}",
    install_steps: str = "[]",
    bindings: str = "{}",
    mcp_config: str = "",
    package: UploadFile | None = None,
) -> dict[str, Any]:
    """发新版本 —— 复用 `update_asset`."""
    out = await marketplace.update_asset(
        code=code, kind=kind, name=name, summary=summary, version=version,
        description=description, use_when=use_when, not_for=not_for,
        category=category, project=project, icon=icon, tags=tags, keywords=keywords,
        featured=featured, permissions=permissions, install_steps=install_steps,
        bindings=bindings, mcp_config=mcp_config,
        files=None, package=package, user=user,
    )
    return out.model_dump(mode="json")


async def update_asset_meta(user: User, code: str, payload: dict[str, Any]) -> dict[str, Any]:
    """只改信息 —— 复用 `update_asset_meta`（pending_action=meta → 审核后不通知市场群）."""
    from app.schemas.asset import AssetMetaUpdateIn

    # ⚠️ AssetMetaUpdateIn 的每个字段默认 None = 不改（不是清空）—— 只传要改的
    body = {k: v for k, v in payload.items() if v is not None}
    out = await marketplace.update_asset_meta(code=code, payload=AssetMetaUpdateIn(**body), user=user)
    return out.model_dump(mode="json")


async def submit_for_review(user: User, code: str, comment: str = "") -> dict[str, Any]:
    """重新提交审核 —— 注意既有函数的用户参数叫 `_user`."""
    out = await marketplace.submit_for_review(code=code, comment=comment, _user=user)
    return out.model_dump(mode="json")


async def unpublish_asset(user: User, code: str, confirm_code: str, comment: str = "") -> dict[str, Any]:
    """下架 —— `confirm_code` 必须等于 code（平台既有的防误操作契约，MCP 不能绕过）."""
    out = await marketplace.unpublish_asset(
        code=code, confirm_code=confirm_code, comment=comment, user=user
    )
    return out.model_dump(mode="json")
```

- [ ] **Step 4: 跑测试确认通过**

Run: `cd backend_gateway && pytest tests/test_mcp_skill_adapter.py -v`
Expected: PASS（3 passed）

- [ ] **Step 5: 提交**

```bash
git add backend_gateway/app/mcp/skill/adapter.py backend_gateway/tests/test_mcp_skill_adapter.py
git commit -m "feat(MCP): 技能域适配层 —— 调既有路由函数（_user 等怪参数名已处理）"
```

---

### Task 16: 14 个工具 + 「不猜」协议

**Files:**
- Modify: `backend_gateway/app/mcp/skill/tools.py`（替换掉 Task 13 的占位工具）
- Modify: `backend_gateway/app/mcp/common/tool.py`（补 `needs_confirmation` 的返回路径）
- Test: `backend_gateway/tests/test_mcp_skill_tools.py`

**Interfaces:**
- Consumes: `app.mcp.skill.adapter`、`app.core.market_rules`、`app.mcp.common.tool.ToolSpec`
- Produces: `app/mcp/skill/tools.py::TOOLS: list[ToolSpec]` —— **恰好 14 个**（9 读 + 5 写）
  读：`skill_search` `skill_get` `skill_read_doc` `skill_read_file` `skill_list_files` `skill_package_info` `skill_categories` `skill_projects` `skill_job_status`
  写：`skill_publish` `skill_update` `skill_edit_meta` `skill_submit_review` `skill_unpublish_request`

- [ ] **Step 1: 写失败的测试**

创建 `backend_gateway/tests/test_mcp_skill_tools.py`：

```python
"""技能域工具 —— 工具清单 / 「不猜」协议."""

from __future__ import annotations

import pytest

from app.mcp.skill.tools import TOOLS

READ_TOOLS = {
    "skill_search", "skill_get", "skill_read_doc", "skill_read_file", "skill_list_files",
    "skill_package_info", "skill_categories", "skill_projects", "skill_job_status",
}
WRITE_TOOLS = {
    "skill_publish", "skill_update", "skill_edit_meta", "skill_submit_review",
    "skill_unpublish_request",
}


def test_exactly_14_tools():
    assert len(TOOLS) == 14
    assert {t.name for t in TOOLS} == READ_TOOLS | WRITE_TOOLS


def test_scopes_are_right():
    for t in TOOLS:
        if t.name in WRITE_TOOLS:
            assert t.scope == "market:write"
            assert t.read_only is False
        else:
            assert t.scope == "market:read"
            assert t.read_only is True


def test_schemas_are_valid_json_schema():
    import jsonschema

    for t in TOOLS:
        jsonschema.Draft202012Validator.check_schema(t.input_schema)


@pytest.mark.asyncio
async def test_publish_without_summary_asks_instead_of_guessing():
    """不猜协议 —— 必填缺失必须拒绝执行, 且不产生副作用."""
    from app.mcp.skill.tools import _needs_confirmation

    r = await _needs_confirmation("create", {"code": "dml-x", "name": "n"}, kind="skill")
    assert r is not None
    assert any(m["field"] == "summary" for m in r["missing_fields"])


@pytest.mark.asyncio
async def test_publish_with_bad_category_returns_choices():
    from app.mcp.skill.tools import _needs_confirmation

    r = await _needs_confirmation(
        "create",
        {"code": "dml-x", "name": "n", "summary": "s", "version": "1.0.0", "category": "不存在"},
        kind="skill",
    )
    assert r is not None
    assert "choices" in r
```

- [ ] **Step 2: 跑测试确认失败**

Run: `cd backend_gateway && pytest tests/test_mcp_skill_tools.py -v`
Expected: FAIL —— 工具数量不对（现在只有 1 个占位工具）

- [ ] **Step 3: 写 14 个工具**

**整份替换** `backend_gateway/app/mcp/skill/tools.py`：

```python
"""技能·插件域的工具定义 —— 14 个（9 读 + 5 写）.

设计文档 §5。

⚠️ **「不猜」协议**（§4.12.3）：必填缺失 / 枚举越界 / 有多候选 / 可选项未确认
   → 一律**拒绝执行**并返回 needs_confirmation，**不产生任何副作用**。
   绝不替用户做默认值兜底。
"""

from __future__ import annotations

import base64
import binascii
from typing import Any

from app.core import market_categories, market_projects
from app.core.market_rules import (
    OPTIONAL_FIELDS,
    check_required,
    validate_code,
    validate_package_name,
)
from app.mcp.common.context import McpContext
from app.mcp.common.tool import ToolSpec
from app.mcp.skill import adapter

DOMAIN = "skill"


async def _needs_confirmation(op: str, payload: dict[str, Any], *, kind: str = "skill") -> dict[str, Any] | None:
    """返回 needs_confirmation 结构；一切正常则返回 None（可以执行）."""
    out: dict[str, Any] = {}

    missing = check_required(op, payload)
    if missing:
        out["missing_fields"] = missing

    # 枚举校验 —— 分类不在表里 → 给候选项
    cat = (payload.get("category") or "").strip()
    if cat and not market_categories.is_valid(cat):
        out["choices"] = {"category": market_categories.names()}

    proj = (payload.get("project") or "").strip()
    if proj and not market_projects.is_valid(proj, market_projects.parse(None)):
        out.setdefault("choices", {})["project"] = market_projects.parse(None)

    # 可选项 —— 没给就列出来让用户确认要不要填
    optional = OPTIONAL_FIELDS.get(op, [])
    pending = [o for o in optional if payload.get(o["field"]) in (None, "", [], {})]
    if pending:
        out["optional_fields"] = pending

    problems: list[str] = []
    code = (payload.get("code") or "").strip()
    if code:
        require_prefix = op == "create"
        msg = validate_code(code, require_prefix=require_prefix)
        if msg:
            problems.append(msg)
    pkg_name = payload.get("package_name")
    if pkg_name:
        msg = validate_package_name(pkg_name, require_prefix=(op == "create"))
        if msg:
            problems.append(msg)
    if problems:
        out["problems"] = problems

    return out or None


def _json_list(v: Any) -> str:
    """列表/字典 → JSON 字符串（既有端点要的是字符串字段）."""
    import json

    return json.dumps(v, ensure_ascii=False)


# ===== 读工具 =====

async def _search(ctx: McpContext, args: dict[str, Any]) -> Any:
    data = await adapter.search_assets(
        ctx.user,  # type: ignore[arg-type]
        keyword=args.get("keyword"),
        category=args.get("category"),
        project=args.get("project"),
        tag=args.get("tag"),
        author=args.get("author"),
        include_unpublished=bool(args.get("include_unpublished", False)),
        page=int(args.get("page", 1)),
        page_size=int(args.get("page_size", 20)),
    )
    return data


async def _get(ctx: McpContext, args: dict[str, Any]) -> Any:
    return await adapter.get_asset(ctx.user, args["code"])  # type: ignore[arg-type]


async def _read_doc(ctx: McpContext, args: dict[str, Any]) -> Any:
    return await adapter.get_asset_doc(ctx.user, args["code"])  # type: ignore[arg-type]


async def _list_files(ctx: McpContext, args: dict[str, Any]) -> Any:
    return await adapter.get_asset_files(ctx.user, args["code"])  # type: ignore[arg-type]


async def _read_file(ctx: McpContext, args: dict[str, Any]) -> Any:
    files = await adapter.get_asset_files(ctx.user, args["code"])  # type: ignore[arg-type]
    items = files.get("files") or files.get("items") or []
    want = str(args["path"]).lstrip("/")
    for f in items:
        if f.get("path") == want:
            # 文本文件内容 —— 包内文件一律走既有下载接口取字节
            body, _sha = await adapter.download_package(
                ctx.user, args["code"], str(args.get("version") or "")  # type: ignore[arg-type]
            )
            return {"path": want, "size": f.get("size"), "note": "包内文件内容请用 download + 自行解包读取"}
    from app.mcp.common.errors import McpError

    raise McpError(code="not_found", message=f"包里没有 {want}",
                   hint="先用 skill_list_files 看文件树")


async def _package_info(ctx: McpContext, args: dict[str, Any]) -> Any:
    asset = await adapter.get_asset(ctx.user, args["code"])  # type: ignore[arg-type]
    version = str(args.get("version") or asset.get("version") or "")
    import os

    base = (os.environ.get("MCP_ISSUER_URL") or "").rstrip("/")
    return {
        "code": asset.get("code"),
        "version": version,
        "download_url": f"{base}/api/v1/assets/{asset.get('code')}/versions/{version}/download",
        "sha256": asset.get("git_commit_sha") or "",
        "size_bytes": asset.get("size") or None,
        "note": "下载走既有接口；下载后请自行核对 sha256",
    }


async def _categories(ctx: McpContext, args: dict[str, Any]) -> Any:
    return await adapter.list_categories(ctx.user)  # type: ignore[arg-type]


async def _projects(ctx: McpContext, args: dict[str, Any]) -> Any:
    return await adapter.list_projects(ctx.user)  # type: ignore[arg-type]


async def _job_status(ctx: McpContext, args: dict[str, Any]) -> Any:
    return await adapter.get_job(ctx.user, int(args["job_id"]))  # type: ignore[arg-type]


# ===== 写工具 =====

async def _publish(ctx: McpContext, args: dict[str, Any]) -> Any:
    payload = {k: v for k, v in args.items() if k not in ("files", "package_base64")}
    need = await _needs_confirmation("create", payload, kind="skill")
    if need:
        return {"ok": False, "needs_confirmation": need}

    package = None
    if args.get("package_base64"):
        try:
            raw = base64.b64decode(args["package_base64"], validate=True)
        except (binascii.Error, ValueError) as exc:
            from app.mcp.common.errors import McpError

            raise McpError(code="invalid_argument", message="package_base64 不是合法 base64") from exc
        package = adapter._package_file(f"{args['code']}.zip", raw)
    elif args.get("files"):
        import io
        import zipfile

        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w") as zf:
            for path, content in (args["files"] or {}).items():
                zf.writestr(path, content)
        package = adapter._package_file(f"{args['code']}.zip", buf.getvalue())

    return await adapter.upload_asset(
        ctx.user,  # type: ignore[arg-type]
        code=args["code"], kind="skill", name=args["name"], summary=args["summary"],
        version=args["version"],
        description=args.get("description", ""), use_when=args.get("use_when", ""),
        not_for=args.get("not_for", ""), category=args.get("category", ""),
        project=args.get("project", ""), icon=args.get("icon", "🧩"),
        tags=_json_list(args.get("tags") or []), keywords=_json_list(args.get("keywords") or []),
        permissions=_json_list(args.get("permissions") or {}),
        install_steps=_json_list(args.get("install_steps") or []),
        bindings=_json_list(args.get("bindings") or {}),
        package=package,
    )


async def _update(ctx: McpContext, args: dict[str, Any]) -> Any:
    payload = {k: v for k, v in args.items() if k not in ("files", "package_base64")}
    need = await _needs_confirmation("update", payload, kind="skill")
    if need:
        return {"ok": False, "needs_confirmation": need}
    # 字段省略 = 保持现状 → read-modify-write
    cur = await adapter.get_asset(ctx.user, args["code"])  # type: ignore[arg-type]
    version = args.get("version") or _bump_version(str(cur.get("version") or "0.0.0"))

    package = None
    if args.get("package_base64"):
        raw = base64.b64decode(args["package_base64"], validate=True)
        package = adapter._package_file(f"{args['code']}.zip", raw)
    elif args.get("files"):
        import io
        import zipfile

        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w") as zf:
            for path, content in (args["files"] or {}).items():
                zf.writestr(path, content)
        package = adapter._package_file(f"{args['code']}.zip", buf.getvalue())

    return await adapter.update_asset(
        ctx.user,  # type: ignore[arg-type]
        code=args["code"], kind="skill",
        name=args.get("name") or cur.get("name"),
        summary=args.get("summary") or cur.get("summary"),
        version=version,
        description=args.get("description", cur.get("description", "")),
        use_when=args.get("use_when", cur.get("use_when", "")),
        not_for=args.get("not_for", cur.get("not_for", "")),
        category=args.get("category", cur.get("category", "")),
        project=args.get("project", cur.get("project", "")),
        icon=args.get("icon", cur.get("icon", "🧩")),
        tags=_json_list(args.get("tags") or cur.get("tags") or []),
        keywords=_json_list(args.get("keywords") or cur.get("keywords") or []),
        permissions=_json_list(args.get("permissions") or cur.get("permissions") or {}),
        install_steps=_json_list(args.get("install_steps") or cur.get("install_steps") or []),
        bindings=_json_list(args.get("bindings") or cur.get("bindings") or {}),
        package=package,
    )


def _bump_version(v: str) -> str:
    """x.y.z → x.y.(z+1)（没给版本时的默认）."""
    parts = (v or "0.0.0").split(".")
    try:
        parts[-1] = str(int(parts[-1]) + 1)
    except (ValueError, IndexError):
        return "0.0.1"
    return ".".join(parts)


async def _edit_meta(ctx: McpContext, args: dict[str, Any]) -> Any:
    payload = {k: v for k, v in args.items() if k != "code"}
    need = await _needs_confirmation("edit_meta", payload, kind="skill")
    if need:
        return {"ok": False, "needs_confirmation": need}
    return await adapter.update_asset_meta(ctx.user, args["code"], payload)  # type: ignore[arg-type]


async def _submit_review(ctx: McpContext, args: dict[str, Any]) -> Any:
    return await adapter.submit_for_review(ctx.user, args["code"], args.get("comment", ""))  # type: ignore[arg-type]


async def _unpublish(ctx: McpContext, args: dict[str, Any]) -> Any:
    return await adapter.unpublish_asset(
        ctx.user, args["code"], confirm_code=args["code"], comment=args.get("reason", "")  # type: ignore[arg-type]
    )


def _schema(props: dict[str, Any], required: list[str] | None = None) -> dict[str, Any]:
    return {
        "type": "object",
        "properties": props,
        "required": required or [],
        "additionalProperties": False,
    }


_STR = {"type": "string"}
_STR_LIST = {"type": "array", "items": {"type": "string"}}
_OBJ = {"type": "object"}


TOOLS: list[ToolSpec] = [
    # ---------- 读 ----------
    ToolSpec(
        name="skill_search",
        description="搜索技能。默认只返回已上架的；include_unpublished=true 仅对作者本人/管理员/审核人生效。",
        input_schema=_schema({
            "keyword": _STR, "category": _STR, "project": _STR, "tag": _STR, "author": _STR,
            "include_unpublished": {"type": "boolean"},
            "page": {"type": "integer", "minimum": 1},
            "page_size": {"type": "integer", "minimum": 1, "maximum": 100},
        }),
        handler=_search, scope="market:read", read_only=True, domain=DOMAIN,
    ),
    ToolSpec(
        name="skill_get",
        description="技能详情（manifest 全字段）。对调用者不可见的资产按「不存在」处理。",
        input_schema=_schema({"code": _STR}, ["code"]),
        handler=_get, scope="market:read", read_only=True, domain=DOMAIN,
    ),
    ToolSpec(
        name="skill_read_doc",
        description="读技能的 SKILL.md（展示文档）—— agent 真正要的内容。",
        input_schema=_schema({"code": _STR}, ["code"]),
        handler=_read_doc, scope="market:read", read_only=True, domain=DOMAIN,
    ),
    ToolSpec(
        name="skill_read_file",
        description="读包内某个文本文件。路径越界会被拒绝。",
        input_schema=_schema({"code": _STR, "path": _STR, "version": _STR}, ["code", "path"]),
        handler=_read_file, scope="market:read", read_only=True, domain=DOMAIN,
    ),
    ToolSpec(
        name="skill_list_files",
        description="列出技能包内的文件树。",
        input_schema=_schema({"code": _STR}, ["code"]),
        handler=_list_files, scope="market:read", read_only=True, domain=DOMAIN,
    ),
    ToolSpec(
        name="skill_package_info",
        description="取技能包的下载 URL 与校验值。zip 字节不会出现在工具返回里。",
        input_schema=_schema({"code": _STR, "version": _STR}, ["code"]),
        handler=_package_info, scope="market:read", read_only=True, domain=DOMAIN,
    ),
    ToolSpec(
        name="skill_categories",
        description="列出合法分类（填表时用）。",
        input_schema=_schema({}),
        handler=_categories, scope="market:read", read_only=True, domain=DOMAIN,
    ),
    ToolSpec(
        name="skill_projects",
        description="列出合法项目（填表时用）。",
        input_schema=_schema({}),
        handler=_projects, scope="market:read", read_only=True, domain=DOMAIN,
    ),
    ToolSpec(
        name="skill_job_status",
        description="查上架/更新任务的状态（git push 结果）。",
        input_schema=_schema({"job_id": {"type": "integer"}}, ["job_id"]),
        handler=_job_status, scope="market:read", read_only=True, domain=DOMAIN,
    ),
    # ---------- 写 ----------
    ToolSpec(
        name="skill_publish",
        description=(
            "上架新技能。files（路径→内容映射）或 package_base64（zip 的 base64）二选一。"
            "缺必填/分类不合法/可选项未确认时**不会执行**，而是返回 needs_confirmation —— "
            "请把问题回问用户，不要自己替他决定。"
        ),
        input_schema=_schema({
            "code": _STR, "name": _STR, "summary": _STR, "version": _STR,
            "description": _STR, "use_when": _STR, "not_for": _STR,
            "category": _STR, "project": _STR, "icon": _STR,
            "tags": _STR_LIST, "keywords": _STR_LIST,
            "permissions": _OBJ, "install_steps": _STR_LIST, "bindings": _OBJ,
            "files": {"type": "object", "additionalProperties": {"type": "string"}},
            "package_base64": _STR,
        }, ["code", "name", "summary", "version"]),
        handler=_publish, scope="market:write", read_only=False, domain=DOMAIN,
    ),
    ToolSpec(
        name="skill_update",
        description=(
            "发新版本（带包）。字段省略 = 保持现状；version 省略时自动 patch 末位。"
            "给了 files/package_base64 = 整体替换包内容。只改说明文字请用 skill_edit_meta。"
        ),
        input_schema=_schema({
            "code": _STR, "name": _STR, "summary": _STR, "version": _STR,
            "description": _STR, "use_when": _STR, "not_for": _STR,
            "category": _STR, "project": _STR, "icon": _STR,
            "tags": _STR_LIST, "keywords": _STR_LIST,
            "permissions": _OBJ, "install_steps": _STR_LIST, "bindings": _OBJ,
            "files": {"type": "object", "additionalProperties": {"type": "string"}},
            "package_base64": _STR,
        }, ["code"]),
        handler=_update, scope="market:write", read_only=False, domain=DOMAIN,
    ),
    ToolSpec(
        name="skill_edit_meta",
        description=(
            "只改信息（简介/说明/标签等），不动包、不发版本。"
            "审核通过后**不会**通知市场群（包没变）。"
        ),
        input_schema=_schema({
            "code": _STR, "name": _STR, "summary": _STR, "description": _STR,
            "use_when": _STR, "not_for": _STR, "category": _STR, "project": _STR,
            "icon": _STR, "tags": _STR_LIST, "keywords": _STR_LIST,
        }, ["code"]),
        handler=_edit_meta, scope="market:write", read_only=False, domain=DOMAIN,
    ),
    ToolSpec(
        name="skill_submit_review",
        description="把被驳回的资产重新提交审核。",
        input_schema=_schema({"code": _STR, "comment": _STR}, ["code"]),
        handler=_submit_review, scope="market:write", read_only=False, domain=DOMAIN,
    ),
    ToolSpec(
        name="skill_unpublish_request",
        description=(
            "申请下架。审核开着 → 转待确认（管理员确认后彻底删除）；"
            "审核关着 → 自助下架（文件保留，可重新上架）。"
        ),
        input_schema=_schema({"code": _STR, "reason": _STR}, ["code"]),
        handler=_unpublish, scope="market:write", read_only=False, domain=DOMAIN,
    ),
]
```

> ⚠️ **`featured` 故意没有**：既有的 `AssetMetaUpdateIn`（`app/schemas/asset.py:280`）里**没有** `featured`
> 字段，`skill_edit_meta` 传了也传不进去。设计文档 §5.2 的 `featured?` 已在 v11 修正时移除。
> ⚠️ **`ctx.user`**：`McpContext` 目前只有 `principal`（没有 ORM 的 `User`）。
> 在 `app/mcp/common/context.py` 加一个方法：

```python
    async def user(self):
        """现查 User —— 权限实时生效（角色/白名单改了立刻生效）."""
        from app.db.session import AsyncSessionLocal
        from app.models.user import User
        from sqlalchemy import select

        async with AsyncSessionLocal() as s:
            u = (await s.execute(select(User).where(User.id == self.principal.user_id))).scalars().first()
            if u is None:
                from app.mcp.common.errors import McpError

                raise McpError(code="unauthorized", message="绑定用户不存在或已被停用")
            return u
```

然后把上面所有 `ctx.user` 改成 `await ctx.user()`。

- [ ] **Step 4: 跑测试确认通过**

Run: `cd backend_gateway && pytest tests/test_mcp_skill_tools.py -v`
Expected: PASS（5 passed）

- [ ] **Step 5: 跑全量测试**

Run: `cd backend_gateway && pytest -q`
Expected: 全绿

- [ ] **Step 6: 提交**

```bash
git add backend_gateway/app/mcp/skill/tools.py backend_gateway/app/mcp/common/ \
        backend_gateway/tests/test_mcp_skill_tools.py
git commit -m "feat(MCP): 14 个技能工具 —— 9 读 5 写 + 不猜协议（needs_confirmation）"
```

---

### Task 17: 工具清单契约测试（对外 API 冻结）

**Files:**
- Create: `backend_gateway/tests/test_mcp_tool_contracts.py`

**Interfaces:**
- Consumes: `app.mcp.skill.tools.TOOLS`
- Produces: 一份「工具清单快照」测试 —— 工具名/参数/scope 变了会红（防止随手改坏 agent 的用法）

- [ ] **Step 1: 写测试**

创建 `backend_gateway/tests/test_mcp_tool_contracts.py`：

```python
"""工具清单契约 —— 名字/参数/scope 冻结.

⚠️ agent 侧（Qoder 等）会记住这些工具名与参数 —— 改名就是破坏性变更，
   必须先更新设计文档与本快照。
"""

from __future__ import annotations

from app.mcp.skill.tools import TOOLS

EXPECTED = {
    "skill_search": (["keyword", "category", "project", "tag", "author",
                       "include_unpublished", "page", "page_size"], [], "market:read"),
    "skill_get": (["code"], ["code"], "market:read"),
    "skill_read_doc": (["code"], ["code"], "market:read"),
    "skill_read_file": (["code", "path", "version"], ["code", "path"], "market:read"),
    "skill_list_files": (["code"], ["code"], "market:read"),
    "skill_package_info": (["code", "version"], ["code"], "market:read"),
    "skill_categories": ([], [], "market:read"),
    "skill_projects": ([], [], "market:read"),
    "skill_job_status": (["job_id"], ["job_id"], "market:read"),
    "skill_publish": (["code", "name", "summary", "version", "description", "use_when",
                        "not_for", "category", "project", "icon", "tags", "keywords",
                        "permissions", "install_steps", "bindings", "files",
                        "package_base64"],
                       ["code", "name", "summary", "version"], "market:write"),
    "skill_update": (["code", "name", "summary", "version", "description", "use_when",
                      "not_for", "category", "project", "icon", "tags", "keywords",
                      "permissions", "install_steps", "bindings", "files",
                      "package_base64"],
                     ["code"], "market:write"),
    "skill_edit_meta": (["code", "name", "summary", "description", "use_when", "not_for",
                          "category", "project", "icon", "tags", "keywords"],
                         ["code"], "market:write"),
    "skill_submit_review": (["code", "comment"], ["code"], "market:write"),
    "skill_unpublish_request": (["code", "reason"], ["code"], "market:write"),
}


def test_tool_snapshot():
    by_name = {t.name: t for t in TOOLS}
    assert set(by_name) == set(EXPECTED)
    for name, (props, required, scope) in EXPECTED.items():
        t = by_name[name]
        assert set(t.input_schema["properties"]) == set(props), name
        assert set(t.input_schema["required"]) == set(required), name
        assert t.scope == scope, name


def test_tool_names_are_prefixed():
    for t in TOOLS:
        assert t.name.startswith("skill_")

---

# Stage S5.5 — 一致性收敛

> 这一阶段是整个方案的**核心资产**（设计文档 §4.13）：
> 把「REST 与 MCP 走同一条流程」从口号变成**会红的测试**。

### Task 18: `GET /assets/rules` + 前端改为拉规则

**Files:**
- Modify: `backend_gateway/app/api/marketplace.py`（**+1 个只读端点**）
- Modify: `frontend_web/src/views/Capability/Catalog/assetForm.ts`
- Modify: `frontend_web/src/views/Capability/Catalog/useAssetUploadForm.ts`
- Test: `backend_gateway/tests/test_market_rules_endpoint.py`

**Interfaces:**
- Consumes: `app.core.market_rules.rules_payload()`
- Produces: `GET /api/v1/assets/rules` → `rules_payload()` 的 JSON

- [ ] **Step 1: 写失败的测试**

创建 `backend_gateway/tests/test_market_rules_endpoint.py`：

```python
"""GET /assets/rules —— 规则的单一出口."""

from __future__ import annotations

import pytest
from httpx import ASGITransport, AsyncClient

from tests._lifespan import lifespan_driver


@pytest.mark.asyncio
async def test_rules_endpoint_returns_rule_bundle():
    from app.main import app

    async with lifespan_driver(app):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://testserver") as c:
            r = await c.get("/api/v1/assets/rules")
    assert r.status_code == 200, r.text
    d = r.json()
    for k in ("code_prefix", "code_pattern", "segment_pattern", "package_ext",
              "required_fields", "optional_fields", "categories", "projects", "enforcement"):
        assert k in d, k
    assert d["code_prefix"] == "dml-"
```

- [ ] **Step 2: 跑测试确认失败**

Run: `cd backend_gateway && pytest tests/test_market_rules_endpoint.py -v`
Expected: FAIL —— 404

- [ ] **Step 3: 加端点**

修改 `backend_gateway/app/api/marketplace.py`，**在 `@router.get("/{code}")` 之前**加（顺序很重要 ——
`/{code}` 会吞掉 `/rules`）：

```python
@router.get("/rules")
async def get_asset_rules(user: User = Depends(get_current_user)) -> dict[str, Any]:
    """上架/更新规则的**唯一出口** —— 前端与 MCP 都从这里取（§4.13.2 L1）."""
    from app.core.market_rules import rules_payload

    return rules_payload()
```

> ⚠️ 放在 `/{code}` **之前**是必须的 —— Starlette 按注册顺序匹配，
> `/{code}` 先注册会把 `/rules` 当成 code 处理。

- [ ] **Step 4: 跑测试确认通过**

Run: `cd backend_gateway && pytest tests/test_market_rules_endpoint.py -v`
Expected: PASS

- [ ] **Step 5: 前端改为拉规则**

修改 `frontend_web/src/views/Capability/Catalog/assetForm.ts`：

```ts
/**
 * 上架规则的默认值 —— **从后端拉**（GET /api/v1/assets/rules）。
 *
 * ⚠️ 2026-10-31: 原来这些常量是**硬编码**在前端，MCP 侧在 Python 里又写了一份
 *    → 两份规则会漂移。现在改成拉接口，后端 app/core/market_rules.py 是唯一真源。
 *
 * 保留这些导出是为了**不破坏既有 import**（单测与其它文件在用），
 * 真实值在 main.ts 里被 fetch 到的规则覆盖。
 */
export const CODE_PREFIX = 'dml-';
export const CODE_PATTERN = /^dml-[a-z0-9]+(?:-[a-z0-9]+)*$/;
export const SEGMENT_PATTERN = /^[a-z0-9]+(?:-[a-z0-9]+)*$/;
export const CODE_EXAMPLE = 'dml-ssd-log-doctor';
export const PACKAGE_EXT_RE = /\.(zip|tar\.gz|tgz)$/i;

/** 后端拉回来的规则（未加载前用上面的默认值兜底） */
export const marketRules = reactive<{
    codePrefix: string;
    codePattern: RegExp;
    segmentPattern: RegExp;
    packageExt: string[];
    requiredFields: Record<string, string[]>;
    optionalFields: Record<string, { field: string; hint: string }[]>;
    categories: string[];
    projects: string[];
    loaded: boolean;
}>({
    codePrefix: CODE_PREFIX,
    codePattern: CODE_PATTERN,
    segmentPattern: SEGMENT_PATTERN,
    packageExt: ['.zip', '.tar.gz', '.tgz'],
    requiredFields: { create: [], update: [], edit_meta: [] },
    optionalFields: {},
    categories: [],
    projects: [],
    loaded: false,
});

/** 拉一次规则并覆盖本地常量 —— 挂应用启动时调用 */
export async function loadMarketRules(): Promise<void> {
    const r = await apiGet<any>('/assets/rules');
    marketRules.codePrefix = r.code_prefix ?? CODE_PREFIX;
    marketRules.codePattern = new RegExp(r.code_pattern ?? CODE_PATTERN.source);
    marketRules.segmentPattern = new RegExp(r.segment_pattern ?? SEGMENT_PATTERN.source);
    marketRules.packageExt = r.package_ext ?? ['.zip', '.tar.gz', '.tgz'];
    marketRules.requiredFields = r.required_fields ?? {};
    marketRules.optionalFields = r.optional_fields ?? {};
    marketRules.categories = r.categories ?? [];
    marketRules.projects = r.projects ?? [];
    marketRules.loaded = true;
}
```

并把 `validateCode` / `validatePackageName` 里的硬编码正则换成 `marketRules.*`：

```ts
export function validateCode(code: string): string {
    const c = (code || '').trim();
    if (!c) return '请填写资产 code';
    if (!c.startsWith(marketRules.codePrefix)) {
        return `资产 code 必须以 "${marketRules.codePrefix}" 开头 (如 ${marketRules.codeExample ?? CODE_EXAMPLE})`;
    }
    if (!marketRules.codePattern.test(c)) {
        return `资产 code 只能用小写字母/数字/连字符, 如 ${CODE_EXAMPLE}`;
    }
    return '';
}
```

修改 `frontend_web/src/views/Capability/Catalog/useAssetUploadForm.ts` 的 `missing` 计算，
把硬编码的 `out.push('名称')` 等改为读 `marketRules.requiredFields`：

```ts
    // ⚠️ 必填清单来自后端（单一真源）—— 不再硬编码
    const need = marketRules.requiredFields[mode()] ?? [];
    for (const f of need) {
        if (f === 'package') { if (!pkgFile.value) out.push('安装包'); continue; }
        if (f === 'category') { if (!form.category) out.push('分类'); continue; }
        if (f === 'code') { if (mode() === 'create' && !form.code.trim()) out.push('资产 code'); continue; }
        const v = (form as any)[f];
        if (v === undefined || v === null || (typeof v === 'string' && !v.trim())) out.push(f);
    }
```

> ⚠️ 前端表单字段名与后端字段名可能不完全一致（如 `summary` ↔「一句话简介」）。
> 改完必须跑前端既有单测（`src/views/Capability/Catalog/__tests__/` 若存在）
> 与 `npm run build`，**有单测断言必填清单文案的地方要同步更新断言**。

- [ ] **Step 6: 在应用启动时拉规则**

修改 `frontend_web/src/main.ts`（或 `App.vue` 的 `onMounted`），加：

```ts
import { loadMarketRules } from '@/views/Capability/Catalog/assetForm';

loadMarketRules().catch(() => {
    // 拉不到就用前端默认值兜底 —— 不能因为规则接口挂了就把整个市场页卡死
});
```

- [ ] **Step 7: 校验**

Run: `cd backend_gateway && pytest tests/test_market_rules.py tests/test_market_rules_endpoint.py -v`
Expected: PASS

Run: `cd frontend_web && npm run build`
Expected: 成功

- [ ] **Step 8: 提交**

```bash
git add backend_gateway/app/api/marketplace.py backend_gateway/tests/test_market_rules_endpoint.py \
        frontend_web/src/views/Capability/Catalog/
git commit -m "feat(MCP): 规则单一真源 —— /assets/rules 端点 + 前端改为拉规则"
```

---

### Task 19: 契约测试（REST vs MCP，8 个场景）

**Files:**
- Create: `backend_gateway/tests/test_mcp_contract.py`
- Create: `backend_gateway/tests/_mcp_client.py`（测试用 MCP 调用器）

**Interfaces:**
- Consumes: `app.mcp.skill.tools.TOOLS`、`app.api.marketplace` 的路由、`app.mcp.common.auth.issue_mcp_access_token`
- Produces: `tests/_mcp_client.py::McpTestClient` —— 一个能直接 `call_tool(name, args)` 的测试助手
  （**用「预置 grant + 签发 token」构造身份，不跑浏览器授权流程** —— §4.13.2）

- [ ] **Step 1: 写 MCP 调用器**

创建 `backend_gateway/tests/_mcp_client.py`：

```python
"""测试用 MCP 调用器 —— 直接调工具, 不走 HTTP.

⚠️ **不走浏览器授权流程**：用「预置 grant + 签发 token」构造身份。
   浏览器流程由 tests/test_mcp_oauth_flow.py 单独覆盖（§4.13.2）。
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from app.db.session import AsyncSessionLocal
from app.mcp.common.auth import issue_mcp_access_token
from app.mcp.common.context import McpContext
from app.models.mcp import McpOAuthGrant
from sqlalchemy import select


class McpTestClient:
    """按名字找工具并直接调 handler."""

    def __init__(self, tools: list, principal) -> None:
        self._tools = {t.name: t for t in tools}
        self._principal = principal

    async def call_tool(self, name: str, args: dict[str, Any]) -> Any:
        spec = self._tools[name]
        ctx = McpContext(principal=self._principal, domain=spec.domain)
        return await spec.handler(ctx, args)


async def make_principal(user: dict, client_id: str = "test-client",
                          scopes=("market:read", "market:write"), role: str = "tester"):
    """造一个 Principal —— 并在 grant 表里落一行（吊销链需要它真实存在）.

    ⚠️ `user` 是 tests/conftest.py 的用户夹具 **dict**（含 id / username / token），
       不是 ORM 实例 —— 与既有测试的用法一致。
    """
    async with AsyncSessionLocal() as s:
        row = (await s.execute(select(McpOAuthGrant).where(
            McpOAuthGrant.user_id == user["id"], McpOAuthGrant.client_id == client_id
        ))).scalars().first()
        if row is None:
            row = McpOAuthGrant(user_id=user["id"], client_id=client_id, client_name=client_id,
                                scopes=list(scopes), created_at=datetime.utcnow())
            s.add(row)
        else:
            row.scopes = list(scopes)
            row.revoked_at = None
        await s.commit()
        await s.refresh(row)
        grant_id = int(row.id)

    from app.mcp.common.auth import Principal

    return Principal(
        user_id=int(user["id"]),
        username=user["username"],
        role=role,
        client_id=client_id,
        client_name=client_id,
        scopes=frozenset(scopes),
        grant_id=grant_id,
    )
```

- [ ] **Step 2: 写契约测试**

创建 `backend_gateway/tests/test_mcp_contract.py`：

```python
"""契约测试 —— 同一场景, REST 与 MCP 各跑一遍, 三项断言一致.

设计文档 §4.13.2 L2。这是「一致性」的可执行定义：红了就是分叉了。

三项断言：
  ① DB 落库状态一致
  ② 钉钉通知事件序列一致
  ③ 返回值一致（字段裁剪后）

⚠️ 身份用「预置 grant + 签发 token」构造（tests/_mcp_client.py），**不跑浏览器授权流程** ——
   浏览器流程由 tests/test_mcp_oauth_flow.py 单独覆盖。
⚠️ 每条路径用**不同的 code**（ct-rest-N / ct-mcp-N），避免第二条撞「code 已存在」。
"""

from __future__ import annotations

import base64
import io
import zipfile

import pytest
from sqlalchemy import select

from app.db.session import AsyncSessionLocal
from app.models.asset import Asset
from app.mcp.skill.tools import TOOLS
from tests._mcp_client import McpTestClient, make_principal
from tests.conftest import set_setting

API = "/api/v1/assets"


def _zip_bytes(files: dict[str, str], filename: str) -> tuple[str, bytes, str]:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        for name, content in files.items():
            z.writestr(name, content)
    return (filename, buf.getvalue(), "application/zip")


def _skill_pkg(code: str) -> tuple[str, bytes, str]:
    return _zip_bytes(
        {"SKILL.md": f"---\nname: {code}\ndescription: d\n---\n\n# {code}\n"},
        filename=f"{code}.zip",
    )


@pytest.fixture()
def notify_spy(monkeypatch):
    """捕获钉钉通知事件序列 —— REST 与 MCP 两条路径都记."""
    calls: list[str] = []

    async def fake_notify_asset(event, asset, **kwargs):
        calls.append(event)
        return True

    import app.core.market_notify as mn

    monkeypatch.setattr(mn, "notify_asset", fake_notify_asset)
    return calls


async def _state(code: str) -> dict:
    """DB 快照 —— 只取与流程有关的字段."""
    async with AsyncSessionLocal() as s:
        a = (await s.execute(select(Asset).where(Asset.code == code))).scalars().first()
        if a is None:
            return {"exists": False}
        return {
            "exists": True,
            "publish_status": a.publish_status,
            "pending_action": a.pending_action,
            "version": a.version,
            "summary": a.summary,
        }


def _norm_result(r: dict, code: str) -> dict:
    """返回值归一化 —— 去掉 code 差异."""
    out = {k: v for k, v in r.items() if k not in ("code", "git_path")}
    out["code"] = "<code>"
    return out


async def _upload(client, headers, code: str) -> dict:
    """上架一个技能（两条路径共用的前置）."""
    pkg = _skill_pkg(code)
    data = {
        "code": code, "kind": "skill", "name": f"资产-{code}", "version": "1.0.0",
        "summary": "摘要", "description": "说明", "use_when": "何时", "not_for": "何时不",
        "category": "misc", "icon": "🧩", "tags": "[]", "keywords": "[]",
        "featured": "false", "permissions": "{}", "install_steps": "[]", "bindings": "{}",
    }
    r = await client.post(f"{API}/upload", data=data,
                          files={"package": (pkg[0], pkg[1], pkg[2])}, headers=headers)
    assert r.status_code == 202, r.text
    return r.json()


async def _rest_update(client, headers, code: str) -> dict:
    pkg = _skill_pkg(code)
    data = {
        "code": code, "kind": "skill", "name": f"资产-{code}", "version": "1.1.0",
        "summary": "新摘要", "description": "说明", "use_when": "何时", "not_for": "何时不",
        "category": "misc", "icon": "🧩", "tags": "[]", "keywords": "[]",
        "featured": "false", "permissions": "{}", "install_steps": "[]", "bindings": "{}",
    }
    r = await client.put(f"{API}/{code}", data=data,
                         files={"package": (pkg[0], pkg[1], pkg[2])}, headers=headers)
    assert r.status_code == 202, r.text
    return r.json()


# ---------- 场景 1：上架新技能 ----------

@pytest.mark.asyncio
async def test_s1_upload_rest_and_mcp_identical(client, auth, ws, restore_git_config,  # noqa: ARG001
                                                publisher_user, notify_spy):
    """场景 1：上架新技能 —— DB 状态与通知序列一致."""
    await set_setting("marketplace.review.enabled", "true")
    await set_setting("marketplace.publisher_usernames", publisher_user["username"])
    ph = {"Authorization": f"Bearer {publisher_user['token']}"}

    rest = await _upload(client, ph, "ct-rest-1")
    rest_state = await _state("ct-rest-1")
    rest_notify = list(notify_spy)
    notify_spy.clear()

    principal = await make_principal(publisher_user)
    pkg = _skill_pkg("ct-mcp-1")
    mcp = await McpTestClient(TOOLS, principal).call_tool("skill_publish", {
        "code": "ct-mcp-1", "name": "资产-ct-mcp-1", "summary": "摘要", "version": "1.0.0",
        "description": "说明", "use_when": "何时", "not_for": "何时不",
        "category": "misc", "icon": "🧩", "tags": [], "keywords": [],
        "permissions": {}, "install_steps": [], "bindings": {},
        "package_base64": base64.b64encode(pkg[1]).decode(),
    })
    mcp_state = await _state("ct-mcp-1")
    mcp_notify = list(notify_spy)
    notify_spy.clear()

    assert rest_state == mcp_state
    assert rest_notify == mcp_notify == ["review"]
    assert rest_state["publish_status"] == "pending"
    assert rest_state["pending_action"] == "new"


# ---------- 场景 2：发新版本 ----------

@pytest.mark.asyncio
async def test_s2_update_rest_and_mcp_identical(client, auth, ws, restore_git_config,  # noqa: ARG001
                                                publisher_user, notify_spy):
    await set_setting("marketplace.review.enabled", "true")
    await set_setting("marketplace.publisher_usernames", publisher_user["username"])
    ph = {"Authorization": f"Bearer {publisher_user['token']}"}

    await _upload(client, ph, "ct-rest-2")
    rest = await _rest_update(client, ph, "ct-rest-2")
    rest_state = await _state("ct-rest-2")
    rest_notify = list(notify_spy)
    notify_spy.clear()

    await _upload(client, ph, "ct-mcp-2")
    notify_spy.clear()          # 上架的通知不计入 —— 只看「更新」这一步
    principal = await make_principal(publisher_user)
    pkg = _skill_pkg("ct-mcp-2")
    mcp = await McpTestClient(TOOLS, principal).call_tool("skill_update", {
        "code": "ct-mcp-2", "name": "资产-ct-mcp-2", "summary": "新摘要", "version": "1.1.0",
        "description": "说明", "use_when": "何时", "not_for": "何时不",
        "category": "misc", "icon": "🧩", "tags": [], "keywords": [],
        "permissions": {}, "install_steps": [], "bindings": {},
        "package_base64": base64.b64encode(pkg[1]).decode(),
    })
    mcp_state = await _state("ct-mcp-2")
    mcp_notify = list(notify_spy)
    notify_spy.clear()

    assert rest_state == mcp_state
    assert rest_notify == mcp_notify == ["review"]
    assert rest_state["pending_action"] == "update"
    assert rest_state["version"] == "1.1.0"


# ---------- 场景 3：只改信息 ----------

@pytest.mark.asyncio
async def test_s3_edit_meta_rest_and_mcp_identical(client, auth, ws, restore_git_config,  # noqa: ARG001
                                                    publisher_user, notify_spy):
    await set_setting("marketplace.review.enabled", "true")
    await set_setting("marketplace.publisher_usernames", publisher_user["username"])
    ph = {"Authorization": f"Bearer {publisher_user['token']}"}

    await _upload(client, ph, "ct-rest-3")
    r = await client.patch(f"{API}/ct-rest-3", json={"summary": "只改了简介"}, headers=ph)
    assert r.status_code == 202, r.text
    rest = r.json()
    rest_state = await _state("ct-rest-3")
    rest_notify = list(notify_spy)
    notify_spy.clear()

    await _upload(client, ph, "ct-mcp-3")
    notify_spy.clear()
    principal = await make_principal(publisher_user)
    mcp = await McpTestClient(TOOLS, principal).call_tool("skill_edit_meta", {
        "code": "ct-mcp-3", "summary": "只改了简介",
    })
    mcp_state = await _state("ct-mcp-3")
    mcp_notify = list(notify_spy)
    notify_spy.clear()

    assert rest_state == mcp_state
    assert rest_notify == mcp_notify == ["review"]
    assert rest_state["pending_action"] == "meta"


# ---------- 场景 4：重新提交审核 ----------

@pytest.mark.asyncio
async def test_s4_submit_review_rest_and_mcp_identical(client, auth, ws, restore_git_config,  # noqa: ARG001
                                                        publisher_user, notify_spy):
    await set_setting("marketplace.review.enabled", "true")
    await set_setting("marketplace.publisher_usernames", publisher_user["username"])
    ph = {"Authorization": f"Bearer {publisher_user['token']}"}

    await _upload(client, ph, "ct-rest-4")
    r = await client.post(f"{API}/ct-rest-4/submit", data={"comment": "再看看"}, headers=ph)
    assert r.status_code == 200, r.text
    rest = r.json()
    rest_state = await _state("ct-rest-4")
    rest_notify = list(notify_spy)
    notify_spy.clear()

    await _upload(client, ph, "ct-mcp-4")
    notify_spy.clear()
    principal = await make_principal(publisher_user)
    mcp = await McpTestClient(TOOLS, principal).call_tool("skill_submit_review", {
        "code": "ct-mcp-4", "comment": "再看看",
    })
    mcp_state = await _state("ct-mcp-4")
    mcp_notify = list(notify_spy)
    notify_spy.clear()

    assert rest_state == mcp_state
    assert rest_notify == mcp_notify


# ---------- 场景 5：申请下架 ----------

@pytest.mark.asyncio
async def test_s5_unpublish_rest_and_mcp_identical(client, auth, ws, restore_git_config,  # noqa: ARG001
                                                   publisher_user, notify_spy):
    await set_setting("marketplace.review.enabled", "true")
    await set_setting("marketplace.publisher_usernames", publisher_user["username"])
    ph = {"Authorization": f"Bearer {publisher_user['token']}"}

    await _upload(client, ph, "ct-rest-5")
    r = await client.post(f"{API}/ct-rest-5/unpublish",
                          data={"confirm_code": "ct-rest-5", "comment": "不维护了"}, headers=ph)
    assert r.status_code == 200, r.text
    rest = r.json()
    rest_state = await _state("ct-rest-5")
    rest_notify = list(notify_spy)
    notify_spy.clear()

    await _upload(client, ph, "ct-mcp-5")
    notify_spy.clear()
    principal = await make_principal(publisher_user)
    mcp = await McpTestClient(TOOLS, principal).call_tool("skill_unpublish_request", {
        "code": "ct-mcp-5", "reason": "不维护了",
    })
    mcp_state = await _state("ct-mcp-5")
    mcp_notify = list(notify_spy)
    notify_spy.clear()

    assert rest_state == mcp_state
    assert rest_notify == mcp_notify
    assert rest_state["publish_status"] == "unpublish_pending"


# ---------- 场景 6/7：人工审核（纯 REST —— 本轮没有 MCP 审核工具, D7） ----------

@pytest.mark.asyncio
async def test_s6_review_publish_notifies_market(client, auth, ws, restore_git_config,  # noqa: ARG001
                                                  publisher_user, notify_spy):
    """场景 6：审核通过 → 通知市场群."""
    await set_setting("marketplace.review.enabled", "true")
    await set_setting("marketplace.publisher_usernames", publisher_user["username"])
    ph = {"Authorization": f"Bearer {publisher_user['token']}"}

    await _upload(client, ph, "ct-review-6")
    notify_spy.clear()
    r = await client.post(f"{API}/ct-review-6/review",
                          data={"decision": "approve", "comment": "可以"}, headers=auth)
    assert r.status_code == 200, r.text
    st = await _state("ct-review-6")
    assert st["publish_status"] == "published"
    assert "publish" in notify_spy


@pytest.mark.asyncio
async def test_s7_review_meta_does_not_notify_market(client, auth, ws, restore_git_config,  # noqa: ARG001
                                                      publisher_user, notify_spy):
    """场景 7：只改信息的资产审核通过 → **市场群收不到通知**（包没变）."""
    await set_setting("marketplace.review.enabled", "true")
    await set_setting("marketplace.publisher_usernames", publisher_user["username"])
    ph = {"Authorization": f"Bearer {publisher_user['token']}"}

    await _upload(client, ph, "ct-review-7")
    await client.patch(f"{API}/ct-review-7", json={"summary": "只改简介"}, headers=ph)
    notify_spy.clear()
    r = await client.post(f"{API}/ct-review-7/review",
                          data={"decision": "approve", "comment": "可以"}, headers=auth)
    assert r.status_code == 200, r.text
    st = await _state("ct-review-7")
    assert st["publish_status"] == "published"
    assert "publish" not in notify_spy


# ---------- 场景 8：管理员确认下架（纯 REST） ----------

@pytest.mark.asyncio
async def test_s8_unpublish_review_deletes_asset(client, auth, ws, restore_git_config,  # noqa: ARG001
                                                 publisher_user, notify_spy):
    """场景 8：管理员确认下架 → 资产被彻底删除."""
    await set_setting("marketplace.review.enabled", "true")
    await set_setting("marketplace.publisher_usernames", publisher_user["username"])
    ph = {"Authorization": f"Bearer {publisher_user['token']}"}

    await _upload(client, ph, "ct-review-8")
    r = await client.post(f"{API}/ct-review-8/unpublish",
                          data={"confirm_code": "ct-review-8", "comment": ""}, headers=ph)
    assert r.status_code == 200, r.text
    r2 = await client.post(f"{API}/ct-review-8/unpublish-review",
                           data={"decision": "approve", "comment": "确认"}, headers=auth)
    assert r2.status_code == 200, r2.text
    st = await _state("ct-review-8")
    assert st["exists"] is False
```

- [ ] **Step 3: 跑测试确认通过（此时可能红）**

Run: `cd backend_gateway && pytest tests/test_mcp_contract.py -v`

如果红了，**先判断是测试写错还是实现不一致**：
- 实现不一致 → **修实现**（这正是这个测试存在的意义）
- 测试写错 → 修测试

- [ ] **Step 4: 提交**

```bash
git add backend_gateway/tests/test_mcp_contract.py backend_gateway/tests/_mcp_client.py
git commit -m "test(MCP): 契约测试 —— 同一场景 REST vs MCP 三项断言（DB/通知/返回值）"
```

---

### Task 20: 参数反射检查（防漏传字段）

**Files:**
- Create: `backend_gateway/tests/test_mcp_adapter_params.py`

**Interfaces:**
- Consumes: `app.mcp.skill.adapter` 与 `app.api.marketplace` 的函数签名
- Produces: 端点加必填字段而 adapter 没传 → **测试立刻红**

- [ ] **Step 1: 写测试**

创建 `backend_gateway/tests/test_mcp_adapter_params.py`：

```python
"""参数反射检查 —— adapter 必须覆盖端点的全部必填参数.

⚠️ 这不是「接口形状」检查，而是**一致性检查**：
   端点加了必填字段而 adapter 漏传 → agent 在生产上报 400 且毫无指导性。
   这条测试让它在 CI 就红。

⚠️ 已知豁免：`submit_for_review` / `list_projects` 的用户参数叫 `_user` ——
   adapter 里参数名必须**逐字一致**（下划线前缀），所以豁免列表为空。
"""

from __future__ import annotations

import inspect

import pytest

from app.api import marketplace
from app.mcp.skill import adapter

#: (adapter 函数, 端点函数) —— 每一对都要覆盖
PAIRS = [
    (adapter.upload_asset, marketplace.upload_asset),
    (adapter.update_asset, marketplace.update_asset),
    (adapter.update_asset_meta, marketplace.update_asset_meta),
    (adapter.submit_for_review, marketplace.submit_for_review),
    (adapter.unpublish_asset, marketplace.unpublish_asset),
    (adapter.search_assets, marketplace.list_assets),
    (adapter.get_asset, marketplace.get_asset),
    (adapter.get_asset_doc, marketplace.get_asset_doc),
    (adapter.get_asset_files, marketplace.get_asset_files),
    (adapter.download_package, marketplace.download_package),
    (adapter.list_categories, marketplace.list_categories),
    (adapter.list_projects, marketplace.list_projects),
    (adapter.get_job, marketplace.get_job),
]


@pytest.mark.parametrize("adapter_fn,route_fn", PAIRS, ids=[p[0].__name__ for p in PAIRS])
def test_adapter_covers_route_params(adapter_fn, route_fn):
    route_params = inspect.signature(route_fn).parameters
    required = {n for n, p in route_params.items()
                if p.default is inspect.Parameter.empty and n not in ("user", "_user")}
    adapter_params = set(inspect.signature(adapter_fn).parameters)
    missing = required - adapter_params
    assert not missing, f"{adapter_fn.__name__} 漏了端点 {route_fn.__name__} 的必填参数: {sorted(missing)}"


@pytest.mark.parametrize("adapter_fn,route_fn", PAIRS, ids=[p[0].__name__ for p in PAIRS])
def test_user_param_name_matches(adapter_fn, route_fn):
    """用户参数名必须逐字一致（`_user` 不是笔误）."""
    route_params = inspect.signature(route_fn).parameters
    adapter_params = inspect.signature(adapter_fn).parameters
    if "_user" in route_params:
        assert "_user" in adapter_params, f"{adapter_fn.__name__} 缺 _user 参数"
```

- [ ] **Step 2: 跑测试**

Run: `cd backend_gateway && pytest tests/test_mcp_adapter_params.py -v`
Expected: PASS（全部覆盖）。若红 → **补 adapter 参数**，不要改这条测试。

- [ ] **Step 3: 提交**

```bash
git add backend_gateway/tests/test_mcp_adapter_params.py
git commit -m "test(MCP): 参数反射检查 —— adapter 漏传端点必填参数即红"
```

---

# Stage S6 — 部署与分发

### Task 21: nginx + 部署配置 + 锁文件

**Files:**
- Modify: `frontend_web/nginx.conf`
- Modify: `deploy/native/units/nginx.conf.tpl`
- Modify: `deploy/docker-compose.yml`
- Modify: `backend_gateway/requirements.txt` / `requirements.lock`（Task 2 已加，确认锁文件里的版本与实际一致）

**Interfaces:**
- Consumes: 无
- Produces: 3 个 nginx location（`/mcp`、`/oauth/`、`/.well-known/oauth-`）+ `MCP_ISSUER_URL` / `MCP_ALLOWED_HOSTS` 环境变量

- [ ] **Step 1: 改 nginx（容器版）**

修改 `frontend_web/nginx.conf`，在既有的 `location /api/` **之后**加：

```nginx
# ===== MCP (Streamable HTTP + SSE) =====
location /mcp {
    proxy_pass http://backend:8000;
    proxy_http_version 1.1;
    proxy_set_header Host $host;            # ⚠️ $host 丢端口 → allowed_hosts 要含裸 host
    proxy_set_header X-Forwarded-Proto $scheme;
    proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
    proxy_set_header Connection '';
    client_max_body_size 200m;
    proxy_buffering off;                   # ⚠️ SSE 必须
    proxy_read_timeout 300s;               # ⚠️ SSE 长连接
}

# ===== OAuth 端点 (DCR / authorize / token / revoke) =====
location /oauth/ {
    proxy_pass http://backend:8000;
    proxy_http_version 1.1;
    proxy_set_header Host $host;
    proxy_set_header X-Forwarded-Proto $scheme;
    proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
}

# ===== OAuth 元数据 (RFC 8414 / 9728) —— 必须在站点根 =====
location ^~ /.well-known/oauth- {
    proxy_pass http://backend:8000;
    proxy_http_version 1.1;
    proxy_set_header Host $host;
    proxy_set_header X-Forwarded-Proto $scheme;
    proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
}
```

> ⚠️ 裸机模板 `deploy/native/units/nginx.conf.tpl` 的 upstream 名字可能不是 `backend:8000`
> （裸机通常是 `127.0.0.1:8000`）—— **照该文件既有的 upstream 写法改**。

- [ ] **Step 2: 加环境变量**

修改 `deploy/docker-compose.yml` 的 backend 服务，加：

```yaml
      environment:
        MCP_ISSUER_URL: ${MCP_ISSUER_URL:-http://platform.example.internal}
        MCP_ALLOWED_HOSTS: ${MCP_ALLOWED_HOSTS:-}
```

> ⚠️ `MCP_ISSUER_URL` 必须与 `marketplace.public_base_url` **一致**（设置项里的那个才是用户看到的地址）。
> 两者不一致 → OAuth 元数据里的 issuer 与市场卡片里的 url 会对不上。
> ⚠️ **改了 `MCP_ISSUER_URL` 要重启后端** —— issuer 在装配时固化（设计文档 §15）。

- [ ] **Step 3: 校验 nginx 语法**

Run: `docker run --rm -v "$PWD/frontend_web/nginx.conf:/etc/nginx/conf.d/default.conf:ro" nginx:alpine nginx -t`
（若本地没有 docker，改用宿主机 nginx 的 `nginx -t -c <临时配置>`；至少**人工核对大括号配对**。）

- [ ] **Step 4: 提交**

```bash
git add frontend_web/nginx.conf deploy/native/units/nginx.conf.tpl deploy/docker-compose.yml
git commit -m "deploy(MCP): nginx 3 处 location + MCP_ISSUER_URL / MCP_ALLOWED_HOSTS"
```

---

### Task 22: 设置页管理组（接入令牌 / allowed_hosts / OAuth 开关）

**Files:**
- Modify: `frontend_web/src/views/Settings/index.vue`

**Interfaces:**
- Consumes: `listTokens()` `createToken()` `revokeToken()`（`api/mcp.ts`，Task 8 已写）
- Produces: 设置页里的「🔌 MCP 接入」组（**adminOnly —— 设置页整个就是 adminOnly**）

- [ ] **Step 1: 加设置组**

修改 `frontend_web/src/views/Settings/index.vue`，按该文件既有的分组写法加一个「🔌 MCP 接入」组：

```vue
<template>
  <section class="tm-settings-group">
    <h3>🔌 MCP 接入</h3>
    <p class="tm-hint">
      普通用户在 Qoder 点「授权」就能接入 —— 这里只放 <b>CI / 脚本用的平台接入令牌</b>。
      令牌明文只显示一次。
    </p>

    <el-form inline>
      <el-form-item label="名称">
        <el-input v-model="tokenLabel" placeholder="如 CI 发布机器人" />
      </el-form-item>
      <el-form-item label="有效期（天，0 = 不过期）">
        <el-input-number v-model="tokenDays" :min="0" :max="3650" />
      </el-form-item>
      <el-form-item>
        <el-button type="primary" :loading="creating" @click="create">签发令牌</el-button>
      </el-form-item>
    </el-form>

    <el-alert v-if="newToken" type="success" show-icon class="mb">
      <template #title>令牌已签发（只显示这一次）</template>
      <pre class="tm-code">{{ newToken }}</pre>
    </el-alert>

    <el-table :data="tokens" v-loading="loadingTokens" size="small">
      <el-table-column prop="label" label="名称" />
      <el-table-column prop="prefix" label="前缀" width="140" />
      <el-table-column label="状态" width="90">
        <template #default="{ row }">
          <el-tag v-if="row.revoked_at" type="info" size="small">已吊销</el-tag>
          <el-tag v-else type="success" size="small">有效</el-tag>
        </template>
      </el-table-column>
      <el-table-column label="操作" width="90">
        <template #default="{ row }">
          <el-button v-if="!row.revoked_at" link type="danger" @click="revoke(row)">吊销</el-button>
        </template>
      </el-table-column>
    </el-table>
  </section>
</template>

<script setup lang="ts">
import { onMounted, ref } from 'vue';
import { ElMessage } from 'element-plus';
import { createToken, listTokens, revokeToken, type McpToken } from '@/api/mcp';

const tokens = ref<McpToken[]>([]);
const loadingTokens = ref(false);
const creating = ref(false);
const tokenLabel = ref('');
const tokenDays = ref(0);
const newToken = ref('');

async function load() {
    loadingTokens.value = true;
    try {
        tokens.value = await listTokens();
    } finally {
        loadingTokens.value = false;
    }
}

async function create() {
    creating.value = true;
    try {
        const r = await createToken(tokenLabel.value, ['market:read', 'market:write'], tokenDays.value);
        newToken.value = r.token;
        tokenLabel.value = '';
        await load();
    } finally {
        creating.value = false;
    }
}

async function revoke(row: McpToken) {
    await revokeToken(row.id);
    ElMessage.success('已吊销');
    await load();
}

onMounted(load);
</script>
```

- [ ] **Step 2: 校验**

Run: `cd frontend_web && npm run build`
Expected: 成功

- [ ] **Step 3: 提交**

```bash
git add frontend_web/src/views/Settings/index.vue
git commit -m "feat(MCP): 设置页管理组 —— 平台接入令牌的签发与吊销"
```

---

### Task 23: 端到端验收 + 文档

**Files:**
- Modify: `README.md`（或 `docs/README.md`，按仓库既有索引位置）
- Create: `docs/runbooks/mcp-ops.md`（运维手册：改地址/吊销/排查）

**Interfaces:**
- Consumes: 全部前置任务
- Produces: 验收记录 + 运维手册

- [ ] **Step 1: 跑全量测试**

Run: `cd backend_gateway && pytest -q`
Expected: 全绿（既有 40+ 测试文件 + 新增 ~15 个）

Run: `cd frontend_web && npm run build && npm run test:unit 2>/dev/null || npm test -- --run 2>/dev/null || true`
Expected: 前端既有单测全绿（若仓库没有前端单测命令就跳过）

- [ ] **Step 2: 起服务做端到端验收**

```bash
cd backend_gateway
uvicorn app.main:app --host 0.0.0.0 --port 8000 --workers 1
```

> ⚠️ **`--workers 1` 是硬要求** —— SSE 与内存态授权码都不支持多进程。

逐条核对设计文档 §12.1 的验收项（1–20），把结果记到验收记录里：

| # | 验收项 | 结果 |
|---|---|---|
| 1 | 市场里能看到「TestMate 平台能力」卡片（带「平台内置」徽标），复制出的配置 url 正确 | ☐ |
| 2 | Qoder 导入 → 401 → 弹「授权」→ 浏览器 → 登录 → 同意页 → 同意 → 自动回到 Qoder | ☐ |
| 3 | 同意页：viewer 只能勾 `market:read`，tester 可勾到 `market:write` | ☐ |
| 4 | `tools/list` 返回 14 个工具，名称与 §5 一致 | ☐ |
| 5 | 搜到技能 → 读 SKILL.md → 取到包 URL 与 sha256 | ☐ |
| 6 | 上架新技能 → job_id → `skill_job_status` succeeded → GitLab 有 commit → 审核台可见 | ☐ |
| 7 | 上架后 `pending`/`new` → 人工审核 → 出现在市场列表 | ☐ |
| 8 | 配额用尽 → `quota_exceeded`（**不是 429**） | ☐ |
| 8b | access token 里**没有 `exp`**；隔一天再调仍可用 | ☐ |
| 8c | 「我的授权」页撤销 → 该客户端下一个请求 401 → Qoder 重新弹授权 | ☐ |
| 9 | 内置资产 `DELETE` → 409；下架 → 409；改 `mcp_config` → 409；**改 summary → 允许** | ☐ |
| 10 | 内置资产 url 随 `public_base_url` 变（不用重启） | ☐ |
| 11 | 既有业务文件改动 < 40 行；既有测试全绿 | ☐ |
| 12 | 上架 → 待审核 + 通知管理员 → 审核通过 → 市场群收到通知；只改信息 → 审核通过 → **市场群收不到** | ☐ |
| 13 | 缺必填/有歧义/可选项未确认 → 拒绝执行 + 无副作用 + `needs_confirmation` | ☐ |
| 14 | 契约测试 8 场景全绿 | ☐ |
| 15 | 改 `market_rules.py` → 前端表单与 MCP 校验同时跟着变 | ☐ |
| 16 | 预留域骨架存在（`app/mcp/kb/`、`app/mcp/software/`） | ☐ |
| 17 | 内网 http 部署能起来；两个元数据端点 200 | ☐ |
| 18 | DCR 三条规则生效 | ☐ |
| 19 | SSE 首帧 endpoint == `/mcp/skill/messages/?session_id=…` | ☐ |
| 20 | 两级配额都返回 `quota_exceeded` | ☐ |

- [ ] **Step 3: 写运维手册**

创建 `docs/runbooks/mcp-ops.md`：

```markdown
# MCP 运维手册

## 常见操作

| 场景 | 怎么做 |
|---|---|
| 改平台对外地址 | 改 `marketplace.public_base_url` **并** 改 `MCP_ISSUER_URL`，然后**重启后端**（issuer 在装配时固化） |
| 某用户的 agent 行为异常 | 「我的授权」页找到对应客户端 → 撤销 → 该客户端下一个请求就 401 |
| CI 要用固定凭证 | 设置页 → 「🔌 MCP 接入」→ 签发平台接入令牌（默认不过期，可设期限） |
| 怀疑有人乱调用 | `SELECT * FROM mcp_tool_calls ORDER BY created_at DESC LIMIT 100` |
| 421 Misdirected Request | `MCP_ALLOWED_HOSTS` 没覆盖当前 Host —— 裸 host 与 `host:port` 都要写 |
| SSE 连不上 | 确认 nginx 有 `proxy_buffering off` 与 `proxy_read_timeout 300s`；确认后端 `--workers 1` |
| 授权页 404 | 同意页路由必须是 `/connect/authorize`，**不能**放在 `/mcp` 下（nginx 前缀匹配会劫持） |

## 部署约束

- 后端**必须单进程**（`BACKEND_WORKERS=1`）—— SSE 与内存态授权码不支持多进程
- `mcp==1.29.1`（升级前先跑 OAuth 集成测试：发现链路 / DCR 三规则 / PKCE）
```

- [ ] **Step 4: 更新 README 索引**

在 `README.md`（或 `docs/README.md`）的文档索引里加两行：

```markdown
- [TestMate MCP 设计](specs/2026-10-31-testmate-mcp-design.md) —— 让 agent 操作技能市场
- [MCP 实施计划](superpowers/plans/2026-10-31-testmate-mcp-implementation.md) —— S0~S6 的完整任务拆解
- [MCP 运维手册](runbooks/mcp-ops.md) —— 改地址 / 吊销 / 排查
```

- [ ] **Step 5: 提交**

```bash
git add README.md docs/README.md docs/runbooks/mcp-ops.md
git commit -m "docs(MCP): 端到端验收记录 + 运维手册 + 文档索引"
```

---

## 自查（写完计划后按 spec 逐条核对）

**1. 设计文档覆盖度**

| 设计文档章节 | 对应任务 |
|---|---|
| §3.3 装配与挂载（Route+Mount / root_path / lifespan） | Task 12 |
| §3.4 DNS rebinding 防护 | Task 12（`allowed_hosts()`）+ Task 21（`MCP_ALLOWED_HOSTS`） |
| §3.5 ToolSpec 契约 | Task 13 |
| §3.6 扩展点清单 | Task 12（`PROVIDERS` 骨架）、Task 13（`CompositeTokenVerifier`）、Task 18（`rules_payload`） |
| §4.2 数据模型 | Task 2 |
| §4.3 OAuth 端点（自写路由 / DCR 三规则 / 发现链路） | Task 3、Task 4、Task 6 |
| §4.4 可插拔鉴权层 | Task 5 |
| §4.5 同意页 | Task 7（后端）、Task 8（前端） |
| §4.6 scope | Task 3（`SUPPORTED_SCOPES`）、Task 8（同意页勾选） |
| §4.7 吊销模型 | Task 7（`revoke_grant`）、Task 9（页面） |
| §4.8 配额（两级） | Task 13 |
| §4.9 内置资产 | Task 10（后端）、Task 11（前端） |
| §4.10 交付链路 | Task 23（验收） |
| §4.11 平台接入令牌 | Task 7（API）、Task 22（页面） |
| §4.12 写操作契约 / 不猜协议 | Task 14（规则）、Task 15（adapter）、Task 16（工具） |
| §4.13 一致性三层防线 | Task 18（L1）、Task 19（L2）、Task 20（L3） |
| §5 工具清单（14 个） | Task 16、Task 17 |
| §5.4 错误码全集 | Task 13（`errors.py`） |
| §6 最小改动 | Task 10（3 处守卫）、Task 18（+1 只读端点） |
| §7 数据流 | Task 6（集成测试复现整条链路） |
| §8 审计 | Task 2（表）、Task 13（`audit.py`） |
| §9 数据库变更 | Task 2、Task 10 |
| §10 部署与分发 | Task 21（nginx/环境变量）、Task 22（设置页） |
| §11 测试策略 | Task 6、Task 12、Task 19、Task 20、Task 23 |
| §12 验收标准 | Task 23（验收表） |
| §13 风险 | Task 23（运维手册） |
| §15 未决事项 | Task 1（S0 结论）、Task 21（`MCP_ISSUER_URL` 与重启约束） |

**2. 占位符扫描**

- 无 "TBD" / "TODO" / "implement later"
- 无「写测试覆盖上面这些」这类空指令 —— 每个测试任务都给了可运行的测试代码
- 标了 ⚠️ 的地方都是**需要按实际代码核对**的点（既有函数签名、字段名、helper 签名），
  并明确写了「先读 X 再改」—— 不是留给实现者猜的空白

**3. 类型与命名一致性**

- `Principal` 字段：`user_id / username / role / client_id / client_name / scopes / grant_id` —— Task 5 定义，Task 13、Task 19 一致使用
- `McpContext`：`principal` + `domain` + `user()` —— Task 12 定义，Task 16、Task 19 一致
- `ToolSpec`：`name / description / input_schema / handler / scope / read_only / domain / annotations` —— Task 13 定义，Task 16、Task 17 一致
- adapter 函数签名：Task 15 定义，Task 16 调用，Task 20 反射检查 —— 三处一致
- `approve_pending` 返回值：Task 3 定义为 `str`，Task 7 改成 `tuple[str, int]` —— **已在 Task 7 Step 3 显式标注要同步改 Task 3 的测试**
- 工具名：Task 16 实现，Task 17 快照 —— 一致（14 个，9 读 5 写）

**4. 已知需要实现者注意的坑（计划里已标注）**

- `approve_pending` 返回值变更（Task 3 → Task 7）
- `ctx.user` 是**方法**不是属性（Task 16）
- `featured` 不在 `AssetMetaUpdateIn` 里 → `skill_edit_meta` 不提供该参数
- `McpContext.user()` 返回的是**新的** ORM 实例（每次现查）
- `Context.current_context()` 的取法要按实际 SDK 签名核对（Task 13 Step 6）
- 三个 `_user` 怪参数名不能「顺手改掉」
