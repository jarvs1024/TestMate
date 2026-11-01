# TestMate MCP Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 在现有 FastAPI 后端交付技能域 MCP、OAuth 2.1、14 个真实工具及前端授权管理，写操作与网页市场完全同链路。

**Architecture:** `transport -> protocol -> skill domain -> existing marketplace`。MCP 适配层显式执行原路由权限依赖；不抽离或复制市场状态机。OAuth 客户端/grant 持久化，授权码进程内一次性保存，access token 以 grant 版本实现即时撤销。

**Tech Stack:** Python 3.11+、FastAPI、Starlette、SQLAlchemy async、MySQL、Redis、`mcp==1.29.1`、python-jose、Vue 3、TypeScript、Element Plus。

**Spec:** `docs/specs/2026-10-31-testmate-mcp-design.md`（v12）

## Global Constraints

- 本地 `master` 已在开发前 fast-forward 到 `2b0556a`；不切换工作区，不推送远端。
- 不做内置连接器：禁止新增 `is_builtin`、seed、特殊守卫或特殊市场卡片。
- 不改既有资产删除、下架、更新、审核、Git 同步和通知语义；只允许新增只读/下载能力。
- 直接调用路由不会执行 `Depends`；写适配器必须显式 `await require_publisher(user)`。
- OAuth token 无 `exp`，但必须校验 `aud/typ/grant_id/grant_version/token_version` 和当前用户状态。
- DCR 仅允许回环 HTTP redirect URI；PKCE 仅 S256；授权码 5 分钟且一次性。
- SPA 路由只用 `/connect/authorize` 与 `/connect/grants`。
- 工具测试走真实 MCP transport，不以直接调用 handler 冒充契约测试。
- 审计不得保存 package_base64、文件内容或文件文本。
- 写测试只用 `testmate_test` 和本地 Git fixture；真实环境不得发钉钉写通知。
- 运维只使用 `deploy/native/tmctl.sh`；e2e 串行，不使用 Docker 替代 native。
- 按用户约定，实现先留本地验证；本计划不自动 commit/push。

---

### Task 1: 依赖、MCP 模型与迁移

**Files:**
- Modify: `backend_gateway/pyproject.toml`
- Modify: `backend_gateway/requirements.txt`
- Modify: `backend_gateway/requirements.lock`
- Create: `backend_gateway/app/models/mcp.py`
- Modify: `backend_gateway/app/models/__init__.py`
- Create: `backend_gateway/alembic/versions/0030_add_mcp_tables.py`
- Modify: `backend_gateway/tests/conftest.py`
- Test: `backend_gateway/tests/test_mcp_models.py`

**Interfaces:**
- Produces: `McpOAuthClient`、`McpOAuthGrant`、`McpApiToken`、`McpToolCall`；grant 的 `(user_id, client_id)` 唯一约束和 `version` 字段。

- [ ] **Step 1: 写失败测试**，断言四张表在 metadata 中、grant 有 version 且联合唯一。
- [ ] **Step 2: 运行** `pytest tests/test_mcp_models.py -v`，预期因模型不存在而失败。
- [ ] **Step 3: 实现模型和迁移**。核心字段：
```python
class McpOAuthGrant(Base):
    __tablename__ = "mcp_oauth_grants"
    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(BigInteger, index=True)
    client_id: Mapped[str] = mapped_column(String(128))
    scopes: Mapped[list] = mapped_column(JSON, default=list)
    version: Mapped[int] = mapped_column(Integer, default=1)
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    __table_args__ = (UniqueConstraint("user_id", "client_id", name="uk_mcp_grant_user_client"),)
```
- [ ] **Step 4: 将模型导入 `app.models`，把四表加入测试清表，锁 `mcp==1.29.1`。**
- [ ] **Step 5: 运行模型测试和现有迁移测试，预期通过。**

### Task 2: OAuth 持久化、DCR 与 token 生命周期

**Files:**
- Create: `backend_gateway/app/mcp/common/oauth.py`
- Create: `backend_gateway/app/mcp/common/context.py`
- Test: `backend_gateway/tests/test_mcp_oauth.py`

**Interfaces:**
- Produces: `register_client(metadata)`、`validate_authorization(params)`、`create_authorization_code(...)`、`exchange_code(...)`、`revoke_token(...)`、`issue_access_token(...)`、`allowed_scopes(user)`。

- [ ] **Step 1: 写失败测试**：非回环 redirect 拒绝；DCR 强制 public client；错误 PKCE 拒绝；授权码二次兑换拒绝；重新授权后旧 token 的 grant_version 失效。
- [ ] **Step 2: 运行测试，确认 ImportError/断言失败。**
- [ ] **Step 3: 实现 DB client/grant 与内存授权码**。PKCE 计算固定为：
```python
expected = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode("ascii")).digest()).rstrip(b"=").decode("ascii")
if not secrets.compare_digest(expected, code.challenge):
    raise OAuthError("invalid_grant", "PKCE 校验失败")
```
- [ ] **Step 4: 签发 token 时写入 `typ=mcp-oauth`、`aud=<public_base>/mcp`、sub/client_id/grant_id/grant_version/token_version/scopes，不写 exp。**
- [ ] **Step 5: 运行 OAuth 测试，预期通过。**

### Task 3: OAuth HTTP 路由与发现元数据

**Files:**
- Create: `backend_gateway/app/mcp/common/oauth_routes.py`
- Modify: `backend_gateway/app/main.py`
- Test: `backend_gateway/tests/test_mcp_oauth_routes.py`

**Interfaces:**
- Produces: `/oauth/register|authorize|token|revoke` 和两个 well-known 端点；authorize 返回 `/connect/authorize?...` 的 302。

- [ ] **Step 1: 写失败集成测试**，覆盖 metadata、DCR、授权 302、code 换 token、revoke。
- [ ] **Step 2: 运行并确认 404。**
- [ ] **Step 3: 实现路由，不调用 SDK `create_auth_routes`**；OAuth 错误统一 JSON `{error, error_description}`，token 成功返回 `access_token/token_type=bearer/scope`。
- [ ] **Step 4: 运行测试并验证内网 `http://127.0.0.1:8081` issuer 不抛 HTTPS 异常。**

### Task 4: TokenVerifier 与实时用户权限

**Files:**
- Create: `backend_gateway/app/mcp/common/auth.py`
- Test: `backend_gateway/tests/test_mcp_auth.py`

**Interfaces:**
- Produces: `McpTokenVerifier.verify_token(token) -> AccessToken | None`；`Principal` 存在 AccessToken.claims 中。

- [ ] **Step 1: 写失败测试**：无 audience/typ 拒绝；撤销 grant 拒绝；重授权旧版本拒绝；inactive/token_version 改变拒绝；DB 当前角色生效；静态 token 撤销/过期拒绝。
- [ ] **Step 2: 实现 verifier**，每次重新加载 User，OAuth 精确按 grant id 查询并比较 user/client/version/revoked_at，scopes 与当前授权能力求交。
- [ ] **Step 3: 运行测试，预期通过。**

### Task 5: 同意、grant 与静态 token REST

**Files:**
- Create: `backend_gateway/app/api/mcp.py`
- Modify: `backend_gateway/app/main.py`
- Test: `backend_gateway/tests/test_mcp_api.py`

**Interfaces:**
- Produces: `GET /api/v1/mcp/authorize/preview`、`POST /api/v1/mcp/authorize`、`GET/DELETE /api/v1/mcp/grants`、`GET/POST/DELETE /api/v1/mcp/tokens`。

- [ ] **Step 1: 写失败测试**：viewer 无 write；发布者按 `can_publish` 得 write；越权 scope 拒绝；返回 callback_url 而非依赖 Axios 302；用户只能撤自己的 grant；token 明文仅创建响应出现。
- [ ] **Step 2: 实现端点**。同意提交重新校验所有 OAuth 参数，授权后返回：
```python
{"callback_url": f"{redirect_uri}?{urlencode({'code': code, 'state': state})}"}
```
- [ ] **Step 3: 运行测试，预期通过。**

### Task 6: 前端同意页、授权管理和 admin token UI

**Files:**
- Create: `frontend_web/src/api/mcp.ts`
- Create: `frontend_web/src/views/Connect/Authorize.vue`
- Create: `frontend_web/src/views/Connect/Grants.vue`
- Modify: `frontend_web/src/router/index.ts`
- Modify: `frontend_web/src/views/Settings/index.vue`
- Test: `frontend_web/src/views/Connect/__tests__/authorize.spec.ts`

**Interfaces:**
- Consumes: Task 5 REST。
- Produces: 两个 `/connect/*` 页面与 admin 平台接入令牌管理。

- [ ] **Step 1: 写失败组件测试**：预览渲染 scope；同意调用 `window.location.assign(callback_url)`；拒绝回 `access_denied`；撤销后刷新列表。
- [ ] **Step 2: 实现 API 与页面，复用现有登录 redirect，不在前端按角色猜 scope。**
- [ ] **Step 3: 运行 Vitest 与 `npx vue-tsc --noEmit`。**

### Task 7: MCP 公共层、真实 schema 注册、配额与审计

**Files:**
- Create: `backend_gateway/app/mcp/common/{server.py,tool.py,audit.py,errors.py}`
- Test: `backend_gateway/tests/test_mcp_tool_runtime.py`

**Interfaces:**
- Produces: `ToolSpec`、`build_mcp(...)`、`build_dispatcher(...)`、`register_tool(...)`、`run_mcp_lifespan(...)`。

- [ ] **Step 1: 写失败测试**：scope 不足、用户/客户端配额、成功/失败审计、敏感参数摘要、Route+Mount 路径。
- [ ] **Step 2: 实现 ToolSpec 和包装层**。摘要规则：
```python
if key == "package_base64":
    out[key] = {"bytes": len(base64.b64decode(value)), "sha256": hashlib.sha256(raw).hexdigest()}
elif key == "files":
    out[key] = {"paths": sorted(value), "count": len(value)}
```
- [ ] **Step 3: 注册工具后将 SDK tool.parameters 设为 spec.input_schema；不得依赖 `_tool(**kwargs)` 自动推导。**
- [ ] **Step 4: 用 AsyncExitStack 对称运行各域 session_manager，运行测试。**

### Task 8: Transport 与 tools/list 协议门禁

**Files:**
- Create: `backend_gateway/tests/_mcp_protocol.py`
- Create: `backend_gateway/tests/test_mcp_transport.py`
- Modify: `backend_gateway/tests/_lifespan.py`（若已有则复用）

**Interfaces:**
- Produces: `initialize(client, token)`、`list_tools(client, token)`、`call_tool(client, token, name, args)` 的 JSON-RPC 测试助手。

- [ ] **Step 1: 写未认证 POST `/mcp/skill` 401 与认证 initialize 成功测试。**
- [ ] **Step 2: 写 tools/list 测试**，断言 14 个名称和每个 inputSchema 的 required/properties，不允许只检查 ToolSpec。
- [ ] **Step 3: 写 SSE 首帧 endpoint 与非法 Host 421 测试。**
- [ ] **Step 4: 修正装配直到全部通过；不得把 401 与 200 写成同一请求的矛盾期望。**

### Task 9: 市场规则单一真源

**Files:**
- Create: `backend_gateway/app/core/market_rules.py`
- Modify: `backend_gateway/app/api/marketplace.py`（仅在 `/{code}` 前新增 `/rules`）
- Modify: `frontend_web/src/views/Capability/Catalog/assetForm.ts`
- Modify: `frontend_web/src/views/Capability/Catalog/useAssetUploadForm.ts`
- Modify: `frontend_web/src/views/Capability/Catalog/index.vue`
- Test: `backend_gateway/tests/test_market_rules_endpoint.py`

**Interfaces:**
- Produces: `rules_payload()` 与 `GET /api/v1/assets/rules`。

- [ ] **Step 1: 写失败端点测试**，断言 code/segment/package/required/categories/projects/enforcement。
- [ ] **Step 2: 实现后端规则包和只读端点，运行测试。**
- [ ] **Step 3: 前端在已登录市场上下文加载规则；加载失败显示重试并禁止提交，不保留可静默漂移的校验兜底。**
- [ ] **Step 4: 跑后端规则测试、前端相关 Vitest 和 vue-tsc。**

### Task 10: 九个只读工具

**Files:**
- Create: `backend_gateway/app/mcp/skill/adapter.py`
- Create: `backend_gateway/app/mcp/skill/tools.py`
- Create: `backend_gateway/app/mcp/skill/server.py`
- Test: `backend_gateway/tests/test_mcp_skill_read.py`

**Interfaces:**
- Produces: `skill_search/get/read_doc/list_files/read_file/package_info/categories/projects/job_status`。

- [ ] **Step 1: 写失败协议测试**：搜索分页、不可见资产 404、文档、文件树、单文件文本、二进制拒绝、分类项目、job 属主。
- [ ] **Step 2: 实现薄适配器**，直接调用既有 list/get/doc/files/bundle 等函数并显式传所有 Query/Form 默认参数。
- [ ] **Step 3: `skill_read_file` 从 bundle 精确选择 path，拒绝 `..`、绝对路径、base64 内容和缺失文件。**
- [ ] **Step 4: `skill_job_status` 使用真实 staged/syncing/pushed/failed 状态并检查 created_by/admin。**
- [ ] **Step 5: 运行协议测试，预期通过。**

### Task 11: 严格版本资产下载票

**Files:**
- Modify: `backend_gateway/app/core/security.py`
- Modify: `backend_gateway/app/api/marketplace.py`（新增 ticket 兑换端点，不改变现有下载分支）
- Modify: `backend_gateway/app/mcp/skill/adapter.py`
- Test: `backend_gateway/tests/test_mcp_asset_download.py`

**Interfaces:**
- Produces: `create_asset_download_ticket/decode_asset_download_ticket`，`GET /api/v1/assets/{code}/versions/{version}/ticket-download?ticket=...`。

- [ ] **Step 1: 写失败测试**：sha256 与真实下载一致；错误 code/version/type/过期拒绝；未发布资产不因 ticket 绕过可见性。
- [ ] **Step 2: 实现 `typ=asset-dl`、uid/code/ver/exp 票据，兑换时加载用户和资产并重新执行可见性检查。**
- [ ] **Step 3: 严格使用请求版本对应的存储包；不存在则 404，禁止 `_find_stored_package` 的任意包回退。**
- [ ] **Step 4: 运行下载与既有软件下载票测试，预期通过。**

### Task 12: 五个写工具与不猜协议

**Files:**
- Modify: `backend_gateway/app/mcp/skill/adapter.py`
- Modify: `backend_gateway/app/mcp/skill/tools.py`
- Test: `backend_gateway/tests/test_mcp_skill_write.py`

**Interfaces:**
- Produces: `skill_publish/update/edit_meta/submit_review/unpublish_request`。

- [ ] **Step 1: 写失败测试**：缺必填/包无副作用；update 无 version/无包拒绝；version 相同拒绝；省略字段保持；只读 scope 写拒绝；非发布者拒绝。
- [ ] **Step 2: 实现适配器并在每个写路由调用前执行：**
```python
await marketplace.require_publisher(user)
result = await marketplace.upload_asset(...全部 Form 参数..., user=user)
```
- [ ] **Step 3: package/files 二选一，base64 严格解码并限制大小；edit_meta 至少一个字段；unpublish 绑定 confirm_code=code。**
- [ ] **Step 4: 运行写工具与既有市场权限测试，预期通过。**

### Task 13: REST/MCP 写场景契约

**Files:**
- Create: `backend_gateway/tests/test_mcp_contract.py`
- Modify: `backend_gateway/tests/_mcp_protocol.py`

**Interfaces:**
- Consumes: 预置 grant + 真实 access token；真实 JSON-RPC，不直接调 handler。

- [ ] **Step 1: 写五个参数化场景**：publish、update、edit_meta、submit_review、unpublish_request；REST 与 MCP 使用不同 code。
- [ ] **Step 2: 每场景比较 DB publish_status/pending_action/version/summary、通知事件序列和归一化响应。**
- [ ] **Step 3: 另写 adapter 参数映射测试**，检查传递的显式参数和值，不强迫 `user` 与 `_user` 内部名称一致。
- [ ] **Step 4: 运行契约测试；人工 approve/reject 保持 REST-only，不计入五个双路径场景。**

### Task 14: 部署代理与单 worker 硬约束

**Files:**
- Modify: `frontend_web/nginx.conf`
- Modify: `deploy/native/units/nginx.conf.tpl`
- Modify: `deploy/native/tmctl.sh`
- Modify: `backend_gateway/app/core/settings_store.py`
- Test: `backend_gateway/tests/test_mcp_deploy_config.py`

**Interfaces:**
- Produces: `/mcp`、`/oauth/`、`/.well-known/oauth-` 代理；`mcp.allowed_hosts` 设置；worker>1 时启动失败。

- [ ] **Step 1: 写配置测试**，断言三处代理、X-Forwarded-Host、SSE buffering off、`/connect/*` 不被代理。
- [ ] **Step 2: 修改两份 nginx，保留 `$http_host` 到 X-Forwarded-Host，allowed_hosts 同时接受裸 host/host:port。**
- [ ] **Step 3: 把 tmctl 的多 worker 警告改成 MCP 启用时的硬错误。**
- [ ] **Step 4: 运行配置测试和 shell 语法检查。**

### Task 15: 全量验证与真实环境只读验收

**Files:**
- Modify: 本文件复选框与验证结果（只在实际运行后勾选）

- [x] **Step 1: 后端全量**：
```bash
cd backend_gateway
set -a && source ../deploy/native/runtime/config/backend.env && set +a
MARKET_WORKSPACE=/tmp/tm-test-ws ../deploy/native/runtime/venv/bin/python3 -m pytest tests -q
```
- [ ] **Step 2: 前端全量**：`cd frontend_web && npx vue-tsc --noEmit && npx vitest run --testTimeout=8000`，禁止 `|| true`。
- [x] **Step 3: 部署**：`./deploy/native/tmctl.sh local update && ./deploy/native/tmctl.sh local check && ./deploy/native/tmctl.sh local status`。
- [ ] **Step 4: 浏览器验证 `/connect/authorize`、登录回跳、grant 撤销、Qoder OAuth 发现和只读工具；Qoder UI 不能自动化时请用户执行该检查点。**
- [x] **Step 5: e2e 按既有锁串行执行；不得对真实钉钉群发送写通知。**
- [x] **Step 6: 汇报实际通过/失败项和遗留限制，由用户决定提交与推送。**

**Task 15 验证结果（2026-11-01，最终工作树）**：
- Step 1 通过：最终全量命令 exit 0，1146 项通过，1 条 `testmate_test` 已存在警告。
- Step 2 已运行但未通过，故不勾选：vue-tsc 通过；原样 Vitest 仍因 Node/jsdom localStorage 环境冲突 exit 1（185 failed / 617 passed / 12 skipped，共 814 项）；`NODE_OPTIONS=--no-experimental-webstorage` 诊断 exit 0（814/814 passed）。
- Step 3 通过：两轮 update/check/status exit 0；check 28 通过 / 7 警告 / 0 失败，服务和健康检查正常。
- Step 4 自动化范围通过、Qoder UI 留人工检查，故不勾选：通过设置页配置 public base 后，discovery 绝对 URL、授权页、登录回跳、state、code 换 token、14 个 tools/list、九个只读 tools/call、严格版本下载字节/SHA256 均通过；grant 撤销后旧 token 立即 401。Qoder UI 内部 connector 添加与授权仍需用户执行。
- Step 5 通过：临时目录补齐 `puppeteer-core` 后，既有锁内只读/通知预览 e2e exit 0，20/20 通过、无控制台错误，未发送真实通知。
- 全分支审查后的集中修复使 schema、失败审计、文件系统清理和撤销防重入通过限定复审；单 worker 修复仍有 `launchd_do_install`（`launchd install` / `local enable`）绕过，属于未解决的合并阻塞，未宣称全分支验收完成。
- 完整命令、退出码、协议观察、文件变化和用户 checkpoint 见 `.superpowers/sdd/2026-10-31-testmate-mcp-implementation/task-15-report.md`。未 commit/push。

---

## 自检结果

- **Spec coverage**：Tasks 1–6 覆盖 OAuth/授权 UI；7–8 覆盖公共层/双 transport；9 覆盖规则；10–12 覆盖 14 工具；13 覆盖一致性；14–15 覆盖部署验收。
- **普通连接器**：全计划无 `is_builtin`、seed、资产守卫或市场卡片改造。
- **类型一致性**：grant_version、token_version、asset-dl、真实 job 状态、`callback_url` 在各任务保持同名。
- **可执行性**：契约测试走真实协议，schema 以 tools/list 为准，所有验证命令均不屏蔽失败。
