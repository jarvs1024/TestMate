# TestMate 智能体市场（Agent Marketplace）设计方案

> 版本: v1.0 · 2026-10-14
> 定位: 把团队沉淀的 AI 资产（插件 / 技能 / 连接器）做成可检索、可审核、可安装、可版本管理的内部市场，并对外以 MCP + 插件形态分发到 Qoder 等 AI Agent 宿主。

---

## 1. 为什么要做

当前 TestMate 的 `agents` 表本质是**执行注册表**：一行 = 一个能在平台里跑起来的智能体（绑 Dify workflow / n8n flow / builtin）。它解决的是"平台能调用什么"，不解决：

- 团队成员写的 prompt / 脚本 / MCP server **散落在各自电脑上**，无法沉淀和共享
- 没有**检索入口**——新人不��道团队里已经有什么现成资产，只能问人
- 没有**版本与审核**——改坏了直接生效，没有灰度和回滚
- 没有**分发通道**——资产出不了 TestMate，进不了 Qoder、Cursor、minimax Code 等宿主的工具链

本方案补的就是这一层：**资产注册表 + 分发通道**，且刻意不改动现有 `agents` 执行链路，降低侵入。

## 2. 现状盘点

已具备（可直接复用）：

| 能力 | 位置 | 说明 |
|---|---|---|
| RBAC 三级 | `app/models/user.py` | admin / tester / viewer |
| 版本与状态枚举 | `app/models/agent.py` | `version` + `AgentStatus`(draft/alpha/beta/stable/deprecated) |
| 灰度与可见性 | `app/models/agent.py` | `visibility` / `allowed_roles` / `beta_ratio` |
| 标签与描述 | `app/models/agent.py` | `tags` / `summary` / `use_when` / `not_for` |
| DB 配置中心 | `app/core/settings_store.py` | env > DB > 默认值，UI 可改，**适合放 webhook / 审核人名单** |
| 迁移工具链 | `alembic/` | 当前 0003，新增从 0004 起 |
| 前端设计体系 | `frontend_web/src/styles` | design tokens，Element Plus + Tailwind |

缺口：

- `app/api/notify.py` 是 **P0 占位**（只返回 `{"status":"ok"}`），钉钉**完全没实现**
- 广场搜索是**纯前端** `Array.filter`，无索引、无分页、无排序权重
- 无资产包存储、无版本历史、无安装记录、无审核流

## 3. 核心概念模型

四个新概念，与现有 `Agent` 并存而非替代：

```
Asset (资产)          —— 市场里的一个条目，如"SSD 日志医生"
  └─ AssetVersion     —— 某个不可变版本，含 manifest + 包体 + 审核状态
       └─ AssetInstall —— 某用户/某宿主装了什么版本
AssetReview           —— 审核流水（谁在何时批/驳，理由）
```

**与现有 `Agent` 的关系**：一个 Asset 通过 `bind_agent_code` 可选地绑定到一个已存在的 `Agent`。绑定后，该资产在 TestMate 内可直接"运行"（走 AgentRunner），同时又能被装进 Qoder。**没绑定的资产照样能上架**——纯分发型资产（别人的 skill、通用 MCP）不需要在 TestMate 里能跑。这条分界线很重要，否则市场会被"必须在平台可运行"这个约束卡死。

## 4. 数据模型

新增 4 张表（alembic `0004_marketplace.py`）：

```sql
-- 资产主表
CREATE TABLE assets (
  id                BIGINT PK AUTO_INCREMENT,
  code              VARCHAR(64)  NOT NULL,          -- 全局唯一 slug，如 ssd-log-doctor
  name              VARCHAR(128) NOT NULL,
  icon              VARCHAR(16)  NOT NULL DEFAULT '🧩',
  asset_type        ENUM('plugin','skill','mcp') NOT NULL,
  category          VARCHAR(32)  NOT NULL,          -- 复用 AgentCategory 语义，另加 general
  summary           VARCHAR(255) NOT NULL,
  readme            MEDIUMTEXT   NULL,              -- 详情页长描述 (markdown)
  tags              JSON         NOT NULL,
  keywords          JSON         NOT NULL,          -- 搜索用，同义词/技术词
  license           VARCHAR(32)  NOT NULL DEFAULT 'internal',
  homepage          VARCHAR(512) NULL,

  owner_id          BIGINT       NOT NULL,
  visibility        VARCHAR(16)  NOT NULL DEFAULT 'team',  -- team | public | private
  status            ENUM('draft','pending_review','published','deprecated','rejected')
                                   NOT NULL DEFAULT 'draft',
  current_version_id BIGINT      NULL,              -- → asset_versions.id

  bind_agent_code   VARCHAR(64)  NULL,              -- 可选: 绑到现有 Agent 就能在平台内运行
  is_featured       TINYINT(1)   NOT NULL DEFAULT 0,

  download_count    BIGINT NOT NULL DEFAULT 0,
  view_count        BIGINT NOT NULL DEFAULT 0,
  created_at        DATETIME NOT NULL,
  updated_at        DATETIME NOT NULL,
  UNIQUE KEY uk_code (code),
  KEY idx_type_status (asset_type, status),
  FULLTEXT KEY ft_search (name, summary, keywords)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

-- 版本表：一个 asset 的不可变快照
CREATE TABLE asset_versions (
  id              BIGINT PK AUTO_INCREMENT,
  asset_id        BIGINT NOT NULL,
  version         VARCHAR(32) NOT NULL,        -- semver: 1.2.0
  manifest        JSON NOT NULL,               -- 统一清单（见 §5）
  readme          MEDIUMTEXT NULL,             -- 该版本快照，不跟主表走
  changelog       TEXT NULL,
  package_path    VARCHAR(512) NOT NULL,       -- volume 内相对路径
  package_sha256  CHAR(64) NOT NULL,
  package_size    BIGINT NOT NULL,
  scan_status     ENUM('pending','passed','failed','skipped') NOT NULL DEFAULT 'pending',
  scan_report     JSON NULL,
  review_status   ENUM('pending','approved','rejected') NOT NULL DEFAULT 'pending',
  reviewer_id     BIGINT NULL,
  review_comment  TEXT NULL,
  reviewed_at     DATETIME NULL,
  created_by      BIGINT NOT NULL,
  created_at      DATETIME NOT NULL,
  UNIQUE KEY uk_asset_version (asset_id, version),
  KEY idx_review (review_status, created_at)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

-- 安装记录：谁、哪台机器、什么宿主、装了哪版
CREATE TABLE asset_installs (
  id            BIGINT PK AUTO_INCREMENT,
  asset_id      BIGINT NOT NULL,
  version_id    BIGINT NOT NULL,
  user_id       BIGINT NOT NULL,
  client_id     VARCHAR(64) NOT NULL,      -- 宿主实例标识 (Qoder/Code 生成 UUID)
  client_kind   ENUM('qoder','minimax-code','cursor','claude','cli','web') NOT NULL,
  client_version VARCHAR(32) NULL,
  status        ENUM('installed','updated','uninstalled') NOT NULL DEFAULT 'installed',
  installed_at  DATETIME NOT NULL,
  updated_at    DATETIME NOT NULL,
  UNIQUE KEY uk_install (asset_id, client_id),
  KEY idx_client (client_id, status)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

-- 审核/操作流水（审计）
CREATE TABLE asset_audits (
  id          BIGINT PK AUTO_INCREMENT,
  asset_id    BIGINT NULL,
  version_id  BIGINT NULL,
  action      VARCHAR(32) NOT NULL,   -- submit/approve/reject/publish/deprecate/install/update
  actor_id    BIGINT NOT NULL,
  comment     TEXT NULL,
  detail      JSON NULL,
  created_at  DATETIME NOT NULL,
  KEY idx_asset (asset_id, created_at)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
```

**设计取舍说明**：

- **不覆盖 `agents` 表**。两者职责不同：agent 是"平台能跑什么"，asset 是"团队有什么可分发的东西"。强行合并会导致大量纯分发资产被 `engine`/`input_schema` 这类执行期字段绑死。
- `FULLTEXT` 建在 `name/summary/keywords` 上，中文需 `ngram` parser（MySQL 8.0 内置），配合普通 LIKE 兜底。
- 安装记录用 `UNIQUE(asset_id, client_id)` 而非含 user_id——同一台机器上两个用户装同一个资产，应视为一次安装（共享宿主文件），但 `user_id` 记"谁装的"用于审计。

## 5. 统一清单规范（Manifest Spec）

这是**跨宿主分发的核心**。不同宿主的插件格式不同，若每种格式各存一份，清单会立刻分裂。

设计原则：**payload 存规范形态，bindings 存宿主适配**。

```jsonc
{
  "schema_version": 1,
  "code": "ssd-log-doctor",
  "name": "SSD 日志医生",
  "version": "1.2.0",
  "type": "mcp",                       // plugin | skill | mcp
  "summary": "解析 dmesg/FW log，自动定位 assert 与超时点",
  "author": { "name": "jarvs", "email": "jarvs@example.com" },

  // ===== 权限声明（安装时必须展示给用户，审核时重点审）=====
  "permissions": {
    "filesystem_read":  ["~/lab/logs/**"],
    "filesystem_write": [],
    "network":          ["git.internal:443"],
    "process_exec":     ["fio", "nvme"],
    "env_read":         ["NVME_*"],
    "secrets":          []            // 显式声明会读哪些凭据；非空必须人工审核
  },

  // ===== 规范载荷：按 type 三选一 =====
  "payload": {
    "mcp": {                           // type=mcp
      "transport": "stdio",            // stdio | http | sse
      "command": "python",
      "args": ["-m", "ssd_log_doctor"],
      "env": { "LOG_LEVEL": "info" },
      "url": null                      // transport=http/sse 时必填
    },
    "skill": {                         // type=skill
      "entry": "SKILL.md",
      "resources": ["references/*.md"]
    },
    "plugin": {                        // type=plugin
      "manifest": "plugin.json",
      "bundles": { "skills": [], "mcp_servers": [], "apps": [], "hooks": [] }
    }
  },

  // ===== 宿主适配层：同一资产在不同 Agent 工具里的落地形态 =====
  "bindings": {
    "qoder": {
      "kind": "mcp",
      "config": { /* Qoder 原生 MCP 配置片段 */ }
    },
    "minimax-code": {
      "kind": "skill",
      "path_hint": "~/.minimax/skills/ssd-log-doctor"
    }
  },

  "compat": {
    "testmate": ">=0.1.0",
    "hosts": ["qoder>=1.0", "minimax-code>=1.0"]
  }
}
```

**为什么这样切分**：`payload.mcp` / `payload.skill` / `payload.plugin` 是宿主无关的规范描述；`bindings` 里放各宿主的具体格式。这样新增一个宿主（比如 Cursor）只需要加一个 binding 解析器，不动存储、不动上传流程。

⚠️ **待验证项**：Qoder 插件清单的确切 schema 需要在实现前对齐（可通过其市场页导出样例反推）。`bindings` 层的设计目的正是把这类不确定性隔离在一个文件里，不让它扩散。

## 6. 存储与分发

包体走 **Docker volume 文件存储**，不入库：

```
/data/marketplace/
  └── {asset_code}/
      └── {version}/
          ├── package.tar.gz       # 规范化包
          └── meta.json            # sha256 / 大小 / 上传人 / 时间
```

挂载到 backend 容器（compose 加一个 volume），下载走 `GET /api/v1/assets/{code}/versions/{v}/download`，带 sha256 校验。

理由：内网无对象存储；tar.gz 便于版本留存与回滚；不进 DB 避免膨胀。

## 7. 安全体系（**本方案的重中之重**）

一个允许上传"会被 AI Agent 执行"的代码的市场，**安全性是成败关键**。绝大多数自建市场倒在这里。

### 7.1 上传即扫描（P0 必备）

自动扫描器在**入库前**跑，命中危险模式直接自动驳回：

| 类别 | 检出模式 |
|---|---|
| 远程代码执行 | `curl ... \| sh`、`wget ... \| bash`、`eval`、`exec(` |
| 凭据外泄 | 读 `~/.ssh`、`~/.aws`、`*.pem`、`/etc/shadow`、`env` 全量 dump |
| 破坏性操作 | `rm -rf /`、`mkfs`、`dd if=... of=/dev/` |
| 反弹 shell | `nc -e`、`/dev/tcp/` |
| 混淆 | 超长 base64 块、高熵字符串 |
| 越权网络 | 非白名单域名的硬编码外联 |

产出 `scan_report` JSON，存版本记录，详情页对用户可见。`scan_status=failed` → 版本自动置 `rejected`，不进审核队列。

### 7.2 人工审核（P0 必备）

状态机：

```
draft ──提交──> pending_review ──批准──> published ──弃用──> deprecated
                    │                      ↑
                    └──驳回──> rejected ──改──> (新版本 draft)
```

- 审核人名单走 `settings_store`（新增 `marketplace.reviewer_ids`），默认 admin
- 审核页展示：manifest 全文、包体文件树、**扫描报告**、权限声明 diff（相对上一版本，权限扩大需额外确认）、README 渲染
- **权限扩大的版本必须二次确认**——防止"先过审一个小权限版本，再发一个大权限版本"
- 全部动作写 `asset_audits`

### 7.3 安装侧

- 安装前弹**权限声明对比**（该资产要什么 vs 同类资产要什么）
- 宿主安装由 **Agent 本体执行**，服务端只下发签名过的 descriptor（§9），不在服务端执行任何上传的代码
- 安装/更新/卸载全量审计

### 7.4 运行侧

资产在 TestMate 内运行（MCP 型）时，容器内以受限环境启动：只挂载声明的路径、`env` 白名单、无外网（除 `network` 白名单）。

## 8. 后端 API

新增 `app/api/marketplace.py`，前缀 `/api/v1/assets`：

| 方法 | 路径 | 权限 | 说明 |
|---|---|---|---|
| GET | `/` | 登录 | 列表：`q` 全文检索 / `type` / `category` / `tag` / `sort`(hot\|new\|name) / 分页 |
| GET | `/{code}` | 登录 | 详情：含当前版本 manifest、README、版本列表、我的安装状态 |
| GET | `/{code}/versions` | 登录 | 版本历史 |
| GET | `/{code}/versions/{v}/download` | 登录 | 下载包体（校验 sha256） |
| POST | `/` | 登录 | 创建资产（草稿） |
| POST | `/{code}/versions` | owner/admin | 上传新版本，触发扫描 |
| POST | `/{code}/submit` | owner | 提交审核 |
| GET | `/reviews/pending` | reviewer | 待审队列 |
| POST | `/versions/{id}/approve` | reviewer | 批准 → 发布 + 钉钉通知 |
| POST | `/versions/{id}/reject` | reviewer | 驳回（必须填理由） |
| POST | `/installs` | 登录 | 记录安装 |
| DELETE | `/installs/{code}` | 登录 | 记录卸载 |
| GET | `/me/installed` | 登录 | 我装的 |
| GET | `/me/updates` | 登录 | 可更新（有新版的） |
| POST | `/{code}/bind-agent` | admin | 绑定到现有 Agent |

## 9. 对外分发：MCP + 安装器插件（**核心诉求**）

把"市场本身"做成一个 MCP server，任何支持 MCP 的宿主都能直接查询和安装。

### 9.1 Marketplace MCP Server

在 backend 上以 streamable-http 暴露：`POST /api/v1/mcp`
（FastAPI 侧用 FastMCP 或 mcp 官方 SDK 挂载，与现有 8 个业务路由共存）

工具集：

| 工具 | 入参 | 返回 |
|---|---|---|
| `search_assets` | `query, type?, category?, tags?, limit?, cursor?` | 资产摘要列表（含当前版本号、是否已安装） |
| `get_asset` | `code, version?` | 详情 + manifest + README + 扫描摘要 + 权限声明 |
| `list_versions` | `code` | 版本历史 + changelog |
| `get_install_plan` | `code, version, host` | **宿主原生安装描述符**（见下） |
| `install_asset` | `code, version, client_id, client_kind` | 写安装记录 + 返回安装描述符 |
| `list_installed` | `client_id` | 该宿主已装列表 |
| `check_updates` | `client_id` | 可更新项（含 changelog 摘要） |
| `uninstall_asset` | `code, client_id` | 卸载记录 |
| `submit_for_review` / `review_asset` | — | 上架方与审核方能力（按 token 角色鉴权） |

认证：复用现有 JWT（`Authorization: Bearer`）。可选签发 scope 化的 API Key 给自动化场景。

### 9.2 安装语义：市场是注册表，宿主负责安装

**关键设计决策**：`install_asset` **不在服务端执行任何安装动作**，只做两件事——记录审计、发回一个宿主原生的安装描述符。由 Agent 宿主自己完成落盘。这样避免服务端成为任意代码执行点，也让不同宿主的安装逻辑各自最优。

返回示例（Qoder MCP 形态）：

```json
{
  "client_kind": "qoder",
  "steps": [
    { "op": "write_mcp_server", "name": "ssd-log-doctor",
      "transport": "stdio", "command": "python", "args": ["-m","ssd_log_doctor"] },
    { "op": "reload_mcp" }
  ],
  "package_url": "https://testmate.internal/api/v1/assets/ssd-log-doctor/versions/1.2.0/download",
  "sha256": "…"
}
```

### 9.3 安装器插件（发给宿主用户）

一个可直接分发的插件包，内含两块：

1. **MCP server 配置**：指向本市场，附安装说明
2. **一个 Skill**：教 Agent 何时该去市场找东西

Skill 的行为约束（示意）：

```markdown
---
name: testmate-market
description: 当用户提到团队内部工具、现成脚本、某个测试流程自动化、
             或询问"团队里有没有现成的…"时，先到 TestMate 市场检索，
             而不是自己从零实现或直接搜索公网。
---

# 使用流程
1. search_assets(query, tags)  —— 先检索，别急着自己写
2. get_asset(code)            —— 看权限声明与场景边界
3. get_install_plan(code, version, host) —— 拿到安装步骤后向用户确认权限
4. install_asset(...)         —— 安装并告知用户装了什么、授予了什么权限

# 硬性要求
- 任何 install 前必须向用户展示 permissions 字段并取得确认
- 若资产权限超出当前任务需要，明确提示用户，拒绝静默安装
```

这样一个插件同时解决**发现**（Agent 知道该去市场找）和**安装**（MCP 给出宿主原生步骤）。

## 10. 前端页面

广场页升级为双 Tab 容器（保留现有智能体网格作为第一个 Tab）：

```
/plaza
├── [智能体]   ← 现有网格，不动
└── [市场]
     ├── 子 Tab: 插件 | 技能 | 连接器      （对齐截图的三分类）
     ├── 筛选: 分类 / 精选 / 状态 / 排序(热门|最新)
     ├── 搜索: 服务端全文检索 + 输入联想
     └── 卡片: 图标 / 名称 / 摘要 / 版本 / 安装数 / 已装标记
```

新增组件：

| 组件 | 职责 |
|---|---|
| `Market/index.vue` | 市场主视图（Tab + 筛选 + 网格） |
| `AssetCard.vue` | 资产卡片 |
| `AssetDetailDrawer.vue` | 详情：README 渲染、manifest、权限声明、扫描报告、版本时间线、安装按钮 |
| `AssetUploadDialog.vue` | 上传：包体 + manifest 编辑器（带 schema 校验）+ 分类标签 |
| `AssetReview.vue` | 审核队列：文件树、扫描报告、权限 diff、批/驳 |
| `MyAssets.vue` | 我的资产 + 我的安装 + 可更新提醒 |

复用现有 `design tokens` 与 `AgentCard` 的交互风格，保持视觉一致。

## 11. 钉钉上架通知

需从零实现（当前 `notify.py` 是占位）：

```python
# app/core/dingtalk.py
def sign(secret: str, timestamp_ms: int) -> str:
    """钉钉加签: base64(hmac_sha256(secret, f"{ts}\n{secret}"))"""

async def send_markdown(webhook: str, title: str, text: str,
                        at_mobiles: list[str] | None = None,
                        is_at_all: bool = False) -> None:
    ...
```

webhook 与加签 secret 存 `settings_store`（新增 `dingtalk.market_webhook` / `dingtalk.secret`），支持 UI 配置，不写死 `.env`。

通知触发点：

| 事件 | 文案 |
|---|---|
| 首次上架 | 🎉 新资产上架 · **{name}** `v{v}`<br>{summary}<br>[查看详情](链接) |
| 版本更新 | 📦 **{name}** 更新至 `v{v}`<br>{changelog 首行}<br>[查看更新日志] |
| 弃用 | ⚠️ **{name}** `v{v}` 已弃用，请迁移 |

设计成**异步非阻塞**（`BackgroundTasks`），通知失败只写日志，不影响发布事务。

## 12. 可行性评估

| 模块 | 可行性 | 工作量 | 风险 |
|---|---|---|---|
| 数据模型 + CRUD | ✅ 高 | 2d | 无 |
| 列表/详情/搜索 | ✅ 高 | 3d | 中文全文检索需验证 ngram |
| 上传 + 扫描器 | ✅ 高 | 4d | 规则误报率需调优 |
| 审核工作流 | ✅ 高 | 3d | 无 |
| 版本管理 | ✅ 高 | 2d | 无 |
| 前端页面 | ✅ 高 | 5d | 无 |
| 钉钉通知 | ✅ 高 | 1d | 需确认签名算法版本 |
| **Marketplace MCP Server** | ⚠️ 中高 | 4d | 需与现有路由共存调试 |
| **安装器插件分发** | ⚠️ 中 | 3d | **Qoder 插件清单 schema 待验证** |
| 沙箱运行 | ⚠️ 中 | 5d | 隔离强度与兼容性权衡 |

**整体可行性：高。** 架构上 90% 是团队已有的模式（alembic + SQLAlchemy async + FastAPI + 现有设计体系），增量集中在"资产包抽象"和"MCP 分发"两块新东西。

**主要风险与对策：**

1. **安全是头号风险**。对策：扫描器 + 人工审核 + 权限声明 + 服务端不执行代码，四层缺一不可。若因工期砍掉人工审核，**强烈建议整个功能不上线**——团队内部同样会出现误传。
2. **Qoder 插件格式未知**。对策：`bindings` 适配层已隔离该不确定性；实现前先导出一个 Qoder 市场插件样例反推 schema。
3. **资产类型分裂**。对策：统一 manifest + payload/bindings 二层结构，新增类型只加适配器。
4. **包体存储与备份**。对策：volume 挂载 + `deploy/backup.sh` 扩展纳入 tar 备份。
5. **范围蔓延**。对策：严格分期，P0 不含 MCP 分发。

## 13. 分期路线

### P0 — 市场底座（2 周）
- 4 张表 + alembic 0004
- `/assets` 列表（服务端搜索/筛选/分页）、详情
- 前端市场 Tab + 卡片 + 详情抽屉
- 上传 + 存储 + sha256 校验
- **扫描器 v1**（§7.1 规则集）

### P1 — 治理闭环（2 周）
- 审核工作流（提交/批/驳 + 审计流水）
- 版本管理（历史、diff、弃用）
- 我的资产 / 我的安装 / 可更新列表
- 钉钉通知（签名 + 三类文案）
- 前端上传弹窗 / 审核页 / 我的资产页

### P2 — 对外分发（1.5 周）
- Marketplace MCP Server（9 个工具）
- 安装器插件（MCP 配置 + Skill）
- `get_install_plan` 的 Qoder binding
- **前置**：确认 Qoder 插件 schema

### P3 — 增强（按需）
- RAGFlow 语义检索（团队已接 RAGFlow，天然适合做"描述式查找"）
- 收藏、评分
- 宿主侧自动更新检查（定时任务 ping 市场）
- 资产使用统计回流（哪个资产真被用了，指导下架）

## 14. 验收标准

P0/P1 完成需满足：

- [ ] 资产可上传，扫描器能拦截 §7.1 中每一类危险模式
- [ ] 未过审的版本在任何列表/搜索/下载入口都不可见、不可达
- [ ] 版本发布后，旧版本仍可下载（可回滚）
- [ ] 权限扩大的版本在审核页有醒目提示，且需二次确认
- [ ] 中文/英文/标签关键词搜索命中率达标
- [ ] 上架/更新/弃用正确推送到钉钉群
- [ ] 所有审核与安装动作可在 `asset_audits` 追溯

P2 完成需满足：

- [ ] Qoder 中通过自然语言即可检索到团队资产并完成安装
- [ ] 安装前展示权限声明并要求用户确认
- [ ] `check_updates` 能准确报出可更新项
- [ ] 市场不可达时 Agent 能优雅降级（不阻断正常编码）

---

## 附录 A：与现有 Agent 的共存

```
用户视角                          数据层
─────────────────────────────────────────────
广场 Tab1 智能体  ──────────→  agents      (执行注册表, 不动)
广场 Tab2 市场    ──────────→  assets      (分发注册表, 新增)
        │
        └─ bind_agent_code ─→ agents      (可选绑定: 绑了才能在平台内直接运行)
```

存量 agent（如 `code-review`）需要上架到市场时，写一条 `assets` 记录并 `bind_agent_code='code-review'` 即可，不需要迁移任何数据。

## 附录 B：配置项（走 settings_store，UI 可改）

| key | 默认 | 说明 |
|---|---|---|
| `marketplace.enabled` | `true` | 总开关 |
| `marketplace.reviewer_ids` | `[1]` | 审核人 user_id 列表 |
| `marketplace.max_package_mb` | `20` | 单包大小上限 |
| `marketplace.scan_strict` | `true` | 扫描命中即自动驳回 |
| `dingtalk.market_webhook` | 空 | 上架通知机器人 |
| `dingtalk.secret` | 空 | 加签密钥 |
| `dingtalk.notify_on_publish` | `true` | 上架通知开关 |
