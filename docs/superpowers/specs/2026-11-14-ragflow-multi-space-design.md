# RAGFlow 多用户空间支持 — 设计

- 日期: 2026-11-14
- 状态: 已确认（方案在会话中逐项确认后落文档）
- 涉及: backend_gateway（模型 / 凭据解析 / REST / MCP / 审计）、frontend_web（知识库页 / 设置页）

## 1. 背景

TestMate 目前只支持配置**一把** RAGFlow API key（`system_settings.ragflow.api_key`）。
RAGFlow 的 API key 与**用户空间**一一对应：换 key 就换整套数据集、文档、分段。
因此现在知识库页只能看到最后一个被配置用户的数据。

实测（本机 RAGFlow，2026-11-14）：

| RAGFlow 账号 | 密钥来源 | 可见数据集 |
| --- | --- | --- |
| jarvs888@gmail.com | 现有 `ragflow.api_key` | 协议文档 / 项目管理 / 技术文档 / 部署运维 |
| jarvs889@gmail.com | 新 key（仅用于本地验证，不落仓库） | 空 |

结论：一把 key = 一个用户空间；需要一个可切换、可配置多把 key 的空间模型。

## 2. 目标

1. 设置页可配置**多个用户空间**（名称 + API key），并指定**默认空间**。
2. 知识库页可切换空间；切换后概览、数据集、文档、健康状态全部显示切换后的空间。
3. 当前用户对知识库的**所有读写接口**跟随当前空间。
4. MCP 知识库工具支持指定空间，未指定时用默认空间。
5. 操作记录增加「用户空间」维度，可按空间筛选。
6. 知识检索 / 知识对话两个 iframe 保持不变（继续用 `search.embed_url` / `chat.embed_url`）。

## 3. 非目标

- 每个空间独立 RAGFlow 地址（base_url 仍为全局唯一）。
- 每个空间独立检索 / 对话嵌入配置。
- MCP 令牌绑定空间（本次只做工具参数）。
- 删除空间时清理 RAGFlow 侧数据（只删 TestMate 配置）。

## 4. 数据模型

### 4.1 新表 `ragflow_spaces`

| 列 | 类型 | 说明 |
| --- | --- | --- |
| `id` | varchar(32) PK | `sp_` + 8 位 hex |
| `name` | varchar(64) unique, not null | 展示名，如「默认空间（jarvs888）」 |
| `api_key_cipher` | text, not null | AES-256-GCM 密文（`app.integrations.crypto`） |
| `is_default` | bool, not null, default false | 全局唯一默认空间 |
| `created_by` | bigint null | 创建人（管理员） |
| `created_at` / `updated_at` | datetime | |

不存明文 key、不存 key 提示；管理员查看时解密后掩码。

### 4.2 审计表扩展 `kb_audits`

新增：

- `space_id` varchar(32) not null default ''
- `space_name` varchar(64) not null default ''（写入时快照，改名不影响历史）
- 索引 `ix_kb_audits_space_created (space_id, created_at)`

`kb_dataset_meta` / `kb_document_meta` **不改**：主键是 RAGFlow 的 dataset/document id，本身全局唯一。

## 5. 后端：凭据解析

### 5.1 空间服务 `app/core/ragflow_spaces.py`

- `list_spaces()` / `get_space(id)` / `default_space()`
- `resolve(space_id | None)`：空 → 默认空间；未知 → 抛 `RagflowSpaceError`（消息含可用空间 id 与名称）
- `create_space(name, api_key, is_default, actor)` / `update_space(...)` / `delete_space(id)` / `set_default(id)`
- `credentials(space)` → `(base_url, api_key)`；base_url 读 `ragflow.base_url` 并做 `_rewrite_loopback`
- 兼容兜底：表为空时用旧 `ragflow.api_key` 充当默认空间（启动迁移会先补上表）
- key 加解密：`encrypt_secret(key, user_id=0, provider="ragflow-space")`

### 5.2 `ragflow_client.py`

每个公开函数增加 `space_id: str | None = None`，内部 `_config(space_id)` / `_headers(space_id)` 统一解析。
**不用 contextvar**——显式传参，测试与 MCP/REST 行为一致。

### 5.3 REST 解析

- 新增依赖 `resolve_kb_space(request)`：读请求头 `X-KB-Space`，空则默认空间。
- `app/api/kb.py` 所有端点接收空间并向下透传（数据集、文档、分块、搜索、下载、上传、更新、重解析、删除、健康）。
- 上传票：claim 增加 `sid`；`ticket-upload` 以票内空间为准，不依赖请求头。
- 全局 `/api/v1/health` 聚合探针仍用默认空间。

## 6. REST 空间管理 API

权限：**读** = 所有登录用户；**写** = admin。

| 方法 | 路径 | 说明 |
| --- | --- | --- |
| GET | `/api/v1/kb/spaces` | `{items: [{id, name, is_default, configured, key_masked?}], default_id}`；`key_masked` 仅 admin |
| POST | `/api/v1/kb/spaces` | `{name, api_key, is_default?}` |
| PUT | `/api/v1/kb/spaces/{id}` | `{name?, api_key?, is_default?}`；`api_key` 空 = 不改 |
| DELETE | `/api/v1/kb/spaces/{id}` | 禁止删默认空间；RAGFlow 数据不动；审计/归属保留 |
| POST | `/api/v1/kb/spaces/{id}/test` | 用该空间 key 探 datasets |

错误必须自解释（中文名 + 当前值 + 合法值），例如空间不存在时列出可用空间；重名给出现有名称。

设置变更写 `AssetAudit`（`setting:ragflow.spaces`），密钥记 `***`。

## 7. MCP

- 12 个 `kb_*` 工具增加可选 `space_id`（string，默认 `""`）。
- 新增 `kb_space_list`（`kb:read`）：返回 `[{id, name, is_default}]`。
- `kb_dataset_list` 等结果回带 `space_id` / `space_name`；写入类结果同样回带。
- 未传 `space_id` → 默认空间；未知空间 → `invalid_arguments`，消息列出可用空间。
- `kb_search` 跟随空间（页面 iframe 不受影响）。
- 上传票返回与 claim 包含空间；`kb_document_write_ticket` 输出 `space_id`。
- ⚠️ 工具 schema 变更后，MCP 客户端需重新连接以刷新 `tools/list` 缓存。

## 8. 前端

### 8.1 API 层

- `api/kb.ts` 增加空间类型与 CRUD。
- 所有 `/kb/*`（`/kb/spaces` 除外）请求自动带 `X-KB-Space`：当前选择存 `localStorage['testmate:kb-space']`。
- 下载用 `fetch`，单独加同一请求头。

### 8.2 知识库页

- 概览卡标题行增加空间切换器（当前空间名 + 下拉）。
- 切换：保存选择 → 清空 datasets / docsByDataset / 审计 / 健康缓存 → 重新加载（`loadAll` + `warmupAllDocs` + `loadAudits(1)`）。
- 用 `spaceEpoch` 丢弃切换前发出的迟到响应，防止旧空间数据落进新空间页面。
- 概览、数据集、文档、上传 / 新建 / 更新 / 删除 / 下载全部跟随。
- 操作记录新增「空间」列 + 空间筛选（默认「全部空间」，独立于切换）。
- 检索 / 对话 iframe、轮询、搜索逻辑不变。

### 8.3 设置页

新增 admin 专属「📚 知识库空间」section：

- 空间列表（名称、密钥掩码、是否默认、连通状态）
- 新增 / 编辑（改名、换 key）/ 删除 / 设为默认 / 测试连接
- 复用现有设置页的按钮与错误提示风格

非管理员：知识库页可切换空间，但设置页看不到该 section。

## 9. 迁移与兼容

1. Alembic `0038_ragflow_spaces`：建表 + `kb_audits` 加列加索引（可重复执行判断）。
2. 启动 `ensure_legacy_space()`（在 `seed_defaults` 之后）：
   - 无空间记录且旧 `ragflow.api_key` 非空 → 建「默认空间」并设默认；
   - 把 `kb_audits.space_id = ''` 的历史行回填到该空间。
3. `ragflow.api_key` 从 `SETTING_SCHEMA` 移除（DB 行保留用于回滚/迁移，不加入 `DEPRECATED_KEYS`，避免启动即删）。
4. `ragflow.base_url` 保留为全局设置，文案改为「所有空间共用」。
5. 未配置空间且无旧 key：行为同现在（未配置，返回空/降级）。

## 10. 安全

- key 落库 AES-256-GCM；API 不回明文；非 admin 连「是否配置」都不返回。
- 空间管理写操作 admin only；切换空间所有登录用户可用，读写权限仍由 `kb_policy` 判定。
- 日志与审计不记录 key。
- 会话中提供的新 key 仅用于本地配置，不写入代码、文档、测试或提交。

## 11. 验证

后端：

- 空间 CRUD、权限、加密往返、默认唯一、删除默认被拒。
- `ragflow_client` 调用确实携带空间（用假客户端捕获参数）。
- 非法空间返回中文可行动错误。
- 审计写入含 space_id / space_name，筛选生效。
- 上传票携带空间并以其为准。
- 无 space 参数时默认空间兼容旧行为。

MCP：

- 契约测试更新 required / 可选参数集合，新增 `kb_space_list`。
- 带 / 不带 `space_id` 的读写契约。

前端：

- 空间选择持久化、切换清缓存、迟到响应丢弃。
- 审计空间列与筛选。
- 设置页空间管理。

端到端（本机）：

- 通过管理接口新增 jarvs889 空间（key 不落仓库）。
- 两空间数据集数量不同；切换后概览/数据集正确。
- 在一个空间上传/删除不影响另一个空间。
- MCP 带 / 不带 `space_id` 命中正确空间。
- 操作记录显示空间并可筛选。
- 检索 / 对话 iframe 无回归。
- 截图核对页面。

## 12. 风险与注意

- `INTEGRATION_CREDENTIAL_KEY` 更换会导致已存空间 key 不可解（与现有集成凭据一致），需在运维文档注明。
- RAGFlow 的 dataset 名称唯一性只在单空间内成立；本次改为**按空间独立**，允许不同空间同名。
- 空间被删除后，其 RAGFlow 数据仍在 RAGFlow 中；重新添加同 key 的空间即可再次看到。
