# TestMate MCP 设计（技能市场先行 · v3）

> 2026-10-31 · 让 **agent 能操作 TestMate**：上架 / 下载 / 更新技能；后续接知识库、软件库。
> 本轮只做**技能·插件**一个域；每个域一个独立 MCP，公共部分单独放一层。
>
> 修订要点：
> 1. `app/mcp/` 改为**按域分目录**（`common/` `skill/` `software/` `kb/`），公共部分归 `common/`
> 2. **每个域一个独立 MCP server**，各自挂载于 `/mcp/{域}`，工具集互不污染
> 3. **对现有业务代码零改动**——不重构 `marketplace.py`，MCP 侧用薄适配层调用现有路由函数
> 4. 补入 **spike 实测结论**（装配路径 / 鉴权取身份 / DNS rebinding 421 / lifespan 500）
> 5. **首期不含审核工具**（14 → 13 个）：上架后由人工在网页审核台处理，agent 不自己盖章
> 6. **令牌模型加料**：绑定方式（必绑具体用户）/ scope 固定枚举 / 默认 90 天有效期 / 每日调用配额
> 7. **不做 SSE 兼容层**：只按 MCP 默认协议（Streamable HTTP）实现
>
> 状态：**设计已定，待实现**。

---

## 一句话

在现有 FastAPI 后端挂一组 `/mcp/{域}` 端点（MCP Streamable HTTP），用**长期 API Token** 鉴权；
每个业务域一个独立 MCP server，技能域首批暴露 **13 个工具**；
**现有业务代码一行不改**，MCP 能力全部收敛在新目录 `app/mcp/` 内。

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
- ❌ 不实现知识库 / 软件库的工具（只留目录骨架与公共层的扩展位）
- ❌ 不做 stdio transport（首批只服务 Qoder，走远程 HTTP）
- ❌ 不做 MCP OAuth 动态注册（静态 API Token，够用且好管）
- ❌ **不重构 `marketplace.py`**（见 §6，这是本方案与 v1 最大的分歧点）

---

## 2. 已定决策

| # | 决策点 | 结论 | 理由 |
|---|---|---|---|
| D1 | MCP server 跑在哪 | **挂进现有 FastAPI 后端**，端点 `/mcp/{域}`（Streamable HTTP） | 一套部署；复用 DB、权限判定、审计、资产 job 队列 |
| D2 | agent 身份 | **新增长期 API Token**（管理员签发/吊销，绑定用户身份 + scope） | agent 配置里只放一个 token；权限可精确到用户 + scope |
| D3 | 首批接入方 | **Qoder**（远程 HTTP，`{url, headers}` 连接器配置） | 团队主力 IDE；平台「连接器」资产格式天然匹配 |
| D4 | MCP 的组织方式 | **`app/mcp/` 按域分目录；每域一个独立 MCP server；公共部分在 `common/`** | 域之间零耦合；agent 可只连需要的域，工具集不污染 |
| D5 | 对现有代码的侵入度 | **零改动**：`marketplace.py` / `kb.py` / `software.py` 一行不动，MCP 侧用薄适配层调用 | 生产代码，3005 行重排的回归风险不可接受；MCP 是独立功能，应能独立落地 |
| D6 | 协议实现 | **官方 `mcp` SDK**（FastMCP），`stateless_http=True` + `json_response=True` | 握手/版本协商/能力声明有 SDK 兜底；依赖与现有锁文件无冲突 |
| D7 | 首期是否含审核工具 | **不含** —— 上架后由人工在**网页审核台**处理 | 审核是人工运营动作，agent 不该自己给自己盖章；写入面更小、更安全 |

---

## 3. 总体架构

### 3.1 目录结构（按域分类）

```
backend_gateway/app/
├── mcp/                        # ★ MCP 功能整体 —— 本轮新增，**全部代码都在这里**
│   ├── common/                 #   公共部分：与具体业务域无关
│   │   ├── __init__.py
│   │   ├── server.py           #     MCP server 工厂 + 分域挂载（dispatcher）
│   │   ├── auth.py             #     API Token 校验 → Principal；FastAPI 中间件
│   │   ├── context.py          #     McpContext（身份 + 域调用入口 + 审计）
│   │   ├── errors.py           #     HTTPException / 业务异常 → MCP tool error
│   │   ├── tool.py             #     ToolSpec 契约 + 注册辅助
│   │   └── audit.py            #     tool 调用审计落库
│   │
│   ├── skill/                  # ★ 技能·插件 域（本轮实现）
│   │   ├── __init__.py
│   │   ├── server.py           #     本域 MCP server 实例（name=testmate-skill）
│   │   ├── adapter.py          #     调 app/api/marketplace.py 的薄适配层
│   │   └── tools.py            #     13 个工具定义（schema + handler）
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
| 技能·插件 | `testmate-skill` | `POST /mcp/skill` | **本轮实现**（13 工具） |
| 软件库 | `testmate-software` | `POST /mcp/software` | 预留骨架 |
| 知识库 | `testmate-kb` | `POST /mcp/kb` | 预留骨架 |

**为什么要分域而不是一个大 server**：

- agent 只需连自己要的域 —— 连 `testmate-skill` 就只看到 13 个技能工具，不会被知识库/软件库工具淹没
- 每个域的 `instructions` 可以写自己的引导语（如「这是技能市场：先 search 再 read_doc 再 publish」）
- 域之间零耦合：新增域 = 新增 `app/mcp/<域>/` 目录 + 在 `common/server.py` 的注册表加一行
- 权限可分域授权（`market:read` / `kb:read` / `software:read`），未来可给 agent 只读某个域的令牌

**工具名仍带 `skill_` 前缀**：即使 server 已按域拆分，也保留前缀——部分 MCP 客户端会把多个 server 的工具名拍平展示，
带前缀能避免 `search` / `get` 这类通用名互相撞车，日志里也更可读。

### 3.3 装配与挂载（spike 已实测）

```python
# app/mcp/common/server.py
def build_mcp(name: str, instructions: str, *, path: str) -> FastMCP:
    return FastMCP(
        name=name,                       # 如 "testmate-skill"
        instructions=instructions,       # 给 agent 的引导语
        stateless_http=True,             # 无状态：不需要 session id，nginx/多副本友好
        json_response=True,              # 响应是 application/json，不走 SSE 流
        streamable_http_path=path,       # "/skill" —— 域路径, 见下方挂载
        transport_security=TransportSecuritySettings(...),  # ⚠️ 必须显式配, 见 §3.4
    )
```

```python
# app/main.py —— 只改这三处
@asynccontextmanager
async def lifespan(app: FastAPI):
    ...
    async with AsyncExitStack() as stack:
        for mcp in ALL_MCPS:                       # 每个域一个
            await stack.enter_async_context(mcp.session_manager.run())
        yield
    ...

app.mount("/mcp", build_dispatcher(ALL_MCPS))     # 分域分发
```

**分域分发**（`common/server.py`）：把各域的 `streamable_http_app()` 挂进一个 Starlette 应用：

```python
def build_dispatcher(apps: dict[str, ASGIApp]) -> Starlette:
    return Starlette(routes=[Route(f"/{name}", endpoint=app) for name, app in apps.items()])
```

路径推演（spike 实测）：

| 请求 | 结果 | 说明 |
|---|---|---|
| `POST /mcp/skill` | **200** | 正确端点，无跳转 |
| `POST /mcp/skill/` | 307 | 尾斜杠会跳转 → **对外公布的 URL 必须不带尾斜杠** |
| `POST /mcp/nope` | 404 | 未注册的域 |
| `GET /mcp/skill` | 406 | SDK 要求 `Accept: application/json, text/event-stream` |

> ⚠️ **不能用 `app.mount("/mcp/skill", ...)` 逐个挂**：Starlette 的 `Mount` 只匹配带尾斜杠的子路径，
> `/mcp/skill`（无尾斜杠）会 307 跳到 `/mcp/skill/`，而不少 MCP 客户端不跟随 POST 重定向 → 必然连不上。
> 所以用「挂一次 `/mcp` + 内部按 `/域` 路由」的 dispatcher 写法。

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

## 4. 鉴权：长期 API Token

### 4.1 表结构

```sql
CREATE TABLE mcp_api_tokens (
  id            BIGINT       NOT NULL AUTO_INCREMENT PRIMARY KEY,
  name          VARCHAR(128) NOT NULL,               -- 令牌名，如 "张三的 Qoder 笔记本"
  token_prefix  VARCHAR(32)  NOT NULL,               -- 明文前 12 位，UI 展示与人工定位用
  token_hash    CHAR(64)     NOT NULL,               -- sha256(明文) 十六进制，唯一索引
  user_id       BIGINT       NOT NULL,               -- 绑定身份：权限完全等同该用户
  scopes        JSON         NOT NULL,               -- ["market:read","market:write"] 取值来自固定枚举
  daily_quota   INT          NOT NULL DEFAULT 200,   -- 每日调用上限; 0 = 不限
  created_by    BIGINT       NULL,
  created_at    DATETIME     NOT NULL,
  last_used_at  DATETIME     NULL,
  expires_at    DATETIME     NULL,                   -- 默认创建后 90 天; NULL = 永不过期
  revoked_at    DATETIME     NULL                    -- 吊销即时生效
);
CREATE UNIQUE INDEX uk_mcp_tokens_hash ON mcp_api_tokens (token_hash);
CREATE INDEX ix_mcp_tokens_user ON mcp_api_tokens (user_id);
```

**只存 sha256，不存明文**：token 是 256-bit 随机串，不存在字典攻击风险；慢哈希（bcrypt）在这里只会拖慢每个请求。
**明文只在签发那一刻返回一次**。

### 4.2 签发与吊销

设置页新增「MCP 接入令牌」组（**admin 专属**），签发表单字段与默认值：

| 字段 | 默认值 | 说明 |
|---|---|---|
| `name` | 必填 | 令牌名，如「张三的 Qoder 笔记本」—— 出问题时靠它定位 |
| `user_id` | 必填 | **绑定的用户**（令牌权限实时取该用户当前角色） |
| `scopes` | `["market:read"]` | 勾选式，**取值来自固定枚举**（见 §4.4），不接受自由字符串 |
| `expires_at` | **创建后 90 天** | 可勾「永不过期」；过期后 agent 会收到明确报错 |
| `daily_quota` | **200 次/天** | 0 = 不限；防跑飞 agent（详见 §4.5） |

- 令牌明文格式：`tm_live_<32字节base64url>`，**签发那一刻返回一次**
- 吊销 = 置 `revoked_at`，**即时生效**（每个请求现查库，无本地缓存 → 吊销后下一个请求必然 401）
- 列表页展示：令牌名 / 前缀 / 绑定用户 / scopes / 配额用量 / 最后使用时间 / 有效期 / 状态

### 4.3 校验链路（spike 已验证身份可传递）

```
请求 → FastAPI 中间件(path startswith /mcp)
     → 取 Authorization: Bearer <token>
     → sha256 → 查 mcp_api_tokens（token_hash 唯一索引，单行查询）
     → 校验: 存在 / 未吊销 / 未过期
     → 加载绑定 user（检查 user.is_active、角色）
     → request.state.principal = Principal(user, token, scopes)   # ← Starlette 自动建 scope["state"]
     ▼
工具函数 → ctx.request_context.request
         ├─ .headers.get("authorization")     → spike 实测: ✅ 能拿到
         └─ .state.principal                  → spike 实测: ✅ 中间件写入的身份可见
```

失败一律 **HTTP 401**（transport 级），不是 tool error——这才是 MCP 客户端期待的认证失败形态，
客户端会据此弹「请重新授权」，而不是把 401 当成工具执行结果。

### 4.4 权限模型（两层 AND）

| 层 | 规则 |
|---|---|
| 用户层 | 沿用平台现有口径：`role` + 发布者白名单（`market_policy.can_publish`）+ 资产归属（`can_modify`） |
| 令牌层 | `scopes` 必须包含该工具的 `scope`；`read_only` 工具额外要求 scope 带 `:read` |

**令牌权限永远不超过绑定用户**：绑定 viewer 就干不了发布者的事；admin 也可以签发只读令牌给 agent 防误删。

#### scope 取值（固定枚举，不接受自由字符串）

| scope | 覆盖的工具 | 能力 |
|---|---|---|
| `market:read` | `skill_search` `skill_get` `skill_read_doc` `skill_read_file` `skill_list_files` `skill_package_info` `skill_categories` `skill_projects` `skill_job_status` | 只读 |
| `market:write` | `skill_publish` `skill_update` `skill_submit_review` `skill_unpublish_request` | 上架 / 更新 / 提交审核 / 申请下架 |
| `market:*` | 上面全部 | 该域全权 |

**枚举是唯一真源**：工具的 `scope` 字段与这里一一对应，后端校验「工具 scope ∈ 枚举」，避免出现
「令牌写了个 `market:write_all` 但工具要的是 `market:write`」这种静默不匹配。将来加域时，
枚举跟着 `common/tool.py` 的 scope 常量一起扩。

#### 绑定方式：必须绑一个具体用户

不提供「绑角色」「绑服务账号」的令牌。理由：

- **审计要追到人**：平台已有的 `asset_audits` 记的是 `actor`（用户名）。令牌绑用户 → agent 的每一次上架都记在真人名下。
- **权限要跟着人走**：角色/白名单在设置页随时可能改，令牌绑用户意味着**实时取该用户当前权限**，
  不会出现「昨天发的令牌今天还是旧权限」的幽灵。
- **配额与封禁要能落到人**：出问题能定位到具体令牌 + 具体人，而不是一锅端某个角色。

「机器身份」的需求用**令牌名**表达（「张三的 Qoder 笔记本」），而不是另开一种绑定类型。

### 4.5 配额（防跑飞 agent）

agent 最危险的失败模式不是「权限越界」，而是**失控循环**：反复 publish/search 把平台刷爆、
把 git 工作区写满、触发一堆钉钉通知。

- 每个令牌有 `daily_quota`（默认 200 次/天，0 = 不限）
- **执行位置：工具包装层**（`common/tool.py`），不在中间件——中间件是 transport 级，
  超额返回 HTTP 429 会被 MCP 客户端当成「可重试的临时故障」→ **重试风暴**。
  在工具层返回 tool error `quota_exceeded`，agent 能读懂「今天超量了，别再试了」。
- **计数来源：`mcp_tool_calls` 表**（每次调用都已落一行）。按 `(token_id, created_at)` 索引做范围计数，
  每日上限 200 时最多扫 200 条索引项，成本可忽略——**不需要引入 Redis 计数器**。
- 计数窗口：自然日（按服务器本地时区），跨日自动归零。
- 超额的那次调用**也要落审计**（`ok=false, error_code=quota_exceeded`），否则计数会漂。

### 4.6 安全红线

- token 不进 URL、不进 query、不进 access log（只走 Authorization 头）
- 明文一次性展示，UI 不缓存明文
- 吊销即时生效；默认 90 天过期，过期与吊销返回**不同的错误码**（`token_expired` vs `token_revoked`），便于 agent 自诊断
- 每次 tool 调用落审计（见 §8），含 token_id，可追责到人
- 令牌明文不进公共市场资产（自举连接器只放 url + 占位符，见 §10.4）

---

## 5. 工具清单（v1 = 技能·插件域，13 个 = 9 读 + 4 写）

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

### 5.2 写工具（scope: `market:write`，`read_only=false`）

| 工具 | 入参 | 出参 | 说明 |
|---|---|---|---|
| `skill_publish` | `code` `name` `version` `summary` `description?` `use_when?` `not_for?` `category?` `project?` `icon?` `tags?` `keywords?` `permissions?` `install_steps?` `bindings?` `files?` `package_base64?` | `{job_id, status, code}` | 上架新技能。`files`（路径→文本内容映射）与 `package_base64`（zip 的 base64）二选一，都不给则 `invalid_argument`。base64 包按 `{code}.zip` 还原（命名契约要求包名与 `code` 一致，`market_naming.check_package_consistency` 会校验） |
| `skill_update` | `code` + 上述任意字段（**均可省略**）+ `files?` / `package_base64?` | `{job_id, status, code}` | 发新版本。**字段省略 = 保持现状**（读当前 DB 资产值合并，read-modify-write）；`version` 省略时自动 patch 当前版本末位（`x.y.z → x.y.(z+1)`），给了则必须与当前版本不同。给了 `files`/`package_base64` = **整体替换**包内容（不是增量合并），未给 = 包内容不变 |
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

### 6.1 结论：业务代码零改动

v1 方案主张把 `marketplace.py` 的业务逻辑抽到 `app/domain/market.py`（REST 与 MCP 共用）。
**v2 放弃这个做法**，改为：

> `app/api/marketplace.py` **一行不动**。MCP 侧新增 `app/mcp/skill/adapter.py`，
> 由它调用**现有的路由函数**，把 HTTP 形状的参数翻译成 MCP 工具的入参。

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
| `app/main.py` | 挂载 dispatcher + lifespan 里跑各域 session manager + 注册 `/api/v1/mcp` 路由（约 15 行） |
| `app/models/__init__.py` | 导出新模型（1 行） |
| `requirements.txt` / `requirements.lock` | 加 `mcp==1.29.1` 及 4 个传递依赖 |
| `frontend_web/nginx.conf` | 加 `location /mcp`（约 12 行） |
| `deploy/native/units/nginx.conf.tpl` | 同上（裸机模板） |
| 前端设置页 | 加「MCP 接入令牌」组（新组件 + 设置页挂载一处） |

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
 │  POST /mcp/skill   Authorization: Bearer tm_live_xxx
 ▼
FastAPI 中间件 ── 验签/有效期/吊销 ──▶ request.state.principal
 ▼
dispatcher (/mcp → /skill) ──▶ FastMCP JSON-RPC: initialize → tools/list → tools/call
 ▼
tool handler (app/mcp/skill/tools.py)
 │  取 principal → 校验 scope → 组装 McpContext
 ▼
adapter (app/mcp/skill/adapter.py)
 ▼
app/api/marketplace.py 的现有路由函数（**一行未改**）
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
`streamable_http_path` / `ctx.request_context.request` / `transport_security` 均存在；2.x 有 breaking change，本轮不碰），
`requirements.lock` 锁到 `mcp==1.29.1` 并补全传递依赖：新增 `httpx-sse`、`sse-starlette`、
`jsonschema`(+`referencing`/`rpds-py`)、`pyjwt[crypto]`。
其余依赖已满足：`starlette 1.8.0 ≥ 0.27`、`pydantic 2.14.1 ≥ 2.11`、`uvicorn 0.54 ≥ 0.31.1`、
`httpx 0.28.1 ≥ 0.27.1`、`anyio 4.15.1 ≥ 4.5`、`pydantic-settings 2.16.0 ≥ 2.5.2`。

> 离线部署：backend 镜像在**有网机器**上构建（`deploy/offline-save.sh` 现有流程），新依赖走正常 pip 解析即可。

### 10.2 nginx

```nginx
location /mcp {
    proxy_pass http://backend:8000;
    proxy_http_version 1.1;
    proxy_set_header Host $host;            # ⚠️ $host 丢端口 → allowed_hosts 要含裸 host
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
    "testmate-skill": {
      "url": "http://<平台地址>/mcp/skill",
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
2. `tools/list` → 返回 13 个工具，名称与 §5 一致
3. `tools/call skill_search` → 能拿到结果
4. 工具函数内能读到 `ctx.request_context.request.headers["authorization"]` 与 `.state.principal`
5. 无 token / 坏 token → **401**；已吊销 token → **401**；已过期 token → **401**（错误码 `token_expired`）
5b. 令牌配额用尽 → 工具**不执行**，返回 tool error `quota_exceeded`（**不是** HTTP 429）
6. **路径断言**：`POST /mcp/skill` = 200（不是 307！）；`POST /mcp/nope` = 404
7. **transport_security 断言**：Host 不在 allowed_hosts 时 = 421（证明防护生效，不是被绕过）

### 11.3 回归

现有 40+ 测试文件**必须全绿**——这是「零改动」方案的核心验收指标：
只要 `marketplace.py` 一行没动，现有测试理应全部原样通过（若有任何失败，说明改到了不该改的地方）。

---

## 12. 验收标准

### 12.0 实施分期（供实施计划拆解用）

| 阶段 | 内容 | 可独立验收 |
|---|---|---|
| S1 | 令牌体系（表 + 模型 + 签发/校验/吊销 API + 配额 + 设置页） | 能签发、能验、能吊销、配额能拦 |
| S2 | MCP 公共层（server 工厂 / dispatcher / 中间件 / 错误映射 / 工具契约 / 审计） | 能握手、能 `tools/list`（空工具集也算通过） |
| S3 | 技能域适配层 + 13 个工具 | §12.1 全部通过 |
| S4 | 部署与分发（nginx / 锁文件 / allowed_hosts 设置 / 自举连接器 / 设置页入口） | Qoder 实连成功 |

S1 是 S2 的前置（中间件要认 token）；S2 与 S1 之间耦合仅在令牌，S3 依赖 S2。S2/S3 可并行。

### 12.1 验收项

1. 管理员在设置页签发令牌 → 拿到 `tm_live_...` 明文（只此一次）
2. Qoder 里配置连接器 `{url: http://<host>/mcp/skill, headers: {Authorization: "Bearer tm_live_..."}}` → 能连上
3. `tools/list` 返回 13 个工具，名称与 §5 一致
4. agent 能：搜到技能 → 读 `SKILL.md` → 取到包 URL 与 sha256 → 下载后 sha256 与 `skill_package_info` 一致
5. agent 能上架新技能 → 返回 job_id → `skill_job_status` 显示 succeeded → GitLab 出现对应 commit → 审核台可见
6. agent 上架后状态为 `pending`（`pending_action=new`）→ **人工在网页审核台**点通过 → 技能出现在市场列表
7. 吊销令牌 → 下一个请求立刻 401（错误码 `token_revoked`）；过期令牌 → 401（`token_expired`）
7b. 令牌当日调用数超 `daily_quota` → 工具不执行，返回 `quota_exceeded`（**不得**返回 429）
8. **`git diff --stat` 证明既有后端业务文件改动 < 40 行**（`app/main.py` ~15 行 + `app/models/__init__.py` 1 行 + 2 个 nginx 各 ~12 行）；现有 40+ 测试全绿
9. 后续接知识库域 = 新增 `app/mcp/kb/` 目录 + `PROVIDERS` 加一行，`common/*` 与业务代码零改动

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

---

## 14. 后续路线

| 阶段 | 内容 | 增量成本 |
|---|---|---|
| **P0（本轮）** | 令牌体系 + MCP 公共层 + 技能域 13 工具 + 部署分发 | — |
| P1 | 知识库域：`app/mcp/kb/` + `kb_search` / `kb_list_datasets` / `kb_read_document` / `kb_ingest` | 1 个目录 + 1 行注册 |
| P2 | 软件库域：`app/mcp/software/` + `software_search` / `software_download` / `software_upload` | 1 个目录 + 1 行注册 |
| P3 | 插件 / 连接器域：`plugin_*` / `connector_*`（复用同一批 adapter 函数，改 kind 即可） | 少量 tool spec |
| P4 | stdio transport 薄壳（本地 CLI agent 用） | 1 个薄壳进程 |
| P5 | MCP Resources / Prompts（把 `SKILL.md` 暴露成 Resource） | SDK 原生支持 |

---

## 15. 未决事项（已按默认取值处理）

| 事项 | 本轮取值 | 何时需要回看 |
|---|---|---|
| 首期是否含审核工具 | **已定：不含**（D7）——上架后人工在网页审核台处理 | 若日后要放开，再加回 `skill_review` 一个 tool spec（受平台审核人权限约束） |
| 令牌有效期 | **已定：默认 90 天**，可勾选「永不过期」 | 用户反馈经常过期影响使用时可调整默认值 |
| 是否做 SSE 兼容层 | **不做** —— 只按 MCP 默认协议（Streamable HTTP）实现 | 若 Qoder 实测不兼容，走 SDK 自带的 SSE transport（不自己写兼容代码） |
| 每 token 调用配额 | **已定：默认 200 次/天**，0 = 不限 | 观察 `mcp_tool_calls` 的真实用量后可调 |
| 是否抽 domain 层 | 本轮**不抽**（§6） | 出现 §6.5 的三个信号时再下沉 |
