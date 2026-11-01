# TestMate MCP 设计（技能市场先行 · v12）

> 2026-11-01 · 在现有 FastAPI 后端提供 `/mcp/skill`，让 agent 能发现、读取、下载、上架和更新技能/插件。
>
> v12 根据当前代码与 `mcp==1.29.1` 源码复核修订：
>
> 1. **取消平台内置连接器**：不新增 `is_builtin`，不 seed 资产，不增加删除/下架/更新守卫，不改市场卡片。需要分发时，按现有流程上架普通 `kind=mcp` 连接器即可。
> 2. **不重写市场业务**：MCP 写操作通过薄适配层调用既有路由函数；显式执行原路由的权限依赖，不复制审核、Git 同步或通知逻辑。
> 3. **OAuth 状态可撤销且不可复活**：DCR 客户端和 grant 持久化；access token 绑定 `grant_id + grant_version + token_version`。
> 4. **真实 14 工具**：补齐包内单文件读取与严格版本绑定的资产下载票；不自动猜版本、分类或可选项。
> 5. **协议级验收**：契约测试通过真实 MCP transport 调用，覆盖鉴权、scope、配额、审计和实际 `tools/list` schema。
> 6. **内网可部署**：自写 OAuth 路由，避免 SDK `create_auth_routes` 的 HTTPS issuer 限制；同时提供 Streamable HTTP 与 SSE。

状态：**已确认，按本版实施**。

---

## 1. 范围

### 1.1 本轮交付

- 技能/插件域 MCP server：`POST /mcp/skill`。
- SSE：`GET /mcp/skill/sse` 与 `POST /mcp/skill/messages/`。
- OAuth 2.1：DCR、PKCE S256、授权同意、长期可撤销 grant、撤销端点和「我的授权」页。
- admin 管理的静态平台接入令牌，用于 CI 和 OAuth 兜底。
- 9 个只读工具 + 5 个写工具。
- 规则单一出口、REST/MCP 写场景契约测试、部署代理与单 worker 约束。

### 1.2 非目标

- 不实现知识库、软件库工具，只保留域扩展位。
- 不提供 MCP 审核工具；审核仍在网页审核台由人工完成。
- 不提供硬删除工具；下架沿用现有状态机。
- 不做 stdio transport、refresh token 或个人令牌页。
- **不做任何内置/特殊资产**：现有资产模型、GitLab 真身、普通连接器生命周期均不变。
- 不重构 `marketplace.py` 的既有业务流程。

---

## 2. 已定决策

| # | 决策 | 结论 |
|---|---|---|
| D1 | 部署形态 | 挂入现有 FastAPI，复用 DB、RBAC、资产 job、审核和通知链路 |
| D2 | 域划分 | 每域独立 MCP server；本轮只注册 `skill` |
| D3 | 协议 | 官方 `mcp==1.29.1`，Streamable HTTP + SSE |
| D4 | 普通用户鉴权 | OAuth 2.1 + DCR + PKCE S256；同意页 `/connect/authorize` |
| D5 | CI 鉴权 | admin 签发的静态 Bearer token；与 OAuth 共用权限和审计 |
| D6 | token 生命周期 | access token 不带 `exp`；每次调用校验 grant 版本、撤销状态、用户状态和 token_version |
| D7 | 写操作 | 调既有 REST 路由函数；显式执行 `require_publisher`，保留作者/admin 检查 |
| D8 | 市场连接器 | 只使用普通资产；不 seed、不加字段、不加守卫、不做特殊 UI |
| D9 | 工具数量 | 14 个：9 读 + 5 写；无审核工具 |
| D10 | 不替用户做主 | 更新必须显式给新版本与包；省略字段表示不变；不自动升版本 |
| D11 | OAuth 路由 | 自写 `/oauth/*` 与 well-known 路由；不向 FastMCP 传 `auth_server_provider` |
| D12 | redirect URI | DCR 仅允许 `http://127.0.0.1:*`、`http://localhost:*`、`http://[::1]:*` |
| D13 | 一致性 | 规则单一真源 + 真实 MCP 契约测试 + 参数映射测试 |
| D14 | 授权管理 SPA | `/connect/authorize` 与 `/connect/grants`，不放在 `/mcp` 前缀下 |
| D15 | 部署 | 启用 MCP 时后端必须单进程；授权码是进程内、5 分钟、一次性状态 |

---

## 3. 架构与目录

```text
backend_gateway/app/
├── mcp/
│   ├── common/
│   │   ├── server.py          # FastMCP 工厂、域 dispatcher、lifespan 管理
│   │   ├── auth.py            # OAuth/静态 token -> AccessToken/Principal
│   │   ├── oauth.py           # DCR、授权码、grant、token 签发与撤销
│   │   ├── oauth_routes.py    # /oauth/* 与 /.well-known/*
│   │   ├── context.py         # Principal 与 McpContext
│   │   ├── tool.py            # ToolSpec、schema 注册、scope/配额/审计包装
│   │   ├── audit.py           # 安全参数摘要与审计落库
│   │   └── errors.py          # 业务异常 -> 安全 tool error
│   └── skill/
│       ├── server.py          # testmate-skill provider
│       ├── adapter.py         # 调 marketplace 既有路由函数
│       └── tools.py           # 14 个 ToolSpec
├── api/mcp.py                 # 同意、grant、静态 token REST
├── models/mcp.py              # OAuth client/grant、API token、tool call
└── main.py                    # 只负责挂载与 lifespan
```

依赖方向固定为 `transport -> protocol -> domain -> existing business`。工具不读取 HTTP header；适配层不直接拼 SQL 替代业务；审计只由工具包装层写入。

### 3.1 MCP 挂载

每个域同时注册：

```python
Route("/skill", endpoint=mcp.streamable_http_app())
Mount("/skill", app=mcp.sse_app())
```

然后把 dispatcher 挂到 `/mcp`。`Route` 保证 `POST /mcp/skill` 精确命中；`Mount` 保证 SSE 子路径命中。SSE 的 `root_path` 必须为 `/mcp/skill`，首帧 endpoint 应为 `/mcp/skill/messages/?session_id=...`。

FastMCP 使用 `stateless_http=True`、`json_response=True`、`token_verifier` 和 `AuthSettings`。DNS rebinding allowed_hosts 合并 `mcp.allowed_hosts`、`marketplace.public_base_url` 的 host 与回环地址；裸 host 和 `host:port` 都保留。

### 3.2 工具 schema 注册

`FastMCP.add_tool()` 会从 Python 函数签名生成 schema，不会自动采用 `ToolSpec.input_schema`。注册后必须把固定版本 SDK 对应 tool 的 `parameters` 设置为 `ToolSpec.input_schema`，并以真实 `tools/list` 测试锁定该行为。升级 SDK 时该测试是兼容性门禁。

---

## 4. OAuth 与权限

### 4.1 数据模型

- `mcp_oauth_clients`：`client_id` 主键，名称、redirect_uris、scopes、created_at。
- `mcp_oauth_grants`：自增 id、`user_id + client_id` 唯一、scopes、`version`、`revoked_at`、时间戳。
- `mcp_api_tokens`：名称、token_hash、user_id、scopes、expires_at、revoked_at、last_used_at。
- `mcp_tool_calls`：user/client/domain/tool/read_only/success/error/args_summary/duration/created_at。

所有模型从 `app.models` 导出；迁移从当前 head `0029_add_asset_pending_action` 之后新增 `0030_add_mcp_tables`。测试清表包含四张新表。

### 4.2 DCR 与授权码

`POST /oauth/register` 强制：

- `token_endpoint_auth_method="none"`；
- `grant_types=["authorization_code"]`、`response_types=["code"]`；
- scope 为 `market:read market:write` 的子集；
- redirect URI 只能是回环 HTTP 地址。

客户端元数据落 DB。授权码只存进程内，绑定 client、redirect URI、user、scope、code_challenge，5 分钟有效且兑换即删除。重启后用户重新同意即可。

### 4.3 同意流

1. `GET /oauth/authorize` 校验 client、redirect、scope、PKCE，然后 302 到 `/connect/authorize?...`。
2. 未登录用户由现有前端登录守卫带去登录，登录后回到原同意 URL。
3. 前端用登录态调用 `/api/v1/mcp/authorize/preview` 获取客户端和**实际可授权 scope**。
4. 提交 `/api/v1/mcp/authorize` 后，后端再次校验并返回 `{callback_url}`。
5. 前端执行 `window.location.assign(callback_url)`；不能依赖 Axios 跟随 302。

`market:read` 可授予活跃用户；`market:write` 仅在 `market_policy.can_publish` 当前允许时可授予。预览和提交必须由后端计算同一口径，前端不根据角色名称猜权限。

### 4.4 token 与撤销

OAuth access token 是无 `exp` 的 JWT，至少含：

```json
{
  "sub": "用户ID",
  "client_id": "DCR客户端",
  "grant_id": 1,
  "grant_version": 1,
  "token_version": 3,
  "scopes": ["market:read", "market:write"],
  "aud": "http://host/mcp",
  "typ": "mcp-oauth"
}
```

重新授权同一 `(user_id, client_id)` 时递增 `grant.version` 并清空 revoked_at。撤销设置 revoked_at；旧 token 因撤销或版本不匹配立即失效，重新授权不会让旧 token 复活。

每次调用都重新加载 User，检查 active、token_version，使用 DB 当前角色，并将 token scopes 与 grant scopes、当前可授权 scopes 求交。静态 token 同样校验 hash、撤销、期限、用户状态和 token_version。

OAuth 元数据：

- `/.well-known/oauth-authorization-server`
- `/.well-known/oauth-protected-resource/mcp/skill`
- `/oauth/register`、`/oauth/authorize`、`/oauth/token`、`/oauth/revoke`

issuer/resource 来自 `marketplace.public_base_url`；修改后重启后端生效。

---

## 5. 工具契约

### 5.1 只读工具（`market:read`）

| 工具 | 输入 | 输出与约束 |
|---|---|---|
| `skill_search` | keyword/category/project/tag/author/include_unpublished/page/page_size | 统一分页；默认只显示 published；未发布可见性沿用市场 |
| `skill_get` | code | manifest、安装/权限/bindings、can_review |
| `skill_read_doc` | code | SKILL.md 或 README.md 正文 |
| `skill_list_files` | code | 包内文件树 |
| `skill_read_file` | code/path | 从既有 bundle 中选一个文本文件；路径精确匹配、拒绝二进制与越界 |
| `skill_package_info` | code/version? | 实际包字节 size/sha256 + 600 秒 `asset-dl` URL；版本严格匹配，不回退到别的包 |
| `skill_categories` | 无 | 后端分类枚举 |
| `skill_projects` | 无 | 后端项目枚举 |
| `skill_job_status` | job_id | staged/syncing/pushed/failed 等真实 job 状态；只能看自己或 admin 可见任务 |

资产下载新增通用 `asset-dl` 票据，不复用 `sw-dl`。票据绑定用户、code、version、到期时间；下载时再次检查资产可见性。未发布资产不因持票而绕过可见性。

### 5.2 写工具（`market:write`）

| 工具 | 既有路由 | 约束 |
|---|---|---|
| `skill_publish` | `POST /assets/upload` | code/name/version/summary 与包必需；可选键出现即视为用户已确认该值 |
| `skill_update` | `PUT /assets/{code}` | 显式 version 且不同于当前版本；必须提供 files 或 package_base64；省略字段从当前资产保留 |
| `skill_edit_meta` | `PATCH /assets/{code}` | 至少一个可编辑字段；不改包、不改版本、不改 featured |
| `skill_submit_review` | `POST /assets/{code}/submit` | comment 可选；状态机由原路由负责 |
| `skill_unpublish_request` | `POST /assets/{code}/unpublish` | confirm_code 由适配层绑定 code；reason 映射 comment；审核开关行为保持原样 |

`package_base64` 解码后限制大小，文件名按 `{code}.zip` 还原；`files` 与 `package_base64` 二选一。所有写工具直接调用原路由函数前显式 `await require_publisher(user)`，由 `_assert_can_modify` 等既有逻辑继续做对象级授权。返回值、DB 状态和通知事件必须与 REST 同场景一致。

---

## 6. 规则、审计与错误

`app/core/market_rules.py` 从既有命名/分类/项目函数生成 `rules_payload()`。`GET /api/v1/assets/rules` 是唯一规则出口，MCP 直接 import，前端在已登录市场上下文中加载。加载失败时禁止提交并显示重试，不静默使用第二份硬编码规则。

每次工具调用由包装层记录审计。参数摘要不保存 `package_base64`、文件内容或文件文本，只保留普通标量、键名、集合长度、字节大小和 SHA256。异常映射为安全 tool error，不回传堆栈、SQL 或密钥。

配额采用 Redis 滑动分钟桶，同时限制 `user` 与 `user+client`；超出返回 tool error，审计仍落库。

---

## 7. 测试与验收

### 7.1 后端

- OAuth：DCR 回环限制、PKCE、授权码一次性、scope 收敛、撤销、重授权旧 token 失效、用户停用/token_version 变化。
- Transport：未认证 401；认证 initialize、`tools/list`、SSE 回传地址、实际 schema。
- 工具：14 个名称冻结；文件读取和资产下载票真实可用；写操作权限与不猜协议。
- 契约：publish/update/edit_meta/submit/unpublish 分别用 REST 与真实 MCP 跑，比较 DB 状态、通知序列和归一化返回值。人工 approve/reject 是 REST-only，不伪称 MCP 场景。
- 审计：base64 和文件内容不落库；配额与 scope 失败也有记录。

### 7.2 前端与部署

- 同意页提交通过顶层导航回 Qoder；grant 撤销立即可见。
- admin 静态令牌只在创建时显示一次。
- 规则加载失败禁止市场提交，重试成功恢复。
- 两份 nginx 配置代理 `/mcp`、`/oauth`、`/.well-known/oauth-*`，保留 Host 端口。
- `tmctl.sh` 在 MCP 启用且 worker 不为 1 时拒绝启动。

### 7.3 验证顺序

1. `testmate_test` 后端全量测试。
2. `vue-tsc --noEmit` 与 Vitest，全量不屏蔽失败。
3. `tmctl.sh local update/check/status`。
4. 在 `http://127.0.0.1:8081/` 做 OAuth 和只读工具验收。
5. 写场景只在测试库执行；真实环境使用通知预览，不向真实钉钉群发消息。

---

## 8. 扩展方式

新增知识库或软件库域时，只新增 `app/mcp/<域>/` 并在 provider 注册表登记；不改技能适配层。新增工具时同步增加协议 schema 测试，新增 REST/MCP 共有写能力时必须增加契约场景。新凭证类型只扩展 `common/auth.py`，不改变工具权限边界。
