# TestMate MCP 设计（技能市场先行）

> 2026-10-31 · 让 **agent 能操作 TestMate**：上架/下载/更新技能，读知识库，取软件包。
> 本轮只做**技能市场**一个域，知识库 / 软件库 / 插件 / 连接器按同一套扩展点后接。
>
> 状态：**设计已定，待实现**。配套实施计划见 `docs/superpowers/specs/` 下的计划文档。

---

## 一句话

在现有 FastAPI 后端里挂一个 `/mcp` 端点（MCP Streamable HTTP），用**长期 API Token** 鉴权，
把「技能市场」的读写能力暴露成 **14 个 MCP 工具**；业务逻辑抽到一层与传输无关的
**domain 服务层**，REST 与 MCP 共用同一份语义——为后续接知识库、软件库留好扩展位。

---

## 1. 背景与目标

### 1.1 现状

| 事实 | 位置 |
|---|---|
| 后端 FastAPI + SQLAlchemy(async) + MySQL + Redis，JWT + RBAC(admin/tester/viewer) | `backend_gateway/app/` |
| 「插件·技能·连接」市场：`kind ∈ {plugin, skill, mcp}`，真身在 GitLab，本地 git 工作区落盘，DB 是查询镜像 | `app/api/marketplace.py`(3005 行) |
| 技能包 = zip（含 `SKILL.md`），上传走 staged → 后台 git commit/push → job 队列（可重试） | `app/core/asset_jobs.py` / `app/core/git_sync.py` |
| 上架有审核流：`publish_status ∈ {pending, published, rejected, unpublished, unpublish_pending}`，`pending_action ∈ {new, update, meta}` | `app/models/asset.py` |
| 连接器（`kind=mcp`）是**配置型资产**，内容就是一段 `mcpServers` JSON | `app/core/mcp_config.py` |
| 知识库走 RAGFlow 代理；软件库是服务端磁盘 + 短时下载票 | `app/api/kb.py`(1512) / `app/api/software.py`(1721) |

**仓库里目前没有任何 MCP server 实现**，只有「连接器」这种被 MCP *配置* 的资产。

### 1.2 目标

1. agent 能**发现**技能：搜索、看详情、读 `SKILL.md`、看包文件树
2. agent 能**获取**技能：取到包（URL + sha256）与文本文件内容
3. agent 能**上架/更新**技能：走与网页完全一致的校验、命名契约、审核流
4. 架构上**可扩展**：后续接知识库 / 软件库 / 插件 / 连接器时，只新增「域模块」，不动 MCP 框架层

### 1.3 非目标（本轮不做）

- ❌ 不提供「硬删资产」工具（删除语义 = 下架审核通过，由平台既有流程承担）
- ❌ 不绕过审核流（agent 不能自行绕过 `marketplace.review.*` 设置）
- ❌ 不做知识库 / 软件库 / 插件 / 连接器的工具实现（只留扩展位与接口占位）
- ❌ 不做 stdio transport（首批只服务 Qoder，走远程 HTTP）
- ❌ 不做 MCP OAuth 动态注册（用静态 API Token，够用且好管）

---

## 2. 已定决策

| # | 决策点 | 结论 | 理由 |
|---|---|---|---|
| D1 | MCP server 跑在哪 | **挂进现有 FastAPI 后端**，新增 `/mcp` 端点（Streamable HTTP） | 一套部署；复用 DB 会话、权限判定、审计、资产 job 队列；改动面最小 |
| D2 | agent 身份 | **新增长期 API Token**（管理员签发/吊销，绑定某个用户身份） | agent 配置里只放一个 token；权限可精确到用户 + scope |
| D3 | 首批接入方 | **Qoder**（远程 HTTP，`{url, headers}` 连接器配置） | 团队主力 IDE；平台「连接器」资产格式天然匹配 |
| D4 | 业务逻辑分层 | **抽 domain 服务层**，REST 与 MCP 共用 | 避免三份适配；扩展成本从「复制一遍」降为「加一个模块」 |
| D5 | 协议实现 | **官方 `mcp` SDK**（FastMCP），`stateless_http=True` + `json_response=True` | 握手/版本协商/能力声明有 SDK 兜底；Qoder 兼容更有把握；依赖与现有锁文件无冲突 |
| D6 | 首期是否含审核工具 | **含**（`skill_review`），完全受平台既有审核人权限约束 | admin 令牌可完成「上架→审核→在架」闭环；权限判定复用 `require_reviewer` 同一套逻辑 |

---

## 3. 总体架构

### 3.1 分层

```
backend_gateway/app/
├── domain/                # ★ 业务域层 —— 与 HTTP / MCP 都无关
│   ├── base.py            #   ToolSpec / DomainProvider 协议
│   ├── errors.py          #   DomainError 家族
│   ├── market.py          #   技能市场域（本轮实现）
│   ├── kb.py              #   知识库域（占位：接口 + 空工具列表）
│   └── software.py        #   软件库域（占位）
├── mcp/                   # ★ MCP 框架层 —— 与业务无关
│   ├── server.py          #   FastMCP 实例、工具注册、ASGI 挂载
│   ├── auth.py            #   API Token → Principal 解析 + 中间件
│   ├── context.py         #   McpContext（身份 + 域调用入口）
│   └── errors.py          #   DomainError → MCP tool error 映射
├── api/
│   ├── marketplace.py     #   瘦身成 HTTP 适配层
│   ├── kb.py              #   后续瘦身（不在本轮范围）
│   └── software.py        #   后续瘦身（不在本轮范围）
└── main.py                #   lifespan 里跑 MCP session manager + 注册域
```

**依赖方向**：`api → domain ← mcp`

- `domain` 不 import `fastapi`（除 Pydantic schema 与 SQLAlchemy 模型），不认识 `Depends` / `Form` / `HTTPException`
- `mcp` 不 import `api`，只依赖 `domain.base` 的接口
- 传输层各管各的：REST 管 HTTP 状态码与 schema，MCP 管 JSON-RPC 与 tool schema

### 3.2 扩展点：域注册表

```python
# app/domain/base.py
@dataclass(frozen=True)
class ToolSpec:
    name: str                                   # 全局唯一，带域前缀
    description: str                            # 给 agent 看的说明
    input_schema: dict[str, Any]                # JSON Schema (draft-07)
    handler: Callable[["McpContext", dict[str, Any]], Awaitable[Any]]
    scope: str                                  # market:read / market:write / kb:read …
    read_only: bool                             # 只读标记（供客户端判断 + 审计分级）
    domain: str                                 # 所属域
    annotations: dict[str, Any] | None = None   # MCP ToolAnnotations（idempotentHint 等）


class DomainProvider(Protocol):
    name: str                                   # 域标识：market / kb / software
    def tools(self) -> list[ToolSpec]: ...
```

注册流程（`app/mcp/server.py`）：

```
启动 → 遍历 PROVIDERS → 逐个取 tools() → 校验 name 全局唯一 → 注册进 FastMCP
```

**加一个新域的完整步骤**（这是「今后扩展性」的可验证承诺）：

1. 写 `app/domain/<new>.py`，实现一个 provider，暴露 `tools()`
2. 在 provider 列表登记一行
3. `app/mcp/*` **零改动**

### 3.3 MCP server 装配

```python
# app/mcp/server.py（要点）
mcp = FastMCP(
    name="testmate",
    instructions="TestMate 平台能力：技能市场 / 知识库 / 软件库",
    stateless_http=True,        # 无状态：不需要 session id，nginx/多副本友好
    json_response=True,         # 响应是 application/json，不走 SSE 流
    streamable_http_path="/",   # 配合下面 mount，最终对外 URL 恰好是 /mcp
)
```

挂载（在 `app/main.py`）：

```python
@asynccontextmanager
async def lifespan(app: FastAPI):
    ...
    async with mcp.session_manager.run():   # ← 关键：子应用 lifespan 不会自动跑
        yield
    ...

app.mount("/mcp", mcp.streamable_http_app())
```

> ⚠️ **Starlette 不会把被 mount 的子应用的 lifespan 传给父应用**——不手动 `async with mcp.session_manager.run()`，
> 端点会 500。这是本设计里最容易踩的坑，实现时必须有对应测试兜住。

对外 URL：`POST {base}/mcp`（`streamable_http_path="/"` + `mount("/mcp")` → 路径不重复）。
SSE 兜底端点 `/mcp/sse` **本轮只预留不实现**（`app/mcp/server.py` 留好挂载位置与开关），Qoder 实测不兼容 Streamable HTTP 时再启用。

---

## 4. 鉴权：长期 API Token

### 4.1 表结构

```sql
CREATE TABLE mcp_api_tokens (
  id            BIGINT       NOT NULL AUTO_INCREMENT PRIMARY KEY,
  name          VARCHAR(128) NOT NULL,               -- 令牌名，如 "张三的 Qoder 笔记本"
  token_prefix  VARCHAR(32)  NOT NULL,               -- 明文前 12 位，UI 展示与人工定位用
  token_hash    CHAR(64)     NOT NULL,               -- sha256(明文) 十六进制，唯一索引
  user_id       BIGINT       NOT NULL,               -- 绑定身份：权限完全等同该用户
  scopes        JSON         NOT NULL,               -- ["market:read","market:write"]
  created_by    BIGINT       NULL,
  created_at    DATETIME     NOT NULL,
  last_used_at  DATETIME     NULL,
  expires_at    DATETIME     NULL,                   -- NULL = 不过期
  revoked_at    DATETIME     NULL                    -- 吊销即时生效
);
CREATE UNIQUE INDEX uk_mcp_tokens_hash ON mcp_api_tokens (token_hash);
CREATE INDEX ix_mcp_tokens_user ON mcp_api_tokens (user_id);
```

**只存 sha256，不存明文**：token 是 256-bit 随机串，不存在字典攻击风险，sha256 足够；慢哈希（bcrypt）在这里只会拖慢每个请求。
**明文只在签发那一刻返回一次**，之后任何接口都拿不到。

### 4.2 签发与吊销

- 设置页新增「MCP 接入令牌」组（admin 专属）：签发（填名称 + 绑定用户 + scopes + 有效期）、吊销、列表（显示 prefix / 绑定用户 / 最后使用时间 / 状态）
- 令牌明文格式：`tm_live_<32字节base64url>`
- 吊销 = 置 `revoked_at`，**即时生效**（每个请求现查库，无本地缓存 → 吊销后下一个请求必然 401）

### 4.3 校验链路

```
请求 → FastAPI 中间件(path startswith /mcp)
     → 取 Authorization: Bearer <token>
     → sha256 → 查 mcp_api_tokens（token_hash 唯一索引，单行查询，成本可忽略）
     → 校验: 存在 / 未吊销 / 未过期
     → 加载绑定 user（检查 user.is_active、角色）
     → principal = Principal(user, token, scopes)
     → scope["state"]["principal"] = principal
```

失败一律 **HTTP 401**（transport 级），不是 tool error——这才是 MCP 客户端期待的认证失败形态，
客户端会据此弹「请重新授权」，而不是把 401 当成工具执行结果。

### 4.4 权限模型（两层 AND）

| 层 | 规则 |
|---|---|
| 用户层 | 沿用平台现有口径：`role` + 发布者白名单（`market_policy.can_publish`）+ 资产归属（`can_modify`）+ 审核人名单 |
| 令牌层 | `scopes` 必须包含该工具的 `scope`；`read_only` 工具额外要求 scope 带 `:read` |

**令牌权限永远不超过绑定用户**：绑定 viewer 就干不了发布者的事；admin 也可以签发只读令牌给 agent 防误删。

### 4.5 安全红线

- token 不进 URL、不进 query、不进 access log（只走 Authorization 头）
- 明文一次性展示，UI 不缓存明文
- 吊销即时生效
- 每次 tool 调用落审计（见 §7），含 token_id，可追责到人

---

## 5. 工具清单（v1 = 技能市场）

命名规范：`<域>_<动作>`，全小写蛇形，全局唯一。域内能力对应 `kind=skill`；
插件 / 连接器后续可用同一批 domain 函数挂 `plugin_*` / `connector_*` 前缀。

### 5.1 读工具（scope: `market:read`，`read_only=true`）

| 工具 | 入参 | 出参 | 说明 |
|---|---|---|---|
| `skill_search` | `keyword?` `category?` `project?` `tag?` `author?` `include_unpublished?` `page?` `page_size?` | `{items:[{code,name,version,summary,category,project,author,publish_status,download_count}], total, page, page_size}` | 搜索技能。默认只返回 `published`；`include_unpublished=true` **仅对作者本人/管理员/审核人生效**，其他调用者的该参数被忽略（不可通过它探测未上架资产）。分页默认 `page=1, page_size=20`，`page_size` 上限 100 |
| `skill_get` | `code` | manifest 全字段 + `install_steps` / `permissions` / `bindings` / `git_web_url` / `can_review` | 技能详情。对调用者不可见的资产（未上架且非作者/非审核人）返回 `not_found`，不泄露存在性 |
| `skill_read_doc` | `code` | `{file, content}` | 读 `SKILL.md`（技能展示文档） |
| `skill_read_file` | `code` `path` | `{path, content, size}` | 读包内文本文件；后缀白名单同 `market_catalog.ALLOWED_SUFFIXES`；路径越界拒绝 |
| `skill_list_files` | `code` | `{files:[{path, size}]}` | 包内文件树 |
| `skill_package_info` | `code` `version?` | `{version, size_bytes, sha256, download_url, expires_at}` | 下载链接 + 校验值。`download_url` 带**短时票据**（新增票据类型 `asset-dl`，绑定 `code`+`version`，TTL 600s，与软件库 `sw-dl` 同机制），票据免登录即可换取包字节；未上架资产不出票据 |
| `skill_categories` | — | `[{name, slug, order, desc}]` | 合法分类枚举 |
| `skill_projects` | — | `[str]` | 合法项目枚举 |
| `skill_job_status` | `job_id` | `{id, action, status, error, commit_sha, created_at, updated_at}` | 上架/更新任务状态（git push 结果） |

### 5.2 写工具（scope: `market:write`，`read_only=false`）

| 工具 | 入参 | 出参 | 说明 |
|---|---|---|---|
| `skill_publish` | `code` `name` `version` `summary` `description?` `use_when?` `not_for?` `category?` `project?` `icon?` `tags?` `keywords?` `permissions?` `install_steps?` `bindings?` `files?` `package_base64?` | `{job_id, status, code}` | 上架新技能。`files`（路径→文本内容映射）与 `package_base64`（zip 的 base64）二选一，都不给则报 `invalid_argument`。base64 包的文件名按 `{code}.zip` 还原（平台命名契约要求包名与 `code` 一致，`market_naming.check_package_consistency` 会校验） |
| `skill_update` | `code` + 上述任意字段（**均可省略**）+ `files?` / `package_base64?` | `{job_id, status, code}` | 发新版本。**字段省略 = 保持现状**（读当前 DB 资产值合并，read-modify-write）；`version` 省略时自动 patch 当前版本末位（`x.y.z → x.y.(z+1)`），给了则必须与当前版本不同。给了 `files`/`package_base64` = **整体替换**包内容（不是增量合并），未给 = 包内容不变 |
| `skill_submit_review` | `code` | `{code, publish_status, pending_action}` | 提交审核 |
| `skill_review` | `code` `approve: bool` `note?` | `{code, publish_status, pending_action}` | 审核通过 / 驳回。需审核人身份，否则 403 |
| `skill_unpublish_request` | `code` `reason?` | `{code, publish_status}` | 申请下架 |

### 5.3 三个刻意的取舍

1. **不提供硬删工具**：平台的删除语义是「下架审核通过 → 彻底删除资产」，属于人工运营动作。
   agent 要下架只能走 `skill_unpublish_request`，需管理员确认。
2. **不绕过审核**：`skill_publish` 内部调用与网页**同一个** `_review_required` 判断逻辑，
   非 admin 令牌上架后落在 `pending`，需要审核；admin 令牌在 `admin_self_approve=true` 时直接上架。
3. **zip 字节不进 tool 返回**：包体可能有 MB 级，塞进 JSON-RPC 响应会撑爆上下文。
   `skill_package_info` 给 URL + sha256，agent 自取；文本内容走 `skill_read_file`。

### 5.4 结果形态

```jsonc
// 成功
{"ok": true, "data": { ... }}
// 失败 → MCP tool error (isError=true)
{"error": {"code": "not_found", "message": "技能 xxx 不存在", "hint": "先用 skill_search 查一下 code"}}
```

---

## 6. 业务逻辑分层改造（domain 抽取）

这是本轮**最大的工作量与最大风险**，单列一节。

### 6.1 目标形态

`app/api/marketplace.py`（3005 行）拆成：

```
app/domain/market.py      业务能力：列表 / 详情 / 文档 / 文件 / 包 / 上架 / 更新 / 审核 / 下架
app/domain/errors.py      DomainError 家族
app/api/marketplace.py    HTTP 适配层：解析 Form/File → 调 domain → 返 Pydantic schema
```

### 6.2 改造原则

- **先搬不改**：逐个函数平移到 domain 层，函数体逻辑一字不改，只把 `Depends` 依赖改成显式入参
- **每搬一个就跑测试**：现有 `tests/test_market_api.py` / `test_market_edge.py` / `test_unpublish_flow.py` /
  `test_permissions.py` / `test_publisher_whitelist.py` / `test_market_meta_edit.py` 全绿再继续
- **路由层保持薄**：路由函数只做「取参 → 调 domain → 抛 HTTPException 或返 schema」
- **审计写在 domain 层**：`_audit(...)` 调用随业务逻辑一起搬过去 → REST 与 MCP 自动共享审计行为

### 6.3 搬不动的部分

与 MCP 无关、本轮**不搬**的部分：jobs 查询、notifications、sync-status、probe、config、
categories、projects 的路由实现（这些留在 api 层，或 domain 暴露纯函数、路由做包装）。
目标不是「一次拆干净」，而是**给 MCP 抽出它需要的那些能力**，同时留下清晰的分层接缝。

### 6.4 错误模型

```python
# app/domain/errors.py
class DomainError(Exception):
    code = "domain_error"
    http_status = 500
class NotFound(DomainError):        code, http_status = "not_found", 404
class PermissionDenied(DomainError):code, http_status = "permission_denied", 403
class Conflict(DomainError):        code, http_status = "conflict", 409
class InvalidArgument(DomainError): code, http_status = "invalid_argument", 422
class UpstreamFailed(DomainError):  code, http_status = "upstream_failed", 502
```

两种出口，同一套异常：

| DomainError | REST 出口 | MCP 出口 |
|---|---|---|
| NotFound | HTTP 404 + `detail` | tool error `code=not_found` |
| PermissionDenied | HTTP 403 | tool error `code=permission_denied` |
| Conflict | HTTP 409 | tool error `code=conflict` |
| InvalidArgument | HTTP 422 | tool error `code=invalid_argument` |
| UpstreamFailed | HTTP 502 | tool error `code=upstream_failed`（附「查 skill_job_status」） |

`app/api/marketplace.py` 加一个异常处理器把 `DomainError` 转 `HTTPException`；
`app/mcp/errors.py` 把 `DomainError` 转 MCP `ToolError`。

---

## 7. 审计

| 落点 | 记什么 | 用途 |
|---|---|---|
| `asset_audits`（既有） | 上架/更新/审核/下架等业务动作，`actor` = 绑定用户，`detail` 增 `transport=mcp` + `token_id` | 谁动了哪个资产 |
| `mcp_tool_calls`（新增） | `token_id` / `user_id` / `tool` / 入参摘要 / `ok` / `error_code` / `duration_ms` / `created_at` | 排查 agent 行为、配额、异常调用 |

```sql
CREATE TABLE mcp_tool_calls (
  id          BIGINT      NOT NULL AUTO_INCREMENT PRIMARY KEY,
  token_id    BIGINT      NOT NULL,
  user_id     BIGINT      NOT NULL,
  tool        VARCHAR(64) NOT NULL,
  domain      VARCHAR(32) NOT NULL,
  args_summary TEXT       NOT NULL,     -- 截断到 2KB，不落全文
  ok          TINYINT     NOT NULL,
  error_code  VARCHAR(32) NOT NULL DEFAULT '',
  duration_ms INT         NOT NULL DEFAULT 0,
  created_at  DATETIME    NOT NULL
);
CREATE INDEX ix_mcp_calls_token ON mcp_tool_calls (token_id, created_at);
```

---

## 8. 数据流

```
Qoder
 │  POST /mcp   Authorization: Bearer tm_live_xxx
 ▼
FastAPI 中间件 ── 验签/有效期/吊销 ──▶ scope["state"]["principal"]
 ▼
FastMCP (JSON-RPC: initialize → tools/list → tools/call)
 ▼
tool handler（app/mcp/server.py 注册的闭包）
 │  取 principal → 校验 scope → 组装 McpContext
 ▼
domain 层（app/domain/market.py）
 │  复用既有 market_policy / market_state / market_catalog / git_sync / asset_jobs
 ▼
Asset 模型 + git 工作区 + GitLab（真身）
 ▼
返回 → domain 结果 → MCP tool result（JSON）
```

失败路径：domain 抛 `DomainError` → `app/mcp/errors.py` 转 tool error（isError=true）→ 记 `mcp_tool_calls`。

---

## 9. 数据库变更

| 迁移 | 内容 |
|---|---|
| `0030_add_mcp_api_tokens.py` | `mcp_api_tokens` 表 + 索引 |
| `0031_add_mcp_tool_calls.py` | `mcp_tool_calls` 表 + 索引 |

ORM 模型放 `app/models/mcp.py`（新文件），随 `app/models/__init__.py` 导出。

---

## 10. 部署与分发

### 10.1 依赖

`requirements.txt` 增 `mcp>=1.29,<2`（**API 已核实于 1.29.1**：`stateless_http` / `json_response` /
`streamable_http_path` / `ctx.request_context.request` 均存在；2.x 有 breaking change，本轮不碰），
`requirements.lock` 锁到 `mcp==1.29.1` 并补全传递依赖：新增 `httpx-sse`、`sse-starlette`、
`jsonschema`(+`referencing`/`rpds-py`)、`pyjwt[crypto]`。
其余依赖已满足：`starlette 1.8.0 ≥ 0.27`、`pydantic 2.14.1 ≥ 2.11`、`uvicorn 0.54 ≥ 0.31.1`、
`httpx 0.28.1 ≥ 0.27.1`、`anyio 4.15.1 ≥ 4.5`、`pydantic-settings 2.16.0 ≥ 2.5.2`。

> 离线部署：backend 镜像在**有网机器**上构建（`deploy/offline-save.sh` 现有流程），
> 新依赖走正常 pip 解析即可，无需额外的离线包机制。

### 10.2 nginx

```nginx
location /mcp {
    proxy_pass http://backend:8000;
    proxy_http_version 1.1;
    proxy_set_header Host $host;
    proxy_set_header X-Forwarded-Proto $scheme;
    proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
    client_max_body_size 200m;
    proxy_buffering off;
    proxy_read_timeout 300s;
}
```
`frontend_web/nginx.conf` 与 `deploy/native/units/nginx.conf.tpl`（裸机模板）**两处都要加**。

### 10.3 裸机模式

同进程，无需额外服务；`tmctl.sh` 的 Python 依赖安装走 `requirements.lock`，自动覆盖。

### 10.4 自举：TestMate 自己作为一个连接器上架

平台「连接器」资产的内容就是 `mcpServers` JSON，已由 `app/core/mcp_config.py` 校验。
把 TestMate MCP 发布成一个连接器资产：

```json
{
  "mcpServers": {
    "testmate": {
      "url": "http://<平台地址>/mcp",
      "headers": {"Authorization": "Bearer tm_live_<用户自行签发的令牌>"}
    }
  }
}
```

- Qoder 可从平台市场直接装这个连接器
- **明文令牌不进公共市场资产**：市场里只放 url 与占位符，令牌由每个用户自己在设置页签发并填进本地连接器配置
- 该连接器资产本身走平台的审核流上架（自举也守规矩）

### 10.5 前端设置页

设置页新增「MCP 接入令牌」组（仅 admin 可见）：令牌列表 / 签发 / 吊销 / 复制明文。
另在「插件·技能·连接」页面加一个入口，说明「agent 可通过 TestMate MCP 操作技能市场」。

---

## 11. 测试策略

### 11.1 单测

| 目标 | 用例要点 |
|---|---|
| domain 层 | 每个操作的正常路径 + 权限拒绝 + 状态机非法迁移 + 参数校验 |
| 令牌 | 签发格式 / 校验通过 / 吊销后失败 / 过期失败 / 绑定用户被停用后失败 / scope 不足被拒 |
| 错误映射 | 每个 `DomainError` → REST 状态码、MCP error code 的映射正确 |
| schema | 每个工具的 `input_schema` 是合法 JSON Schema，且 name 全局唯一 |
| 作用域 | 只读令牌调写工具 → `permission_denied` |

### 11.2 集成测试

用 `httpx.ASGITransport` 走完整 MCP 握手：
`initialize` → `tools/list` → `tools/call`；
断言：无 token → 401；坏 token → 401；好 token → 能列出全部工具、能读到 `SKILL.md`。
另测 **挂载路径正确**（`/mcp` 而非 `/mcp/mcp`）与 **session manager 生命周期**（lifespan 里已启动）。

### 11.3 回归

现有 40+ 测试文件全绿（`marketplace.py` 瘦身是主要风险面）。

---

## 12. 验收标准

### 12.0 实施分期（供实施计划拆解用）

| 阶段 | 内容 | 可独立验收 |
|---|---|---|
| S1 | 令牌体系（表 + 模型 + 签发/校验/吊销 API + 设置页） | 能签发、能验、能吊销 |
| S2 | domain 抽取（`app/domain/market.py` + 路由瘦身），**行为零变化** | 现有 40+ 测试全绿 |
| S3 | MCP 框架层（FastMCP 装配 + 中间件 + 错误映射 + 工具注册机制） | 能握手、能 `tools/list`（空工具集也算通过） |
| S4 | 技能市场 14 个工具实现 | §12.1 全部通过 |
| S5 | 部署与分发（nginx / 锁文件 / 自举连接器 / 设置页入口） | Qoder 实连成功 |

S2 是 S4 的前置（工具要调 domain）；S1 是 S3 的前置（中间件要认 token）。S2 与 S3 之间无耦合，可并行。

### 12.1 验收项

1. 管理员在设置页签发令牌 → 拿到 `tm_live_...` 明文（只此一次）
2. Qoder 里配置连接器 `{url: http://<host>/mcp, headers: {Authorization: "Bearer tm_live_..."}}` → 能连上
3. `tools/list` 返回 14 个工具，名称与 §5 一致
4. agent 能：搜到技能 → 读 `SKILL.md` → 取到包 URL 与 sha256 → 下载后 sha256 与 `skill_package_info` 一致
5. agent 能上架新技能 → 返回 job_id → `skill_job_status` 显示 succeeded → GitLab 出现对应 commit → 审核台可见
6. 审核人在 agent 侧（或网页）审核通过后，技能出现在市场列表
7. 吊销令牌 → 下一个请求立刻 401
8. `git log` 能看到 domain 抽取是**独立提交**，可单独回滚
9. 后续接知识库域 = 新增 `app/domain/kb.py` 一个 provider 模块 + 登记一行，`app/mcp/*` 零改动

---

## 13. 风险与对策

| 风险 | 影响 | 对策 |
|---|---|---|
| 瘦身 `marketplace.py` 引入回归 | 高 | 先搬不改 + 逐步跑既有测试 + 独立提交可回滚；领域层不动 HTTP 层契约 |
| Qoder 客户端对 `stateless_http`/`json_response` 兼容性未知 | 中 | 保留 SSE 挂载 `/mcp/sse` 兜底；实现阶段先做联调 spike 验证握手 |
| 新增 pip 依赖影响离线部署 | 低 | 镜像在有网机器构建；锁文件补全；仅 4 个新传递依赖 |
| agent 误上架 / 误删 | 中 | 无硬删工具；审核流不变；scopes 可只读；每次调用留审计 |
| token 泄漏 | 中 | 明文一次性展示；只存 sha256；吊销即时生效；不进 URL / 不进 access log |
| domain 层抽象过早 / 抽象不足 | 中 | 本轮只抽 MCP 需要的操作；kb / software 域接入时再调整 seam，不做大爆炸重构 |

---

## 14. 后续路线

| 阶段 | 内容 | 增量成本 |
|---|---|---|
| **P0（本轮）** | 令牌体系 + MCP 框架层 + 技能市场 14 工具 + domain 抽取 | — |
| P1 | 知识库域：`kb_search` / `kb_list_datasets` / `kb_read_document` / `kb_ingest` | 1 个 provider 模块 |
| P2 | 软件库域：`software_search` / `software_download` / `software_upload` | 1 个 provider 模块 |
| P3 | 插件 / 连接器域：`plugin_*` / `connector_*`（复用 market domain 函数，改 kind 即可） | 少量 tool spec |
| P4 | stdio transport 薄壳（本地 CLI agent 用） | 1 个薄壳进程 |
| P5 | MCP Resources / Prompts（把 `SKILL.md` 暴露成 Resource） | SDK 原生支持 |

---

## 15. 未决事项（已按默认取值处理）

| 事项 | 本轮取值 | 何时需要回看 |
|---|---|---|
| 首期是否含审核工具 | **含**（D6），但严格受平台审核人权限约束 | 用户若只想让 agent 提交待审，删掉 `skill_review` 一个 tool spec 即可 |
| 令牌有效期 | 默认**不过期**（`expires_at=NULL`），可签发时指定 | 内部网场景可接受；对外暴露时收紧 |
| SSE 兜底端点 | 先实现 Streamable HTTP，**预留** `/mcp/sse` | Qoder 实测不兼容时启用 |
| 每 token 调用配额 | 本轮**不限**，只审计 | 观察一段时间后按 `mcp_tool_calls` 加限流 |
