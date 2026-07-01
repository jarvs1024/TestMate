# SSD 测试组 AI 工作平台 — 整体方案

- 日期: 2026-07-01
- 状态: 设计稿 v1(已通过用户多轮澄清)
- 读者: 项目经理 / 平台使用者 / 后续接手开发者

---

## 1. 背景与目标

### 1.1 背景

SSD 测试组(3~10 人)日常涉及大量知识密集型工作:

- 查 spec / 协议 / datasheet
- 查历史 bug(GitLab issues / MRs)
- 分析 fio / kernel / smart log
- 实验室机器状态查询、FW 部署、问题排查
- 写周报 / 测试报告 / 测试用例

目前这些工作散落在多个工具(共享盘、GitLab、Excel、IM),**查信息和动手操作成本高**,新人 onboarding 慢,知识沉淀在个人脑子里。

### 1.2 目标

搭建一个**内网部署的 AI 工作平台**,作为 SSD 测试组的统一入口,提供:

1. **知识检索与问答** — 把 spec / 历史 bug 灌进 RAG,问 AI
2. **日志分析辅助** — 上传 log,AI 解读
3. **环境运维操作** — 查机器状态 / 部署 FW / 排查(走钉钉通知)
4. **测试报告与设计** — AI 辅助生成报告 / 用例

### 1.3 范围与非范围

**做**:

- 内网 Docker Compose 一键部署
- 3~10 人共用同一份配置
- RAGFlow(知识库) + Dify(agent 编排) + 自研 / GitLab / 钉钉 webhook
- 钉钉群机器人单向通知

**不做(YAGNI)**:

- 完整登录 / 多租户(先用 L2:读公开 / 改要 admin token)
- IM 双向消息(只发群机器人)
- 移动端 / 桌面端(只桌面浏览器)
- 多语言 i18n
- 端到端加密(信任内网)

---

## 2. 架构

### 2.1 总览图

```
┌──────────────────────── 内网 (SSD 测试组) ────────────────────────┐
│                                                                   │
│   ┌────────── Browser (React SPA) ──────────────────────────┐    │
│   │  - 主页:agent 卡片网格(最近使用 + 全部功能)             │    │
│   │  - /agent/:id:iframe 嵌入 RAGFlow / Dify 分享页         │    │
│   │  - /settings:配置 agent / 钉钉 / 通知规则(管理员)       │    │
│   │  - 鉴权:本地 admin token(unlock 后可改配置)             │    │
│   └────────────────────────┬────────────────────────────────┘    │
│                            │                                     │
│                            │ 业务请求                            │
│                            │ (Dify / RAGFlow iframe 嵌入)       │
│                            │                                     │
│                            │ 配置请求                           │
│                            │ GET /api/*    公开(读 agents 等)  │
│                            │ POST/PUT/DELETE /api/*  要 token   │
│                            ▼                                     │
│   ┌────────── Config Backend (FastAPI, ~300 行) ─────────────┐   │
│   │  - agents / dingtalk / rules / notification_logs CRUD    │   │
│   │  - admin token 鉴权(管理员前端用)                        │   │
│   │  - service token 鉴权(Dify 用,只读钉钉配置 + 写日志)    │   │
│   │  - SQLite + SQLAlchemy                                   │   │
│   └────────────────────────┬─────────────────────────────────┘   │
│                            │ SQL                                 │
│                            ▼                                     │
│                      ┌───────────┐                               │
│                      │  SQLite   │                               │
│                      └───────────┘                               │
│                                                                   │
│   ┌────────── RAGFlow ───────┐  ┌────────── Dify ──────────┐    │
│   │  - 知识库数据集           │  │  - agent workflow 编排    │    │
│   │  - search 分享页          │  │  - chat 分享页            │    │
│   │  - chat 分享页            │  │  - HTTP 工具节点:         │    │
│   │                           │  │    · 调 config-backend    │    │
│   │                           │  │    · 调 GitLab API        │    │
│   │                           │  │    · 调 自研平台 API      │    │
│   │                           │  │    · 调 钉钉 webhook      │    │
│   └──────────────────────────┘  └──────────────────────────┘    │
│                                                                   │
└───────────────────────────────────────────────────────────────────┘
            │              │                │              │
            ▼              ▼                ▼              ▼
        GitLab        自研平台         实验室机器        钉钉
        (issues)     (REST API)       (SSH / API)    (群机器人)
```

### 2.2 关键组件

| 组件 | 角色 | 部署位置 |
|---|---|---|
| **Frontend** | React SPA(主页 + agent 详情 + 配置页) | Nginx 静态托管 / 同机 |
| **Config Backend** | 配置中心:agents / 钉钉 / 规则 / 日志 CRUD | Docker,同机 |
| **SQLite** | 配置持久化 | 数据卷挂载 |
| **RAGFlow** | 知识库引擎(embedding / 检索 / chat) | Docker,同机 |
| **Dify** | agent 编排 + 工具调用 | Docker,同机 |
| **钉钉** | 群机器人单向通知 | 外部 SaaS,webhook 调 |

### 2.3 数据流(典型场景:用户在 Dify agent 里说"完成后通知性能组")

```
1. 用户在浏览器点 Dify agent 卡片
   → /agent/:id 路由
   → iframe 嵌入 Dify chat 分享页

2. 用户在 Dify 对话框输入:"分析这份 log,完成后通知性能组"
   → Dify workflow 启动

3. Dify workflow 节点 1:上传 log 处理(LLM 读 + 规则检测)
   → 节点内业务逻辑

4. Dify workflow 节点 2:HTTP GET http://config-backend:8000/api/dingtalk/性能组
   Header: Authorization: Bearer <DIFY_SERVICE_TOKEN>
   → 拿到 { webhook_url, secret, msg_template }

5. Dify workflow 节点 3:HTTP POST <webhook_url>
   Body: 钉钉 markdown 消息(模板渲染后)

6. Dify workflow 节点 4:HTTP POST /api/notifications/logs
   → 写 SQL 留痕

7. Dify workflow 返回结果给用户(iframe 内显示)
```

### 2.4 配置流(管理员改一次,所有人看到)

```
管理员浏览器 → 输入 admin token → unlock → /settings
  → 增/改/删 agent / 钉钉 / 规则
  → 写 SQL(POST/PUT/DELETE 校验 admin token)

普通用户浏览器 → 打开主页 → GET /api/agents 公开 → 看到最新 agents
```

---

## 3. 选型与优点

### 3.1 整体选型:RAGFlow + Dify + 自建前端 + 自建配置后端

**为什么这套组合**:

- **RAGFlow** 是为生产级 RAG 设计的开源引擎,比 LangChain + 自建 pipeline 稳定得多
- **Dify** 解决"agent 编排 + 工具调用",**这块自己写要 1000 行起**,Dify 直接可视化配置
- **自建前端** = iframe 嵌入分享页,**最大程度复用** RAGFlow / Dify 的 UI,**不重复造轮子**
- **自建配置后端** = 仅 300 行,只管"配置共享 + token 托管",业务编排全在 Dify,职责清晰

**为什么不上 FastAPI 业务中台**(原方案的扩展):

- 业务编排都在 Dify,我们再写一份业务逻辑是双重实现
- 配置后端 + iframe 嵌入的组合**已经满足 L2 权限模型**需求
- 开发量更小,运维更轻

### 3.2 前端:Vite + React + TypeScript

**优点**:

- **Vite**:启动 < 1s,HMR 极快,生产构建产物小(本案预计 JS bundle < 200KB)
- **React**:生态最广,iframe 嵌入 / 路由 / 状态管理都有成熟方案
- **TypeScript**:配置后端有 4 张表,前端要拉数据,**类型安全减少 bug**
- **react-router-dom v6**:3 个路由(`/` / `/agent/:id` / `/settings`)够用,无需复杂路由方案
- **无状态管理库**:全局状态只有"当前用户是否解锁 admin",用 `useState` 即可,不引 Redux/Zustand

**不引 Tailwind / CSS-in-JS**:全局单文件 CSS(沿用上一版经验),5KB 以内,简单可控。

### 3.3 配置后端:FastAPI + SQLite + SQLAlchemy

**FastAPI 优点**:

- **Python 生态**:跟 SSD 测试工程师技能栈贴近(运维 / 脚本 / 数据处理都熟)
- **自动 OpenAPI 文档**:前端开发可对照 `/docs` 直接试 API
- **Pydantic 校验**:请求体 / 响应体自动校验,减少手写校验代码
- **异步原生**:SQLAlchemy 2.0 异步支持,后期升 Postgres 无痛

**SQLite 优点**:

- **零运维**:单文件,无需单独起数据库服务
- **够用**:本案 4 张表,数据量小(配置 + 日志,日增几百条),SQLite 性能足够
- **易备份**:`cp sqlite.db backup.db` 完事
- **平滑升 Postgres**:SQLAlchemy 换连接串即可,代码层零改动

**SQLAlchemy 优点**:

- **ORM + 显式 SQL 都行**:复杂查询写原生 SQL,简单 CRUD 用 ORM
- **Migration 工具 Alembic**:后期表结构变更可版本化

**不引复杂栈**:

- **不上 Redis**:配置量小,后端本地缓存即可
- **不上 Celery**:通知写日志是同步写 SQL,毫秒级
- **不上 Nginx 反代**:Dify / RAGFlow 各自有内置 web server,前端用 Vite preview 或静态托管即可

### 3.4 RAGFlow — 核心优点

针对本案"知识库 + 历史 bug 检索"场景:

| 维度 | RAGFlow 的优势 |
|---|---|
| **文档解析** | 内置 PDF / Word / Excel / Markdown 解析,支持表格 / 图片 OCR,**比 LangChain 手写 loader 强太多** |
| **分块策略** | 多种内置模板(通用 / 问答 / 手册),针对 SSD spec 这种长文档效果比固定切分好 |
| **Embedding** | 支持多种模型(bge / m3e / OpenAI),内网部署可用本地模型 |
| **检索** | **混合检索**(关键词 + 向量),比纯向量检索召回率高(尤其专业术语) |
| **RAG 编排** | 内置"问题改写 → 检索 → 重排 → 生成"全流程,可视化配置 |
| **分享页** | 任何 dataset / chat assistant 都可一键生成分享链接,带 auth token,**原生支持 iframe 嵌入** |
| **多用户** | 自带用户系统,后期我们做 L3 登录可直接对接 |
| **开源 Apache 2.0** | 可内网部署,无授权问题 |
| **中文友好** | 中文文档 / 中文社区,SSD 工程师上手快 |

**为什么不用 LangChain + LlamaIndex 自建**:

- 文档解析 / 分块 / 重排要自己写,**工作量是 RAGFlow 的 5~10 倍**
- 维护成本高(库版本迭代快,API 经常 breaking)
- 团队已有 RAGFlow 部署经验,**复用现成的**

### 3.5 Dify — 核心优点

针对本案"agent 编排 + 工具调用"场景:

| 维度 | Dify 的优势 |
|---|---|
| **可视化 workflow** | 拖拽式编排,业务逻辑改动无需发版,**给非开发者(测试工程师)调 agent 提供可能** |
| **工具节点丰富** | HTTP / 时间 / 变量 / 代码 / 知识库检索节点全内置 |
| **多模型支持** | OpenAI / Claude / 通义千问 / Ollama,内网环境配 Ollama 即可 |
| **分享页** | 每个 app / workflow 一键生成 chat 分享链接,**原生支持 iframe 嵌入** |
| **RAG 集成** | 内置知识库节点(可对接 RAGFlow 或自建),减少切换成本 |
| **审计** | workflow 执行日志完整(prompt / 工具调用 / 响应),可查 |
| **开源 Apache 2.0 + 商业版** | 社区版够用,后期数据量 / 用户量起来可升商业版 |
| **Dify DSL** | workflow 可导出为 YAML,版本管理 / 团队协作方便 |

**为什么不用自建 agent 框架(比如直接写 LangGraph)**:

- LangGraph 要写 Python 代码,改 workflow 要发版
- 测试工程师**不会写代码也能配 Dify workflow**,降低协作门槛
- 工具节点的可视化配置比手写 HTTP 调用清晰

### 3.6 钉钉:只走群机器人 webhook

**优点**:

- **零审批** — 群机器人 URL 谁都能建,不需要企业自建 app 权限
- **单向** — 不需要主动给个人发消息,群消息够用
- **签名校验** — 可选加签(`secret` 字段),防伪造
- **Markdown 消息** — 报告 / 异常支持富文本展示
- **@ 人员** — 消息里可 @ 指定人 / @ 所有人

**为什么不走企业自建 app**:

- 需 `Corp+User` 系列权限,大概率审批不下来(组织架构 / 安全考虑)
- 需要拉通讯录 / 主动发个人消息,本期用不到
- 群机器人**已经覆盖所有本期需求**

### 3.7 部署:Docker Compose 单机

**优点**:

- **一键起 / 一键停** — `docker compose up -d` 拉起全部服务
- **服务隔离** — RAGFlow / Dify / config-backend 各自容器,升级互不影响
- **数据卷挂载** — SQLite / RAGFlow 知识库 / Dify 数据集挂载到主机,易备份
- **可平滑迁集群** — Compose 改 K8s manifests 即可
- **资源可控** — 单机部署,内存 / CPU 配上限,避免 OOM

**为什么不直接 K8s**:

- 单机部署,Compose 足够,K8s 是过度设计
- K8s 学习 / 维护成本高,组里不一定有人熟

---

## 4. 页面与路由

### 4.1 路由

```
/                          主页(agent 网格 + 最近使用)
/agent/:id                 agent 详情页(iframe 嵌入)
/settings                  配置页(管理员可编辑,普通用户看到 token 输入框)
```

3 个路由,简洁。

### 4.2 主页布局

```
┌─────────────────────────────────────────────────────────────┐
│  AI 工作平台                                       ⚙ 设置    │
├─────────────────────────────────────────────────────────────┤
│                                                             │
│   最近使用                                                  │
│   ┌──────┐ ┌──────┐ ┌──────┐                               │
│   │ 📊   │ │ 🔍   │ │ 🐛   │                               │
│   │ 性能 │ │ 知识 │ │ 历史 │                               │
│   │ 日志 │ │ 检索 │ │ bug  │                               │
│   └──────┘ └──────┘ └──────┘                               │
│                                                             │
│   📚 知识库                                                 │
│   ┌──────┐ ┌──────┐                                        │
│   │ 🔍   │ │ 💬   │                                        │
│   │ 检索 │ │ 问答 │                                        │
│   └──────┘ └──────┘                                        │
│                                                             │
│   🐛 研发辅助                                               │
│   ┌──────┐ ┌──────┐ ┌──────┐                               │
│   │ 🐛   │ │ 📄   │ │ 🧪   │                               │
│   │ 历史 │ │ 测试 │ │ 测试 │                               │
│   │ bug  │ │ 报告 │ │ 设计 │                               │
│   └──────┘ └──────┘ └──────┘                               │
│                                                             │
│   ⚙ 工程                                                    │
│   ┌──────┐ ┌──────┐                                       │
│   │ 📊   │ │ ⚙   │                                        │
│   │ 日志 │ │ 环境 │                                        │
│   │ 分析 │ │ 运维 │                                        │
│   └──────┘ └──────┘                                        │
│                                                             │
└─────────────────────────────────────────────────────────────┘
```

### 4.3 agent 详情页

```
┌─────────────────────────────────────────────────────────────┐
│  ← 返回      性能日志分析    DIFY                  ⛶ 全屏    │
├─────────────────────────────────────────────────────────────┤
│   ┌─────────────────────────────────────────────────────┐  │
│   │           iframe 嵌入 RAGFlow/Dify 分享页           │  │
│   │           占满除顶栏外的全部空间                      │  │
│   └─────────────────────────────────────────────────────┘  │
└─────────────────────────────────────────────────────────────┘
```

### 4.4 配置页(管理员)

5 个卡片:

1. **Agent 列表** — 增 / 改 / 删 / 排序
2. **钉钉配置** — 增 / 改 / 删 / 测试
3. **通知规则** — 场景 → 钉钉组映射
4. **通知历史** — 查 SQL 里的 log
5. **导出 / 导入** — JSON 备份恢复

---

## 5. 数据模型(SQL)

```sql
-- agent 定义(主页卡片 + iframe 嵌入)
CREATE TABLE agents (
  id            TEXT PRIMARY KEY,
  name          TEXT NOT NULL,
  type          TEXT NOT NULL,           -- 'ragflow_search' | 'ragflow_chat' | 'dify_agent' | 'gitlab_issues' | 'external'
  url           TEXT NOT NULL,
  icon          TEXT,                    -- emoji 或 url
  color         TEXT,                    -- 卡片颜色 hex
  description   TEXT,
  show_on_home  INTEGER NOT NULL DEFAULT 1,
  sort_order    INTEGER NOT NULL DEFAULT 0,
  created_at    TIMESTAMP NOT NULL,
  updated_at    TIMESTAMP NOT NULL
);

-- 钉钉配置(可多组)
CREATE TABLE dingtalk_configs (
  id            TEXT PRIMARY KEY,
  name          TEXT NOT NULL UNIQUE,    -- 引用键,如"性能组"
  webhook_url   TEXT NOT NULL,
  secret        TEXT,                    -- 可选加签密钥
  msg_template  TEXT,
  created_at    TIMESTAMP NOT NULL,
  updated_at    TIMESTAMP NOT NULL
);

-- 通知规则
CREATE TABLE notification_rules (
  id            TEXT PRIMARY KEY,
  scenario      TEXT NOT NULL,           -- 'report_done' | 'env_alert' | 'deploy_done' | 'custom'
  dingtalk_id   TEXT NOT NULL,
  enabled       INTEGER NOT NULL DEFAULT 1,
  condition     TEXT,                    -- JSON 简单条件
  created_at    TIMESTAMP NOT NULL,
  updated_at    TIMESTAMP NOT NULL,
  FOREIGN KEY (dingtalk_id) REFERENCES dingtalk_configs(id) ON DELETE CASCADE
);

-- 通知历史
CREATE TABLE notification_logs (
  id            TEXT PRIMARY KEY,
  scenario      TEXT NOT NULL,
  dingtalk_id   TEXT NOT NULL,
  payload       TEXT NOT NULL,
  status        TEXT NOT NULL,
  error         TEXT,
  sent_at       TIMESTAMP NOT NULL
);
```

---

## 6. 鉴权设计

| 角色 | 鉴权 | 能做什么 |
|---|---|---|
| **普通用户** | 无(打开主页即可) | 浏览主页、用所有 agent、查通知历史 |
| **管理员** | admin token(unlock 后存 localStorage) | 普通用户 + 改配置 |
| **Dify 服务** | service token(放 Dify 工具节点 Header) | 调 config-backend 读钉钉配置、写通知日志 |

- **首次启动**:config-backend 自动生成 admin token,打到日志
- **admin token 传递**:`Authorization: Bearer <token>` (POST/PUT/DELETE 校验)
- **service token 传递**:同上(独立 token,跟 admin 分开)
- **Dify 工具节点配置**:`http://config-backend:8000/api/dingtalk/性能组`,Header `Authorization: Bearer <service_token>`

---

## 7. 部署

### 7.1 一键起

```bash
cd /path/to/ssd-ai-platform
docker compose up -d
```

启动:

- `config-backend` (FastAPI,port 8000)
- `frontend` (Nginx 静态托管,port 8080)
- `ragflow` (RAGFlow,port 18080)
- `dify` (Dify,port 80)
- `ragflow-es` / `ragflow-mysql` / `ragflow-redis` / `ragflow-minio`(RAGFlow 依赖)
- `dify-postgres` / `dify-redis` / `dify-weaviate`(Dify 依赖)

### 7.2 数据卷

```
./data/sqlite/         SQLite 数据库
./data/ragflow/        RAGFlow 数据
./data/dify/           Dify 数据集 + workflow
```

### 7.3 备份

```bash
# 配置 + 日志
cp data/sqlite/ssd-platform.db backup/ssd-platform-$(date +%F).db

# 知识库
docker compose exec ragflow tar czf /backup/ragflow-$(date +%F).tar.gz /var/lib/ragflow

# 工作流
docker compose exec dify tar czf /backup/dify-$(date +%F).tar.gz /var/lib/dify
```

---

## 8. 实施路线

### P0 — 跑得起来(1~2 周)

- Docker Compose 编排(RAGFlow + Dify + config-backend + frontend)
- FastAPI 后端:SQLite + SQLAlchemy + 4 张表 + CRUD API + 双 token 鉴权
- 前端骨架:主页 + 配置页 + agent 详情页 + admin token 输入
- 2 个 iframe demo(RAGFlow search + chat)
- Dify workflow demo:读钉钉配置 → 调钉钉 → 写日志
- 测试钉钉按钮

### P1 — 核心场景补齐(2~3 周)

- 7 个功能页(iframe 嵌入)
- 钉钉多组 / 消息模板 / 通知规则
- 通知历史查询页
- 工作台"最近使用"
- 导出 / 导入配置 JSON

### P2 — 增强(按需)

- 完整登录(L2 → L3)
- 审计日志(谁改了配置)
- 升 Postgres
- 监控告警(Prometheus + Grafana)
- 升 K8s(数据量 / 用户量起来后)

---

## 9. 风险与备选

| 风险 | 影响 | 备选 |
|---|---|---|
| Dify 0.x 配置 GitLab / 自研平台 token 麻烦 | 中 | 多花时间配,或起轻量代理转发 |
| 钉钉群机器人 URL 泄露 | 低 | 加签 secret 校验,定期轮换 |
| RAGFlow 知识库更新不及时 | 中 | Dify workflow 加 cron 节点,定期触发同步 |
| 单机部署单点故障 | 中 | 数据卷每日备份;P2 升 K8s |
| Dify 直接 SQL 不可行 | 已规避 | 走 HTTP 调 config-backend |
| L2 鉴权被绕过 | 中 | admin token 放后端 env,前端只 unlock 不存明文 |
| iframe 跨域限制 | 低 | 嵌入的是 RAGFlow / Dify 自家分享页,无跨域问题 |

---

## 10. 范围之外(明确不做)

- **多租户 / 跨团队共用** — 单租户
- **完整 SSO / OAuth** — 后期 L3 才考虑
- **IM 双向消息** — 钉钉群机器人单向通知
- **移动端 / 桌面端** — 桌面浏览器
- **端到端加密** — 信任内网
- **复杂权限模型** — L2 够用

---

## 11. 参考

- RAGFlow 官方文档: <https://ragflow.io/docs>
- Dify 官方文档: <https://dify.ai/docs>
- 钉钉自定义机器人: <https://open.dingtalk.com/document/orgapp/custom-robot-access>
- 上一版 RAGFlow+Dify iframe 平台(已落地): `docs/superpowers/specs/2026-06-30-ai-platform-design.md`
