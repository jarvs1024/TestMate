# TestMate MCP 设计（技能市场先行 · v11）

> 2026-10-31 · 让 **agent 能操作 TestMate**：上架 / 下载 / 更新技能；后续接知识库、软件库。
> 本轮只做**技能·插件**一个域；每个域一个独立 MCP，公共部分单独放一层。
>
> 修订要点（1–13 为历史版本要点，此处只列增量）：
> 1. `app/mcp/` 改为**按域分目录**（`common/` `skill/` `software/` `kb/`），公共部分归 `common/`
> 2. **每个域一个独立 MCP server**，各自挂载于 `/mcp/{域}`，工具集互不污染
> 3. **不动现有业务逻辑**——不重构 `marketplace.py`（仅 3 处内置资产守卫 + 1 个只读端点），MCP 侧用薄适配层调用现有路由函数
> 4. 补入 **spike 实测结论**（装配路径 / 鉴权取身份 / DNS rebinding 421 / lifespan 500）
> 5. **首期不含审核工具**：上架后由人工在网页审核台处理，agent 不自己盖章
> 6. **transport 双端点**：Streamable HTTP（`POST /mcp/skill`）+ **SSE**（`GET /mcp/skill/sse` + `POST /mcp/skill/messages/`）
>    —— Qoder CN 走 SSE 模式，SSE **必须做**
> 7. **鉴权走 OAuth 2.1**：Qoder 点「授权」→ 浏览器打开平台 → 登录并同意 → 自动回到 Qoder。
>    **普通用户不需要个人令牌页**；同意页（`/connect/authorize`）取代它
> 8. **TestMate MCP 作为平台内置连接器上架**在「插件·技能·连接」市场：
>    **不可删除、不可下架**；文案可改，但 **url（`mcp_config`）不可改**（见 §4.9）
> 9. 设置页（adminOnly）保留「平台接入令牌」作为 **CI/脚本/兜底**通道，不做个人令牌页
> 10. **授权不过期**：access token 不带 `exp`；安全靠 **grant 表**（授权记录）+ 「我的授权」页撤销
> 11. **架构规范化**：新增 §3.6「扩展点清单」—— 每种扩展都有明确落点，且有三条不变量（鉴权/业务/审计各只有一处）
> 12. **写操作与前端对齐**（§4.12）：MCP 上架/更新/下架 = 调**既有 REST 端点**，审核与通知链路完全复用；
>     合法性检查按前端表单同口径；**有选择/可选项一律先问用户，不许猜**（13 → 14 个工具，多一个 `skill_edit_meta`）
> 13. **一致性机制**（§4.13）：三层防线 —— ① 规则单一真源（前端改为拉 `/assets/rules`，MCP 直接 import）
>     ② **契约测试**：同一场景 REST 与 MCP 各跑一遍，断言 DB 状态 + 钉钉通知序列 + 返回值三者一致
>     ③ 参数反射检查：adapter 必须覆盖端点全部必填参数。新增能力漏写契约场景 → CI 直接红
>
> **v11 = 最后自审修正**（逐条对着 `mcp==1.29.1` 源码与 Starlette 路由实测核过）：
> 14. **【致命】OAuth 装配不能用 SDK 的 `create_auth_routes`** —— 它第一行就调 `validate_issuer_url`，
>     强制 issuer 必须 HTTPS（localhost 除外）。内网 `http://10.0.0.5:8081` 会在**装配时**直接抛
>     `ValueError: Issuer URL must be HTTPS` → 服务起不来。
>     → 自写 `app/mcp/common/oauth_routes.py`（复用 SDK 的 `AuthorizationHandler`/`TokenHandler`，
>     只跳过 issuer 校验）；且**绝不能给 FastMCP 传 `auth_server_provider`**（传了它就会走
>     `create_auth_routes` → 同样炸）。只用 `token_verifier` + `AuthSettings`。
> 15. **【致命】dispatcher 装配写法**：必须是 `Route("/{域}")`（精确匹配 streamable）
>     **与** `Mount("/{域}")`（前缀匹配 SSE）**并存**。只用 `Mount` → `POST /mcp/skill` 404；
>     只用 `Route` → `/mcp/skill/sse` 404。
> 16. **SSE 回传地址 = `scope["root_path"]` + 内层 endpoint**（SDK `sse.py:170-183`）→ 挂载路径写错，
>     客户端会 POST 到错地址。装配必须保证 root_path = `/mcp/{域}`，并加集成测试断言。
> 17. **【新发现】DCR 必须强制写 `scope`**：SDK 的 `OAuthClientMetadata.validate_scope` 在客户端注册时
>     没带 `scope` 会**拒绝任何带 scope 的授权请求**（`invalid_scope`）；且
>     `token_endpoint_auth_method=None` 会让 token 端点抛「Unsupported auth method」。
>     → **自写 DCR 处理器**：强制 `none` + `grant_types=["authorization_code"]` + 完整 scope 集
>     （不用 SDK 的 `RegistrationHandler`，它默认发 client_secret 且要求含 refresh_token）。
> 18. **同意页 SPA 路由不能放在 `/mcp` 下** —— nginx 的 `location /mcp` 是前缀匹配，会把 SPA 路由
>     劫持到后端 → 404。→ SPA 路由定为 `/connect/authorize`；OAuth 端点统一放 `/oauth/*`
>     （nginx 一个 `location /oauth/` 覆盖全部 4 个端点）。
> 19. **DCR 的 `redirect_uris` 只允许回环地址**（`http://127.0.0.1:*` / `http://localhost:*`），
>     否则授权码可能被送到任意外部站点（开放重定向 + 授权码泄露）。
> 20. **issuer / resource URL 在 FastMCP 构造时固化** → 改 `marketplace.public_base_url`
>     需**重启后端**才生效（写进设置项说明与已知限制）。
> 21. **内置连接器资产允许改文案**（summary / description 等），仅禁止改 `mcp_config`（url 改坏就废）。
> 22. **契约测试用「预置 grant + 签发 token」构造身份**，不跑浏览器授权流程（浏览器流程另设专门集成测试）。
> 23. **配额增加「按 user 的总量上限」**（现只有 user+client 维度）。
> 24. **S0 改成独立的最小 OAuth 探针**（~100 行，不依赖本项目实现）；若 Qoder 不走 OAuth，
>     切静态令牌路线**还需额外约 1 天**（个人令牌页 + 复制配置流程），不是现成的。
>
> 状态：**设计已定稿（v11），待实现**。

---

## 一句话

在现有 FastAPI 后端挂一组 `/mcp/{域}` 端点（**MCP Streamable HTTP + SSE 双端点**），
用 **OAuth 2.1 授权流**鉴权（Qoder 点「授权」→ 浏览器登录同意 → 自动回到 Qoder）；
每个业务域一个独立 MCP server，技能域首批暴露 **14 个工具**；
**现有业务逻辑零改动**（仅 3 处内置资产守卫 + 1 个只读端点），
MCP 能力全部收敛在新目录 `app/mcp/` 内。

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
3. agent 能**上架 / 更新**技能：走与网页完全一致的校验、命名契约、审核流
4. 架构上**可扩展**：后续加知识库 / 软件库时，只新增 `app/mcp/<域>/` 一个目录，**不改公共层、不改业务代码**

### 1.3 非目标（本轮不做）

- ❌ 不提供「硬删资产」工具（删除语义 = 下架审核通过，由平台既有流程承担）
- ❌ 不绕过审核流（agent 不能自行绕过 `marketplace.review.*` 设置）
- ❌ **不提供审核（approve/reject）工具** —— 审核由人工在网页审核台完成（D7）
- ❌ **不做个人令牌页**（D9）—— 普通用户只走 OAuth；设置页的「平台接入令牌」是 admin 专用的 CI/兜底通道
- ❌ 不实现知识库 / 软件库的工具（只留目录骨架与公共层的扩展位）
- ❌ 不做 stdio transport（首批只服务 Qoder，走远程 HTTP）
- ❌ **不做 MCP OAuth 动态注册**（静态 API Token，够用且好管）  ← **v11 修正：这条已作废**
  → OAuth 2.1 要求 DCR（RFC 7591），Qoder 靠它自助注册；本轮**做 DCR**，
  但**只允许回环 redirect_uri**（§4.3.3）
- ❌ **不重构 `marketplace.py`**（见 §6，这是本方案与 v1 最大的分歧点）

---

## 2. 已定决策

| # | 决策点 | 结论 | 理由 |
|---|---|---|---|
| D1 | MCP server 跑在哪 | **挂进现有 FastAPI 后端**，端点 `/mcp/{域}`（Streamable HTTP） | 一套部署；复用 DB、权限判定、审计、资产 job 队列 |
| D2 | agent 身份 | **OAuth 2.1 授权流**（Qoder 点「授权」→ 平台登录 + 同意 → 自动回客户端）；设置页另有**平台接入令牌**兜底 | 用户零操作、零密钥粘贴；权限随用户身份实时生效 |
| D3 | 首批接入方 | **Qoder**（远程 HTTP，`{url, headers}` 连接器配置） | 团队主力 IDE；平台「连接器」资产格式天然匹配 |
| D4 | MCP 的组织方式 | **`app/mcp/` 按域分目录；每域一个独立 MCP server；公共部分在 `common/`** | 域之间零耦合；agent 可只连需要的域，工具集不污染 |
| D5 | 对现有代码的侵入度 | **近乎零改动**：`marketplace.py` 不动业务逻辑，只在 **3 个函数顶部加内置资产守卫**（共约 9 行）+ 新增 1 个只读端点 `GET /assets/rules`；MCP 侧用薄适配层调用 | 生产代码，3005 行重排的回归风险不可接受；MCP 是独立功能，应能独立落地 |
| D6 | 协议实现 | **官方 `mcp` SDK**（FastMCP），`stateless_http=True` + `json_response=True` | 握手/版本协商/能力声明有 SDK 兜底；依赖与现有锁文件无冲突 |
| D7 | 首期是否含审核工具 | **不含** —— 上架后由人工在**网页审核台**处理 | 审核是人工运营动作，agent 不该自己给自己盖章；写入面更小、更安全 |
| D8 | TestMate MCP 的市场身份 | **平台内置连接器**：上架在「插件·技能·连接」，**不可删除 / 不可下架 / url 不可改**（文案可改），url 动态生成 | 平台自己的核心能力不该被当成普通资产随便删掉；内置资产不该走审核流 |
| D9 | 普通用户的接入路径 | **只有 OAuth 一条**：Qoder 点「授权」→ 浏览器登录同意 | 用户不需要碰令牌；个人令牌页没有存在价值 |
| D10 | MCP 写操作的行为 | **与前端同链路**：同一套合法性校验、同一个 REST 端点、同一条审核与通知链；**且不替用户做主**（有选择/可选项一律先确认） | agent 走出的结果必须和人在网页上走出来的一致，否则用户会看到两套平台 |
| D11 | 授权有效期 | **不过期**（access token 不带 `exp`），靠 grant 表撤销兜底 | 用户体验优先；安全靠「可撤销 + 每次调用查 grant」 |
| D12 | 架构分层 | transport → 协议 → 领域 → 既有业务；三条不变量（鉴权/业务/审计各只有一处） | 可扩展性 + 可维护性 |
| D13 | 一致性机制 | 三层防线：L1 规则单一真源 + L2 契约测试（REST vs MCP 三项断言）+ L3 参数反射检查 | 「一致性」不能靠自觉，要靠会红的测试 |
| **D16** | **OAuth 路由怎么写** | **自写 `app/mcp/common/oauth_routes.py`**（复用 SDK handler，跳过 issuer HTTPS 校验）；**不给 FastMCP 传 `auth_server_provider`** | SDK 的 `create_auth_routes` 强制 HTTPS，内网 http 部署直接起不来（v11 §4.3） |
| **D17** | **OAuth 端点路径** | `/oauth/register`、`/oauth/authorize`、`/oauth/token`、`/oauth/revoke`；元数据在 `/.well-known/…`；**issuer = 站点根** | nginx 只需 2 个 location（`/oauth/` + `/.well-known/oauth-`），不与 SPA 路由冲突（v11 §4.3） |
| **D18** | **同意页放哪** | SPA 路由 **`/connect/authorize`**（不在 `/mcp` 下）；OAuth `/oauth/authorize` 只负责 302 过去 | nginx `location /mcp` 是前缀匹配，会劫持 SPA 路由（v11 §4.5） |

---

## 3. 总体架构

### 3.1 目录结构（按域分类）

```
backend_gateway/app/
├── mcp/                        # ★ MCP 功能整体 —— 本轮新增，**全部代码都在这里**
│   ├── common/                 #   公共部分：与具体业务域无关
│   │   ├── __init__.py
│   │   ├── server.py           #     MCP server 工厂 + 分域挂载（dispatcher）
│   │   ├── auth.py             #     TokenVerifier（OAuth access token + 静态令牌）→ Principal
│   │   ├── oauth_provider.py   #     OAuth 授权服务器 provider 实现（见 §4.4）
│   │   ├── oauth_routes.py     # ★   OAuth 元数据 + 4 个端点（**自写**，不用 SDK 的 create_auth_routes）
│   │   ├── builtin_assets.py   #     内置连接器资产的 seed（照抄 seed_agents 范式）
│   │   ├── context.py          #     McpContext（身份 + 域调用入口 + 审计）
│   │   ├── errors.py           #     HTTPException / 业务异常 → MCP tool error
│   │   ├── tool.py             #     ToolSpec 契约 + 注册辅助 + 配额包装层
│   │   └── audit.py            #     tool 调用审计落库
│   │
│   ├── skill/                  # ★ 技能·插件 域（本轮实现）
│   │   ├── __init__.py
│   │   ├── server.py           #     本域 MCP server 实例（name=testmate-skill）
│   │   ├── adapter.py          #     调 app/api/marketplace.py 的薄适配层
│   │   └── tools.py            #     14 个工具定义（schema + handler）
│   │
│   ├── software/               #   软件库域（预留：只有骨架，无工具）
│   │   └── __init__.py
│   └── kb/                     #   知识库域（预留：只有骨架，无工具）
│       └── __init__.py
│
├── api/
│   ├── marketplace.py          #   **不改动**
│   ├── mcp.py                  # ★ 新增：令牌管理 REST（/api/v1/mcp/tokens，仅 admin）
│   └── ...
├── models/mcp.py               # ★ 新增：mcp_api_tokens / mcp_tool_calls ORM
└── main.py                     #   仅改 3 处：挂载 / lifespan / 路由注册
```

> ⚠️ **命名易混淆，注意区分**：
> `app/core/mcp_config.py` = 「连接器**资产**里那段 MCP 配置的校验器」（既有代码，不动）
> `app/mcp/` = 「TestMate **自己作为 MCP server** 的实现」（本轮新增）
>
> ⚠️ `app/mcp/` 与 PyPI 的 `mcp` 包**同名但不冲突**：后端一律以 `uvicorn app.main:app` 启动
> （工作目录 = `backend_gateway/`，其下没有 `mcp/` 目录），Python 3 绝对导入下
> `from mcp.server.fastmcp import FastMCP` 仍指向 site-packages 的官方 SDK。
> ⚠️ 但**禁止**在 `backend_gateway/` 目录下新建顶层 `mcp/` 目录，也禁止把 `app/` 本身加入 `sys.path`，
> 否则 `import mcp` 会解析到 `app/mcp/` → 官方 SDK 导入失败。

### 3.2 分域 MCP：一个域一个 server

| 域 | MCP server name | 端点 | 状态 |
|---|---|---|---|
| 技能·插件 | `testmate-skill` | `POST /mcp/skill` | **本轮实现**（14 工具） |
| 软件库 | `testmate-software` | `POST /mcp/software` | 预留骨架 |
| 知识库 | `testmate-kb` | `POST /mcp/kb` | 预留骨架 |

**为什么要分域而不是一个大 server**：

- agent 只需连自己要的域 —— 连 `testmate-skill` 就只看到 14 个技能工具，不会被知识库/软件库工具淹没
- 每个域的 `instructions` 可以写自己的引导语（如「这是技能市场：先 search 再 read_doc 再 publish」）
- 域之间零耦合：新增域 = 新增 `app/mcp/<域>/` 目录 + 在 `common/server.py` 的注册表加一行
- 权限可分域授权（`market:read` / `kb:read` / `software:read`），未来可给 agent 只读某个域的令牌

**工具名仍带 `skill_` 前缀**：即使 server 已按域拆分，也保留前缀——部分 MCP 客户端会把多个 server 的工具名拍平展示，
带前缀能避免 `search` / `get` 这类通用名互相撞车，日志里也更可读。

### 3.3 装配与挂载（spike 已实测 + SDK 源码核实）

#### 3.3.1 域 server 工厂

```python
# app/mcp/common/server.py
def build_mcp(name: str, instructions: str, *, path: str,
              issuer_url: str, resource_server_url: str,
              token_verifier: TokenVerifier) -> FastMCP:
    return FastMCP(
        name=name,                       # 如 "testmate-skill"
        instructions=instructions,       # 给 agent 的引导语
        stateless_http=True,             # 无状态：不需要 session id，nginx/多副本友好
        json_response=True,              # 响应是 application/json，不走 SSE 流
        streamable_http_path=path,       # "/skill" —— 域路径（相对于 /mcp 挂载点）
        sse_path="/sse",                 # SSE 入口（相对于域挂载点）
        message_path="/messages/",       # SSE 回传地址（相对于域挂载点）
        # ⚠️ 只给 token_verifier，**绝不给 auth_server_provider** ——
        #    给了它 FastMCP 会去调 create_auth_routes()，而那个函数第一行就
        #    validate_issuer_url() → 内网 http issuer 直接 ValueError（v11 §4.3）
        auth=AuthSettings(
            issuer_url=issuer_url,                   # http://host（站点根，不带路径）
            resource_server_url=resource_server_url, # http://host/mcp/skill
            required_scopes=[],                      # scope 校验放在工具层做（域级）
        ),
        token_verifier=token_verifier,
        transport_security=TransportSecuritySettings(...),  # ⚠️ 必须显式配, 见 §3.4
    )
```

> ⚠️ **`AuthSettings` 本身不校验 HTTPS**（只有 `create_auth_routes` 里的 `validate_issuer_url` 校验），
> 所以 `issuer_url=http://10.0.0.5:8081` 在这里**完全合法**。这正是我们自写 OAuth 路由的原因（§4.3）。

#### 3.3.2 分域 dispatcher：**Route + Mount 必须并存**

```python
# app/mcp/common/server.py
def build_dispatcher(domains: dict[str, FastMCP]) -> Starlette:
    routes: list[Route | Mount] = []
    for name, mcp in domains.items():
        # ① Streamable HTTP：Route 精确匹配 "/{域}"（POST /mcp/skill）
        routes.append(Route(f"/{name}", endpoint=mcp.streamable_http_app()))
        # ② SSE：Mount 前缀匹配 "/{域}/..."（GET /mcp/skill/sse、POST /mcp/skill/messages/）
        routes.append(Mount(f"/{name}", app=mcp.sse_app()))
    return Starlette(routes=routes)
```

**为什么必须两个都有**（Starlette 路由语义，实测）：

| 挂法 | `POST /mcp/skill` | `GET /mcp/skill/sse` | `POST /mcp/skill/messages/` |
|---|---|---|---|
| 只用 `Route("/skill")` | ✅ 200 | ❌ 404 | ❌ 404 |
| 只用 `Mount("/skill")` | ❌ 404（Mount 只匹配带尾斜杠的子路径） | ✅ 200 | ✅ 200 |
| **Route + Mount（本作法）** | ✅ 200 | ✅ 200 | ✅ 200 |

> ⚠️ **不要用 `app.mount("/mcp/skill", ...)` 逐个挂**：`Mount("/mcp/skill")` 不匹配 `/mcp/skill`（无尾斜杠）
> → 客户端连 `POST /mcp/skill` 会 307/404，而不少 MCP 客户端不跟随 POST 重定向 → 必然连不上。
> 所以用「挂一次 `/mcp` + 内部按 `/域` 路由」的 dispatcher 写法。

#### 3.3.3 SSE 的 root_path：客户端回传地址由它决定

SDK `SseServerTransport.connect_sse`（`mcp/server/sse.py:170-183`）：

```python
root_path = scope.get("root_path", "")
full_message_path_for_client = root_path.rstrip("/") + self._endpoint
client_post_uri_data = f"{quote(full_message_path_for_client)}?session_id={session_id.hex}"
```

- `self._endpoint` = SSE transport 的 messages 路径（我们保持默认 `/messages/`，
  **不要给 `sse_app(mount_path=...)` 传值**，否则会被拼成 `/mcp/skill/messages/` 再叠加 root_path）
- `scope["root_path"]` 由 Starlette 的 `Mount` 自动设置 = `/mcp` + `/skill` = **`/mcp/skill`**

⇒ 客户端收到的回传地址 = `/mcp/skill` + `/messages/` = **`/mcp/skill/messages/?session_id=…`** ✅

> ⚠️ 这条**必须写集成测试**：`GET /mcp/skill/sse` 的第一帧 `event: endpoint` 的 `data`
> 必须等于 `/mcp/skill/messages/?session_id=…`。挂载路径写错 → 客户端 POST 到不存在的地址 → 永远收不到响应。

#### 3.3.4 主应用挂载（三处改动）

```python
# app/main.py
@asynccontextmanager
async def lifespan(app: FastAPI):
    ...
    async with AsyncExitStack() as stack:
        for mcp in ALL_MCPS:                       # 每个域一个
            await stack.enter_async_context(mcp.session_manager.run())
        yield
    ...

# ① MCP 端点：/mcp/{域}（streamable + sse）
app.mount("/mcp", build_dispatcher(ALL_MCPS))

# ② OAuth 元数据（RFC 8414 / RFC 9728）：在**站点根**，不在 /mcp 下
app.include_router(mcp_oauth_router)          # /.well-known/... 与 /oauth/*

# ③ 内置连接器 seed（幂等）
```

> ⚠️ `mcp.session_manager` 在 `streamable_http_app()` 被调用前访问会抛
> `RuntimeError: ... calling streamable_http_app()`。⇒ **各域 app 必须在模块加载期构建好**
> （`build_domain_apps()`），lifespan 里只负责 `run()`。

**路径推演（spike 实测）**：

| 请求 | 结果 | 说明 |
|---|---|---|
| `POST /mcp/skill` | **200** | 正确端点，无跳转 |
| `POST /mcp/skill/` | 307 | 尾斜杠会跳转 → **对外公布的 URL 必须不带尾斜杠** |
| `GET /mcp/skill/sse` | **200** | SSE 入口 |
| `POST /mcp/skill/messages/?session_id=…` | 200 | SSE 回传 |
| `POST /mcp/nope` | 404 | 未注册的域 |
| `GET /mcp/skill` | 406 | SDK 要求 `Accept: application/json, text/event-stream` |

### 3.4 DNS rebinding 防护必须显式配置（spike 实测）

FastMCP 默认 `host="127.0.0.1"` → **自动开启** DNS rebinding 防护，只放行 `127.0.0.1:*` / `localhost:*` / `[::1]:*`。
TestMate 是用 `http://10.0.0.5:8081` 这类内网地址访问的，Host 头匹配不上 → **每个请求都 421 Misdirected Request**。

```python
TransportSecuritySettings(
    enable_dns_rebinding_protection=True,
    allowed_hosts=[...],   # ⚠️ 见下方格式要求
    allowed_origins=[...],
)
```

**allowed_hosts 的格式坑**（spike 实测）：

- SDK 的 `:*` 通配**只匹配带端口的 Host**（`host.startswith(base + ":")`）
- nginx 的 `proxy_set_header Host $host;` **会丢掉端口** → 实际 Host 头是 `10.0.0.5` 而不是 `10.0.0.5:8081`
- ⇒ allowed_hosts 必须**同时**包含裸 host 与 `host:port` 两种形式

allowed_hosts 来源（按优先级合并）：

1. 新设置项 `mcp.allowed_hosts`（管理员显式填，逗号分隔）—— 主入口
2. 既有设置项 `marketplace.public_base_url` 的 host 部分 —— 平台对外地址
3. 内置兜底：`localhost:*`、`127.0.0.1:*`、`[::1]:*`

allowed_origins 同理（浏览器侧 Origin），默认留空（Origin 缺失时 SDK 放行）。

### 3.5 扩展点：域注册表

```python
# app/mcp/common/tool.py
@dataclass(frozen=True)
class ToolSpec:
    name: str                                   # 全局唯一，带域前缀
    description: str                            # 给 agent 看的说明
    input_schema: dict[str, Any]                # JSON Schema
    handler: Callable[["McpContext", dict[str, Any]], Awaitable[Any]]
    scope: str                                  # market:read / market:write / kb:read …
    read_only: bool                             # 只读标记（客户端判断 + 审计分级）
    domain: str                                 # 所属域
    annotations: dict[str, Any] | None = None   # MCP ToolAnnotations


class DomainProvider(Protocol):
    domain: str                                 # "skill" / "software" / "kb"
    server_name: str                            # "testmate-skill"
    instructions: str                           # 给 agent 的引导语
    def tools(self) -> list[ToolSpec]: ...
```

注册（`common/server.py`）：

```
PROVIDERS = [SkillProvider()]            # ← 新增一个域 = 加一行 + 写一个 app/mcp/<域>/ 目录
ALL_MCPS  = {p.domain: build_mcp(p) for p in PROVIDERS}
```

**加一个新域的完整步骤**（这是「今后扩展性」的可验证承诺）：

1. 建 `app/mcp/<新域>/` 目录（`server.py` + `tools.py` + 需要的 `adapter.py`）
2. 实现一个 provider，暴露 `tools()`
3. 在 `PROVIDERS` 列表登记一行
4. `app/mcp/common/*` 与业务代码 **零改动**

---

### 3.6 扩展点清单：以后怎么加东西

「架构规范」不是口号，是**每种扩展都有明确的落点，且不碰其它层**。下表是承诺清单：

| 想加什么 | 改哪里 | 要不要动其它层 |
|---|---|---|
| **新业务域**（知识库 / 软件库） | 新建 `app/mcp/<域>/`（server + tools + adapter）＋ `PROVIDERS` 加一行 | ❌ common 不动、业务代码不动 |
| **新业务操作**（在已有域内） | 后端端点 + 前端 UI + MCP 工具 + **契约测试加一个场景**（§4.13.3） | 漏了契约场景 → CI 红 |
| **新工具**（在已有域内） | 往该域的 `tools.py` 加一个 `ToolSpec` | ❌ 框架不动 |
| **新 scope** | 该域的 `ToolSpec.scope` + `common/scopes.py` 的枚举 | ❌ 其它域不动 |
| **新凭证类型**（服务账号 / 内部系统调用） | 在 `common/auth.py` 加一个 `CredentialVerifier` 实现，注册进 `VERIFIERS` | ❌ provider 与工具不动 |
| **新 OAuth 端点 / 新授权方式**（如设备码流） | `common/oauth_routes.py` 加路由 + `common/oauth_provider.py` 加方法 + 集成测试加一条 | ❌ 工具与业务不动 |
| **新 transport**（比如 stdio 薄壳） | `common/server.py` 的装配层加一个 app | ❌ 工具不动 |
| **一个域多个 server**（如只读子集） | dispatcher 的 `{path: app}` 加一项 | ❌ 工具不动 |
| **新内置资产**（不止 MCP 连接器） | `common/builtin_assets.py` 的清单加一项 | ❌ 其它不动 |
| **新平台设置项** | `settings_store` 的 seed 加 `mcp.*` 一项 | ❌ 其它不动 |

**分层纪律（review 时按这个查）**：

```
依赖方向（只能从上往下，不能反向）
  transport 层  (common/server.py)      ← 知道 HTTP/Starlette，不知道业务
      ↓
  协议层       (common/tool.py, errors.py, auth.py)  ← 知道 MCP，不知道业务
      ↓
  领域层       (skill/, kb/, software/)   ← 知道业务，通过 adapter 调既有 API
      ↓
  既有业务层   (api/marketplace.py …)    ← 业务逻辑不改（仅 3 处守卫）

❌ 禁止：domain 层 import fastapi 的 Request/Depends/Form
❌ 禁止：common 层 import 任何业务模块
❌ 禁止：adapter 层绕过 domain 直接写 DB
```

**三条「不变量」**（破坏了就该重写，不是补丁）：

1. **鉴权只有一处** —— 凭证解析永远在 `common/auth.py` 的 `TokenVerifier`；工具通过 `McpContext` 拿身份，**永不自己读 header**。
2. **业务只有一处** —— 技能相关的一切都走 `app/api/marketplace.py` 的既有函数；MCP 侧**不复制业务逻辑**。
3. **审计只有一处** —— 每次工具调用必定落一行 `mcp_tool_calls`，由 `common/tool.py` 的包装层统一写，工具实现自己不写审计。

---

## 4. 鉴权：OAuth 2.1 授权流（Qoder 点「授权」）

### 4.1 为什么改成 OAuth（而不是个人令牌页）

原来的设计是「用户去令牌页签发个人令牌 → 复制明文 → 手拼 mcpServers JSON → 粘进 Qoder」。
问题很实在：**门槛高（要复制带密钥的 JSON）、易泄漏、还得自己管过期与吊销**。

而 Qoder 对远程 MCP 原生支持标准流程：**点「授权」→ 浏览器打开平台 → 登录并同意 → 自动回到 Qoder**。
平台内置连接器 + OAuth 才是贴合「平台内置能力」这个定位的做法。

**结论：普通用户不需要个人令牌页**。鉴权统一走 OAuth。

> 保留一条**运维兜底**：设置页（本就 adminOnly）里仍可签发**平台接入令牌**（静态 Bearer），
> 给 CI / 脚本 / 以及 OAuth 发现失败时用。`TokenVerifier` 同时认两种凭证，
> 权限判定（scope + 用户平台能力）与审计完全共用 —— 换凭证不换能力边界。

### 4.2 数据模型

| 东西 | 存哪 | 生命周期 |
|---|---|---|
| OAuth 客户端注册表 | **新表** `mcp_oauth_clients`（DCR 动态注册产生） | 长期 |
| 授权码（authorization code） | **进程内字典** | 5 分钟、一次性 |
| **授权（grant）** | **新表** `mcp_oauth_grants` —— (user_id, client_id, scopes, revoked_at) | **长期，不过期**；可随时撤销 |
| access token | **无状态 JWT**（`JWT_SECRET` 签名，payload：`sub`=user_id / `client_id` / `scopes` / `grant_id` / `aud`）—— **不带 `exp`** | **不过期** |
| refresh token | **不发**（不过期就不需要刷新） | —— |
| 平台接入令牌（兜底） | `mcp_api_tokens` 表 | 默认**不过期**，可设期限 |

> ⚠️ **「不过期」与「可吊销」是一对**：无状态 JWT 本身吊销不了，
> 所以每次调用验签后**必须再查一次 grant**（`user_id + client_id` 唯一索引，单行查询）。
> 撤销 = 置 `revoked_at` → **下一个请求立刻失效**。这是「不过期」能成立的前提。

> 授权码放内存而非 DB/Redis：SSE 已经要求后端**单进程**（`BACKEND_WORKERS=1`），
> 进程内字典完全够用；进程重启导致授权码失效 → 用户重新点一次「同意」即可，代价可忽略。

### 4.3 OAuth 端点：**必须自写路由**（不能用 SDK 的 `create_auth_routes`）

#### 4.3.1 【致命】为什么不能用 SDK 的现成路由

SDK 的 `create_auth_routes()`（`mcp/server/auth/routes.py:84`）第一行就是：

```python
def validate_issuer_url(url: AnyHttpUrl):
    # RFC 8414 requires HTTPS, but we allow localhost HTTP for testing
    if (url.scheme != "https" and url.host != "localhost"
            and (url.host is not None and not url.host.startswith("127.0.0.1"))):
        raise ValueError("Issuer URL must be HTTPS")
```

TestMate 的对外地址是内网 `http://10.0.0.5:8081` → **装配时直接抛 ValueError，服务起不来**。

已核实的三件事：

| 事实 | 结论 |
|---|---|
| `validate_issuer_url` **只在 `create_auth_routes` 一处**被调用 | `build_metadata` / `AuthSettings` / `ProtectedResourceMetadata` **都不校验** |
| `AuthSettings.issuer_url` 是 `AnyHttpUrl` | pydantic 的 `AnyHttpUrl` **接受 http**，不强制 HTTPS |
| FastMCP 只在 `self._auth_server_provider` 非空时才调 `create_auth_routes` | **只传 `token_verifier` 就完全绕开校验** |

⇒ **两条硬约束**：

1. **绝不给 FastMCP 传 `auth_server_provider`**（传了 → FastMCP 内部调 `create_auth_routes` → 同样炸）
2. OAuth 端点由我们**自己拼路由**，复用 SDK 的 handler（`AuthorizationHandler` / `TokenHandler` /
   `MetadataHandler`）与 `build_metadata`，只**跳过 `validate_issuer_url` 这一步**

```python
# app/mcp/common/oauth_routes.py —— 抄 SDK 的 create_auth_routes，删掉 validate_issuer_url 那行
def build_auth_routes(provider, issuer_url, ...) -> list[Route]:
    metadata = build_metadata(issuer_url, ...)          # SDK 的函数，不校验 HTTPS
    client_authenticator = ClientAuthenticator(provider)
    token_handler = TokenHandler(provider, client_authenticator)
    return [
        Route("/oauth/register", endpoint=..., methods=["POST"]),
        Route("/oauth/authorize", endpoint=..., methods=["GET", "POST"]),
        Route("/oauth/token",      endpoint=..., methods=["POST"]),
        Route("/oauth/revoke",     endpoint=..., methods=["POST"]),
    ]
```

#### 4.3.2 端点表（全部自写）

| 端点 | 作用 | 实现 |
|---|---|---|
| `GET /.well-known/oauth-protected-resource/mcp/{域}` | 受保护资源元数据（RFC 9728）：告诉客户端「授权服务器是谁」 | 我们自己写（FastMCP 内部那份路由在 `/mcp` 挂载下不可达，见下注） |
| `GET /.well-known/oauth-authorization-server` | 授权服务器元数据（RFC 8414） | `build_metadata()` + 我们的调整 |
| `POST /oauth/register` | 动态客户端注册（DCR，RFC 7591） | **自写**（§4.3.3） |
| `GET\|POST /oauth/authorize` | 授权入口 → 302 到同意页 | SDK `AuthorizationHandler` + 我们的 provider |
| `POST /oauth/token` | code → access token（PKCE 校验） | SDK `TokenHandler` + 我们的 provider |
| `POST /oauth/revoke` | 吊销 | SDK `RevocationHandler`（可选启用） |

**路径选择的理由**：

- 全部 OAuth 端点放 **`/oauth/`** 下 → nginx **一个** `location /oauth/` 覆盖 4 个端点（不写 4 个 location）
- 元数据放**站点根**的 `/.well-known/…` → 符合 RFC 8414 / RFC 9728 的固定路径
- **issuer = 站点根**（`http://10.0.0.5:8081`，不带路径）→ 元数据 URL 就是
  `http://10.0.0.5:8081/.well-known/oauth-authorization-server`（**最通用、最兼容的形态**）
- 端点 URL 由 AS 元数据里的 `authorization_endpoint` / `token_endpoint` 显式给出，
  **不依赖客户端按 issuer 推导路径** → 放 `/oauth/` 完全安全

> 📌 **关于 FastMCP 内部那份 PR metadata 路由**：`resource_server_url` 一旦设置，FastMCP 会
> 在域 app 内部注册 `/.well-known/oauth-protected-resource/mcp/{域}`。但域 app 被挂在 `/mcp` 下，
> 该路由**不可达（404）**。所以我们在**站点根**自己注册权威版本；
> 集成测试断言 `GET /.well-known/oauth-protected-resource/mcp/skill` 返回 200 + 正确的 `authorization_servers`。

#### 4.3.3 DCR 的三条强制规则（自写注册处理器）

SDK 的 `RegistrationHandler` 不能直接用（它默认 `token_endpoint_auth_method="client_secret_post"`
并签发 client_secret，且**要求 `grant_types` 含 `refresh_token`**——我们不发 refresh token）。
我们**自写注册处理器**，强制三条：

| # | 规则 | 不这么做会怎样 |
|---|---|---|
| 1 | **`token_endpoint_auth_method = "none"`**（公开客户端 + PKCE），不签发 client_secret | SDK 的 `ClientAuthenticator` 对 `None` 直接抛「Unsupported auth method」；发 secret 则要求客户端保存密钥，违背 OAuth 2.1 公开客户端模型 |
| 2 | **`scope` 强制写入本服务支持的全部 scope**（`"market:read market:write"`，即使客户端没传） | SDK 的 `OAuthClientMetadata.validate_scope`：`allowed_scopes = [] if self.scope is None` → 客户端注册时没带 scope，**任何带 scope 的授权请求都会被拒**（`invalid_scope`）→ Qoder 直接授权失败 |
| 3 | **`grant_types = ["authorization_code"]`**，**不签 refresh token** | 与「授权不过期」的产品决策一致；SDK handler 强制要求含 `refresh_token`，故不能复用 |

#### 4.3.4 发现链路（Qoder 侧看到的顺序）

```
POST /mcp/skill  (无 Authorization)
  → 401 + WWW-Authenticate: Bearer error="invalid_token", resource_metadata="http://host/.well-known/oauth-protected-resource/mcp/skill"
  → GET /.well-known/oauth-protected-resource/mcp/skill
      { "resource": "http://host/mcp/skill", "authorization_servers": ["http://host"], "scopes_supported": [...] }
  → GET /.well-known/oauth-authorization-server
      { "issuer": "http://host", "authorization_endpoint": "http://host/oauth/authorize",
        "token_endpoint": "http://host/oauth/token", "registration_endpoint": "http://host/oauth/register",
        "code_challenge_methods_supported": ["S256"], ... }
  → POST /oauth/register   (DCR，带 redirect_uris=[http://127.0.0.1:xxxx/callback])
  → 浏览器 GET /oauth/authorize?...  → 我们 302 到同意页 SPA /connect/authorize?...
  → 同意 → 302 回 redirect_uri?code=…&state=…
  → POST /oauth/token  (code + code_verifier) → access_token（JWT，无 exp）
  → 之后所有 POST /mcp/skill 带 Authorization: Bearer <access_token>
```

#### 4.3.5 redirect_uri 白名单：只允许回环地址

DCR 是**客户端自己声明**回调地址，若不限制，授权码可能被送到任意外部站点（开放重定向 + 授权码泄露）。

> **规则**：DCR 时 `redirect_uris` **只允许** `http://127.0.0.1:*` 与 `http://localhost:*`；
> 其它一律 `400 invalid_redirect_uri`。
> 已登记客户端在 `/oauth/authorize` 时仍按 SDK 的 `validate_redirect_uri` **逐字比对**（防开放重定向）。

### 4.4 我们要自己写的五块（+ nginx 配置）

| # | 东西 | 位置 | 量级 |
|---|---|---|---|
| 1 | `OAuthAuthorizationServerProvider` 实现：客户端注册表读写、授权码生成/消费、PKCE S256 校验、**redirect_uri 白名单校验**、签发 access token | `app/mcp/common/oauth_provider.py` | ~320 行 |
| 2 | **OAuth 路由与元数据**（自写，绕开 SDK 的 HTTPS 校验）+ **自写 DCR 处理器**（§4.3.3 三条强制规则） | `app/mcp/common/oauth_routes.py` | ~180 行 |
| 3 | `CredentialVerifier` 协议 + 两个实现（OAuth token / 静态令牌）+ `Principal` 模型 | `app/mcp/common/auth.py` | ~120 行 |
| 4 | **同意页**（前端 SPA 路由 `/connect/authorize`） | `views/Connect/authorize.vue` | 1 个页面 |
| 5 | **「我的授权」页**（前端，撤销授权） | `views/McpGrants/index.vue` | 1 个轻量页面 |
| 6 | nginx 加 2 处 location（`/oauth/` 与 `/.well-known/oauth-`）+ 1 处 `/mcp` | `frontend_web/nginx.conf` + `deploy/native/units/nginx.conf.tpl` | ~50 行 |

#### 鉴权层的可插拔结构（扩展点，不是 if/else）

```python
# app/mcp/common/auth.py
@dataclass(frozen=True)
class Principal:
    user: User            # 绑定身份 —— 权限实时取该用户当前角色
    client_id: str        # 'oauth:<client_id>' 或 'static'
    client_name: str
    scopes: frozenset[str]
    grant_id: int | None  # OAuth 才有；静态令牌为 None


class CredentialVerifier(Protocol):
    # 一个凭证类型的验证器 —— 加新凭证类型 = 加一个实现 + 注册一行
    async def verify(self, credential: str) -> Principal | None: ...


class OAuthTokenVerifier:   # 验签 + 查 grant（确认未撤销）
class StaticTokenVerifier:  # 查 mcp_api_tokens（确认未吊销）

VERIFIERS: list[CredentialVerifier] = [OAuthTokenVerifier(), StaticTokenVerifier()]
```

> 将来加「服务账号」「内部系统调用」「临时票据」等凭证，**只加一个类 + 注册一行**，
> 工具、provider、其它层一行都不用动（§3.6 的承诺之一）。

### 4.5 同意页（取代原「个人令牌页」）

**两个 URL，别混淆**：

| URL | 谁提供 | 作用 |
|---|---|---|
| `/oauth/authorize` | **后端**（OAuth 端点） | OAuth 协议入口：校验 client / redirect_uri / scope / PKCE 参数，然后 302 到同意页 |
| `/connect/authorize` | **前端 SPA**（Vue 页面） | 用户看到的同意界面（勾 scope、同意/拒绝） |

> ⚠️ **SPA 路由为什么不能是 `/mcp/authorize`**：nginx 的 `location /mcp` 是**前缀匹配**，
> 会把 `/mcp/authorize` 劫持到后端 → 前端路由拿不到 → 404。同理不能是 `/oauth/authorize`
> （那是后端端点）。⇒ 定为 `/connect/authorize`。

```
GET /oauth/authorize?client_id=…&redirect_uri=…&code_challenge=…&state=…&scope=…
  │  （SDK 的 AuthorizationHandler 校验 client / redirect_uri / scope / PKCE 参数）
  ↓  provider.authorize() 返回一个 URL（我们返回同意页地址）
  │
  └─ 后端生成一次性 ticket → 302 到 SPA 同意页
        /connect/authorize?ticket=xxxx
        （**后端不检查登录态** —— 浏览器跳转请求没有 Authorization 头，
          登录态由 SPA 用 localStorage 里的 JWT 处理）
  ↓
同意页 /connect/authorize（Vue）
  ├─ 未登录 → 跳 TestMate 登录页（带 redirect 回跳本页）→ 登录完回到本页
  ├─ GET /api/v1/mcp/oauth/authorize-info?ticket=…（带 JWT）
  │    → { client_name, requested_scopes[], resource, redirect_uri }
  ├─ 渲染：客户端名 + scope 清单（**逐条勾选**，可选项 = 该用户的平台能力上限）
  ├─ [同意] → POST /api/v1/mcp/oauth/consent  {ticket, granted_scopes[]}
  └─ [拒绝] → POST /api/v1/mcp/oauth/consent  {ticket, deny: true}
        → 后端建授权码 → 302 回 redirect_uri?code=…&state=…
        → 拒绝则 302 回 redirect_uri?error=access_denied&state=…
```

**为什么中间要一个 ticket**：同意页是前端页面，前端传来的任何参数都不可信。
`redirect_uri` / `code_challenge` / `client_id` / `state` **全部由后端保管**（放在后端的
「待处理授权请求」缓存里，key = 随机 ticket，TTL 10 分钟，一次性），SPA 只提交
`ticket` + 用户勾选的 scope。⇒ 前端无法篡改回调地址。

> 「待处理授权请求」缓存放在**进程内内存**（与授权码同款）：SSE 已经要求后端单进程
> （`BACKEND_WORKERS=1`），内存足够；进程重启 → 用户重新点一次「同意」即可。

**安全要点**（都在我们这侧，SDK 不代劳）：

- `redirect_uri` **必须**与客户端注册时登记的值逐字比对 —— 否则就是开放重定向漏洞
- **DCR 时只允许回环 redirect_uri**（§4.3.5）
- `state` 原样回传（CSRF 防护由客户端负责，我们不能丢）
- 同意页表单自带 CSRF token
- 授权码一次性、5 分钟过期、绑定 `client_id` + `redirect_uri` + `code_challenge`
- token 端点校验 PKCE：`code_verifier` 的 S256 必须等于登记的 `code_challenge`（SDK 的 `TokenHandler` 已做）
- 用户勾选的 scope **必须**是「请求的 scope ∩ 用户平台能力上限」，越权直接拒绝

> **授权不过期**：同意页不显示有效期选项，签发的 access token **不带 `exp`**。
> 代价是「授权」变成一个长期状态 → 必须给用户一个**撤销入口**（见 §4.7「我的授权」）。

### 4.6 scope：同意时授予，写进 token

| scope | 覆盖的工具 | 能力 |
|---|---|---|
| `market:read` | 9 个只读工具 | 只读 |
| `market:write` | `skill_publish` `skill_update` `skill_edit_meta` `skill_submit_review` `skill_unpublish_request` | 上架 / 发新版本 / 只改信息 / 提交审核 / 申请下架 |

**可选项上限 = 绑定用户的平台能力**（复用 `market_policy.can_publish`，与网页一致）：
非发布者只能给 `market:read`；发布者（含默认的 tester）可给 `market:write`；admin 全部。

授予的 scope 写进 access token 的 JWT；每次工具调用从 token 里取，**不再查库**。

> 「以后都同意」（记住授权）本轮**不做**：每次授权都问一次。多一步点击，换来用户对「这个 agent 现在能干什么」有明确认知。

### 4.7 吊销模型：授权不过期，那怎么收回？

「授权不过期」是产品要求，但**长期有效的凭证必须有回收口**，否则离职/换机器/泄漏都没法补救。

**授权 = 一条 grant**（用户对某个客户端的一次授权），存 `mcp_oauth_grants`：

```sql
CREATE TABLE mcp_oauth_grants (
  id           BIGINT       NOT NULL AUTO_INCREMENT PRIMARY KEY,
  user_id      BIGINT       NOT NULL,
  client_id    VARCHAR(128) NOT NULL,
  client_name  VARCHAR(128) NOT NULL DEFAULT '',   -- 同意页上显示的名字
  scopes       JSON         NOT NULL,               -- 用户实际勾选的
  created_at   DATETIME     NOT NULL,
  last_used_at DATETIME     NULL,
  revoked_at   DATETIME     NULL                  -- 撤销 = 置这个
);
CREATE UNIQUE INDEX uk_mcp_grant ON mcp_oauth_grants (user_id, client_id);
```

**每次工具调用的校验链**（固定两查一验）：

```
① 验签 + 解析 JWT → sub(user_id) / client_id / scopes / grant_id
② 查 mcp_oauth_grants（user_id + client_id）→ 确认存在且 revoked_at IS NULL
③ 校验 scope 覆盖本次工具
```

第②步是「不过期」的安全底座：**吊销后下一个请求立刻失效**。

**「我的授权」页**（轻量，**不是令牌页**——它不发令牌，只管理已有的授权）：

- 路由 `/mcp/grants`（所有登录用户）
- 列出：客户端名 / 授权的 scope / 授权时间 / 最后使用时间 / [撤销]
- [撤销] → grant 置 `revoked_at` → 该客户端的 access token 立刻失效
- 撤销后客户端下次调用收到 401 → Qoder 重新弹「授权」→ 用户重新同意

> 这个页面是「授权管理」，不是「令牌签发」——用户不需要在这里拿到任何密钥，
> 所以与「不做个人令牌页」不冲突。恰恰相反：**没有它，「不过期」就是安全隐患**。

### 4.8 配额

agent 最危险的失败模式不是越权，而是**失控循环**。配额改挂在**用户 + 客户端**上（OAuth 之后没有「令牌记录」了）：

- 每个 access token 带 `quota`（默认 200 次/天），签发时按用户当天已用量算
- **执行位置：工具包装层**（`common/tool.py`），不在中间件 —— 中间件是 transport 级，
  超额返回 HTTP 429 会被 MCP 客户端当成「可重试的临时故障」→ **重试风暴**。
  在工具层返回 tool error `quota_exceeded`，agent 能读懂「今天超量了，别再试了」。
- **计数来源：`mcp_tool_calls` 表**（每次调用都落一行），按 `(user_id, client_id, created_at)` 索引范围计数
- 超额那次调用**也要落审计**（`ok=false, error_code=quota_exceeded`），否则计数会漂
- **两级上限**（v11 补）：
  - **客户端级**：`user + client` 维度，默认 200 次/天
  - **用户总量级**：`user` 维度，默认 1000 次/天
    —— 因为「授权不过期 + 一个用户可授权多个客户端」，只卡单客户端会被「多客户端并用」绕过。
    两级都超 → 同样返回 `quota_exceeded`（先判客户端级，再判用户级）。

### 4.9 内置连接器资产（平台内置，不可删除）

**要求**：TestMate 自己的 MCP 以「连接器」身份出现在「插件·技能·连接」市场里，
**平台内置、不能删除、不能下架、不能改坏**。

实现（照抄平台现成的 `seed_agents()` 范式）：

| 事项 | 做法 |
|---|---|
| 资产标记 | `Asset` 表新增 `is_builtin`（Integer 0/1）+ alembic 迁移 |
| seed | 新增 `app/mcp/common/builtin_assets.py`，启动时 upsert（幂等）；`created_by=NULL` 标记为 seed 行 |
| 不进 GitLab | 内置资产**只存 DB**，不进市场仓库 —— 避免与「GitLab 是真身」的模型打架 |
| 同步安全 | `market_catalog.apply_index_to_db` **只 upsert、不删库里的行**（已核实）→ 仓库同步不会把内置资产冲掉 ✓ |
| url 动态生成 | 内置资产的 `mcp_config` 里 url 是占位符 `{{BASE}}/mcp/skill`，**读的时候**用 `marketplace.public_base_url` 替换（每套部署地址不同，不能写死进 GitLab） |
| 不可删 | `DELETE /api/v1/assets/{code}` → 409「平台内置资产不可删除」 |
| 不可下架 | `unpublish_asset` / `unpublish_request` → 409 同理 |
| **url 不可改** | `update_asset` 改 `mcp_config`（含 url）→ 409「平台内置连接器的地址不可修改」 |
| **文案可改** | `summary` / `description` / `icon` / `tags` 等**普通字段允许修改**（走正常审核流）——「不可编辑」只针对 `mcp_config`（改坏 url 平台能力就废了），不是整块资产焊死 |
| 不进审核台 | `publish_status` 恒为 `published`，`pending_action` 恒空 |
| 前端 | 卡片标「平台内置」徽标；**不显示「下架/删除」按钮**；「更新」按钮保留，但表单里**连接器配置（`mcp_config`）字段只读**，只能改文案 |

### 4.10 交付链路（最终形态）

```
① 市场「插件·技能·连接」→ 连接器 tab → 「TestMate 平台能力」卡片（带「平台内置」徽标）
      └─ [复制连接器配置] → {"mcpServers":{"testmate":{"type":"http",
                                        "url":"http://<平台地址>/mcp/skill"}}}
         （没有 headers —— 鉴权交给 OAuth）
② Qoder：设置 → 连接器与 MCP → + → 粘贴 JSON 配置 → 导入
③ Qoder 探活 POST /mcp/skill → 我们回 401 + WWW-Authenticate
      → Qoder 发现授权服务器 → 显示「授权」按钮
④ 点「授权」→ 浏览器打开 http://<平台地址>/oauth/authorize?…
      → 登录 TestMate → 同意页 /connect/authorize（显示客户端名 + scope）→ [同意]
      → 302 回 Qoder → Qoder 用 code 换 access token（POST /oauth/token）
⑤ 之后所有调用带 Authorization: Bearer <access_token> → 开始用 14 个工具
```

**内置连接器资产里绝不放任何密钥**：它只是 `{url}`，鉴权全靠 OAuth 流程。

### 4.11 兜底：平台接入令牌（设置页，adminOnly）

设置页保留一个「🔌 MCP 接入」组（**admin 可见**，不是个人令牌页）：

- 签发**平台接入令牌**（静态 `tm_live_*`）：给 CI / 脚本 / 内部系统调用；**默认不过期**（可设期限）
- 配置 `mcp.allowed_hosts`（防 DNS rebinding，见 §3.4）
- 开关「是否允许 OAuth 自助授权」—— 关闭后只有管理员能签发令牌（内网收紧用）

普通用户看不到这一组，也不需要令牌 —— 他们在 Qoder 点「授权」就行。

### 4.12 MCP 写操作契约：与前端同链路、同校验、不替用户做主

> 这是本设计里**最容易做歪**的一节。MCP 是另一条入口，但它必须让 agent 走出
> **和人在网页上完全一样的流程**——同样的合法性检查、同样的审核、同样的通知。

#### 4.12.1 流程对齐：MCP 只做「触发」，不重写流程

**原则**：MCP 的写工具**不实现任何状态机、通知或审核逻辑**，它只做三件事：
① 收集参数 → ② 校验 → ③ 调**既有的 REST 端点**。
之后的落盘、git commit、审核流转、钉钉通知，全部由既有的后端逻辑完成。

| MCP 工具 | 前端页面上对应哪一步 | 调的既有端点 | 之后的既有流程 | 通知（既有逻辑，不重写） |
|---|---|---|---|---|
| `skill_publish` | 「上传新资产」 | `POST /assets/upload` | 落盘 → git commit → 审核 | `pending_action=new` → **通知管理员审核** |
| `skill_update` | 「发新版本」（带包） | `PUT /assets/{code}` | 落盘 → git commit → 审核 | `pending_action=update` → **通知管理员审核** |
| `skill_edit_meta` | 「编辑信息」（只改简介/说明，**不动包**） | `PATCH /assets/{code}` | 审核 | `pending_action=meta` → 通知管理员审核；⚠️ **审核通过后不通知市场群**（包没变，发那条是假消息） |
| `skill_submit_review` | 「重新提交审核」（被驳回后） | `POST /assets/{code}/submit` | 状态机 | 通知审核 |
| `skill_unpublish_request` | 「下架」（填 code 确认） | `POST /assets/{code}/unpublish`（`confirm_code` 必填） | 审核开关**开** → 申请制（`unpublish_pending`）→ 管理员确认后**彻底删除**<br>审核开关**关** → 自助下架（文件保留，可重新上架） | 下架通知；管理员确认走「通过下架」通知 |
| ——（**人工在网页审核台**） | 审核台 | `POST /assets/{code}/review` | 通过 → 在架 | **通知市场群**（`pending_action=meta` 时不通知） |
| ——（**人工在网页审核台**） | 下架审核 | `POST /assets/{code}/unpublish-review` | 通过 → 彻底删除 | 通过下架通知 |

**所以 MCP 侧不需要审核工具**（D7）：审核是人工动作，agent 不该自己盖章。
MCP 上架一次 = 走完「提交 → 待审核 → 人工审核 → 通知市场群」整条链，
其中只有第一步是 agent 做的。

#### 4.12.2 合法性检查：与前端表单同口径

前端的必填/格式规则写在 `frontend_web/src/views/Capability/Catalog/assetForm.ts` + `useAssetUploadForm.ts`（TS）。
MCP 在后端，**不能直接复用 TS**，所以在后端补一份**权威实现**（新文件，不动既有代码）：

```
backend_gateway/app/core/market_rules.py     ← 新增：上架/更新前的合法性规则（单一真源）
```

它复用后端已有校验，并补齐前端特有的一条：

| 检查项 | 规则 | 复用的后端能力 |
|---|---|---|
| 必填 | `code` / `name` / `summary` / `version`；技能还要有包（或 MCP 要有配置） | — |
| **code 格式** | `dml-` 前缀 + 小写字母/数字/连字符分段（**仅新建时**要求前缀，与前端一致） | `market_catalog.CODE_RE`（后端**不**强制前缀）+ 前端同款前缀规则 |
| **包名 = code** | 上传的包文件名必须等于 code | `market_naming.check_package_consistency`（前端 `validatePackageName` 的后端孪生） |
| **version** | semver（可带 `-beta`） | `market_catalog.validate_version` |
| **分类** | 必须在分类表里，自填的一律归「其它」 | `market_categories.is_valid` / `normalize` |
| **项目** | 必须在项目列表里，否则归「通用」 | `market_projects.normalize` |
| **包结构体检** | 有 `SKILL.md` / 无路径穿越 / 后缀白名单 / 无敏感文件 | **直接调既有 `POST /assets/preview-package`**（前端上架前用的就是它 —— 同一路径 = 同一结论） |

> ⚠️ **MCP 侧比网页更严是故意的**：网页有前端兜底，MCP 没有前端，
> agent 可能从任何地方拼参数。后端是**最终关卡**，必须自己把住。
> 代价：**过渡期**多一份 `market_rules.py` 与前端 TS 规则平行。
> **S5.5 收敛**（在 P0 范围内）：把规则做成 `GET /api/v1/assets/rules`，前端改为拉取 → 单一真源，
> 平行状态只存在于 S5 与 S5.5 之间（§4.13.2 L1）。

#### 4.12.3 「不猜」协议：agent 不能替用户做决定

用户的要求：**有选择就让用户确认才进行，包含可选的也是需要用户确认。**
落到工具行为上就是一条铁律：

> **MCP 的写工具不做任何「默认值兜底决策」。**
> 凡是需要人拍板的地方（必填缺失、有多个候选、可选项未确认），工具**拒绝执行**，
> 返回结构化的「需要确认」信息，由 agent 回问用户，拿到答复后再带参调用。

| 情形 | 工具行为 |
|---|---|
| 必填字段缺失 | **不执行** → 返回 `missing_fields`（字段名 + 一句话说明 + 该填什么） |
| 分类/项目不在枚举里 | **不执行** → 返回 `valid_values`（枚举清单） |
| 有多个合理候选（如 category 有 5 个、icon 有多个） | **不执行** → 返回 `choices`（候选项 + 各自含义） |
| **可选字段**（`use_when` / `not_for` / `tags` / `keywords` / `permissions` / `install_steps` / `featured` / `icon` / `project`）调用方没给 | **不执行** → 返回 `optional_fields`（列出这些可选项 + 说明「留空 vs 填了会影响什么」），让用户确认要不要填、填什么 |
| 校验不通过（code 非法、包名不符、版本号非法…） | **不执行** → 返回逐条问题清单 |

返回体：

```jsonc
{
  "ok": false,
  "needs_confirmation": {
    "missing_fields":  [{"field": "summary", "hint": "一句话简介 —— 会在市场卡片和钉钉通知里显示"}],
    "choices":        {"category": ["质量保障", "效率工具", "流程规范", "管理协同", "其他"]},
    "optional_fields":[{"field": "use_when", "hint": "什么场景该用它（留空则市场页不显示这一栏）"},
                       {"field": "not_for",  "hint": "什么场景别用它（写清楚能避免误用）"}],
    "problems":       ["包名 xxx.zip 与资产 code yyy 不一致 —— 平台要求两者相同"]
  }
}
```

**能不能直接弹窗问用户？** MCP 规范有 **elicitation**（`ctx.elicit()`），客户端支持时可以直接在工具里弹表单。
但 elicitation 需要较新的客户端（Qoder 未必支持），所以：

- **优先**：`ctx.elicit()`（客户端支持 → 用户当场选）
- **降级**：返回上面的 `needs_confirmation` payload → agent 回问 → 再调用

两种方式都遵守同一条铁律：**不猜**。

#### 4.12.4 由此带来的工具清单变化

多一个 **`skill_edit_meta`**（只改信息）。理由不是凑数，而是**两条流程的审核后行为不同**：

| | `skill_update`（发新版本，带包） | `skill_edit_meta`（只改信息） |
|---|---|---|
| 端点 | `PUT /assets/{code}` | `PATCH /assets/{code}` |
| `pending_action` | `update` | `meta` |
| 审核通过后 | **通知市场群** | **不通知市场群**（包没变） |

合成一个工具会让 agent 不知道自己踩的是哪条流程，agent 和人都容易误判 → 分开。

---

### 4.13 一致性机制：让「REST 与 MCP 走同一条流程」可验证、不靠自觉

> 需求原话：「确保一致性，后续新增功能也能同步，维护也方便，修改也不容易出错」。
> 答案不是「写文档提醒大家」，而是**把一致性变成会红的测试**。

#### 4.13.1 先看清：现在有哪三处会漂移

| # | 漂移点 | 现状 | 后果 |
|---|---|---|---|
| ① | **校验规则两份** | 前端 `assetForm.ts` 硬编码 `CODE_PATTERN` / `SEGMENT_PATTERN` / `PACKAGE_EXT_RE`，`useAssetUploadForm.ts` 里还有一份 `missing` 必填清单；MCP 侧要在 Python 里另写一份 | 前端改了后端没改 → agent 能提交前端不让提交的东西 |
| ② | **adapter 与端点脱节** | MCP adapter 手写参数列表去调路由函数 | 端点加了必填字段，adapter 漏传 → 400，且**报错对 agent 毫无指导性** |
| ③ | **新增能力只改一半** | 加一个业务操作要动：后端端点 + 前端 UI + MCP 工具 | 漏一处 → 网页有、MCP 没有（或反之），用户觉得「平台有两套」 |

而**状态机与通知这一块天然一致**（§4.12.1）——因为 MCP 调的就是同一个端点。
所以一致性机制只需解决 ①②③。

#### 4.13.2 三层防线

**L1 · 规则单一真源（解决 ①）**

```
app/core/market_rules.py          ← 唯一真源（Python）
        │
        ├── MCP 直接 import（同进程，零成本、零漂移）
        │
        └── GET /api/v1/assets/rules   ← 前端从接口取，不再硬编码
```

规则包里有什么：

| 键 | 内容 | 谁在用 |
|---|---|---|
| `code_pattern` / `segment_pattern` | code 的两条正则（新建要前缀 / 存量不要求） | 前端表单校验、MCP 校验 |
| `required_fields` | 按操作分的必填清单：`create` / `update` / `edit_meta` | 前端 `missing`、MCP 校验 |
| `package_ext` | 允许的包扩展名 | 前端、MCP |
| `categories` / `projects` | 枚举（本来就来自后端，顺手一起发） | 前端、MCP |
| `enforcement` | 每条规则**谁负责把关**（见下） | 排查用 |

**「约定」与「技术限制」分两档**（前端注释里已经写得很清楚，MCP 必须沿用同一口径）：

| 档 | 例子 | 前端 | MCP | REST 端点 |
|---|---|---|---|---|
| **技术合法性** | code 分段合法、version 是 semver、分类在表里、包名 = code | ✅ 卡 | ✅ 卡 | ✅ 卡（既有逻辑） |
| **团队约定** | 新建 code 必须 `dml-` 前缀 | ✅ 卡 | ✅ 卡 | ⚠️ **暂不卡**（保持向后兼容：存量 14 个资产没前缀，强卡会锁死它们的更新） |

> 「团队约定」这一档 REST 端点故意保持宽松 —— 这是**有意的兼容取舍**，不是遗漏。
> `enforcement` 字段把这个取舍显式写出来，避免以后有人以为是 bug。

**L2 · 契约测试（解决 ②③，也是「一致性」的可执行定义）**

核心思路：**同一个场景，分别从 REST 和 MCP 各走一遍，断言两者产出完全一致。**

```python
# backend_gateway/tests/test_mcp_contract.py
Scenario(
    name="上架新技能",
    rest=lambda c: c.post("/api/v1/assets/upload", data=NEW_SKILL),
    mcp =lambda c: c.call_tool("skill_publish", NEW_SKILL_ARGS),
    expect={"publish_status": "pending", "pending_action": "new"},
    expect_notify=["review"],          # 钉钉事件序列
)

@pytest.mark.parametrize("sc", SCENARIOS, ids=lambda s: s.name)
async def test_rest_and_mcp_identical(sc, db, notify_spy):
    rest = await run_via_rest(sc, db, notify_spy)
    mcp  = await run_via_mcp(sc, db, notify_spy)
    assert mcp.db_state == rest.db_state             # ① DB 落库状态一致
    assert mcp.notifications == rest.notifications   # ② 钉钉通知事件序列一致
    assert mcp.result == rest.result                  # ③ 返回值一致（字段裁剪后）
```

场景表覆盖 §4.12.1 的每一条：上架 / 发新版本 / 只改信息 / 重新提交 / 下架申请 / 人工审核通过 / 人工审核下架确认。

- **钉钉通知用 spy 捕获**（mock `market_notify.notify_asset`，记事件名 + actor + detail）
  —— 通知是「流程一致」最直接的证据：REST 触发了 `review`、MCP 也必须触发 `review`，
  且 `pending_action=meta` 时两边都**不能**发市场群通知。
- 这条测试红 = 一致性破了。**这是整个一致性机制的核心资产。**
- **契约测试不跑浏览器授权流程**（v11 明确）：测试用「**预置 grant + 直接签发 access token**」
  构造身份（一个 fixture：建 user → 建 grant → 用 provider 签 token），
  OAuth 的浏览器流程由 §11.2 的**专门集成测试**覆盖。理由：契约测试要跑 **8 场景 × 2 条路径 × 多次**，
  每次都拉浏览器会让测试慢到不可用，且失败时不好定位。

**L3 · 参数契约反射检查（解决 ②，防「漏传字段」）**

```python
# backend_gateway/tests/test_mcp_adapter_params.py
@pytest.mark.parametrize("tool,route", TOOL_ROUTE_MAP)
def test_adapter_covers_route_params(tool, route):
    # MCP 工具必须覆盖端点的全部必填参数 —— 漏一个就是不一致
    required = {p.name for p in inspect.signature(route).parameters.values()
                if p.default is inspect.Parameter.empty}
    assert required <= set(inspect.signature(tool).parameters), \
        f"{tool} 漏了端点 {route.__name__} 的必填参数"
```

**新增一个 Form 字段忘了在 adapter 传 → 这条测试立刻红**，而不是等 agent 在生产上报 400。

#### 4.13.3 新增一个业务能力时的动作清单

| 步 | 做什么 | 漏了会怎样 |
|---|---|---|
| ① | 后端加端点（业务逻辑写在既有模块里） | — |
| ② | 前端加 UI（规则从 `/assets/rules` 拿，不硬编码） | 前端与 MCP 规则漂移 |
| ③ | MCP 加工具（adapter 调该端点，参数一一对应） | 契约测试红 |
| ④ | **契约测试加一个场景** | ← **这一步漏了，后面全漏** |

> ④ 是关键：**每个新能力都必须有一个「REST vs MCP」的场景用例**。
> 场景表就是那张「能力登记表」—— 代码即文档，不另写文档（避免文档和代码各说各话）。

#### 4.13.4 这套机制的成本

| 成本项 | 量级 | 一次性? |
|---|---|---|
| `app/core/market_rules.py` | ~120 行 | 一次性 |
| `GET /api/v1/assets/rules` | ~15 行（只读端点，不改任何现有函数体） | 一次性 |
| 前端 `assetForm.ts` / `useAssetUploadForm.ts` 改为拉规则 | ~40 行（替换硬编码常量与 `missing` 清单） | 一次性 |
| 契约测试（8 个场景 × 2 条路径） | ~250 行 | 一次性，但**每加一个能力就加一个场景** |
| 参数反射检查 | ~50 行 | 一次性 |

> ⚠️ 唯一会让人不适的地方：**前端要改**（把硬编码规则换成拉接口）。
> 这是「规则单一真源」的必要代价，也是唯一一次性的结构收敛 ——
> 做完之后，规则永远只有一份，以后加能力不会再有「两份规则要不要同步」的问题。

---

## 5. 工具清单（v1 = 技能·插件域，14 个 = 9 读 + 5 写）

全部挂在 `testmate-skill` server（端点 `/mcp/skill`）下，作用于 `kind=skill`。
插件（`kind=plugin`）与连接器（`kind=mcp`）走同一批底层能力，后续加 `plugin_*` / `connector_*` 前缀即可复用。

### 5.1 读工具（scope: `market:read`，`read_only=true`）

| 工具 | 入参 | 出参 | 说明 |
|---|---|---|---|
| `skill_search` | `keyword?` `category?` `project?` `tag?` `author?` `include_unpublished?` `page?` `page_size?` | `{items:[{code,name,version,summary,category,project,author,publish_status,download_count}], total, page, page_size}` | 搜索技能。默认只返回 `published`；`include_unpublished=true` **仅对作者本人/管理员/审核人生效**，其他调用者的该参数被忽略（不可探测未上架资产）。分页默认 `page=1, page_size=20`，上限 100 |
| `skill_get` | `code` | manifest 全字段 + `install_steps` / `permissions` / `bindings` / `git_web_url` / `can_review` | 技能详情。对调用者不可见的资产（未上架且非作者/非审核人）返回 `not_found`，不泄露存在性 |
| `skill_read_doc` | `code` | `{file, content}` | 读 `SKILL.md`（技能展示文档）——agent 真正要的东西 |
| `skill_read_file` | `code` `path` | `{path, content, size}` | 读包内文本文件；后缀白名单同 `market_catalog.ALLOWED_SUFFIXES`；路径越界拒绝 |
| `skill_list_files` | `code` | `{files:[{path, size}]}` | 包内文件树 |
| `skill_package_info` | `code` `version?` | `{version, size_bytes, sha256, download_url, expires_at}` | 下载链接 + 校验值。`download_url` 带**短时票据**（新增票据类型 `asset-dl`，绑定 `code`+`version`，TTL 600s，与软件库 `sw-dl` 同机制），票据免登录即可换取包字节；未上架资产不出票据 |
| `skill_categories` | — | `[{name, slug, order, desc}]` | 合法分类枚举（agent 填表用） |
| `skill_projects` | — | `[str]` | 合法项目枚举 |
| `skill_job_status` | `job_id` | `{id, action, status, error, commit_sha, created_at, updated_at}` | 上架/更新任务状态（git push 结果） |

### 5.2 写工具（scope: `market:write`，`read_only=false`，5 个）

| 工具 | 入参 | 出参 | 说明 |
|---|---|---|---|
| `skill_publish` | `code` `name` `version` `summary` `description?` `use_when?` `not_for?` `category?` `project?` `icon?` `tags?` `keywords?` `permissions?` `install_steps?` `bindings?` `files?` `package_base64?` | `{job_id, status, code}` | 上架新技能。`files`（路径→文本内容映射）与 `package_base64`（zip 的 base64）二选一，都不给则 `invalid_argument`。base64 包按 `{code}.zip` 还原（命名契约要求包名与 `code` 一致，`market_naming.check_package_consistency` 会校验） |
| `skill_update` | `code` + 上述任意字段（**均可省略**）+ `files?` / `package_base64?` | `{job_id, status, code}` | 发新版本（**带包**）。**字段省略 = 保持现状**（读当前 DB 资产值合并，read-modify-write）；`version` 省略时自动 patch 当前版本末位（`x.y.z → x.y.(z+1)`），给了则必须与当前版本不同。给了 `files`/`package_base64` = **整体替换**包内容（不是增量合并），未给 = 包内容不变 → ⚠️ 未给包时**不算发新版本**，应当改用 `skill_edit_meta` |
| `skill_edit_meta` | `code` + `name?` `summary?` `description?` `use_when?` `not_for?` `category?` `project?` `icon?` `tags?` `keywords?` | `{job_id, status, code}` | **只改信息，不动包** → 审核后**不通知市场群**（`pending_action=meta`）。与 `skill_update` 分开是因为两条流程的审核后行为不同（§4.12.4）。⚠️ **不含 `featured`** —— 既有的 `AssetMetaUpdateIn`（`app/schemas/asset.py`）里没有这个字段，传了也传不进去 |
| `skill_submit_review` | `code` | `{code, publish_status, pending_action}` | 提交审核 |
| `skill_unpublish_request` | `code` `reason?` | `{code, publish_status}` | 申请下架（转 `unpublish_pending`，由管理员在网页确认；确认后资产才被彻底删除） |

### 5.3 三个刻意的取舍

1. **不提供硬删工具**：平台的删除语义是「下架审核通过 → 彻底删除资产」，属于人工运营动作。
   agent 要下架只能走 `skill_unpublish_request`，需管理员确认。
2. **不提供审核工具，上架后走人工网页审核台**：`skill_publish` / `skill_update` 内部调用与网页**同一个**
   `_review_required` 判断逻辑 —— 非 admin 令牌上架后落在 `publish_status=pending` + `pending_action=new|update`，
   由**人工在网页审核台**点通过才上架。MCP 侧**不提供 approve/reject 工具**：审核是人工运营动作，
   agent 不该自己给自己盖章。agent 仍可用 `skill_submit_review` 把**被驳回的**资产重新提交审核。
   （admin 令牌在 `marketplace.review.admin_self_approve=true`（默认）时上传即上架——这是平台既有口径，MCP 不改。）
3. **zip 字节不进 tool 返回**：包体可能有 MB 级，塞进 JSON-RPC 响应会撑爆上下文。
   `skill_package_info` 给 URL + sha256，agent 自取；文本内容走 `skill_read_file`。
4. **写操作与前端同链路、且不替用户做主**：MCP 的写工具只做「收集 → 校验 → 调既有端点」，
   状态机/审核/通知全部复用既有逻辑（§4.12）；必填缺失、有歧义、可选项未确认时**拒绝执行**，
   返回 `needs_confirmation` 让 agent 回问用户 —— **不许猜**。

### 5.4 结果形态

```jsonc
// 成功
{"ok": true, "data": { ... }}
// 失败 → MCP tool error (isError=true)
{"error": {"code": "not_found", "message": "技能 xxx 不存在", "hint": "先用 skill_search 查一下 code"}}
```

**MCP 错误码全集**（`common/errors.py` 负责产出）：

| code | 触发场景 | 出口 |
|---|---|---|
| `not_found` | 资产不存在 / 对当前调用者不可见 | tool error |
| `permission_denied` | scope 不足；或绑定用户没有该操作权限（发布者白名单、资产归属） | tool error |
| `conflict` | 状态机不允许（如已上架再提交审核、code 已存在） | tool error |
| `invalid_argument` | 参数不合法（分类/项目/版本号/包名与 code 不一致…） | tool error |
| `bad_request` | 其它 400（如连接器类资产没有安装包） | tool error |
| `upstream_failed` | GitLab / RAGFlow 等外部依赖失败 | tool error（附「查 skill_job_status」） |
| `quota_exceeded` | 令牌当日调用数超 `daily_quota` | tool error（**不是** HTTP 429，避免客户端重试风暴） |
| `token_expired` | 令牌已过期 | HTTP 401 |
| `token_revoked` | 令牌已吊销 | HTTP 401 |
| `unauthorized` | 无 token / token 不存在 / 签名不匹配 | HTTP 401 |

---

## 6. 对现有代码的最小改动（本方案与 v1 的核心分歧）

### 6.1 结论：业务逻辑零改动（只有 3 处守卫 + 1 个只读端点）

v1 方案主张把 `marketplace.py` 的业务逻辑抽到 `app/domain/market.py`（REST 与 MCP 共用）。
**v2 放弃这个做法**，改为：

> `app/api/marketplace.py` **不动任何业务逻辑**。MCP 侧新增 `app/mcp/skill/adapter.py`，
> 由它调用**现有的路由函数**，把 HTTP 形状的参数翻译成 MCP 工具的入参。

**v11 修正一处「零改动」的夸大**：§4.9 要求「内置连接器不可删 / 不可下架 / 不可改 url」，
这是**服务端必须拦**的规则（前端隐藏按钮只是体验，不是防线）→ 必须动 3 个既有函数。
但改动是**纯守卫**，不碰任何业务分支：

```python
# app/api/marketplace.py —— 仅这 3 个函数顶部各加 2 行（共约 9 行）
if asset.is_builtin:
    raise HTTPException(status_code=409, detail="平台内置资产不可删除")   # delete_asset
    raise HTTPException(status_code=409, detail="平台内置资产不可下架")   # unpublish_asset / unpublish_request
    raise HTTPException(status_code=409, detail="平台内置连接器的地址不可修改")  # update_asset（仅当改了 mcp_config）
```

除此之外 `marketplace.py` **一行不动**，且**不新增 import**（`is_builtin` 是模型自带字段）。

### 6.2 为什么这个更合理

| 维度 | v1（抽 domain 层） | **v2（零改动 + 适配层）** |
|---|---|---|
| 回归风险 | 高 —— 要搬 3005 行生产代码，虽有 40+ 测试兜底，仍是最大风险源 | **零** —— 现有代码一行不动，现有测试必然全绿 |
| 交付节奏 | 必须先完成重构才能做 MCP（串行） | MCP 可独立落地（重构变成可选优化） |
| 语义一致性 | 最强（同一份函数） | **同样强**（MCP 调的就是网页在调的同一个函数，不是复制品） |
| 架构整洁度 | 边界最干净 | 有一处 HTTP 形状耦合，**集中在 adapter.py 一个文件里** |
| 未来演进 | 已到位 | 需要时可**平滑下沉**成 service 层：REST 与 MCP 同时改为调用它，是自然演进而非重写 |

关键认知：**MCP 调现有路由函数，不是「复制一份业务逻辑」**。语义一致性不打折。

### 6.3 适配层要处理的具体细节（已逐个核对函数签名）

| 细节 | 现状 | adapter 的处理 |
|---|---|---|
| 参数形状 | 路由用 `Form(...)` / `Query(...)` 默认值 | 直接调用时**必须显式传全部参数**（默认值是 `Form` 对象不是值），adapter 内逐个补齐 |
| 用户参数名不一致 | `submit_for_review` / `list_projects` 的参数名是 **`_user`**（下划线前缀） | adapter 按关键字传 `_user=...`；**在代码里写注释说明原因**，免得后人以为是笔误 |
| 错误类型 | 路由抛 `HTTPException(status_code, detail)` | adapter 捕获 → 按 status 映射成 MCP error code（400→bad_request / 403→permission_denied / 404→not_found / 409→conflict / 422→invalid_argument / 5xx→upstream_failed） |
| 上传包 | 路由要 `UploadFile` | adapter 用 `UploadFile(file=BytesIO(data), filename=f"{code}.zip")` 构造 |
| 多文件上传 | 路由要 `list[UploadFile]` | adapter 逐个构造 |
| 下载 | 路由返回 `Response`（bytes + `X-Content-Sha256` 头） | adapter 取 `response.body` 与响应头，不让 bytes 进 tool 返回 |
| 审核 | `review_asset(code, decision="approve"|"reject", comment)` | **本轮不做**（D7：审核由人工在网页审核台完成，MCP 不提供 approve/reject 工具） |
| 下架 | `unpublish_asset(code, confirm_code, comment)` | MCP 工具**必须**回填 `confirm_code=code`（这是平台既有的防误操作契约，MCP 不能绕过） |
| 返回值 | Pydantic 模型（`AssetOut` / `AssetJobOut` …） | `model_dump(mode="json")` 后裁剪字段，避免把内部字段（如 `git_path`）泄给 agent |
| 权限 | 依赖注入 `Depends(require_publisher)` 等 | adapter **显式传入**已解析的用户 → 依赖注入的检查在函数体内仍会执行 |

### 6.4 实际要改的既有文件（后端业务文件合计 < 40 行）

| 文件 | 改动 |
|---|---|
| `app/main.py` | 挂载 dispatcher + lifespan 里跑各域 session manager + 挂 OAuth 路由（`/oauth/*` 与 `/.well-known/*`）+ 注册 `/api/v1/mcp` 路由 + seed 内置连接器（约 30 行） |
| `app/models/__init__.py` | 导出新模型（1 行） |
| `app/models/asset.py` | 加 `is_builtin` 字段（1 行 + 迁移） |
| `app/core/market_rules.py` | **新文件**：上架/更新前的合法性规则（复用既有校验，不改既有模块） |
| `app/api/marketplace.py` | **+1 个只读端点** `GET /assets/rules` + **3 处内置资产守卫**（约 9 行，不动业务逻辑，见 §6.1） |
| 前端 `Catalog/assetForm.ts` / `useAssetUploadForm.ts` | 硬编码正则与必填清单 → 改为从 `/assets/rules` 拉（§4.13.2 L1） |
| `requirements.txt` / `requirements.lock` | 加 `mcp==1.29.1` 及 4 个传递依赖 |
| `frontend_web/nginx.conf` | 加 **3 处** location：`/mcp`、`/oauth/`、`/.well-known/oauth-`（约 40 行） |
| `deploy/native/units/nginx.conf.tpl` | 同上（裸机模板） |
| 前端 | 新增 `views/Connect/authorize.vue`（同意页，SPA 路由 `/connect/authorize`）+ `views/McpGrants/index.vue`（我的授权）+ `api/mcp.ts`（新文件）；改 `router/index.ts`（加路由）、`views/Capability/Catalog/index.vue` 与 `AssetCard.vue`（内置资产徽标 + 隐藏下架/删除 + 配置只读）、`views/Settings/index.vue`（admin 管理组） |

**其余全部是新增文件**：`app/mcp/**`、`app/api/mcp.py`、`app/models/mcp.py`、alembic 迁移、测试。

### 6.5 什么时候才值得抽 domain 层

等 MCP 稳定运行一段时间后，如果出现下列信号再考虑下沉：

- 同一段业务逻辑在 REST / MCP / 定时任务三处出现**第三份**实现
- REST API 的 Form 结构频繁变动，导致 adapter 反复改
- 需要让**非 HTTP** 的调用方（CLI worker）复用业务能力

到那时把 `marketplace.py` 的相关函数平移到 `app/domain/market.py`，REST 路由与 MCP adapter 同时改为调用它，
是一次**机械搬移**（不是重写），且有测试兜底。

---

## 7. 数据流

```
Qoder
 │  ① POST /mcp/skill   (无 Authorization)
 ▼
SDK 的 RequireAuthMiddleware ── 没 token ──▶ 401 + WWW-Authenticate: Bearer resource_metadata="…"
 │                                （SDK 自动带，URL 由 auth.resource_server_url 推导）
 ▼
Qoder ② GET /.well-known/oauth-protected-resource/mcp/skill  → 我们在**站点根**提供
 ▼
Qoder ③ GET /.well-known/oauth-authorization-server  → 拿到 issuer / authorize / token / register
 ▼
Qoder ④ POST /oauth/register  (DCR：redirect_uris=[http://127.0.0.1:*/cb])
 ▼
Qoder 显示「授权」按钮 → 浏览器打开
 │  ⑤ GET /oauth/authorize?client_id=…&code_challenge=…&state=…&scope=…
 ▼
后端校验登录态 → 302 到同意页 /connect/authorize?ticket=…
 ▼
同意页（Vue）── 登录 TestMate → 勾 scope → [同意] → POST /api/v1/mcp/oauth/consent
 ▼
后端建授权码 → 302 回 redirect_uri?code=…&state=…
 ▼
Qoder ⑥ POST /oauth/token  (code + PKCE verifier) ──▶ 换到 access token（JWT，无 exp）
 ▼
Qoder ⑦ POST /mcp/skill   Authorization: Bearer <access_token>
 ▼
dispatcher (/mcp → /skill) ──▶ FastMCP JSON-RPC: initialize → tools/list → tools/call
 ▼
tool handler (app/mcp/skill/tools.py)
 │  取 Principal（来自 token 的 sub/scopes）→ 校验 scope → 组装 McpContext
 ▼
adapter (app/mcp/skill/adapter.py)
 ▼
app/api/marketplace.py 的现有路由函数（**业务逻辑未改**）
 ▼
Asset 模型 + git 工作区 + GitLab（真身）
 ▼
返回值 → adapter 裁剪 → MCP tool result（JSON）
```

失败路径：`HTTPException` → `common/errors.py` → MCP tool error（isError=true）→ 记 `mcp_tool_calls`。

---

## 8. 审计

| 落点 | 记什么 | 用途 |
|---|---|---|
| `asset_audits`（既有） | 上架/更新/审核/下架等业务动作，`actor` = 绑定用户 | 谁动了哪个资产（**既有逻辑，无需改动**） |
| `mcp_tool_calls`（新增） | `user_id` / `client_id` / `client_name` / `tool` / 入参摘要 / `ok` / `error_code` / `duration_ms` / `created_at` | 排查 agent 行为、配额、异常调用 |

```sql
CREATE TABLE mcp_tool_calls (
  id          BIGINT      NOT NULL AUTO_INCREMENT PRIMARY KEY,
  user_id     BIGINT      NOT NULL,     -- 授权人（token 的 sub）
  client_id   VARCHAR(128) NOT NULL DEFAULT '',   -- OAuth 客户端；静态令牌走 'static'
  client_name VARCHAR(128) NOT NULL DEFAULT '',   -- 客户端名，审计时人看得懂
  tool        VARCHAR(64) NOT NULL,
  domain      VARCHAR(32) NOT NULL,
  args_summary TEXT       NOT NULL,     -- 截断到 2KB，不落全文
  ok          TINYINT     NOT NULL,
  error_code  VARCHAR(32) NOT NULL DEFAULT '',
  duration_ms INT         NOT NULL DEFAULT 0,
  created_at  DATETIME    NOT NULL
);
CREATE INDEX ix_mcp_calls_user ON mcp_tool_calls (user_id, client_id, created_at);
```

---

## 9. 数据库变更

| 迁移 | 内容 |
|---|---|
| `0030_add_mcp_api_tokens.py` | `mcp_api_tokens` 表 + 索引（**平台接入令牌**，adminOnly，无个人令牌页） |
| `0031_add_mcp_tool_calls.py` | `mcp_tool_calls` 表 + 索引（审计 + 配额计数） |
| `0032_add_mcp_oauth_clients.py` | `mcp_oauth_clients` 表 + 索引（DCR 客户端注册表） |
| `0033_add_asset_is_builtin.py` | `assets.is_builtin` 字段 + 索引 |
| `0034_add_mcp_oauth_grants.py` | `mcp_oauth_grants` 表 + 唯一索引（授权：不过期，可撤销） |

ORM 模型放 `app/models/mcp.py`（新文件），随 `app/models/__init__.py` 导出。

`mcp_oauth_clients` 结构：

```sql
CREATE TABLE mcp_oauth_clients (
  id             BIGINT       NOT NULL AUTO_INCREMENT PRIMARY KEY,
  client_id      VARCHAR(128) NOT NULL,      -- DCR 下发的 client_id
  client_secret_hash CHAR(64) NULL,          -- 公开客户端可为空 (PKCE)
  client_name    VARCHAR(128) NOT NULL DEFAULT '',   -- 同意页上显示给用户看的名字
  redirect_uris  JSON         NOT NULL,      -- 登记的回调地址 —— **redirect_uri 必须逐字比对**
  created_at     DATETIME     NOT NULL,
  last_used_at   DATETIME     NULL
);
CREATE UNIQUE INDEX uk_mcp_oauth_client ON mcp_oauth_clients (client_id);
```

---

## 10. 部署与分发

### 10.1 依赖

`requirements.txt` 增 `mcp>=1.29,<2`（**API 已核实于 1.29.1**：`stateless_http` / `json_response` /
`streamable_http_path` / `ctx.request_context.request` / `transport_security` 均存在；2.x 有 breaking change，本轮不碰），
`requirements.lock` 锁到 `mcp==1.29.1` 并补全传递依赖：新增 `httpx-sse`、`sse-starlette`、
`jsonschema`(+`referencing`/`rpds-py`)、`pyjwt[crypto]`。
其余依赖已满足：`starlette 1.8.0 ≥ 0.27`、`pydantic 2.14.1 ≥ 2.11`、`uvicorn 0.54 ≥ 0.31.1`、
`httpx 0.28.1 ≥ 0.27.1`、`anyio 4.15.1 ≥ 4.5`、`pydantic-settings 2.16.0 ≥ 2.5.2`。

> 离线部署：backend 镜像在**有网机器**上构建（`deploy/offline-save.sh` 现有流程），新依赖走正常 pip 解析即可。

### 10.2 nginx

**新增 3 处 location**（`frontend_web/nginx.conf` 与 `deploy/native/units/nginx.conf.tpl`
裸机模板**两处都要加**，内容保持一致）：

```nginx
# ① MCP 端点（Streamable HTTP + SSE）
location /mcp {
    proxy_pass http://backend:8000;
    proxy_http_version 1.1;
    proxy_set_header Host $host;            # ⚠️ $host 丢端口 → allowed_hosts 要含裸 host
    proxy_set_header X-Forwarded-Proto $scheme;
    proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
    proxy_set_header Connection '';
    client_max_body_size 200m;
    proxy_buffering off;
    proxy_read_timeout 300s;
}

# ② OAuth 端点（DCR / authorize / token / revoke）
location /oauth/ {
    proxy_pass http://backend:8000;
    proxy_http_version 1.1;
    proxy_set_header Host $host;
    proxy_set_header X-Forwarded-Proto $scheme;
    proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
}

# ③ OAuth 元数据（RFC 8414 / RFC 9728）—— 必须在站点根
location ^~ /.well-known/oauth- {
    proxy_pass http://backend:8000;
    proxy_http_version 1.1;
    proxy_set_header Host $host;
    proxy_set_header X-Forwarded-Proto $scheme;
    proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
}
```

> ⚠️ **三处都要写 `proxy_set_header Host $host;`** —— 丢了 Host 头，
> SDK 的 DNS rebinding 防护（§3.4）会把请求判成 421。
> 而 `$host` **不带端口** → `mcp.allowed_hosts` 必须同时包含裸 host 与 `host:port` 两种形式。

> ⚠️ **SSE 需要的 nginx 配置**（已在 ① 里，此处强调）：
> · `proxy_buffering off` —— **必须有**，否则 SSE 事件流会被 nginx 攒着不发，客户端一直转圈
> · `proxy_read_timeout 300s` —— SSE 是长连接，超时太短会周期性断开
> · `proxy_set_header Connection ''` —— 避免上游 keep-alive 干扰长连接
> · `location /mcp` 是**前缀匹配** ⇒ `/mcp/skill`、`/mcp/skill/sse`、`/mcp/skill/messages/` 一次全中，不用再开 location
>
> ⚠️ **不要把 `/connect/authorize`（前端同意页）写进 `location /mcp`** ——
> 它必须由 nginx 的默认 SPA location 服务（`try_files $uri /index.html`）。
> 同理 `/oauth/` 与 `/.well-known/` **不能**被 SPA 的 `location /` 吞掉 → 才有上面 ②③ 两处。

### 10.3 裸机模式

同进程，无需额外服务；`tmctl.sh` 的 Python 依赖安装走 `requirements.lock`，自动覆盖。

### 10.4 内置连接器：TestMate 自己上架在「插件·技能·连接」

平台的「连接器」资产的内容就是 `mcpServers` JSON，已由 `app/core/mcp_config.py` 校验。
TestMate MCP 作为一个**平台内置连接器**（`kind=mcp`）上架：

```json
{
  "mcpServers": {
    "testmate": {
      "type": "http",
      "url": "http://<平台地址>/mcp/skill"
    }
  }
}
```

- **没有 headers** —— 鉴权全靠 OAuth 流程（§4.9）
- **url 是动态生成的**（`{{BASE}}` 占位符 + `marketplace.public_base_url` 替换），
  因为每套部署的对外地址不同，不能写死进市场仓库
- 用户在市场里看到这张卡 → [复制连接器配置] → 粘进 Qoder → 点「授权」
- 资产**不可删除 / 不可下架 / url 不可改**（文案可改）（§4.9），也不进审核台

### 10.5 前端：同意页 + 市场卡片 + 设置页管理组

⚠️ **没有个人令牌页**（D9）：普通用户走 OAuth，在 Qoder 点「授权」即可，全程不碰令牌。

| 文件 | 改动 | 说明 |
|---|---|---|
| `views/Connect/authorize.vue` | **新增页面** | **同意页**（SPA 路由 `/connect/authorize`）：显示客户端名 + scope 勾选 + [同意]/[拒绝]；未登录先跳登录页 |
| `views/McpGrants/index.vue` | **新增页面** | **「我的授权」**：我在哪些客户端授权过 TestMate + [撤销]（**不是令牌页 —— 不发任何密钥**） |
| `router/index.ts` | 加路由 | `connect/authorize`（`requiresAuth: false`，未登录自己跳登录）+ `mcp/grants`（`requiresAuth: true`） |
| `views/Capability/Catalog/AssetCard.vue` | 改 | 内置资产加「平台内置」徽标，隐藏「下架/删除」按钮，「更新」时配置字段只读 |
| `views/Capability/Catalog/index.vue` | 改 | `canModify` 计算加 `&& !is_builtin`；连接器卡片加「复制连接器配置」按钮 |
| `views/Settings/index.vue` | 加 admin 组 | 「🔌 MCP 接入」：签发**平台接入令牌**（CI/脚本/兜底）/ 配 `mcp.allowed_hosts` / 开关 OAuth 自助授权 |
| `api/mcp.ts` | **新增** | 平台接入令牌 CRUD + `getConnectionConfig()` + 同意页提交 |

后端新增 `app/api/mcp.py`（`/api/v1/mcp`，**仅 admin**）：

| 端点 | 权限 | 说明 |
|---|---|---|
| `GET /tokens` | admin | 平台接入令牌列表 |
| `POST /tokens` | admin | 签发（响应带一次明文） |
| `DELETE /tokens/{id}` | admin | 吊销 |
| `GET /connection-config` | 登录 | 返回 Qoder 格式的 mcpServers JSON（`type` + `url`），供市场卡片复制 |
| `GET /oauth/authorize-info?ticket=…` | 登录 | 同意页渲染用：客户端名 + 请求的 scope + 回调地址 |
| `POST /oauth/consent` | 登录 | 同意页提交：`{ticket, granted_scopes[]}` 或 `{ticket, deny:true}` → 302 回 `redirect_uri` |
| `GET /grants` | 登录 | **我的授权**列表（自己的） |
| `DELETE /grants/{client_id}` | 登录 | **撤销**自己的某个授权（= 该客户端的 token 立刻失效） |

> 内置连接器的配置复制**不需要令牌**，所以这个端点任何登录用户都能调（市场卡片要给普通用户用）。

## 11. 测试策略

### 11.1 单测

| 目标 | 用例要点 |
|---|---|
| adapter 层 | 每个适配函数：正常路径 + HTTPException 映射 + `UploadFile` 构造 + 返回值裁剪 |
| 令牌 | 签发格式 / 校验通过 / 吊销后失败(`token_revoked`) / 过期失败(`token_expired`) / 绑定用户被停用后失败 / scope 不足被拒 / 配额超限被拒(`quota_exceeded`) / 跨日配额归零 |
| 错误映射 | 每个 HTTP 状态码 → MCP error code 的映射正确 |
| schema | 每个工具的 `input_schema` 是合法 JSON Schema，且 name 在域内唯一 |
| 作用域 | 只读令牌调写工具 → `permission_denied` |

### 11.2 集成测试（spike 已给出可行写法）

**关键**：`httpx.ASGITransport` **不触发 lifespan** → 测试里必须手动驱动，否则报
`RuntimeError: Task group is not initialized. Make sure to use run()`。
在 `backend_gateway/tests/_lifespan.py` 提供一个最小 lifespan 驱动（发 `lifespan.startup` → 等 `startup.complete`）。

用例：

1. `initialize` → 拿到 serverInfo.name == `testmate-skill`
2. `tools/list` → 返回 14 个工具，名称与 §5 一致
3. `tools/call skill_search` → 能拿到结果
4. 工具函数内能读到 `ctx.request_context.request.headers["authorization"]` 与 `.state.principal`
5. 无 token → **401** 且带 `WWW-Authenticate: Bearer resource_metadata="…"`（Qoder 据此弹「授权」）
5a. **元数据**：`GET /.well-known/oauth-protected-resource/mcp/skill` → 200，`resource` / `authorization_servers` 正确；
    `GET /.well-known/oauth-authorization-server` → 200，`issuer` / 4 个端点 URL 正确
5b. **OAuth 全流程**：`POST /oauth/register` → `GET /oauth/authorize` → 302 到 `/connect/authorize?ticket=…`
    → `GET /api/v1/mcp/oauth/authorize-info?ticket=…` → `POST /api/v1/mcp/oauth/consent` → 302 回客户端
    → `POST /oauth/token`（code + PKCE verifier）→ 拿到 access token → 带 token 调 `tools/call` 成功
5c. PKCE 错误 / redirect_uri 不在白名单 → 拒绝发码
5c2. **DCR 三条强制规则**：注册时没带 `scope` → 授权请求带 scope **不报 invalid_scope**；
    注册结果 `token_endpoint_auth_method == "none"` 且无 `client_secret`；
    `redirect_uris` 含非回环地址 → **400 invalid_redirect_uri**
5d. 配额用尽 → 工具**不执行**，返回 tool error `quota_exceeded`（**不是** HTTP 429）
5f. **grant 撤销后** → 同一个 access token 再调 → **401**（证明「不过期」不等于「不可回收」）
5g. **流程对齐**：MCP `skill_publish` 成功后 → 资产 `publish_status=pending` / `pending_action=new`
    → 钉钉收到「提交了新资产, 等管理员审核」→ 人工在页面审核通过 → **市场群收到上架通知**
    → `pending_action=meta` 的资产审核通过 → **市场群不收到通知**（断言通知事件差异）
5h. **不猜协议**：缺 `summary` 调用 `skill_publish` → **不产生任何副作用**（DB 无新资产、无通知），
    返回 `needs_confirmation.missing_fields`
5i. `skill_unpublish_request` 后 → `publish_status=unpublish_pending`；人工在页面确认 → 资产被彻底删除
5e. 静态平台接入令牌仍然可用（兜底通道）
6. **路径断言**：`POST /mcp/skill` = 200（不是 307！）；`POST /mcp/nope` = 404；
    `GET /mcp/skill/sse` = 200，且**首帧 `event: endpoint` 的 `data` == `/mcp/skill/messages/?session_id=…`**
    （SSE 回传地址由 `root_path` 决定，挂载写错就错在这里 —— §3.3.3）
7. **transport_security 断言**：Host 不在 allowed_hosts 时 = 421（证明防护生效，不是被绕过）

### 11.3 一致性测试（§4.13 的核心资产）

| 文件 | 断言什么 |
|---|---|
| `tests/test_mcp_contract.py` | **同一场景 REST vs MCP**：DB 状态、钉钉通知事件序列、返回值三者一致（8 个场景） |
| `tests/test_mcp_adapter_params.py` | adapter 函数签名**覆盖**路由函数的全部必填参数（漏传即红） |
| `tests/test_market_rules.py` | 规则包自洽：必填清单与实际端点签名不矛盾；`enforcement` 档位符合预期 |

> 这三个文件是「一致性」的可执行定义 —— 它们红了，就是 REST 与 MCP 已经分叉了。

### 11.4 回归

现有 40+ 测试文件**必须全绿**——这是「不动业务逻辑」方案的核心验收指标：
只要 `marketplace.py` 一行没动，现有测试理应全部原样通过（若有任何失败，说明改到了不该改的地方）。

---

## 12. 验收标准

### 12.0 实施分期（供实施计划拆解用）

| 阶段 | 内容 | 可独立验收 |
|---|---|---|
| **S0** | **Qoder 真机探针**（**独立最小 OAuth spike**，~100 行，与本项目实现完全无关）：起一个最小 AS（http、自签、无 TLS）+ 一个最小 RS（`/mcp/skill` 返回 401 + PR metadata + AS metadata），在 Qoder 里配置后看**会不会自动弹「授权」** | 决定 OAuth 路线是否成立 |
| S1 | **OAuth 骨架**：provider 实现 + **自写路由**（`oauth_routes.py`，**不调 SDK 的 `create_auth_routes`**）+ 自写 DCR 处理器 + access token 签发/校验 | 能用 code 换到 token |
| S2 | **同意页 + grant 表**（前端）+ scope 勾选 + 登录回跳 + 「我的授权」页（撤销） | 浏览器里能走完「登录→同意→回客户端」，且撤销后 token 立刻失效 |
| S3 | **内置连接器资产**：`is_builtin` + seed + 不可删/不可下架/不可改 url + url 动态生成 + 市场卡片「复制连接器配置」 | 市场里能看到这张卡，复制出来的配置 url 正确 |
| S4 | MCP 公共层（server 工厂 / dispatcher / 中间件 / 错误映射 / 工具契约 / 审计 / 配额） | 能握手、能 `tools/list`（空工具集也算通过） |
| S5 | 技能域适配层 + 14 个工具 + `market_rules.py` 合法性校验 + 「不猜」协议 | §12.1 全部通过（尤其流程对齐与不猜） |
| **S5.5** | **一致性收敛**：`/assets/rules` 端点 + 前端改为拉规则 + **契约测试 8 场景** + 参数反射检查 | 契约测试全绿（REST 与 MCP 产出完全一致） |
| S6 | 部署与分发（nginx 3 处 + 锁文件 + `mcp.allowed_hosts` 设置 + 设置页管理组） | 全链路打通 |

**阶段依赖与兜底**：

```
S0（独立探针）──通过──▶ S1 → S2 ──▶ S6
   │
   └──不通过──▶ 切「静态令牌路线」：S1/S2 降级为「令牌页 + 复制配置」
                （⚠️ 额外约 1 天工作量：个人令牌页 + Qoder 手填 Bearer header 的引导流程）
```

- S0 排在最前 —— 它验证的是整条路线的地基，且**不依赖本项目任何代码**（否则就是循环依赖）
- S1/S2 与 S3/S4 之间无强耦合，可并行
- S4 的 dispatcher 必须按 §3.3.2 **Route + Mount 并存**实现（否则 SSE 与 streamable 必有一个连不上）

### 12.1 验收项

1. **普通测试工程师**（tester，非 admin）在市场看到「TestMate 平台能力」连接器卡片（带「平台内置」徽标），点「复制连接器配置」→ 得到 Qoder 格式 JSON（`type` + `url`，**无 headers**）
2. Qoder 导入该配置 → 探活收到 401 → **弹出「授权」按钮** → 点开浏览器 → 跳到 TestMate 登录页 → 登录 → 同意页显示客户端名与 scope → [同意] → 自动回到 Qoder
3. 同意页：viewer 只能勾 `market:read`；tester 可勾到 `market:write`；admin 全部
4. Qoder `tools/list` 返回 14 个工具，名称与 §5 一致
5. agent 能：搜到技能 → 读 `SKILL.md` → 取到包 URL 与 sha256 → 下载后 sha256 与 `skill_package_info` 一致
6. agent 能上架新技能 → 返回 job_id → `skill_job_status` 显示 succeeded → GitLab 出现对应 commit → 审核台可见
7. agent 上架后状态为 `pending`（`pending_action=new`）→ **人工在网页审核台**点通过 → 技能出现在市场列表
8. 配额用尽 → 工具不执行，返回 `quota_exceeded`（**不得**返回 429）
8b. **授权不过期**：签发的 access token 里**没有 `exp`**；隔一天再调仍然可用
8c. 在「我的授权」页撤销某客户端 → 该客户端的 token **下一个请求就 401** → Qoder 重新弹「授权」
9. **内置资产不可删**：管理员调 `DELETE /api/v1/assets/testmate` → 409「平台内置资产不可删除」；下架同样 409；
    改 `mcp_config`（url）→ 409；**但改 summary/description 等文案是允许的**
10. 内置资产的 url 随 `marketplace.public_base_url` 改而变（不用重启、不用改仓库）
11. **既有后端业务文件改动 < 40 行**（`app/main.py` ~30 行 + `app/models/*` 2 行 + `marketplace.py` 守卫 9 行 + nginx 3 处）；现有 40+ 测试全绿
12. **流程与前端一致**：MCP 上架 → 待审核 + 通知管理员 → 人工在页面审核通过 → **市场群收到上架通知**；
    只改信息（`skill_edit_meta`）→ 待审核 + 通知管理员 → 审核通过 → **市场群收不到通知**
13. **不猜协议**：缺必填 / 有歧义 / 可选项未确认时，MCP 写工具**拒绝执行且无任何副作用**，返回 `needs_confirmation`
14. **一致性**：契约测试（8 个场景 × REST/MCP 两条路径）全绿 —— DB 状态、钉钉通知序列、返回值三者一致
15. **规则单一真源**：改 `market_rules.py` 里的必填清单 → 前端表单与 MCP 校验**同时**跟着变（前端不再有第二份硬编码）
16. 后续接知识库域 = 新增 `app/mcp/kb/` 目录 + `PROVIDERS` 加一行，`common/*` 与业务代码零改动
17. **【v11】内网 http 部署可用**：后端能正常启动（没有 `Issuer URL must be HTTPS` 报错），
    `GET /.well-known/oauth-authorization-server` 与 `GET /.well-known/oauth-protected-resource/mcp/skill` 都返回 200
18. **【v11】DCR 三条强制规则生效**：客户端注册时不带 `scope` 也能完成带 scope 的授权；
    注册结果无 client_secret 且 `token_endpoint_auth_method=none`；非回环 `redirect_uris` 被拒
19. **【v11】SSE 回传地址正确**：`GET /mcp/skill/sse` 首帧 `event: endpoint` 的 data
    == `/mcp/skill/messages/?session_id=…`，且该地址能被 POST 成功
20. **【v11】两级配额**：客户端级超限与用户总量级超限都返回 tool error `quota_exceeded`（不是 429）

---

## 13. 风险与对策

| 风险 | 影响 | 对策 |
|---|---|---|
| **allowed_hosts 没配对 → 全站 421** | 高（全功能不可用） | §3.4 已明确格式（裸 host + `host:port` 双写）；集成测试断言 421 场景；设置项兜底 |
| **子应用 lifespan 未驱动 → 500** | 高 | 父应用 lifespan 用 `AsyncExitStack` 跑各域 session manager；集成测试手动驱动 lifespan |
| **`/mcp/skill` 路径 307 跳转 → 客户端连不上** | 高 | dispatcher 写法（不逐个 mount）；集成测试断言 200 而非 307 |
| 适配层与路由函数签名漂移 | 中 | adapter 是唯一耦合点；单测逐个覆盖；路由签名变更时 adapter 单测会红 |
| `_user` 这类怪参数名被后人「顺手改掉」→ adapter 崩 | 中 | adapter 内写明注释；单测覆盖该路径 |
| Qoder 对 `stateless_http` / `json_response` 兼容性未知 | 中 | 只按 MCP 默认协议实现，不加 SSE 兼容层；若实测不兼容，改客户端或改用 SDK 默认 SSE transport（SDK 自带，无需自己写） |
| 新增 pip 依赖影响离线部署 | 低 | 镜像在有网机器构建；锁文件补全；仅 4 个新传递依赖 |
| agent 误上架 / 误删 | 中 | 无硬删工具；审核流不变；scopes 可只读；每次调用留审计 |
| token 泄漏 | 中 | 明文一次性展示；只存 sha256；吊销即时生效；不进 URL / 不进 access log |
| agent 失控循环刷爆平台 | 中 | 令牌级 `daily_quota`（默认 200/天）；超限在**工具层**拦（返回 tool error，不返 429，避免客户端重试风暴） |
| **REST 与 MCP 悄悄分叉** | 高 | §4.13 三层防线：规则单一真源 + **契约测试（REST vs MCP 三项断言）** + 参数反射检查；分叉 = CI 红 |
| 前端收敛改动引入回归 | 中 | `assetForm.ts` / `useAssetUploadForm.ts` 改拉规则后，跑既有前端单测（该目录已有 `__tests__/`）；后端既有 40+ 测试不动即绿 |
| **【v11】OAuth 路由自写 → 与 SDK 版本漂移** | 中 | 只复用 SDK 的 handler（`AuthorizationHandler`/`TokenHandler`/`MetadataHandler`）与 `build_metadata`，**不重写协议逻辑**；锁 `mcp==1.29.1`；升级 SDK 时跑 §11.2 的 5a/5b/5c2 用例即可发现 |
| **【v11】DCR 未强制 scope → Qoder 授权直接失败** | 高 | §4.3.3 三条强制规则 + 集成测试 5c2 锁死 |
| **【v11】SSE root_path 写错 → 客户端 POST 到不存在的地址** | 高 | §3.3.3 装配约束 + 集成测试断言首帧 endpoint 的 data 字符串 |
| **【v11】同意页路由被 nginx `location /mcp` 劫持 → 404** | 中 | 同意页定在 `/connect/authorize`（不在 `/mcp` 下）；nginx 配置评审清单里带上这一条 |
| **【v11】issuer / resource URL 固化 → 改域名后 OAuth 发现失败** | 中 | 已知限制（§15）：改 `marketplace.public_base_url` 后**必须重启后端**；设置项说明里写死这句提醒 |
| **【v11】授权码 / 待处理授权请求在内存 → 多进程会失效** | 中 | SSE 已要求单进程（`BACKEND_WORKERS=1`）；`tmctl` 已在 >1 时告警；文档化这条部署约束 |

---

## 14. 后续路线

| 阶段 | 内容 | 增量成本 |
|---|---|---|
| **P0（本轮）** | OAuth 授权流 + 同意页 + 内置连接器资产 + MCP 公共层 + 技能域 14 工具 + **一致性收敛（规则真源 + 契约测试）** + 部署分发 | — |
| P1 | 知识库域：`app/mcp/kb/` + `kb_search` / `kb_list_datasets` / `kb_read_document` / `kb_ingest` | 1 个目录 + 1 行注册 |
| P2 | 软件库域：`app/mcp/software/` + `software_search` / `software_download` / `software_upload` | 1 个目录 + 1 行注册 |
| P3 | 插件 / 连接器域：`plugin_*` / `connector_*`（复用同一批 adapter 函数，改 kind 即可） | 少量 tool spec |
| P3.5 | 同意页增强：「以后都同意」（记住授权，不再每次问）、refresh token | 小 |
| P4 | stdio transport 薄壳（本地 CLI agent 用） | 1 个薄壳进程 |
| P5 | MCP Resources / Prompts（把 `SKILL.md` 暴露成 Resource） | SDK 原生支持 |

---

## 15. 未决事项（已按默认取值处理）

| 事项 | 本轮取值 | 何时需要回看 |
|---|---|---|
| 首期是否含审核工具 | **已定：不含**（D7）——上架后人工在网页审核台处理 | 若日后要放开，再加回 `skill_review` 一个 tool spec（受平台审核人权限约束） |
| **OAuth access token 有效期** | **已定：不过期**（D11）—— 不带 `exp`；安全靠 grant 表撤销 | 用户反馈长期授权有风险时，再引入 refresh token（P3.5） |
| **是否做 SSE transport** | **已定：做**（Qoder CN 的类型下拉里 SSE 与 HTTP 并列，必须都支持） | 若实测 SSE 不可用，再降级为只留 Streamable HTTP |
| 静态平台接入令牌有效期 | **已定：默认不过期**，可设期限（adminOnly 的 CI/兜底通道） | — |
| 每客户端调用配额 | **已定：默认 200 次/天**，0 = 不限；**另加用户总量 1000 次/天** | 观察 `mcp_tool_calls` 的真实用量后可调 |
| 是否抽 domain 层 | 本轮**不抽**（§6） | 出现 §6.5 的三个信号时再下沉 |
| 个人令牌页 | **已定：不做**（D9）—— 普通用户只走 OAuth | **若 S0 证明 Qoder 不走 OAuth，则必须补回来**（约 1 天工作量） |
| **Qoder 是否会自动走 OAuth 发现** | **待 S0 验证**（无 Qoder 客户端环境，无法离线确认） | S0 探针跑完即定；不成立则切静态令牌路线 |
| 内置连接器的 code | 约定 `testmate`（用户可见、可改） | 改的话要注意已装到 Qoder 的用户配置会失效 |
| **【v11】改 `marketplace.public_base_url` 后是否要重启** | **要重启后端**（issuer / resource URL 在 FastMCP 构造时固化） | 若将来要求热改，需要把 URL 改成运行时读取（增加一层间接） |
| **【v11】OAuth 端点路径** | 已定：`/oauth/*` + 站点根 `/.well-known/…`（D17） | 将来若要兼容「只认 SDK 默认路径」的客户端，再加别名路由 |
