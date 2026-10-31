# TestMate MCP 设计（技能市场先行 · v6）

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
> 7. **令牌自助签发**：任何登录用户可给自己签发（设置页是 adminOnly，放那儿等于只有管理员能用 agent）；
>    scope 上限 = 用户平台能力（复用 `market_policy.can_publish`）
> 8. **令牌页 `/mcp-tokens` + 一键复制连接器配置**：用户不用手拼 mcpServers JSON，url 自动取 `marketplace.public_base_url`
> 9. **transport 双端点**：Streamable HTTP（`POST /mcp/skill`）+ **SSE**（`GET /mcp/skill/sse` + `POST /mcp/skill/messages/`）
>    —— Qoder CN 走 SSE 模式，SSE **必须做**（v5 写的「不做 SSE」已被 Qoder 官方文档推翻，见 §4.9）
> 10. **鉴权用静态 Bearer 令牌**：Qoder 官方文档明确支持 MCP 服务器配 `Headers: Authorization: Bearer ...`
>    ⇒ **不需要 OAuth**；截图里的「需要授权」是 Qoder 内置市场连接器（第三方各自的 OAuth），与自定义 MCP 无关
> 11. **Qoder 的 OAuth 2.1 授权流**（§4.8）降级为 **P3.5 可选增强**（静态令牌已够用）；SDK 有一等支持，
>    将来若要「点一下就授权」的用户体验再上
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

**谁可以签发**：**任何登录用户都能给自己签发**（自助），管理员额外可以**代发给别的用户**。

⚠️ 原设计写成「设置页 admin 专属」是错的：`/settings` 整个页面是 **adminOnly**
（路由守卫 `adminOnly` + UserMenu 隐藏入口 + 页面内兜底，普通用户连进都进不去），
放那儿等于**只有管理员能用 agent**，普通测试工程师想用就得找人代开 —— 瓶颈且不合理。

签发方式改为两条路：

| 路径 | 谁能用 | 绑定谁 | scope 上限 |
|---|---|---|---|
| **自助签发** | 任何登录用户 | 只能绑自己 | 该用户当前的平台能力（见 §4.4） |
| **管理员代发** | admin | 可选任意用户 | 同上（仍是那个用户的权限） |

平台开关 `mcp.tokens.self_service`（默认 **true**）：admin 关掉后，只有 admin 能签发。

签发表单字段与默认值：

| 字段 | 默认值 | 说明 |
|---|---|---|
| `name` | 必填 | 令牌名，如「我的 Qoder 笔记本」—— 出问题时靠它定位 |
| `user_id` | 自助=自己；代发=手选 | **绑定的用户**（令牌权限实时取该用户当前角色） |
| `scopes` | `["market:read"]` | 勾选式，**取值来自固定枚举**（见 §4.4），不接受自由字符串；**可选项受 scope 上限约束** |
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

#### scope 上限 = 绑定用户的平台能力（自助签发时自动收敛）

不靠"按钮能不能点"来管权限，而是**复用平台已有的能力判定**——发 scope 时按用户能力自动收敛可选项：

| 用户的平台能力（既有口径） | 可选 scope |
|---|---|
| 非发布者（viewer / 不在发布者白名单） | 只能 `market:read` |
| 发布者（`market_policy.can_publish` 为真，默认 tester 即可） | `market:read` + `market:write` |
| admin | 全部 + `market:*` |

这样普通测试工程师能自助拿到「能上架技能」的 agent 令牌，而 viewer 拿到的必然是只读令牌，
**不需要管理员逐个发**。判定逻辑复用 `app/core/market_policy.py`，MCP 侧不另造一套角色体系。

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

### 4.7 令牌怎么进到 MCP 客户端（交付链路）

MCP 客户端（Qoder）需要的不只是一个 token，而是**一整段配置**：

```json
{
  "mcpServers": {
    "testmate-skill": {
      "url": "http://10.0.0.5:8081/mcp/skill",
      "headers": { "Authorization": "Bearer tm_live_xxxxxxxx" }
    }
  }
}
```

让用户自己手拼这段 JSON 极易出错（漏引号、url 写错路径、少了 `/mcp/skill`）。所以交付链路是：

```
令牌页(新建 /mcp-tokens)
  ├─ [签发令牌]  → 明文 tm_live_xxx（只此一次，弹窗 + 一键复制）
  ├─ [复制连接器配置 · HTTP] → {"mcpServers":{"testmate-skill":{
  │        "type":"streamable-http","url":"http://<平台地址>/mcp/skill",
  │        "headers":{"Authorization":"Bearer tm_live_xxx"}}}}   ← 一键复制
  │        (对应 Qoder「传输类型」下拉选 **HTTP**)
  ├─ [复制连接器配置 · SSE] → 同上，url 换成 .../mcp/skill/sse、type 换成 "sse"
  │        (对应 Qoder「传输类型」下拉选 **SSE**)
  └─ [工具清单] → 列出本域 13 个工具，让用户知道 agent 能干什么
                          ↓ 粘贴
                    Qoder：设置 → 连接器与 MCP → + → 粘贴 JSON 配置 → 导入
                          ↓
                    Qoder 连 http://<平台地址>/mcp/skill
```

⚠️ **输出格式要按 Qoder 的来**：Qoder 的「粘贴 JSON 配置」样例带 `type` 字段
（`"type": "streamable-http"` / `"sse"`），这是 Qoder 特有的。
平台自己的 `app/core/mcp_config.py` 校验连接器配置时**只检查已知字段、忽略未知键**，
所以 `type` 不会导致校验失败 —— 两边格式天然兼容，不用改既有校验器。

**url 自动取对**：后端用既有设置项 `marketplace.public_base_url`（已是「对外可达的基地址」，
marketplace.json 和钉钉通知链接都在用它）+ `/mcp/skill` 拼出，用户不用手填 IP。
该设置项留空时回落到「请求来源 host」（与 `app/core/dingtalk.py` 的做法一致）。

**为什么不让平台市场直接下发带令牌的连接器**：「连接器」资产是**公共**的（全员可见），
把某个人的明文令牌写进去 = 全员可见的长期凭证。绝不这么做。
市场里的 TestMate 连接器资产只放 url 与 `<你的令牌>` 占位符，令牌由每个人自己在令牌页签发。

### 4.8 Qoder 的「点授权 → 跳系统 → 网页同意」流程（OAuth 2.1，可选增强）

Qoder 里配好 MCP 后弹「需要授权」、点一下跳到网页去同意、再回到 Qoder 拿到工具权限——
这是 **MCP 规范里的标准 OAuth 2.1 流程**（Resource Server + Authorization Server 双角色），不是 Qoder 私有机制。

完整链路：

```
① Qoder 探活 POST /mcp/skill  → 我们返回 401
   + WWW-Authenticate: Bearer resource_metadata="http://host/.well-known/oauth-protected-resource/mcp/skill"
② Qoder 读「受保护资源元数据」→ 得知授权服务器在 http://host
③ Qoder 读「授权服务器元数据」 http://host/.well-known/oauth-authorization-server
   → 拿到 authorization_endpoint / token_endpoint / registration_endpoint
④ Qoder 动态注册客户端 POST http://host/register  (RFC 7591)
⑤ Qoder 打开浏览器 http://host/authorize?...&code_challenge=...&state=...
   → 我们引导登录 TestMate → **同意页**（显示客户端名 + 请求的 scope）→ [同意]
   → 生成授权码 → 302 回 Qoder 的 redirect_uri?code=...&state=...
⑥ Qoder 用 code + PKCE 校验串换 access token  POST http://host/token
   → 之后所有请求带 Authorization: Bearer <access_token>
```

#### SDK 已经给好了大半（已逐个核实 API）

| SDK 能力 | 位置 | 我们要写什么 |
|---|---|---|
| `FastMCP(auth=AuthSettings(issuer_url, resource_server_url), auth_server_provider=..., token_verifier=...)` | `mcp/server/fastmcp/server.py` | 传参即可 |
| `create_auth_routes(provider, issuer_url, ...)` | `mcp/server/auth/routes.py` | **零代码**，自动生成 `/.well-known/oauth-authorization-server`、`/authorize`、`/token`、`/register`、`/revoke` |
| `BearerAuthBackend` | `.../middleware/bearer_auth.py` | **零代码**，401 时自动带 `WWW-Authenticate: Bearer resource_metadata=...`（就是①的触发器） |
| `OAuthAuthorizationServerProvider` 协议 | `mcp/server/auth/provider.py` | **要实现**：`register_client` / `authorize` / `exchange_authorization_code` / `load_access_token` / `get_client` / `revoke_token` 等 10 个方法 |
| `AuthorizationParams.code_challenge`（**必填**） | 同上 | PKCE S256 校验（公开客户端无 secret，必须 PKCE） |
| `AuthorizationCode.subject` / `AccessToken.subject` | 同上 | 资源所有者身份 → 同意页登录的用户 = token 的 `sub` |

#### 我们必须自己写的四块

1. **provider 实现**（`app/mcp/common/oauth_provider.py`，约 300 行）
   - OAuth 客户端注册表（新表 `mcp_oauth_clients`）
   - 授权码存储（短时，建议放 Redis 或新表；一次性、5 分钟过期）
   - **PKCE S256 校验**（`exchange_authorization_code` 里比对 `code_verifier`）
   - **redirect_uri 白名单校验**（必须比对客户端注册时登记的 redirect_uri —— 否则就是开放重定向漏洞）
2. **同意页**（前端新页面 `/mcp/authorize`）
   - 未登录 → 跳 TestMate 登录页（带 redirect 回跳）
   - 登录后 → 显示「客户端名 + 请求的 scope（逐条）+ 有效期」→ [同意] / [拒绝]
   - [同意] → 调后端生成 code → 302 回客户端 `redirect_uri`
3. **token 验证入口**：一个 `TokenVerifier` **同时接受两种凭证** —— 静态 `tm_live_*` 与 OAuth access token
4. **nginx 加 location**：OAuth 端点在**根路径**（`/.well-known/...`、`/authorize`、`/token`、`/register`、`/revoke`），
   **不在 `/api/` 下**，而现有 nginx 只把 `/api/` 转发给后端 → 必须单独加（否则 404 落到前端静态页）

#### 代价与取舍

| 维度 | 静态个人令牌（§4.2） | OAuth 2.1 授权流 |
|---|---|---|
| 用户操作 | 复制令牌 → 粘进配置 | 点「授权」→ 浏览器同意 → 完事 |
| 后端工作量 | 1 张表 + 签发/校验/吊销 | 再加 1 张表 + provider(300行) + 同意页 + 4 处 nginx |
| 凭证生命周期 | 长期（90 天或永不过期） | 短期 access token + refresh |
| 适用场景 | Qoder / curl / CI / 脚本 | 图形化客户端（Qoder 等） |

**推荐：两条都留，一个验证入口。**
`TokenVerifier` 同时认 `tm_live_*` 和 OAuth access token，权限判定（scope + 用户平台能力）与审计
（`mcp_tool_calls`）完全共用 —— 用户选哪种凭证，能力边界一模一样。

### 4.9 Qoder 鉴权怎么弄（官方文档结论）

**来源**：QoderWork CN 官方文档「连接器」章节（阿里云帮助中心）
`https://www.alibabacloud.com/help/tc/lingma/qoderwork-cn/user-guide/getting-started`

官方原文要点：

> **手动填写配置** → 服务器类型选 **Streamable HTTP / SSE** → 需要填写：
> **Server Name**、**Server URL**、**Headers（可选）：认证头，如 `Authorization: Bearer your-token`**
>
> **粘贴 JSON 配置**样例：
> ```json
> { "mcpServers": { "service-name": {
>     "type": "streamable-http",
>     "url": "https://mcp-server-url.example.com/sse",
>     "headers": { "Authorization": "Bearer your-token" } } } }
> ```
>
> 「Streamable HTTP 是 SSE 的更新、更强大的继任者。如果市场提供 Streamable HTTP URL，应优先选择该类型。」

**⇒ 结论一：静态 Bearer 令牌就是正解**，鉴权不需要 OAuth：

```
Qoder「设置 → 连接器与 MCP → + → 手动填写配置」
  服务器类型：Streamable HTTP / SSE
  Server URL：http://<平台地址>/mcp/skill          （SSE 模式则填 /mcp/skill/sse）
  Headers：Authorization: Bearer tm_live_xxxxxxxx
```

**⇒ 结论二：截图里那些「需要授权」与自定义 MCP 无关**。
GitHub / 阿里云 DevOps / 七鱼查 / AMAP 是 **Qoder 内置市场**的连接器，各自带第三方 OAuth 端点，
点「授权」是去它们各自的系统登录。而**用户自己添加的 MCP 服务器显示在「已安装 → Custom」分类下**，
走的是「配置 + Headers」这条路，**没有授权按钮**。

> 佐证：本机 `~/.qoder-cn/logs/qoder-qmind/qmind-mcp.log` 里能看到 Qoder 的 MCP 客户端
> 有完整的鉴权状态机（`mcp.auth.state_applied` / `mcp.auth.logged_in` / `principalType:"user"`），
> 那是 Qoder **自带连接器**（stdio 型）的登录态，与我们自己配的远程 server 是两条路。

**⇒ 结论三：OAuth 从「可能必需」降级为「可选增强」**（§4.8 保留设计，列为 P3.5）。
只有当将来想让用户「点一下就授权」而完全不用碰令牌时，才需要上那 300 行 provider + 同意页。

#### ⚠️ 先决问题：Qoder 到底需不需要 OAuth？

这是**目前唯一没有实测证据**的点。两种可能：

- **Qoder 支持在 MCP 配置里带 `headers`** → 静态令牌直接可用，**完全不需要 OAuth**
  （平台的连接器资产格式本来就带 `headers`，`app/core/mcp_config.py` 一直在校验这个结构）
- **Qoder 不发自定义头 / 坚持走自己的授权流程** → 必须实现 OAuth

这台机器上没有 Qoder 客户端，无法直接验证。**建议实现阶段第一步就做这个 spike**（约 30 分钟）：
用设计好的静态令牌在 Qoder 里配一次，看是直接连上、还是弹授权框。
这一步直接决定 OAuth 是 P0 还是 P2 —— 别在没验证前就把 300 行 provider 写完。

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
| 前端 | 新增 `views/McpTokens/index.vue` + `api/mcp.ts`（新文件）；改 `router/index.ts`（加路由）、`components/UserMenu.vue`（加菜单项）、`views/Settings/index.vue`（加 admin 管理组） |

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

> ⚠️ **SSE 需要的 nginx 配置**（上面已包含，此处强调）：
> · `proxy_buffering off` —— **必须有**，否则 SSE 事件流会被 nginx 攒着不发，客户端一直转圈
> · `proxy_read_timeout 300s` —— SSE 是长连接，超时太短会周期性断开
> · `proxy_set_header Connection ''` —— 避免上游 keep-alive 干扰长连接
> · `location /mcp` 是**前缀匹配** ⇒ `/mcp/skill`、`/mcp/skill/sse`、`/mcp/skill/messages/` 一次全中，不用再开 location

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

### 10.5 前端：新增「MCP 令牌」页 + 设置页管理组

⚠️ **不能只做设置页**：设置页是 adminOnly，普通用户进不去，个人令牌必须有自己的页面。

| 文件 | 改动 | 说明 |
|---|---|---|
| `views/McpTokens/index.vue` | **新增页面** | 「我的 MCP 令牌」：列表 / 签发 / 吊销 / 复制明文 / **复制连接器配置（Streamable HTTP / SSE 两个按钮）** / 工具清单 |
| `router/index.ts` | 加一条路由 | `{ path: 'mcp-tokens', meta: { requiresAuth: true, title: 'MCP 令牌' } }`——**不加 `adminOnly`** |
| `components/UserMenu.vue` | 加菜单项 | 「MCP 令牌」，**所有登录用户可见**，放在「设置」条目旁边（设置仍只给 admin） |
| `api/mcp.ts` | **新增** | 令牌 CRUD + `getConnectionConfig()`（拿可粘贴的 mcpServers JSON） |
| `views/Settings/index.vue` | 加一个 admin 组 | 「🔌 MCP 接入」：看**全部**令牌 / 吊销别人的 / 开关自助签发（`mcp.tokens.self_service`）/ 配 `mcp.allowed_hosts` |

后端新增 `app/api/mcp.py`（`/api/v1/mcp`）：

| 端点 | 权限 | 说明 |
|---|---|---|
| `GET /tokens` | 登录 | 自己的令牌；admin 可带 `?all=1` 看全部 |
| `POST /tokens` | 登录（自助）/ admin（代发） | 签发，**响应里带一次明文** |
| `DELETE /tokens/{id}` | 本人 / admin | 吊销 |
| `GET /connection-config?transport=http\|sse` | 登录 | 返回拼好的 **Qoder 格式** mcpServers JSON（`type` + `url` + `headers.Authorization`），供一键复制；`transport=http` → `type=streamable-http` + `/mcp/skill`；`transport=sse` → `type=sse` + `/mcp/skill/sse` |
| `GET /tools` | 登录 | 本域工具清单（供页面展示） |

另在「插件·技能·连接」页加一个入口，说明「agent 可通过 TestMate MCP 操作技能市场」并链到令牌页。

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
| **S0** | **Qoder 真机联调**：用静态令牌在 Qoder 里配一次，确认能连上 / 走的是 SSE 还是 Streamable HTTP / 头有没有带上 | 打通客户端接入（§4.9 末尾） |
| S1 | 令牌体系（表 + 模型 + 签发/校验/吊销 API + 配额 + 设置页） | 能签发、能验、能吊销、配额能拦 |
| S2 | MCP 公共层（server 工厂 / dispatcher / 中间件 / 错误映射 / 工具契约 / 审计） | 能握手、能 `tools/list`（空工具集也算通过） |
| S3 | 技能域适配层 + 13 个工具 | §12.1 全部通过 |
| S4 | 部署与分发（nginx / 锁文件 / allowed_hosts 设置 / 自举连接器 / 设置页入口） | Qoder 实连成功 |

S1 是 S2 的前置（中间件要认 token）；S2 与 S1 之间耦合仅在令牌，S3 依赖 S2。S2/S3 可并行。

### 12.1 验收项

1. **普通测试工程师**（tester，非 admin）登录后进 `/mcp-tokens` → 自助签发 → 拿到 `tm_live_...` 明文（只此一次）
1b. **viewer** 签发时 scope 只有 `market:read`（可选项被自动收敛）；tester 可勾到 `market:write`
2. 令牌页点「复制连接器配置」→ 得到一段 mcpServers JSON（url 自动取 `marketplace.public_base_url`）→ 粘进 Qoder → 能连上
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
| **P3.5** | **OAuth 2.1 授权流**（可选增强，静态令牌已够用）：provider + 同意页 + 4 处 nginx；与静态令牌共用 `TokenVerifier` | 约 300 行后端 + 1 个前端页 |
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
| **Qoder 是否需要 OAuth** | **已定：不需要** —— 官方文档确认支持 `Headers: Authorization: Bearer ...`（§4.9）；OAuth 降级 P3.5 | 若将来要「点一下就授权」的体验再上 |
| OAuth 的同意页放哪 | 暂定 `/mcp/authorize`（独立页，非设置页——设置页是 adminOnly） | 真正做的时候再定 |
