# 知识库 MCP 设计（`/mcp/kb`）

> 2026-11-06 · 参考扩展库 MCP（`/mcp/skill`）的实现，为知识库（RAGFlow：数据集 / 文档 / 分段 / 检索）增加 MCP 能力，并接入前后端。
>
> 本版在 2026-10-31《TestMate MCP 设计》的域扩展位之上落地第二个域 `kb`。原文「本轮不实现知识库」由本文取代，其余约束（单进程、OAuth + 静态令牌、scope/配额/审计、真实 transport 契约测试）继续沿用。

状态：**设计已确认，按本版实施**。

---

## 1. 背景与目标

知识库的日常操作目前只能在网页端完成：建库、上传文档、换文件、重解析、看分段、做检索。Agent 在会话里要用知识库，必须由人先切到网页端操作一遍再把结果贴回来。

本轮目标：

1. 增加独立 MCP 域 `kb`，端点 `POST /mcp/kb`（Streamable HTTP）与 `GET /mcp/kb/sse`，不改扩展库域的行为。
2. 能力范围：**只读 + 写文档**。读覆盖数据集 / 文档 / 分段 / 语义检索；写覆盖建库、上传、替换、重解析。
3. 二进制文件（PDF / Word / Excel）不经过 base64 —— 走「上传票 + 直传」两步，字节路径与网页端完全一致。
4. 前端零新增页面：知识库助手以「扩展库内置卡片」的形式出现；令牌页增加 `kb:read` / `kb:write` 两个权限。
5. 顺手关掉一个已存在的鉴权口子：MCP 令牌当前可以被普通 REST API 当成登录令牌使用。

---

## 2. 已定决策

| # | 决策 | 结论 |
|---|---|---|
| D1 | 域划分 | 新域 `kb`，server 名 `testmate-kb`，路径 `/mcp/kb`；与 `extensions` 共用 dispatcher / lifespan / Redis 配额 |
| D2 | scope | `kb:read`（所有启用账号）、`kb:write`（admin / tester）；存储仍是 JSON 列，**无数据库迁移** |
| D3 | 工具数量 | 12 个：7 读 + 5 写（含 `kb_document_status` 轮询解析进度） |
| D4 | 文本上传 | `kb_document_upload` / `kb_document_update` 直接收 UTF-8 文本，支持单次 1..5 篇批量，逐篇返回结果 |
| D5 | 二进制上传 | `kb_document_write_ticket` 签**数据集级、可复用**的票，Agent 用 `curl -F` 直传现有上传逻辑，**不走 base64** |
| D6 | URL 拉取 | 本轮**不做** `source_url`，理由见 §10 |
| D7 | 删除 | 本轮**不暴露**删除类工具（删文档 / 删库 / 取消解析）；破坏性操作留在网页端 |
| D8 | 复用 | 写操作调用 `app/api/kb.py` 中抽取出的核心函数，不复制审核、审计、归属、自动解析逻辑 |
| D9 | 错误 | 403/404/409/413/422 的业务提示原样透出（固定文案），502/RAGFlow 内部错误统一转 `kb_unavailable`，不泄露地址与 key |
| D10 | 内置卡片 | `testmate-extensions` + `testmate-kb` 两条种子，注册表化；同步器继续按 code 跳过 |
| D11 | 鉴权加固 | `get_current_user` 明确拒绝 `typ in {mcp-static, mcp-oauth}` 的令牌 |
| D12 | 票据 | 上传票 30 分钟、绑定用户 + 数据集，**同一张票可复用于整批上传**；放请求头，不放进 URL |
| D13 | 慢上传 | 端点先验票、再读 multipart —— 票的有效期按**请求开始时刻**算，不按请求体读完的时刻算 |
| D14 | 异步解析 | 上传/替换/重解析工具**只保证已提交**（网关落库 + 发起解析）就返回；解析结果由 `kb_document_status` 查询，Agent 不靠猜等待 |

---

## 3. 为什么二进制不能"照抄前端"

网页端上传是一条纯 multipart 路径，字节从不进入 JSON：

- [kb.py:764](../../backend_gateway/app/api/kb.py#L764) `upload_docs(file: list[UploadFile] = File(...))` —— 每个文件是独立的 form part；
- [kb.py:793](../../backend_gateway/app/api/kb.py#L793) 分块读取、限量、洗文件名，攒成 `(name, bytes, content_type)`；
- [ragflow_client.py:304](../../backend_gateway/app/core/ragflow_client.py#L304) `upload_documents()` 再用 httpx 发一遍 multipart 给 RAGFlow。

MCP 的 `tools/call` 是 JSON-RPC 2.0，`params.arguments` 只能是 JSON 对象：

- 协议里没有「文件 part」「multipart 通道」「流式上传入参」；
- MCP 的 image / audio / embedded resource 是**服务端返回给客户端**的内容类型，不是上传入参；
- 因此「让工具收一个文件」在协议层不存在，只能把字节塞进 JSON 字段。

base64 在扩展库可行，是因为安装包只有 KB 量级（`package_base64`，[tools.py:74](../../backend_gateway/app/mcp/skill/tools.py#L74)）。知识库单文件上限 20MB，base64 后约 27MB，塞进一次工具调用会超客户端限制，Agent 还得先把本地二进制读进上下文。**文本内联 + 票据直传** 才是与网页端等价的路径。

---

## 4. 方案总览

```text
Agent
 ├─ tools/call kb_document_upload      → UTF-8 文本 × 1..5 → 网关 → RAGFlow（multipart）
 ├─ tools/call kb_document_update      → UTF-8 文本 × 1..5 → 网关 → 四步替换
 ├─ tools/call kb_document_status      → 轮询解析进度（可选等待 ≤60s）
 └─ tools/call kb_document_write_ticket(dataset_id)
        ← { ticket, upload_url, expires_in: 1800, reusable: true }
        └─ curl -H "X-KB-Upload-Ticket: <ticket>" \
                -F "file=@a.pdf" -F "file=@b.docx" ... <upload_url>
              → 先验票、再读 body → 与网页端同一个上传/替换核心 → RAGFlow（multipart）
```

三条通道职责：

| 通道 | 适用 | 大小 | 走 MCP？ |
|---|---|---|---|
| 文本内联 | `.txt` / `.md` / `.csv` / `.log` 等 | 单篇 ≤ 2MB、单次 ≤ 5 篇 | 是，单次调用完成 |
| 上传票直传 | PDF / Word / Excel / 任意二进制 | 单篇 ≤ 20MB、单次 ≤ 5 篇 | 签票走 MCP，上传走 HTTP；一张票可复用 |
| 网页端 | 人工操作 | ≤ 20MB × 5 | 否 |

**两阶段语义（上传 / 替换 / 重解析都适用）**：

| 阶段 | 发生什么 | 谁负责 | 何时可见 |
|---|---|---|---|
| 提交 | 验权 → 写入 RAGFlow → 落 TestMate 归属与审计 → 调 RAGFlow 解析接口 | MCP 工具，同步返回 | 工具返回时已完成 |
| 解析 | RAGFlow 切片、向量化、建索引 | RAGFlow，异步（分钟级） | 由 `kb_document_status` 或文档列表「解析」列查看 |

因此工具返回的 `ok=true` 只表示**已经提交给 TestMate 并成功发起解析**，不代表解析成功。返回体里每篇文档都带 `run`（提交时的状态），调用方应继续查 `kb_document_status`（含 `progress` / `progress_msg`），直到 `run=DONE` 或 `run=FAIL`。这样工具调用不会被异步解析拖到超时。

---

## 5. 后端设计

### 5.1 目录与模块

```text
backend_gateway/app/mcp/kb/
├── __init__.py
├── server.py     # build_kb_server(): build_mcp("kb", ...) + 注册 TOOL_SPECS
├── tools.py      # 12 个 ToolSpec（显式 JSON Schema）
└── adapter.py    # 调 app/api/kb.py 的核心函数；错误归一化
```

与 `skill/` 保持同构：`server.py` 只做装配，`tools.py` 只声明契约，`adapter.py` 只做参数转换与调用。

### 5.2 权限模型

`app/mcp/common/oauth.py`：

```python
SUPPORTED_SCOPES = frozenset({
    "extensions:read", "extensions:write", "kb:read", "kb:write",
})
_SCOPE_ORDER = ("extensions:read", "extensions:write", "kb:read", "kb:write")
```

`allowed_scopes(user)`：

- 账号启用即有 `extensions:read`、`kb:read`；
- `extensions:write` 沿用 `ext_policy.can_publish(user)`；
- `kb:write` 取角色：`admin` / `tester`（与 [kb.py:52](../../backend_gateway/app/api/kb.py#L52) `_can_write` 同口径）。

为避免 MCP 层反向依赖 API 层，新增 `app/core/kb_policy.py`：

```python
def can_write_kb(user: User) -> bool:
    role = user.role.value if hasattr(user.role, "value") else str(user.role)
    return role in (UserRole.admin.value, UserRole.tester.value)
```

`api/kb.py::_can_write` 改成 `can_write_kb` 的薄包装（保留现有调用点与函数名，减少改动面），保证 REST 与 MCP 只有一处判定。

`api/mcp.py` 的两处 scope 校验文案改为按 `SUPPORTED_SCOPES` 动态生成，不再硬编码「extensions:read extensions:write」。

### 5.3 工具清单

读（`scope="kb:read"`，`read_only=True`）：

| 工具 | 参数 | 返回 | 说明 |
|---|---|---|---|
| `kb_dataset_list` | `page` 1..、`page_size` 1..100（默认 50）、`keyword` | `{items, page, page_size, has_more}` | 无 `keyword`：直接透传分页，`has_more = len(items) == page_size`；有 `keyword`：最多取 5 页（≤500 个库）按名称/描述过滤后本地分页，`has_more` 按本地切片判断。RAGFlow 不返回总数 |
| `kb_document_list` | `dataset_id`、`page`、`page_size` 1..100（默认 30）、`orderby`、`desc`、`keywords`、`run` | `{docs, total}` | 与 REST 同字段，含上传者 |
| `kb_document_search` | `keywords`（必填）、`dataset_id` 可选、`limit` 1..500 | `{items, total, truncated}` | 只搜文件名，跨库并发 |
| `kb_document_chunks` | `dataset_id`、`document_id`、`page`、`page_size` 1..100（默认 100）、`keywords` | `{chunks, total, doc}` | 已去掉 `content_ltks` |
| `kb_document_status` | `dataset_id`、`document_id`、`name` 可选、`wait_seconds` 0..60（默认 0） | `{document_id, name, run, progress, progress_msg, chunk_count, token_count, timed_out}` | 解析是异步的：`run ∈ UNSTART/RUNNING/CANCEL/DONE/FAIL`，`progress` 0..1。`wait_seconds > 0` 时每 2 秒轮询一次，到点返回**当前状态**而不是报错 |
| `kb_search` | `question`、`dataset_ids` 1..20、`document_ids`、`top_k`、`similarity_threshold`、`vector_similarity_weight`、`keyword`、`highlight`、`page_size` 1..50 | `{total, chunks, doc_aggs, elapsed_ms}` | 语义检索 |
| `kb_health` | 无 | `{status, message}` | 诊断 RAGFlow 可达性 |

写（`scope="kb:write"`，`read_only=False`）。所有写工具的 `description` 都要写明「返回成功只代表已提交，解析结果用 `kb_document_status` 查询」：

| 工具 | 参数 | 行为 |
|---|---|---|
| `kb_dataset_create` | `name` 1..128、`description`、`chunk_method`（枚举）、`language`（Chinese/English） | 复用 `create_kb_dataset`；重名、非法切片方式原样报错 |
| `kb_document_upload` | `dataset_id`；单个 `name` + `content` + `content_type` 可选，**或** `documents` 数组 1..5（每项 `{name, content, content_type?}`） | 逐篇上传并自动解析；返回 `uploaded / failed / docs / errors`，一篇失败不拖垮整批 |
| `kb_document_update` | `dataset_id`；单个 `document_id` + `content`，**或** `documents` 数组 1..5（每项 `{document_id, content}`） | 逐篇四步替换并自动解析；同样逐篇返回结果 |
| `kb_document_write_ticket` | `dataset_id` | 校验数据集存在后签 30 分钟、可复用的上传票；替换时在直传请求里带 `document_id` 表单字段 |
| `kb_document_reparse` | `dataset_id`、`document_id` | 内容不变，重跑解析 |

写工具统一返回「已提交」口径：

```json
{
  "ok": true,
  "state": "submitted",
  "uploaded": 3,
  "failed": 0,
  "ingest_started": true,
  "warning": "",
  "docs": [
    {"document_id": "abc", "name": "a.md", "state": "submitted",
     "run": "UNSTART", "size": 1234}
  ],
  "errors": [],
  "replaced": "old-doc-id"
}
```

- `state`: `submitted`（全部已提交）/ `partial`（部分失败）/ `failed`（全部失败）；
- `ok=true` 只代表提交成功并发起了解析，**不代表解析成功**；每篇的 `run` 是提交那一刻的状态（RAGFlow 上传响应自带），`progress` 只在 `kb_document_status` 中返回；
- 上传成功但发起解析失败时 `ingest_started=false`：文件已入库，用 `kb_document_reparse` 重试解析；
- 替换成功后多返回 `replaced`（旧 `document_id`）。旧文档在**提交阶段**就已删除：若新文档之后 `run=FAIL`，旧内容不会自动恢复，需要修正内容后重新替换，不要重试旧 id；
- `kb_document_reparse` 同样只发起解析，返回后仍需查状态。

文本内联的两个工具只接受文本扩展名白名单：

```python
TEXT_DOC_EXTENSIONS = {
    ".txt", ".md", ".markdown", ".csv", ".json", ".log", ".html", ".htm",
}
MAX_MCP_INLINE_BYTES = 2 * 1024 * 1024   # 单篇
MAX_MCP_BATCH_DOCS = 5                   # 与 REST 单次上传篇数一致
MAX_MCP_BATCH_BYTES = 8 * 1024 * 1024    # 一次工具调用的文本总量
```

传入 `.pdf` / `.docx` 时报 `invalid_document_type`，并提示改用 `kb_document_write_ticket` —— 避免把文本塞进二进制扩展名，生成一份 RAGFlow 永远解析不了的坏文档。

### 5.4 上传票协议

**设计原则：票据绑定「谁能写哪个数据集」，不绑定单个文件。**

批量上传/更新是长耗时场景：5 个 20MB 文件、或慢速内网、或 Agent 在两个动作之间停顿，都可能超过一张短票的窗口。票据按文件签、按 10 分钟过期，会让「前 3 个成功、后 2 个 401」成为常态，最终结果就不可靠了。

因此：

- 一张票覆盖**整个数据集**，同一张票可连续上传多篇；
- 有效期 **30 分钟**（`KB_UPLOAD_TICKET_TTL = 1800`），覆盖一批 5 × 20MB 的常规耗时；
- 票过期不会污染已完成的文件：重新签一张票，继续传剩下的即可；
- 替换时目标文档由**表单字段** `document_id` 指定，不写进票据 —— 同一张票可以连续替换多篇。

**签发**：`kb_document_write_ticket(dataset_id)`

```json
{
  "ticket": "<JWT>",
  "upload_url": "http://<public_base>/api/v1/kb/datasets/<id>/documents/ticket-upload",
  "method": "POST",
  "file_field": "file",
  "replace_field": "document_id",
  "expires_in": 1800,
  "expires_at": "2026-11-06T15:30:00Z",
  "max_bytes_per_file": 20971520,
  "max_files_per_request": 5,
  "reusable": true,
  "note": "30 分钟内可复用；上传多篇就重复 -F file；替换时加 -F document_id=<id>。批量超过 30 分钟就重新签票，已传文件不受影响。"
}
```

票据函数放在 `app/core/security.py`，与下载票同风格：

```python
KB_UPLOAD_TICKET_TYPE = "kb-upload"
KB_UPLOAD_TICKET_TTL = 1800   # 30 分钟；批量更大可在这里上调

def create_kb_upload_ticket(
    *, user_id: int, token_version: int, dataset_id: str,
    ttl_seconds: int = KB_UPLOAD_TICKET_TTL,
) -> tuple[str, int]: ...

def decode_kb_upload_ticket(ticket: str) -> dict[str, Any] | None: ...
```

载荷：

```json
{
  "typ": "kb-upload",
  "uid": 12,
  "tv": 0,
  "ds": "<dataset_id>",
  "exp": "<utc now + 1800s>"
}
```

`upload_url` 的基地址取 `resolve_public_base()`（设置里的 `extensions.public_base_url` 优先，否则用当前请求来源），与内置卡片的 MCP 配置保持同一个地址口径。

**接收**：新增 `POST /api/v1/kb/datasets/{dataset_id}/documents/ticket-upload`。

请求形态（与网页端完全一致的 multipart）：

```bash
# 批量上传 5 篇
curl -H "X-KB-Upload-Ticket: $T" \
     -F "file=@a.pdf" -F "file=@b.docx" -F "file=@c.xlsx" \
     "<upload_url>"

# 替换一篇
curl -H "X-KB-Upload-Ticket: $T" \
     -F "document_id=<doc_id>" -F "file=@a-v2.pdf" \
     "<upload_url>"
```

**慢上传的关键顺序**：端点签名用 `request: Request`，**先验票、再 `await request.form()`**。

- 若沿用 `file: UploadFile = File(...)`，FastAPI 会先把整个 20MB 请求体解析完才进函数体 —— 客户端传得慢，票可能在函数执行前就过期了；
- 先验票保证「请求开始时刻票有效」即可，票据 TTL 不会因为传输耗时被吃掉；
- 验票失败立刻返回 401，不浪费带宽接收 20MB 请求体。

校验顺序（失败返回 401/403/404/413，不泄露内部信息）：

1. 请求头 `X-KB-Upload-Ticket` 存在，签名有效，`typ == "kb-upload"`，未过期（**在读 body 之前**）；
2. 票据 `ds` 与路径 `dataset_id` 一致；
3. 用户仍存在、`is_active`、`token_version` 与票据 `tv` 一致；
4. `can_write_kb(user)`；
5. `await request.form(max_files=5, max_fields=5)`；取 `form.getlist("file")` 与可选的 `form.get("document_id")`；
6. 上传模式：1..5 个文件；替换模式：必须恰好 1 个文件 + 一个 `document_id`；
7. 每个文件 ≤ 20MB（`MAX_UPLOAD_BYTES`）；文件名按 `_sanitize_kb_filename` / `_fit_kb_name_bytes` 清洗；
8. 替换模式先确认 `document_id` 属于该数据集且存在；
9. 调用与网页端相同的核心函数；结束后 `await form.close()` 清理临时文件。

响应与 REST 上传一致（`docs[]` 带 `run`），同样是「已提交」口径：返回 200 只代表文件已入库、解析已发起；解析结果回到 MCP 调 `kb_document_status` 查询（加固后 MCP 令牌不能直接调 REST 读接口）。

票据放**请求头**而不是 query：query 会进 nginx access_log。票是数据集级、可复用的，泄露面由「30 分钟 + 用户/数据集绑定 + `can_write_kb`」共同限制；不做一次性消费（Redis 不在 REST 层保证可用，且同一用户重复上传本就是其既有权限）。

### 5.5 复用与重构（关键）

当前上传与替换的全部业务逻辑都写在路由函数体内。为了让网页端、文本内联、票据直传三条入口行为完全一致，从 `api/kb.py` 抽取两个核心函数（**纯函数化，不新增业务规则**）：

```python
async def upload_prepared_documents(
    dataset_id: str,
    prepared: list[tuple[str, bytes, str]],
    user: User,
) -> dict: ...

async def replace_document(
    dataset_id: str,
    document_id: str,
    name: str,
    payload: bytes,
    content_type: str,
    user: User,
) -> dict: ...
```

- `upload_prepared_documents` = 现有 `upload_docs` 中 `prepared` 之后的全部逻辑（上传、manual 数据集告警、自动解析、逐篇审计、归属）；
- `replace_document` = 现有 `update_kb_document` 中「查旧文档 + 扩展名校验 + 四步替换 + 归属迁移 + 解析」；
- `upload_docs` / `update_kb_document` 只保留参数校验与文件读取，然后调用核心函数；
- 票据端点和 MCP 文本工具调用同一组核心函数；
- 核心函数**不等待解析完成**：`ingest_documents` / `parse_documents` 返回即结束，与网页端行为一致。

返回值保持现有契约不变（都是「提交结果」）：

- 上传：`{ok, uploaded, ingest_started, warning, docs[]}`；
- 替换：`{ok, updated, replaced, ingest_started, warning}`。

**批量执行策略（MCP 侧）**：批量工具不把 5 篇塞进一次 RAGFlow 请求，而是**逐篇调用核心函数**并收集结果：

```python
{
  "ok": failed == 0,
  "state": "submitted" | "partial" | "failed",
  "uploaded": 3,          # 或 updated
  "failed": 2,
  "docs": [ ... ],        # 成功项: id / name / state / run / size
  "errors": [ {"name": "b.pdf", "error": "file_too_large"} ],
  "ingest_started": true,
  "warning": "..."
}
```

逐篇执行的意义：一篇坏文件（超限、扩展名不符、RAGFlow 单篇报错）不会把整批回滚；已经成功的文件保留，失败的进入 `errors`，Agent 只需重试失败项。票据直传的批量请求也由核心函数逐篇处理、逐篇审计，返回同样的口径。

同时把 `get_datasets` 的字段清洗抽成 `_dataset_items(page, page_size, keyword="")`，REST 仍用默认参数（行为不变），MCP 用分页参数。

`kb_document_status` 的实现：优先用 `list_documents(keywords=name)` 精确定位（1 次请求）；没有 `name` 时退回现有 `_find_document` 分页查找。`wait_seconds > 0` 时每 2 秒查一次，到点返回当前 `run/progress`，并置 `timed_out: true` —— **超时只是"还没解析完"，不是工具失败**。

### 5.6 注册与部署

`app/main.py` lifespan：

```python
mcp_dispatcher.configure({
    "extensions": build_skill_server(
        public_base_url=public_base_url,
        allowed_hosts=await _get_setting("mcp.allowed_hosts", ""),
    ),
    "kb": build_kb_server(
        public_base_url=public_base_url,
        allowed_hosts=await _get_setting("mcp.allowed_hosts", ""),
    ),
})
```

`McpDispatcher.configure` 已按域循环建路由，无需改动；`/skill` 兼容别名仍只给 `extensions`。

`build_kb_server`：

```python
server = build_mcp(
    "kb",
    public_base_url=public_base_url,
    allowed_hosts=allowed_hosts,
    redis_client=redis_client,
    server_name="testmate-kb",
)
for spec in TOOL_SPECS:
    register_tool(server, "kb", spec, redis_client=redis_client)
```

配额沿用 `mcp.quota.user_per_minute` / `mcp.quota.client_per_minute`，审计落 `mcp_tool_calls`（`domain="kb"`）。RAGFlow 调用本身的耗时由工具内的 httpx 超时控制（沿用 `ragflow_client` 现有限制）。

### 5.7 错误映射

`McpRuntimeError` 的 message 会原样返回给 Agent，因此只透出**代码里写死的业务文案**：

| 来源 | 映射 |
|---|---|
| HTTPException 403 | `permission_denied` + detail（如「只读账号不能上传文档」） |
| HTTPException 404 | `not_found` + detail |
| HTTPException 409 | `conflict` + detail |
| HTTPException 413 | `file_too_large` + detail |
| HTTPException 422 | `invalid_arguments` + detail |
| HTTPException 502 / 其他异常 | `kb_unavailable` + 「知识库服务暂时不可用，请稍后重试。」 |
| `McpRuntimeError` | 原样 |

502 的 detail 里含 RAGFlow 地址或 key 片段（现有路由用 `f"ragflow error: {e}"`），**绝不能**透传。

### 5.8 鉴权加固（顺带修复）

现状：`decode_token()`（[security.py:44](../../backend_gateway/app/core/security.py#L44)）不校验 `typ`/`aud`；`get_current_user()`（[auth.py:125](../../backend_gateway/app/api/auth.py#L125)）读 `tv`，而 MCP 令牌写的是 `token_version` —— `tv` 缺失被当成 0，正好等于存量用户的 `token_version`。结果是 **MCP 静态令牌可以当普通登录令牌调任何 REST API**。

修复：

```python
MCP_TOKEN_TYPES = frozenset({"mcp-static", "mcp-oauth"})

# get_current_user 解码成功后
if payload.get("typ") in MCP_TOKEN_TYPES:
    raise HTTPException(status_code=401, detail="token 类型无效")
```

不做「白名单 `typ`」：存量登录 token 没有 `typ` 字段，白名单会让所有老会话立即失效。只拒绝两种 MCP 类型，范围最小且可验证。

新增回归测试：用 `kb:read` 静态令牌请求 `/api/v1/kb/datasets`、`/api/v1/extensions`，必须 401；同一令牌请求 `/mcp/kb` 正常。

---

## 6. 前端设计

### 6.1 内置连接器卡片

`app/core/builtin_assets.py` 从「单条常量」改为「注册表」：

```python
@dataclass(frozen=True)
class BuiltinAsset:
    code: str
    mcp_path: str
    fields: dict[str, Any]

BUILTIN_ASSETS = (EXTENSIONS_ASSET, KB_ASSET)   # testmate-extensions → /mcp/skill
                                                # testmate-kb         → /mcp/kb

def is_builtin_code(code: str) -> bool: ...
def builtin_path(code: str) -> str | None: ...
def builtin_mcp_config(code: str, base: str) -> dict[str, Any]: ...
async def ensure_builtin_assets(session: AsyncSession) -> None: ...
```

- `main.py` 改调 `ensure_builtin_assets`；
- `api/extensions.py::_to_out` 改调 `builtin_mcp_config(a.code, mcp_base)`；
- `ext_catalog.apply_index_to_db`、资产编辑/更新/删除守卫继续用 `is_builtin_code`，自动覆盖两条；
- 幂等刷新保留 `download_count` / `created_at`；`mcp_config` 仍不入库。

新增 `testmate-kb` 卡片字段：

| 字段 | 值 |
|---|---|
| `code` | `testmate-kb` |
| `name` | TestMate 知识库助手 |
| `icon` | 📚 |
| `kind` | `mcp` |
| `summary` | 让 Agent 检索知识库、读取分段，并向数据集上传或更新文档 |
| `category` | 其他 |
| `tags` | 内置 / 知识库 / MCP |
| `keywords` | 内置 / 知识库 / 文档 / 检索 / MCP / 上传 |
| `install_steps` | 复制配置 → 建 Token（`kb:read`，需要写入再勾 `kb:write`）→ 替换占位 Token → 重启会话；末尾说明二进制文件用上传票直传，上传/替换只代表「已提交」，需用 `kb_document_status` 确认解析完成 |

MCP 配置与扩展库同规则：HTTPS 不预置 headers；纯 HTTP 预置 `Authorization: Bearer <你的API Token>` 占位，因为官方 SDK 拒绝明文 http 的 OAuth token 端点。

前端卡片 / 详情抽屉 / 「🔒 内置」徽标 / 「复制 JSON」均已按 `builtin` 字段泛化，**无需改 Vue 组件**。

### 6.2 令牌与授权 UI

`frontend_web/src/api/mcp.ts`：

```ts
export type McpScope =
  | 'extensions:read' | 'extensions:write'
  | 'kb:read' | 'kb:write';
```

`views/Settings/components/McpTokens.vue`：

- 新增两个复选框：`kb:read`「读取知识库」、`kb:write`「写入知识库」（后者 `:disabled="!canKbWrite"`）；
- `scopeText()` 改为映射表，避免三元表达式继续膨胀；
- `loadScopes()` 的失败兜底改为 `['extensions:read', 'kb:read']`，只读能力在接口失败时仍可用；
- 默认勾选保持 `['extensions:read']`，不擅自替用户扩大权限。

`views/Connect/Authorize.vue` 与 `views/Connect/GrantsPanel.vue` 同步补文案：

- `kb:read`「读取知识库」：查看数据集、文档与分段，并按问题检索知识库内容；
- `kb:write`「写入知识库」：在你可操作的数据集里新建数据集、上传或替换文档、重新解析。

### 6.3 知识库页面

不新增入口按钮，不改 `views/Capability/Library/index.vue`。接入方式统一由扩展库的内置卡片承载，避免同一件事出现两个入口。后续若需要，可在概览卡加一行「MCP 接入」链接，本轮不做。

---

## 7. 错误处理与边界

| 场景 | 行为 |
|---|---|
| 数据集不存在 | 上传/建票前 404 `not_found`，不产生半成品 |
| 文档不存在 | 替换/重解析/建票前 404 |
| viewer 调写工具 | 工具层 scope 检查直接 `insufficient_scope`，不进入业务 |
| 文本工具传 `.pdf` | `invalid_document_type`，提示改用上传票 |
| 文本内容 > 2MB | `file_too_large`，提示改用上传票 |
| 二进制 > 20MB | 上传端点 413；票面上已写明 `max_bytes` |
| manual 分块数据集 | 上传成功但不自动解析，`warning` 原样返回（与网页端一致） |
| RAGFlow 不可达 | `kb_unavailable`，不透出 base_url / key |
| 票过期 / 数据集不匹配 / 用户被停用 | 401/403；票过期时 Agent 重新签票，**已传文件不受影响** |
| 替换扩展名不一致 | 422，沿用现有文案 |
| 批量中单篇失败 | 其余继续；`ok=false`，失败项进 `errors`，成功项照常入库并解析 |
| 提交成功但发起解析失败 | `ingest_started=false`，文件已入库；提示用 `kb_document_reparse` 重试，不要重新上传（会生成同名副本） |
| 解析还没完成 | `ingest_started=true`；用 `kb_document_status` 轮询，`timed_out=true` 只表示"还没好" |
| 工具返回 `ok=true` 但解析失败 | 提交成功、解析异步。`kb_document_status` 返回 `run=FAIL` + `progress_msg`；修正内容后重新上传/替换。替换场景旧文档在提交时已删除，不会自动回滚 |
| Agent 把 `ok=true` 当成解析成功 | 返回体带 `state=submitted`、每篇 `run≠DONE`、`ingest_started`；工具描述里直接写明「需查 `kb_document_status` 确认」 |
| 上传/替换请求超时、结果未知 | 先 `kb_document_list(keywords=文件名)` 确认是否已成功，再决定是否重试（重传会因 RAGFlow 同名机制生成 `(1)` 副本；替换可先用旧 `document_id` 探测：404 说明旧版已被替换） |
| 批量耗时超过 30 分钟 | 剩余文件会 401；重新签票继续，前序结果不回滚 |

---

## 8. 测试计划

### 8.1 后端（pytest，真实 MCP transport）

`tests/_mcp_protocol.py` 的 `_ENDPOINT` 当前写死 `/mcp/extensions`，改为 `endpoint: str = "/mcp/extensions"` 参数，KB 用例传 `/mcp/kb`。

新增：

- `test_kb_mcp_read.py`
  - `tools/list` 恰好 12 个工具，schema 中 `required` 与 `additionalProperties=false` 正确；
  - `kb_dataset_list` / `kb_document_list` / `kb_document_search` / `kb_document_chunks` / `kb_search` / `kb_health` 的正常路径（mock `ragflow_client`，复用 `test_kb_upload.py` 的 mock 方式）；
  - `kb_document_status`：`run=RUNNING → DONE` 的轮询；`wait_seconds` 到点返回 `timed_out=true` 且不报错；`run=FAIL` 时原样带出 `progress_msg`；
  - 只有 `kb:read` 的令牌调 `kb_document_upload` → `insufficient_scope`。
- `test_kb_mcp_write.py`
  - `kb_dataset_create`；
  - `kb_document_upload` 文本内联 → `upload_documents` 收到正确 `(name, bytes, ctype)`，`ingest_documents` 被调用；
  - `kb_document_upload` **返回即提交结束**：mock 的文档状态停在 `RUNNING` 时，返回值仍是 `state=submitted`、`run=RUNNING`，且 handler 内没有轮询等待；
  - `kb_document_update` 返回体带 `replaced`（旧 id），`state=submitted`；
  - `kb_document_reparse` 返回后 `run` 为 `UNSTART`/`RUNNING`，不等待 `DONE`；
  - `kb_document_upload` 批量 3 篇：第 2 篇超限 → `ok=false`、`uploaded=2`、`failed=1`、`errors` 含第 2 篇；前 2 篇仍入库并解析；
  - `kb_document_update` → 旧文档删除、新文档改名、归属迁移；
  - `kb_document_reparse`；
  - viewer 令牌调写工具 → `insufficient_scope`；tester 正常。
- `test_kb_mcp_ticket.py`
  - 建票前数据集不存在 → 404；
  - 同一张票连续上传 2 篇 → 都成功（可复用）；
  - 票正常直传（multipart，1 个和 5 个 `file` 部分）→ 与 REST 上传结果一致；
  - 票过期 / `ds` 不匹配 / 用户停用 / `token_version` 变化 → 401/403；
  - 票过期后用新票继续传剩余文件 → 成功，已传文件不受影响；
  - **先验票再读 body**：票无效时 monkeypatch `Request.form`，断言它没有被调用；
  - 超过 20MB → 413；
  - 替换模式：`document_id` 表单字段指向的文档被替换，返回新 id；`document_id` 不属于该数据集 → 404；
  - 替换模式带多个 `file` → 422。
- `test_mcp_auth.py` 增补
  - `mcp-static` / `mcp-oauth` 调 REST → 401；
  - 同一令牌调 `/mcp/kb` → 成功。
- `test_ext_builtin.py` 更新
  - 两条内置资产都种入；`testmate-kb` 的配置 URL 为 `{base}/mcp/kb`；
  - 两条都不可编辑/更新/删除；同步器都跳过。
- `test_mcp_oauth.py` 增补
  - `allowed_scopes(viewer)` 含 `kb:read` 不含 `kb:write`；
  - `allowed_scopes(tester)` 含 `kb:write`；
  - 令牌创建拒绝超出可授权范围的 scope。

### 8.2 前端

- `McpTokens.spec.ts`：两个新复选框渲染；无 `kb:write` 时禁用；创建请求带 `kb:read` / `kb:write`；`scopeText` 新文案。
- `authorize.spec.ts` / `grants.spec.ts`：新 scope 的标题与描述。
- `npm run typecheck`（`McpScope` 联合类型扩展后全量编译）。

### 8.3 线上验收（本机 native local）

1. 重启后端，确认启动日志无报错，扩展库出现第二张内置卡片。
2. 建一个 `kb:read` 令牌 → 用 MCP 客户端连 `/mcp/kb` → `tools/list` 返回 12 个工具。
3. 真实读路径：列出本机 RAGFlow 的数据集、文档、分段，跑一次 `kb_search`。
4. 文本写路径（单篇）：上传一篇 `.md` → 工具秒级返回 `state=submitted`、`run≠DONE`（不阻塞等解析）→ 用 `kb_document_status` 轮询到 `run=DONE` → 能检索到；再替换内容 → id 变化、内容更新，并在返回体里看到 `replaced` 指向旧 id。
5. 文本写路径（批量）：`kb_document_upload` 一次传 3 篇，其中 1 篇故意超限 → 返回 `uploaded=2 / failed=1`，`errors` 指明失败项，成功的 2 篇仍入库并解析；再用 `kb_document_update` 批量替换 2 篇 → 两个 `document_id` 都变。
6. 二进制写路径（单篇）：签票 → `curl -H "X-KB-Upload-Ticket: ..." -F "file=@<一个真实 PDF>" <upload_url>` → 文档出现且大小与本地一致。
7. 二进制写路径（批量 + 票复用）：同一张票连传 3 个文件 → 都成功；中途等待到票过期后再传第 4 个 → 401，重新签票后第 4 个成功，前 3 个不受影响。
8. 慢上传：对 10MB 级文件把客户端带宽限到 1MB/s（或人为延迟发 body）→ 票在请求开始时刻仍有效，上传不被中断。
9. 用 `kb:read` 令牌调写工具 → `insufficient_scope`。
10. 用同一个 MCP 令牌直接请求 `/api/v1/kb/datasets` → 401（加固生效）。

---

## 9. 迁移与兼容

- **无数据库迁移**：`McpApiToken.scopes` / `McpOAuthGrant.scopes` 是 JSON 列，新 scope 直接写入。
- **无 nginx 变更**：`client_max_body_size 200m` 已覆盖 20MB 上限。
- **无前端路由变更**。
- 启动时多一条内置资产种子；同步器按 code 跳过，不会被 GitLab 覆盖。
- 既有扩展库 MCP 令牌的 scope 不变、行为不变；新增的只有「MCP 令牌不能再调 REST」这一条收紧，属于安全修复。
- 单进程约束不变：OAuth 授权码仍是进程内状态。

---

## 10. 明确不做 / 后续

| 项 | 原因 |
|---|---|
| `source_url` 服务端拉取 | 本项目部署在内网，文档常位于 `10.x` / `192.168.x`。要可用就不能拦私网地址，而不拦私网就是一个任何 `kb:write` 用户都能触发的 SSRF 原语。收益低（Agent 多处理本地文件），风险高，本轮不做 |
| base64 二进制入参 | 20MB → 27MB JSON，超客户端工具调用上限且浪费上下文；扩展库的 1KB 安装包场景不可类比 |
| 删除文档 / 删除数据集 | 破坏性操作，保留在网页端由 admin 人工确认 |
| `kb_ingest` 启停工具 | 上传/替换已自动发起解析；取消解析属于运维操作，Agent 不需要 |
| 文档原文下载 | 需要另一个下载票 + 直传协议；本轮读能力由分段与检索覆盖 |
| 审计查询工具 | 治理台账面向人工，Agent 调用价值低 |
| 知识库页面新增 MCP 入口 | 与扩展库内置卡片重复；先观察使用情况 |

---

## 11. 验收标准

- [ ] `/mcp/kb` 能完成 `initialize` / `tools/list` / `tools/call`，列出 7 读 + 5 写共 12 个工具。
- [ ] `kb:read` 令牌可完成全部读工具；调用写工具返回 `insufficient_scope`。
- [ ] `kb:write` 令牌可完成建库、文本上传、文本替换、重解析。
- [ ] 文本上传 / 替换支持单次 1..5 篇批量；部分失败时返回逐篇结果（`uploaded` / `failed` / `errors`），成功项不受影响、已开始解析。
- [ ] 上传 / 替换 / 重解析工具在解析完成前返回：`ok=true` 且 `state=submitted` 仅代表已提交，每篇带 `run`；`kb_document_status` 能观察到 `RUNNING→DONE`，`FAIL` 能带出 `progress_msg`。
- [ ] `kb_document_status` 能按文档轮询解析进度；超过 `wait_seconds` 返回 `timed_out=true` 而非报错。
- [ ] 上传票绑定用户 + 数据集、30 分钟内可复用，同一张票连续传多份全部成功；票过期后重新签票可继续，已上传文件不受影响。
- [ ] 长耗时上传（body 慢于票剩余有效期）仍成功：端点先验票、再读 multipart。
- [ ] 上传票直传的 PDF 大小 / 类型与网页端上传结果一致，且自动发起解析。
- [ ] 所有写操作在 `kb_audits` 留下与网页端一致的记录（actor、动作、文档名、大小）。
- [ ] 扩展库出现「TestMate 知识库助手」内置卡片，复制的 JSON 指向 `/mcp/kb`；HTTPS 无占位 header，HTTP 有占位 header。
- [ ] 令牌页与授权页展示四项权限，viewer 的 `kb:write` 置灰。
- [ ] MCP 静态令牌与 OAuth 令牌直接请求 REST API 返回 401。
- [ ] 后端 pytest 全绿；前端 typecheck 与相关单测全绿。
