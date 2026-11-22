# PingCode 集成（凭据配置 + 内置 MCP）设计

> 状态：已实现（工具数量后续扩展，现以 `/mcp/pingcode` 的 `tools/list` 为准）
> 日期：2026-11-12
> 参考实现：`/Users/jarvs/AiTestX`（浏览器扩展桥接版 MCP）
> 目标读者：实现者、评审者、运维

## 1. 背景与目标

TestMate 要把 PingCode（内网 `http://10.20.24.30/`）的日常查询/提单能力内置到平台：

1. 用户在**个人中心**录入自己的 PingCode 账号密码；密码前后端全程加密，落库加密。
2. 后端用账号密码完成登录，拿到 JWT 与会话 cookie；缓存登录态。
3. 登录态过期时自动续期/重登，保证 MCP 长期稳定可用。
4. 把 AiTestX 已实现的 PingCode MCP 工具迁入 TestMate 内置 MCP（新域 `/mcp/pingcode`）。
5. 为 PLM（`https://plm.twsc.com.cn/`）复用同一套凭据/集成框架；PLM 服务端登录与 MCP 已在
   [2026-11-14-plm-integration-design.md](2026-11-14-plm-integration-design.md) 实现。

## 2. 已核实事实（实现依据）

以下均已在真实内网环境用真实账号实测通过：

| 项 | 值 |
|---|---|
| 登录页 | `http://10.20.24.30/signin`（`/login` 会跳走，不是登录路由） |
| 登录接口 | `POST /api/typhon/team/signin` |
| 登录请求体 | `{"signin_name": "<手机号/邮箱/用户名>", "password": "<md5(明文) 小写十六进制>", "captcha_code": "", "captcha_id": ""}` |
| 登录响应 | `{"code":200,"data":{"value":{"user":{"uid","name"},"team":{"_id","name","domain"},"access_token":"<JWT>"}}}` |
| 会话 cookie | `s-<team_id>`（约 2 小时，可续期）、`wt_aid`（约 30 天） |
| JWT 结构 | `{uid, team_id, iat}`，**无 `exp` 字段**；有效性随会话 |
| 业务请求头 | `Authorization: Bearer <JWT>` + `X-Team-Id: 66209672995cb95d777b6aec` |
| 换新 JWT | `GET /api/typhon/account/access-token`（凭 cookie，返回 `data.value`） |
| 续期会话 | `POST /api/typhon/passport/prolong-logged-state`（凭 cookie，200 即续期） |
| 错误形态 | 业务错误常返回 **HTTP 200 + `{"code":401,...}`**，必须按 JSON `code` 判定 |
| 重复登录 | 连续 signin 均成功，当前无验证码、无限流 |
| 团队 | `66209672995cb95d777b6aec`（企业级产品中心） |
| 验收提单项目 | `TIANFU V100R001`：`project_id=663ede052100d4724722f6a6`，`identifier=TF2` |
| 验收提单类型 | 「缺陷」`work_item_type_id=662096879f86b6cac7599096` |

已验证可用的读取接口：`/api/typhon/account/me`、`/api/typhon/team`（成员）、`/api/agile/projects/select-options`、`/api/agile/work-items`、`/api/agile/work-items/{id}`、`/api/agile/work-items/{id}/comments`、`/api/testhub/test-libraries`。

PLM 现状：YonBIP/CAS 体系，服务端登录与 14 个 MCP 工具已按
[2026-11-14-plm-integration-design.md](2026-11-14-plm-integration-design.md) 落地。

## 3. 范围与非目标

### 本期范围
- `integration_credentials` 表与 migration 0036
- 传输加密 RSA + 落库加密 AES-256-GCM
- PingCode 服务端登录、token/cookie 缓存、主动续期与 401 自动重登
- 个人中心「外部系统」页签与 PingCode 凭据卡
- REST API：凭据 CRUD、测试连接、公钥下发
- 内置 MCP 域 `/mcp/pingcode` + 14 个工具 + `pingcode:read/write` scope
- PLM：同表、同 API、同 UI 框架；服务端登录与 MCP 工具见 PLM 设计文档

### 非目标
- PLM 的密码登录与工具（二期）
- PingCode 开放平台 OAuth / 企业密钥模式（后续可选增强）
- 测试用例库（testhub）相关工具（AiTestX 有 3 个，本期不迁）
- 管理员查看他人凭据（任何角色都看不到他人的密码/密文）

## 4. 架构

```
前端 个人中心 / 外部系统
  │ ①GET 公钥 ②RSA 加密账号+密码 ③PUT 凭据 / POST 测试
  ▼
REST /api/v1/integrations/*  ── AES-GCM 落库 ──▶ integration_credentials
  │
  ▼
IntegrationRegistry(provider)
  ├─ PingCodeProvider ── PingCodeClient ──▶ http://10.20.24.30
  │     TokenManager：缓存 / 单飞 / 401 重登
  └─ PlmProvider（占位，抛 NotImplementedError）

MCP /mcp/pingcode
  └─ ToolSpec(principal.user) → PingCodeProvider.for_user(user) → 工具适配器
```

新增后端包 `backend_gateway/app/integrations/`：

| 文件 | 职责 |
|---|---|
| `base.py` | `IntegrationProvider` 协议、`ProviderStatus`、注册表 |
| `crypto.py` | RSA 私钥解密、AES-256-GCM 加解密、密钥解析 |
| `credentials.py` | 凭据行读取/写入/删除、状态更新 |
| `token_manager.py` | 单飞登录、缓存判定、刷新、失败冷却 |
| `api.py` | `/api/v1/integrations` 路由 |
| `pingcode/client.py` | PingCode HTTP 客户端（登录、请求、分页、错误归一） |
| `pingcode/adapter.py` | 14 个工具的业务实现（从 AiTestX 移植） |
| `pingcode/templates.py` | 标准 10 段提单描述模板 |
| `pingcode/tools.py` | `ToolSpec` 列表 |
| `pingcode/server.py` | `build_pingcode_server()` |
| `plm/client.py` | `PlmProvider` 占位 |

## 5. 数据模型

### 5.1 新表 `integration_credentials`（migration `0036_add_integration_credentials`）

| 列 | 类型 | 说明 |
|---|---|---|
| `id` | BigInteger PK | |
| `user_id` | BigInteger FK→users.id, `ON DELETE CASCADE` | |
| `provider` | String(32) | `pingcode` / `plm` |
| `username` | String(255) | 登录账号，明文（仅本人可见） |
| `secret_encrypted` | Text | AES-GCM 密文（内为密码明文），格式 `v1:<b64(nonce+ciphertext)>` |
| `key_version` | Integer, default 1 | 预留密钥轮换 |
| `token_encrypted` | Text nullable | 加密后的 JWT |
| `cookies_encrypted` | Text nullable | 加密后的 cookie JSON |
| `token_expires_at` | DateTime nullable | token 主动过期时间（UTC） |
| `status` | String(24) | `ok` / `reauth_required` / `error` |
| `last_login_at` | DateTime nullable | 最近一次登录成功 |
| `last_error` | String(500) nullable | 最近一次失败原因（脱敏） |
| `login_failures` | Integer, default 0 | 连续失败次数 |
| `last_attempt_at` | DateTime nullable | 最近一次登录尝试 |
| `created_at` / `updated_at` | DateTime | |

索引：`UNIQUE(user_id, provider)`。

### 5.2 Redis 键（非持久数据）
- 单飞锁：`integration:login:<credential_id>`，`SET NX EX 30`
- 提单幂等：`integration:pingcode:create:<user_id>:<client_request_id>`，TTL 600s，值为结果 JSON

## 6. 加密设计

### 6.1 传输加密
- 后端启动时生成 **RSA-2048** 临时密钥对（仅内存，重启即换）。
- `GET /api/v1/integrations/crypto/public-key`（需登录）返回 `{"algorithm":"RSA-PKCS1v15","public_key":"-----BEGIN PUBLIC KEY-----..."}`。
- 前端用 `jsencrypt` 加密一个 JSON：`{"username":"...","password":"..."}`，得到 base64 密文，放入 `PUT credentials` 的 `payload_encrypted` 字段。
- 后端用私钥解密；密文长度上限 4096 字符；解密失败返回 400，不回显任何明文。
- 密码不进 URL、不进日志、不进 MCP 参数。

### 6.2 落库加密
- 算法：AES-256-GCM，随机 12 字节 nonce，密文格式 `v1:<base64(nonce||ciphertext||tag)>`。
- AAD：`f"{user_id}:{provider}"`，防止密文跨行/跨用户搬运。
- 密钥：环境变量 `INTEGRATION_CREDENTIAL_KEY`（32 字节 base64）。
  - 生产（`ENV=production`）缺失或长度不符 → 启动失败，与 `JWT_SECRET` 同等对待。
  - 开发/测试未配置 → 由 `JWT_SECRET` 经 HKDF-SHA256（`info=b"testmate-integration-credentials"`）派生 32 字节。
  - 更换主密钥会让旧密文不可解 → 用户重新录入；`key_version` 为未来双读预留。

### 6.3 泄漏面控制
- 所有 API 响应只返回 `username`、状态、时间、脱敏错误；绝不返回密码、JWT、cookie、密文。
- `last_error` 只允许预定义文案（如「账号或密码错误」「会话过期且重登失败」），不透传上游 `stack`。
- MCP 审计已有 `summarize_arguments`；本域工具参数不含凭据，无需额外过滤。
- 凭据 API 路由不记录请求体日志。

## 7. 登录与续期

### 7.1 登录
```
signin(username, password_md5):
  POST /api/typhon/team/signin
  → 解析 data.value: access_token, team._id, user
  → 保存 token/cookies(Set-Cookie 原样转 JSON)，token_expires_at = now + 90min
  → status=ok, login_failures=0, last_login_at=now, last_error=NULL
```
- 密码 MD5 在服务端计算（`hashlib.md5`）。
- 登录超时 15s；连接错误/超时不标记为密码错误。

### 7.2 使用与刷新
```
ensure_session(user):
  cred = load(user, 'pingcode')
  无 cred            → McpRuntimeError('integration_not_configured', ...)
  now < expires_at   → 直接用缓存
  否则进入单飞锁:
    ① cookie 换 JWT：GET /api/typhon/account/access-token
       成功 → 更新 token/cookies/expires_at(now+90min)
    ② 失败 → 完整 signin（用解密后的密码）
    ③ 仍失败 → status=reauth_required, last_error='会话过期且自动重登失败'
```
- 每次刷新后异步调用 `prolong-logged-state`（失败忽略，不阻塞业务）。
- 主动阈值 90 分钟（会话 2h，留 30 分钟余量）。

### 7.3 业务请求的错误处理
`PingCodeClient.request()`：
1. 发送请求（Bearer + `X-Team-Id` + cookie）。
2. 若 HTTP 401/403，或 HTTP 200 且 JSON `code` 为 401/403 → 触发一次强制刷新（跳过 90 分钟判断）。
3. 刷新成功则重试原请求 **一次**；仍失败则抛 `integration_reauth_required`。
4. 其它 `code != 200` → 映射为可读错误（如权限不足、对象不存在）。

### 7.4 失败冷却（防止账号被锁）
- 连续 `login_failures >= 3` 后，5 分钟内不再尝试密码登录，直接返回「账号连续登录失败，请稍后再试或检查凭据」。
- 成功登录清零。
- 用户重新保存凭据时清零并立即验证。

## 8. REST API

前缀 `/api/v1/integrations`，全部需登录，只能操作自己的数据。

| 方法 | 路径 | 说明 |
|---|---|---|
| GET | `/providers` | 返回 `{items:[{code,name,enabled,bound,username,status,last_login_at,last_error}]}`；PLM `enabled=false` |
| GET | `/crypto/public-key` | `{algorithm, public_key}` |
| PUT | `/{provider}/credentials` | body `{payload_encrypted}`；解密→登录验证→加密落库；失败 400 且不落库 |
| DELETE | `/{provider}/credentials` | 删除凭据与缓存的 token/cookie |
| POST | `/{provider}/test` | 用当前凭据强制登录一次，返回 `{display_name, team_name, login_at}` |

约束：
- `provider` 仅接受注册表中的 code（未知 → 404）。
- PLM 的 PUT/POST 返回 409 `{"detail":"PLM 集成尚未接入"}`。
- `PUT` 成功后返回与 `providers` 相同结构。
- `PUT` 与 `test` 共用限流：同一用户 10 秒内最多 3 次（Redis 计数），防止用平台做密码爆破。

## 9. 内置 MCP

### 9.1 域与 scope
- 新域 `pingcode`，构建 `build_pingcode_server(public_base_url, allowed_hosts)`，在 `app/main.py` 的 `mcp_dispatcher.configure` 注册。
- `SCOPE_ORDER` 增加 `pingcode:read`、`pingcode:write`（顺序放在 kb 之后）。
- `allowed_scopes(user)`：活跃用户同时获得 `pingcode:read` 与 `pingcode:write`（已确认：写权限给所有活跃用户）。
- **存量令牌/授权**：新增 scope 不会自动加到已签发的静态令牌或 OAuth 授权里；个人中心「访问令牌」页重建令牌并勾选新 scope，或重新走一次 OAuth 授权即可。前端无需特殊处理。

### 9.2 工具（21 个，命名 `pingcode_<领域>_<动作>_<对象>`）

领域四档：`common`（通用：账号/项目/成员）、`issue`（问题单：工单/缺陷/评论/附件）、`case`（用例库：testhub 用例）、`plan`（测试计划：testhub 计划/执行记录/报告）。

| 工具 | scope | 只读 | 关键参数 |
|---|---|---|---|
| `pingcode_common_whoami` | read | 是 | 无 |
| `pingcode_common_list_projects` | read | 是 | 无 |
| `pingcode_common_list_members` | read | 是 | `project_id` |
| `pingcode_issue_list_types` | read | 是 | `project_id` |
| `pingcode_issue_get_schema` | read | 是 | `project_id`, `work_item_type_id`, `project_template_type?` |
| `pingcode_issue_search` | read | 是 | `project_id?`, `project_identifier?`, `keyword?`, `type_id?`, `state_id?`, `state_ids?`, `assignee_id?`, `updated_after?`, `page?`, `page_size?` |
| `pingcode_issue_get` | read | 是 | `id?`, `identifier?`, `project_id?`（后两者至少一个） |
| `pingcode_issue_list_comments` | read | 是 | `id`, `page?`, `page_size?` |
| `pingcode_issue_list_attachments` | read | 是 | `id` |
| `pingcode_issue_download_attachment` | read | 是 | `url?`, `file_id?`, `name?`, `max_bytes?`, `token?` |
| `pingcode_issue_preview` | read | 是 | `project_id`, `work_item_type_id`, `project_template_type?`, `properties`, `description_template?`, `description_fields?` |
| `pingcode_issue_create` | write | 否 | 同上 + `attachments?`, `confirm`, `client_request_id` |
| `pingcode_issue_upload_attachment` | write | 否 | `path?`, `content_base64?`（二选一）, `name?`, `purpose?`（`attachment`/`inline`）, `work_item_id?`, `confirm`, `client_request_id?` |
| `pingcode_issue_add_comment` | write | 否 | `id`, `content`, `confirm` |
| `pingcode_case_list_libraries` | read | 是 | 无 |
| `pingcode_case_get_properties` | read | 是 | `library_id` |
| `pingcode_case_search` | read | 是 | `library_id`, `keyword?`, `identifier?`, `filters?`, `created_by?`, `updated_by?`, `page?`, `page_size?` |
| `pingcode_case_get` | read | 是 | `library_id`, `identifier` |
| `pingcode_plan_search` | read | 是 | `library`, `keyword?`, `status?`, `assignee?`, `page?`, `page_size?` |
| `pingcode_plan_run_search` | read | 是 | `plan`, `keyword?`, `result?`, `include_steps?`, `page?`, `page_size?` |
| `pingcode_plan_report` | read | 是 | `plan`, `sections?`, `page?`, `page_size?`, `defect_keyword?`, `defect_state?` |

实现约束：
- 工具一律通过 `principal.user.id` 取凭据；未绑定返回 `integration_not_configured`（提示去个人中心绑定）。
- `create_work_item` / `add_comment` / `upload_attachment`：`confirm` 必须为 `true`，否则 `confirmation_required`。
- `create_work_item` 必须带 `client_request_id`；`attachments` 为已上传 file_id 列表，建单成功后逐个调用 `POST /api/agile/work-items/{id}/attachment` 关联，单个失败只在该条结果里报 `ok: false`，不回滚工单；命中 Redis 幂等键（10 分钟）直接返回上次结果，附件不会重复关联。
- `preview_work_item` / `create_work_item`：`properties` 允许省略。缺少必填或选项值非法时拒绝，并给出字段中文名、类型提示与合法选项 `_id=text`；`preview` 另返回 `missing_fields` / `invalid_fields`。必填校验放在 handler 而非 inputSchema，避免 MCP 客户端预校验只回裸字段名。`assignee` 为空时返回 `assignee_required`（提示用 `pingcode_common_list_members` 查成员 uid）。
- 必填字段按 `project_id` 所属项目自身的字段模板判定：省略 `project_template_type` 时从 `GET /api/agile/projects/select-options?can_create_work_item=1` 解析该项目的 `template_type`；项目不在可提单列表时返回 `invalid_arguments`（提示用 `pingcode_common_list_projects`）。`is_local_configure=1` 的项目必须命中项目级模板，404 时 `preview_work_item` 返回 `project_schema_unavailable`，避免用全局必填项误导调用方；`is_local_configure=0` 的项目本来就共用全局模板，取全局是项目真实配置而非兜底。`get_property_schema` 返回 `template_type`、`is_local_configure` 与 `used_global_fallback`。`create_work_item` 保留原有兜底（模板取不到时交由 PingCode 校验）。
- `upload_attachment`：`path` 与 `content_base64` 恰好提供一个；`purpose=inline` 返回公共图片 URL，`purpose=attachment` 可带 `work_item_id` 直接关联；`client_request_id` 命中 Redis 幂等键直接返回上次结果（10 分钟）。
- `download_attachment`：图片返回 `{content_type, base64, bytes}`；非图片返回 `{url, token, name, bytes}`（客户端自行下载）；超过 `max_bytes`（默认 20MB，上限 100MB）返回错误而不截断。
- `upload_attachment` 单文件上限 100MB，超限返回 `attachment_too_large`。
- 分页参数上限：`page_size <= 100`；`search_work_items` 默认 20。
- 测试计划链：`plan_search`（`library` 传测试库 `_id` 或 identifier，内部先解析成 `_id`）→ `short_id` → `plan_run_search` / `plan_report`。执行记录接口的分页参数必须放请求体（`pi`/`ps`），查询串会被忽略。报告缺陷列表不返回描述正文（描述可能含环境凭据），细节把缺陷编号传给 `pingcode_issue_get`。非法 `status`/`result`/`defect_state`/`sections` 返回中文可选值。
- 描述模板与 `description_fields` 渲染规则从 `pingcode/templates.py` 移植，字段缺失渲染为 `-`。

## 10. 前端

### 10.1 个人中心
`frontend_web/src/views/Profile/index.vue` 增加第三个页签「外部系统」：
- 复用 `.kind-tabs` / `.kind-tab`；页签 `key='integrations'`。
- 新组件 `views/Profile/IntegrationAccounts.vue`，每个 provider 一张卡。

PingCode 卡片：
- 状态徽标：未绑定 / 可用 / 需重新登录 / 异常。
- 表单：账号（`textbox`）、密码（`password`，`autocomplete="new-password"`）。
- 按钮：`保存并验证`（PUT）、`测试连接`（POST test）、`解除绑定`（DELETE，二次确认）。
- 展示：`last_login_at`、`last_error`；成功后提示「已连接：<display_name>（<team_name>）」。
- 密码输入框在任何时候都不回填。

PLM 卡片：只读占位，文案「PLM 集成建设中，暂不支持配置」，按钮禁用。

### 10.2 传输加密
- 新增依赖 `jsencrypt`（`frontend_web/package.json`）。
- 新工具 `src/utils/rsaTransport.ts`：`fetchPublicKey()`（会话内缓存）→ `encryptPayload({username,password})`。
- 新 API 模块 `src/api/integrations.ts`。
- 不写入 `localStorage` / `sessionStorage`；表单提交后立即清空密码字段。

### 10.3 测试
- `src/api/__tests__/integrations.spec.ts`：路径与请求体。
- `src/utils/__tests__/rsaTransport.spec.ts`：mock 公钥加密调用（jsencrypt 可注入）。
- `views/Profile/__tests__/IntegrationAccounts.spec.ts`：保存/测试/解绑的调用与错误展示。

## 11. PLM 预留设计

- 同一 `integration_credentials` 表：`provider='plm'`。
- 同一 REST/UI 框架；`GET /providers` 返回 `{code:'plm', name:'PLM', enabled:false}`。
- `PlmProvider` 实现 `IntegrationProvider` 协议，方法体抛 `NotImplementedError`；不注册 MCP 域。
- 二期实现时只需补 `plm/client.py`（CAS 登录/会话探测）与 `plm/tools.py`，无需改表、API、UI 结构。
- 文档化差异：PingCode 用 Bearer JWT；PLM 预计用 CAS cookie + HTML 重定向判定（与 AiTestX `PLM_PROBE_SESSION` 一致）。

## 12. 配置与部署

新增环境变量（`deploy/native/.env`、docker compose、`app/core/config.py`）：

```
INTEGRATION_CREDENTIAL_KEY=<base64 32 bytes>
```

- 生产缺失 → 启动失败（与 JWT_SECRET 校验同一处）。
- 开发可缺省（HKDF 派生）。
- nginx 无需改动（`/api/v1` 与 `/mcp` 已代理）。
- Qoder 侧 MCP 配置：`http://<host>:8081/mcp/pingcode`，OAuth 授权勾选 `pingcode:read` `pingcode:write`。

## 13. 测试策略

### 13.1 后端单测（pytest，使用本地 MySQL/Redis）
1. `crypto`：AES 往返；AAD 不匹配解密失败；密钥缺失/长度错误；密文格式校验。
2. `credentials`：唯一约束；删除级联；`last_error` 脱敏。
3. `token_manager`：
   - 首次登录写入 token/cookie；
   - 未过期直接用（mock 时间）；
   - 过期 → cookie 刷新成功；
   - 刷新失败 → 密码重登；
   - 重登失败 → `reauth_required`；
   - 3 次失败冷却；
   - 并发 10 个请求只登录 1 次（单飞）。
4. `client`：HTTP 200 + `code=401` 触发刷新并重试一次；重试仍失败抛错；非 401 错误映射。
5. API：未登录 401；越权访问他人凭据不可达；PUT 解密失败 400；PLM 409；测试接口限流。
6. MCP：14 个工具 schema 严格校验（多余字段拒绝）；scope 缺失拒绝；`confirm` 缺失拒绝；幂等键命中；未绑定凭据报错；审计记录 write 标记。

### 13.2 前端
- Vitest 用例见 10.3；`vue-tsc` 通过。

### 13.3 端到端验收（真实内网）
1. 浏览器打开 `http://127.0.0.1:8081`，个人中心 → 外部系统 → 录入账号密码 → 保存并验证。
2. 测试连接展示真实姓名与团队名。
3. Qoder 连接 `/mcp/pingcode`：`whoami`、`search_work_items(project_identifier="TF2")`、`get_work_item(identifier="TF2-<id>")`。
4. **真实建单**：`preview_work_item` 干跑确认后，`create_work_item` 在 `TIANFU V100R001`（`663ede052100d4724722f6a6`）以「缺陷」（`662096879f86b6cac7599096`）创建一条标题为「【TestMate MCP 联调】请忽略」的工单；随后 `add_comment` 追加验证评论。记录工单 `identifier` 与 `id` 作为验收证据。附件路径：`upload_attachment` 上传截图（`purpose=attachment`）后用 `create_work_item.attachments` 关联；内嵌图用 `purpose=inline` 的 `public_url` 写入 `properties.description`；回读确认描述含该 URL、`attachment_count >= 1` 且附件列表可见。
5. 重启后端进程后再次调用 `whoami`，确认登录态从加密缓存恢复（不重新输入密码）。
6. 截图核对个人中心卡片状态；确认浏览器控制台 0 错误。

## 14. 验收标准

- 凭据在数据库中仅为密文；接口、日志、MCP 响应中不出现密码/JWT/cookie。
- 后端全量测试通过；前端 typecheck + Vitest 通过。
- 真实账号完成第 13.3 节 1–6 步，TIANFU 工单创建成功并可查询。
- 后端重启后 MCP 连续调用成功（无人工干预）。
- PLM 在 providers 与 UI 中可见但明确为「建设中」，PUT/TEST 返回 409。

## 15. 风险与缓解

| 风险 | 缓解 |
|---|---|
| `team/signin` 非公开 API，PingCode 升级可能变更 | 集中在 `pingcode/client.py`；错误可观测（`last_error`）；异常时 UI 提示重新绑定 |
| 密码 MD5 算法变更 | 登录失败时明确提示；模板可配置为「密码预处理函数」单点修改 |
| 账号被风控/验证码 | 失败冷却 5 分钟；不自动重试轰炸；错误提示人工处理 |
| 内网 HTTP 被抓包 | 应用层 RSA 加密凭据；建议后续启用 HTTPS（不在本期） |
| 多 worker 并发登录 | Redis 单飞锁；后端当前单 worker，仍保留锁 |
| 密钥丢失/轮换 | 密文不可解 → `reauth_required`，用户重新录入；`key_version` 预留轮换 |

## 16. 分阶段实施

1. **Phase 1**：模型 + migration 0036 + crypto + credentials + REST API（含测试）
2. **Phase 2**：PingCode client + token manager + 14 个工具 + MCP 域 + scopes（含测试）
3. **Phase 3**：前端外部系统页签 + RSA 工具 + 测试
4. **Phase 4**：真实账号端到端验收（含 TIANFU 建单）+ 文档
5. **Phase 5**：PLM 占位与框架文档

## 17. 已确认决策

1. `pingcode:write` 授予所有活跃用户。
2. PLM 本期仅框架占位，不做服务端登录。
3. 验收允许用真实账号创建一条测试工单，项目固定为 `TIANFU V100R001`（`TF2`），类型为「缺陷」。
