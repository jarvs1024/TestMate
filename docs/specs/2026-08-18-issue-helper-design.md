# 辅助提单系统 — 方案 (P0 设计稿)

> 起草: 2026-08-18 · 状态: 设计中(待评审) · 范围: 仅方案, 不含实现

## 1. 背景与目标

SSD 测试组日常向 pingcode 提问题单存在两个痛点:

- **字段不规整**: 提单人自由发挥, 关键信息(主机 SN / FW 版本 / 测试阶段 / 失败现象)经常缺漏, 二次沟通成本高
- **现场信息搬运成本大**: 串口 log / 训练器 trace / Quarch 仪器输出散落在不同机器上, 提单人靠人肉打包

**目标**: 在 TestMate 广场页面增加"辅助提单"入口, 通过:

1. **结构化模板**: 复用现有 `/Users/jarvs/Documents/工作/问题单模板.docx` 的字段, 内置一个"Bug 提单(标准)"模板, 强制关键字段必填
2. **外部系统联动**: 一键调用自研 aitest 系统, 自动拉日志 / 关键字段填充表单
3. **一键提单**: 表单填齐后, 调 pingcode API 提交, 记录工单号回写到 TestMate 草稿

**非目标**:

- 不做 issue 全生命周期管理(只看 pingcode 单号, 不在 TestMate 里复刻状态流转)
- 不替代 pingcode 现有 UI(只做"提单这一刻"的辅助)
- 不动现有 8 个后端路由的契约

## 2. 架构总览

```
┌─────────────────────────────────────────────────────────────────┐
│  Plaza (广场)                                                    │
│    └─ 新增卡片: "辅助提单" → 跳路由 /issue-helper                 │
└──────────────────────┬──────────────────────────────────────────┘
                       │
                       ▼
┌─────────────────────────────────────────────────────────────────┐
│  View: IssueHelperPage (/issue-helper)                           │
│  ┌──────────────┬──────────────────┬─────────────────────────┐  │
│  │ 模板选择      │ 动态表单(按模板)   │ 实时预览(markdown)        │  │
│  │              │  - 必填校验       │  - 同步渲染              │  │
│  │              │  - aitest 拉取   │  - 复制到剪贴板          │  │
│  └──────────────┴──────────────────┴─────────────────────────┘  │
│         [保存草稿]            [一键提单到 pingcode]                │
└──────────────────────┬──────────────────────────────────────────┘
                       │ axios + JWT
                       ▼
┌─────────────────────────────────────────────────────────────────┐
│  FastAPI 新增路由: /api/issue-templates · /api/issues            │
│  ┌──────────────────┐ ┌──────────────────┐ ┌────────────────┐  │
│  │ issue_template    │ │ aitest_client    │ │ pingcode_client │  │
│  │   service         │ │   (httpx async)  │ │   (httpx async) │  │
│  └──────────────────┘ └──────────────────┘ └────────────────┘  │
└─────────────────────────────────────────────────────────────────┘
```

外部依赖:

- **pingcode**: 私有部署 or SaaS(待确认), 提供 issue 创建 API
- **aitest**: 自研, 提供 run_id 维度的日志 / 字段查询接口(待确认协议)
- **Dify / RAGFlow**: 本期**不依赖**, 后续可加"AI 润色描述"作为可选

## 3. 页面入口 — 两个候选

### 候选 A: 独立 view + 独立路由 (推荐)

- 新增 `frontend_web/src/views/IssueHelper/index.vue`, 注册路由 `/issue-helper`
- 不入 `Agent` 表, 不走 `AgentRunner`
- Plaza 页面**新增一张固定卡片**(硬编码在 Plaza/index.vue, 跟搜索/筛选平级展示, 不参与 `listAgents` 加载)

**优点**:

- 不污染 `Agent` 模型语义(辅助提单不是 AI 智能体)
- 页面交互复杂(wizard + 实时预览), 独立 view 便于维护
- 配置集中在 settings, 不混在 agent.engine_config 里

**缺点**:

- Plaza 卡片目前是"智能体网格", 多一张非智能体卡视觉上有点突兀 → 用专门样式区分(置顶 + 不同色块)

### 候选 B: 入 Agent 表 + route 跳转

- 在 `agents` 表插入一条 `code=issue-helper` 的记录
- `route='page:issue-helper'`, `engine=builtin`, `category` 新增 `ssd-issue`
- 复用现有 `AgentCard` 展示

**优点**: 改动最小, 跟现有智能体入口一致
**缺点**: 把"AI 智能体"和"提单工作流"混在一起, 模型语义被拉伸; 后续做提单统计 / 权限隔离时, 会发现这卡不是 Agent 又要跟 Agent 共用表

**结论**: 选 A。Agent 模型已在 `engine_config` 里塞过不少不是 AI 的配置, 这次别再加。

## 4. 模板系统设计

### 4.1 存储

新增一张表 `issue_templates`(放 `backend_gateway/app/models/issue_template.py`):

| 字段 | 类型 | 说明 |
|---|---|---|
| `code` | str(64) PK-like | 模板唯一标识, 例 `bug-standard` |
| `name` | str(64) | 显示名, 例 "Bug 提单(标准)" |
| `category` | str(32) | `bug` / `feature` / `compat` / `perf`(枚举值, 便于后续分类) |
| `version` | str(16) | 模板自身版本, 升级时递增 |
| `field_schema` | JSON | 字段定义数组, 见 4.2 |
| `markdown_template` | Text | Jinja2 模板, 用 `{{ field_key }}` 占位 |
| `pingcode_mapping` | JSON | pingcode 字段名 → 本地 field_key 映射, 见 4.3 |
| `is_builtin` | bool | 内置模板(由 seed 写入, 不可删) / 用户自定义 |
| `is_active` | bool | 上下架开关 |
| `created_by` / `created_at` / `updated_at` | — | 审计 |

**为什么不放在 `system_settings`**: settings 是 KV 单值, 模板是有版本/分类/上下架的集合资源, 用表更合适。settings 里只放"全局开关"(mock 模式、aitest 默认 endpoint 等)。

### 4.2 field_schema 格式

参照现有 `Agent.input_schema`, 但扩展 `aitest_ref` / `file_multi` / `enum` 等类型:

```json
[
  {"key": "title",        "label": "BUG 标题",      "type": "text",       "required": true,
   "placeholder": "【BUG】【项目】【测试阶段】问题描述"},
  {"key": "test_phase",   "label": "测试阶段",      "type": "enum",       "required": true,
   "options": ["100%网表前", "TO 前", "回片后", "产品化-TR4", "产品化-TR4A",
               "产品化-TR5", "产品化-TR6", "产品化-TR6 后", "生产"]},
  {"key": "module",       "label": "测试特性/开发模块", "type": "text",    "required": true},
  {"key": "precondition", "label": "预置条件",      "type": "textarea",   "required": true},
  {"key": "steps",        "label": "关键操作步骤",  "type": "textarea",   "required": true},
  {"key": "expected",     "label": "预期效果",      "type": "textarea",   "required": true},
  {"key": "actual",       "label": "测试失败现象",  "type": "textarea",   "required": true},
  {"key": "host_info",    "label": "主机信息",      "type": "object",     "required": true,
   "fields": [
     {"key": "ip",      "label": "IP/主机名",  "type": "text", "required": true},
     {"key": "sn",      "label": "SN",         "type": "text", "required": true},
     {"key": "os",      "label": "OS",         "type": "text", "required": true},
     {"key": "ssd_topology", "label": "SSD 数量及连接方式", "type": "text", "required": true}
   ]},
  {"key": "fw_version",   "label": "FW 版本",      "type": "text",       "required": true,
   "aitest_ref": {"endpoint": "/api/run/{run_id}/fw", "path": "fw_version"}},
  {"key": "aitest_run_id", "label": "aitest run_id", "type": "text",     "required": false,
   "help": "填入后, 点右侧'自动收集'可一键拉日志和关键字段"},
  {"key": "logs",         "label": "测试日志附件",  "type": "file_multi", "required": false,
   "accept": [".log", ".txt", ".qac", ".csv", ".evtx"], "max_count": 20}
]
```

**字段类型枚举(初版)**: `text` / `textarea` / `number` / `enum` / `bool` / `date` /
`object`(嵌套子表单) / `file` / `file_multi` / `machine_select`(复用现有) /
`aitest_ref`(只存 run_id, 提交时由 aitest_client 拉取实际内容并塞到日志)

### 4.3 pingcode_mapping 格式

```json
{
  "title":        "{{title}}",
  "description":  "## 预置条件\n{{precondition}}\n\n## 步骤\n{{steps}}\n\n## 预期\n{{expected}}\n\n## 实际\n{{actual}}",
  "project_id":   "{{settings.pingcode.project_id}}",
  "priority":     "{{priority | default('medium')}}",
  "labels":       ["testmate-auto", "phase:{{test_phase}}"],
  "custom_fields": {
    "fw_version":   "{{fw_version}}",
    "host_ip":      "{{host_info.ip}}",
    "host_sn":      "{{host_info.sn}}",
    "module":       "{{module}}",
    "aitest_run_id":"{{aitest_run_id}}"
  }
}
```

说明:

- `{{key}}` 走 Jinja2 渲染, 字段缺失时**强制报错**(除非显式 `| default(...)`)
- `{{settings.X.Y}}` 引用 system_settings 里的值, 便于统一改默认项目/标签
- `labels` 支持模板字符串拼接

### 4.4 内置"Bug 提单(标准)"模板来源

直接复刻 `/Users/jarvs/Documents/工作/问题单模板.docx` 的字段结构(本次方案已抄录 11 节内容), `code=bug-standard`, `is_builtin=True`, seed 时插入。

## 5. aitest 集成

### 5.1 假设(待确认)

- aitest 提供 REST API, 至少支持按 `run_id` 拉取:
  - `GET /api/runs/{run_id}` → 关键字段(fw_version / host_info / module)
  - `GET /api/runs/{run_id}/logs?type=serial` → 串口日志
  - `GET /api/runs/{run_id}/logs?type=trace` → 训练器 trace
  - `GET /api/runs/{run_id}/logs?type=quarch` → 仪器输出
  - `POST /api/runs/{run_id}/artifacts` → 下载附件
- 认证: Bearer token(参照现有 review_agent 配置模式)

> **风险**: aitest 实际接口协议待确认。如果协议不同(RPC / 消息队列 / 拉文件), 需要在 `aitest_client` 里再封装一层适配。

### 5.2 前端交互

填了 `aitest_run_id` 后, 表单右上角出现"🔄 自动收集"按钮:

- 点击 → `POST /api/issues/{draft_id}/auto-collect`
- 后端拿到 run_id → 调 aitest_client 批量拉数据 → 回写到 `field_values`
- 前端轮询 / SSE 推送填充进度(待定, 先用一次性返回 + 字段标"已自动填充")

**降级**:

- aitest 超时(>10s) → 字段不填, 提示"aitest 无响应, 请手动补"
- aitest 未配置(`AITEST_MOCK=true` / 配置缺失) → 按钮置灰, 提示"未配置"

## 6. pingcode 集成

### 6.1 假设(待确认)

- pingcode 提供 issue 创建 API(典型 REST): `POST /api/v1/issues` 或工作项类接口
- 认证: API Token(类似 `pat_xxx`)放 header
- 响应: 返回 `issue_id` / `issue_key`(例 `BUG-123`)

> **风险**: pingcode 私有部署 vs SaaS 路径不同; 工作项 / 缺陷 / 任务三类接口分开。**提单前需拉一次 pingcode 真实接口文档**, 否则 mapping 全是猜的。

### 6.2 pingcode_client 形态

参照 `backend_gateway/app/core/dify_client.py` 写一个 `pingcode_client.py`:

```python
class PingCodeClient:
    def __init__(self, base_url, api_key, mock=False): ...
    async def create_issue(self, payload: dict) -> IssueRef: ...
    async def get_issue(self, issue_key: str) -> dict: ...
    async def list_projects(self) -> list[dict]: ...   # 给模板配置下拉用
```

`PingCodeMockClient` 走 fake 流(参照 `DIFY_MOCK`), 沙箱环境可用。

## 7. 后端数据模型 + API

### 7.1 新增表

- `issue_templates`(见 4.1)
- `issue_drafts`: 草稿, 字段含 `id` / `template_code` / `field_values` / `status`(`draft`/`submitting`/`submitted`/`failed`) / `pingcode_issue_key` / `error_msg` / `created_by` / `created_at` / `updated_at`

### 7.2 新增 API 路由(`backend_gateway/app/api/issue.py`)

| Method | Path | 说明 |
|---|---|---|
| GET | `/api/issue-templates` | 列出可用模板(active + 用户可见) |
| GET | `/api/issue-templates/{code}` | 取单模板详情) |
| POST | `/api/issues/draft` | 创建草稿 |
| GET | `/api/issues/draft/{id}` | 取草稿 |
| PATCH | `/api/issues/draft/{id}` | 更新字段 |
| POST | `/api/issues/draft/{id}/auto-collect` | 触发 aitest 自动收集 |
| POST | `/api/issues/draft/{id}/submit` | 一键提交到 pingcode |
| GET | `/api/issues/draft/{id}/preview` | 渲染 markdown 预览(不提交) |

> **注意**: 草稿**不存**渲染好的 markdown, 每次预览 / 提交都现渲染, 模板改了草稿自动跟上。

### 7.3 权限

- `viewer`: 看不到入口
- `tester` / `admin`: 可创建/编辑/提交草稿, 仅看自己的草稿
- `admin`: 可见全部草稿 + 可管理模板(模板的 CRUD 走 `/api/issue-templates` 的 admin-only 端点)

## 8. 前端页面结构

```
IssueHelperPage
├── IssueHeader            标题 + 模板选择器 + 版本
├── IssueForm (左, 60%)    动态表单, 按 field_schema 渲染
│   ├── FieldRenderer      text/textarea/enum/object/file/...
│   ├── AitestCollectPanel aitest_run_id + 自动收集按钮 + 进度
│   └── FileDropZone       拖拽 / 点选, 走 /api/uploads (复用现有?)
├── IssuePreview (右, 40%) markdown 实时渲染 + "复制"按钮
├── IssueToolbar (底)      保存草稿 / 提交(调 submit)
└── IssueDraftList (顶 tab)  "新建" / "我的草稿" / "已提交"
```

`IssueForm` 用 Element Plus 组件 + 自定义渲染器; 不引第三方 form-builder(避免膨胀)。

**校验**: 提交前前端先跑一遍必填校验, 后端再校验一次(防绕过)。

## 9. 配置项(注册到 `settings_store.py`)

```python
{
    "key": "aitest.base_url",          "category": "integration",
    "value_type": "url",  "default": settings.AITEST_BASE_URL,
    "description": "aitest 系统 API 基础地址"},
{"key": "aitest.api_key",             "category": "integration",
 "value_type": "secret", "default": settings.AITEST_API_KEY,
 "description": "aitest Bearer Token"},
{"key": "aitest.mock_mode",           "category": "integration",
 "value_type": "bool",  "default": settings.AITEST_MOCK,
 "description": "沙箱模式: 不真调 aitest, 返回 fixture"},

{"key": "pingcode.base_url",          "category": "integration",
 "value_type": "url",  "default": settings.PINGCODE_BASE_URL,
 "description": "pingcode API 基础地址"},
{"key": "pingcode.api_key",           "category": "integration",
 "value_type": "secret", "default": settings.PINGCODE_API_KEY,
 "description": "pingcode API Token (pat_xxx)"},
{"key": "pingcode.project_id",        "category": "integration",
 "value_type": "string","default": settings.PINGCODE_PROJECT_ID,
 "description": "默认目标项目 ID (提单模板里 {{settings.pingcode.project_id}} 用)"},
{"key": "pingcode.mock_mode",         "category": "integration",
 "value_type": "bool",  "default": settings.PINGCODE_MOCK,
 "description": "沙箱模式: 不真调 pingcode, 返回 fake issue_key"},
```

`.env.example` 同步加 6 个变量。

## 10. 可观测性

- 沿用 structlog JSON 日志, 每条草稿/提交都打 `issue.draft.created` / `issue.draft.submitted` / `issue.draft.failed`
- 失败时记录 `aitest_error` / `pingcode_error` 完整堆栈(trace_id 一并)
- 后续可在 PM dashboard 加提单漏斗(创建草稿 → 自动收集成功 → 提交成功), **本期不做**

## 11. 降级与安全

- aitest 不可达 → 字段不自动填, 表单仍可手填 + 提交(pingcode 不依赖 aitest)
- pingcode 不可达 → 草稿存为 `submitting`, 后台 worker(P1) 重试; 本期先在前端弹错, 让用户重试
- 文件上传: 走 `/api/uploads`(若已存在), 否则只存文件名 + 元信息到草稿, 真正上传在 `submit` 时随 pingcode API 一起带过去(取决于 pingcode 是否支持附件)
- 模板 `markdown_template` / `pingcode_mapping` 用 Jinja2 sandbox(不引 `{% exec %}`, 不引文件读写), 防被恶意模板 RCE

## 12. 待确认项(动手前必须问清楚)

| # | 问题 | 影响范围 |
|---|---|---|
| Q1 | pingcode 提单 API 的真实 endpoint / 鉴权方式 / 字段名 | `pingcode_mapping` 全套 |
| Q2 | pingcode 私有部署还是 SaaS, 默认 project_id 是多少 | 配置默认值 |
| Q3 | aitest 接口协议(REST/RPC/...), 鉴权方式, 字段命名 | `aitest_client` 整套 |
| Q4 | aitest 一次 run_id 能拉到哪些字段 / 日志类型 | `aitest_ref` 字段配置 |
| Q5 | 提单时是否要带附件 / 附件怎么传(直传 / 走 OSS 中转) | `file_multi` 字段类型是否要做 |
| Q6 | 是否需要从 pingcode 拉"项目列表 / 成员列表"做下拉 | 前端表单复杂度 |
| Q7 | "我的草稿"要不要支持 admin 跨人查看 | 后端权限模型 |
| Q8 | 内置模板只放一个"标准 Bug", 还是要再加"性能 / 兼容 / FW 比对"几套 | `issue_templates` seed 数据量 |

## 13. 实现阶段拆分(待评审确认后再启动)

### Phase 1: MVP(2~3 天, 跑通端到端)

1. 加 `issue_templates` / `issue_drafts` 两张表 + alembic 迁移
2. seed 内置 `bug-standard` 模板(直接抄 docx 字段)
3. 后端: `/api/issue-templates` 列表 + 详情, `/api/issues/draft` 增删改
4. 前端: `/issue-helper` 页面 + Plaza 加卡片 + 动态表单 + 实时预览
5. **不接** pingcode / aitest, submit 按钮先打"待对接"

### Phase 2: 接入 aitest(1~2 天)

1. 拿到 aitest 接口文档后, 写 `aitest_client` + 配置项
2. 后端: `/auto-collect` 端点
3. 前端: 自动收集按钮 + 进度反馈

### Phase 3: 接入 pingcode(1~2 天)

1. 拿到 pingcode 接口文档后, 写 `pingcode_client`
2. `pingcode_mapping` 配字段
3. 后端: `/submit` 端点 + 失败重试状态
4. 前端: 提交后跳转到 pingcode 单号链接

### Phase 4: 打磨(滚动)

- 模板管理页(在设置里加一个 tab)
- 我的草稿列表 + 筛选
- 提单统计(PM dashboard 增量)

---

## 附录 A: 与现有架构的契合点

- 配置层: 复用 `SystemSetting` + `settings_store` 注册表模式, 加 `integration` 分类
- 前端布局: 复用 `MainLayout`, 跟其他 view 一致
- 鉴权: 复用 JWT + RBAC, 不另起
- 日志: 复用 `structlog`, 不引新依赖
- HTTP 客户端: 复用 `httpx`(已在 `dify_client` / `ragflow_client` 用), 不引 requests

## 附录 B: 不做什么(明确)

- 不做 issue 全生命周期(状态流转 / 评论 / 验收) — 都在 pingcode 看
- 不做"AI 润色描述" — 后续可选
- 不动现有 Agent / Plaza 数据契约
- 不引入新前端组件库 / 后端依赖
