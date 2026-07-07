# TestMate 智能测试辅助平台 — 整体技术方案

- 日期:2026-07-04
- 状态:方案稿 v1
- 仓库:`jarvs1024/TestMate`
- 平台名:**TestMate 智能测试辅助平台**

---

## 1. 设计思路与核心理念

### 1.1 "前店后厂"架构

- **前店(前端)**:拒绝"万能输入框",改为**基于任务流的结构化卡片**。前端不再让 LLM 自己造入口,而是把"日志诊断"、"协议检索"、"用例生成"、"机台运维"等场景**显式拆成独立的工作台**。
- **后厂(后端)**:Dify / RAGFlow 作为"隐形黑盒引擎",被 **FastAPI 中台完全包裹**。所有 token / 鉴权 / 业务编排 / 硬件触达都走中台,AI 引擎不直接对外。

### 1.2 三轴驱动布局

```
┌─ 左轴 ─┬─ 中轴 ────────────┬─ 右轴 ─┐
│ 导航   │ 核心测试交互       │ RAG 协议│
│ +      │ (双栏代码高亮)     │ 规范随身│
│ 机台状态│                   │ 查      │
└────────┴───────────────────┴────────┘
```

- **左轴**:导航 + 实时机台状态(在线 / 离线 / 占用)
- **中轴**:核心测试交互(代码 / log 高亮、AI 回答、下发控制)
- **右轴**:常驻 RAG 协议规范检索(NVMe / JEDEC / 企业 spec 切片)

### 1.3 物理世界隔离原则(防炸机)

- 坚决**不将硬件状态交给大模型维护**
- 通过数据库**互斥锁(Mutex Lock)** 防止多 agent 并发操作同一台机台
- 通过**指令白名单** 防止 AI 产生幻觉下发高危 / 冲突指令
- 所有下机台的命令必须经 FastAPI 中台二次校验,**Dify 永远不直连机台**

### 1.4 混合开发流(Mac → Linux)

- Mac 宿主机:Vite HMR 极速断点调试
- 最终交付:打包到 x86 Linux 测试服务器,环境一致
- 统一 Docker 编排,开发 / 生产同一镜像

---

## 2. 核心技术栈精选

| 分层 | 选型 | 理由 |
|---|---|---|
| **前端展现层** | Vue 3 + Vite + TypeScript | 响应快,国内测试团队易上手 |
| | Tailwind CSS | 一键实现暗黑 / 亮色科技风,utility-first 免命名 |
| | Element Plus | 国内成熟的 UI 组件库,Drawer / Form / Table 即拿即用 |
| | Monaco Editor | VS Code 同款,完美承载 Python 脚本 + 串口 log 高亮 |
| | PDF.js | 协议文档 PDF 切片 + 高亮显示 |
| **后端中台** | Python 3.11+ | SSD 测试工程师技能栈 |
| | FastAPI | 原生异步,完美承接 Dify 的 SSE 流式响应 |
| | Pydantic v2 | 强制参数校验,OpenAPI 自动生成 |
| | SQLAlchemy 2.0(async) | ORM + 异步,后期可平滑迁 Postgres |
| | httpx / aiohttp | 异步 HTTP,转发 Dify / RAGFlow / GitLab |
| | paramiko | SSH 连机台执行测试脚本 |
| **AI 引擎** | Dify 1.x | ReAct 多轮对话 / 工具调用 / workflow 编排 / SSE 流式 |
| | RAGFlow 0.18+ | NVMe / JEDEC 复杂 PDF + 表格视觉切片(开源顶流) |
| **数据 / 部署** | MySQL 8 / PostgreSQL 16 | 互斥锁 / 资产字典 / 审计日志;SQLite 不够并发 |
| | Redis 7 | 限流 / 缓存 / SSE 连接管理 / 互斥锁分布式协调 |
| | Docker + Docker Compose | 一键离线部署,隔离环境差异 |

**不引**:

- Redux / Pinia(状态用 Vue 3 `reactive` 即可,Monorepo 小)
- LangChain / LlamaIndex(用 Dify + RAGFlow 顶替,工作量省 5~10 倍)
- 完整 OAuth / SSO(L2:admin token 够用)
- K8s(单机部署,Compose 足够)

---

## 3. 全局数据流与执行流程

### 3.1 短任务流(秒级推理)

```
[前端结构化卡片]
  ↓ POST /api/v1/diagnose  (上传 log + 环境变量)
[FastAPI 中台]
  ├─ 1. 鉴权(JWT / 内部 SSO)
  ├─ 2. 校验:机台状态 / 互斥锁(SELECT ... FOR UPDATE)
  ├─ 3. 大文件预处理:截断 + 提取 Error 堆栈
  ├─ 4. 转发:Dify workflow(Dify 直连 RAGFlow 取历史缺陷图谱)
  ├─ 5. SSE 流式返回:思考过程 / 结论 / 生成的修复脚本
  ↓
[前端 Monaco Editor 实时打字渲染]
```

### 3.2 长任务流(机台执行)

```
[前端] 工程师点击"下发测试"
  ↓ POST /api/v1/jobs(脚本 + 机台 id + 测试计划)
[FastAPI 中台]
  ├─ 1. 鉴权 + 角色校验(Tester / Admin)
  ├─ 2. 申请机台互斥锁(Redis SETNX + DB lock)
  ├─ 3. 指令白名单校验(脚本 AST / shell 关键字匹配)
  ├─ 4. 入库 jobs 表(status=queued)
  └─ 5. Celery worker(或 FastAPI BackgroundTasks)异步:
       ├─ paramiko SSH 登录机台
       ├─ 上传脚本 + 运行
       ├─ 轮询 status,流式回报给前端 SSE
       └─ 写回 jobs 表(status=done / failed)
  ↓
[前端] 实时显示机台 stdout / 最终 Pass / Fail
```

### 3.3 知识检索流(右轴 RAG 随身)

```
[前端右轴搜索框] 输入"NVMe 2.0 random write latency spec"
  ↓ GET /api/v1/kb/search?q=...&dataset=nvme-2.0
[FastAPI 中台]
  ├─ 鉴权
  ├─ 转发 RAGFlow /api/v1/retrieval
  └─ 返回:切片 id + 原文 + 高亮区间 + 跳转锚点
  ↓
[前端右轴] PDF.js 渲染对应文档,高亮命中段落
```

### 3.4 通知流(Dify → 中台 → 钉钉)

```
[Dify workflow 节点] "报告生成完" → 调用
  ↓ POST /api/v1/notify  {scenario, payload}
[FastAPI 中台]
  ├─ 查 notification_rules 表(找到对应钉钉组)
  ├─ 渲染 msg_template(替换 {{var}})
  ├─ 调钉钉 webhook(可选加签)
  ├─ 写 notification_logs
  └─ 返回结果给 Dify
```

---

## 4. 核心功能矩阵

| 场景 | 关键能力 | 主要技术 |
|---|---|---|
| **PCIe / 串口 log 极速诊断** | 上传 → 截断 → 提取 assert → 对比历史缺陷图谱 → 三段式根因 | RAGFlow + Dify + SSE |
| **协议用例自动化构建** | 输入需求 → RAG 检索 NVMe spec → Dify 生成符合 `import ssd_tool` 规范的 pytest 脚本 → 双栏纠错 | RAGFlow + Dify + Monaco |
| **FTL & NAND 仿真交互** | 对话式输入仿真参数(GC 开销 / 坏块增长率)→ 推演配置策略 | Dify(强 LLM:DeepSeek-R1 / Claude) |
| **测试资产与算力管理(PM 视角)** | Token 消耗漏斗、Prompt 灰度发布、团队动态时间线 | Dify API + 自建 dashboard |
| **机台状态实时监控** | 左轴状态胶囊,FastAPI 周期 ping + 报活 | FastAPI + paramiko + Redis |
| **环境运维(部署 FW / 跑脚本)** | Dify agent 接中台 executor,中台申请锁 + 白名单校验 + SSH | Dify + FastAPI + paramiko + 互斥锁 |
| **钉钉通知** | 报告 / 异常 / 部署完成 → 群机器人单向推送 | Dify → 中台 → 钉钉 webhook |

---

## 5. 工程项目架构(Monorepo)

```
TestMate/
├── frontend_web/                # 1. 前端 Vue 项目
│   ├── .env.production          # 指向真实后端 IP
│   ├── src/
│   │   ├── layouts/
│   │   │   └── MainLayout.vue   # 三轴外壳(Sidebar + Main + RAG-drawer)
│   │   ├── components/
│   │   │   ├── MonacoEditor.vue
│   │   │   ├── PdfHighlighter.vue
│   │   │   ├── MachineStatusCapsule.vue
│   │   │   └── FilterDrawer.vue
│   │   ├── views/
│   │   │   ├── KnowledgeBase/   # 协议检索(右轴 + 主区双栏)
│   │   │   │   ├── index.vue
│   │   │   │   └── components/
│   │   │   ├── LogDiagnosis/    # log 诊断
│   │   │   ├── TestCaseBuilder/ # 用例生成
│   │   │   ├── EnvOps/          # 环境运维
│   │   │   ├── Assets/          # PM 视角
│   │   │   └── Settings/
│   │   ├── router/index.js
│   │   ├── stores/              # Pinia(user role, token, machines)
│   │   ├── utils/request.js     # Axios 拦截器
│   │   └── styles/
│   ├── Dockerfile
│   └── nginx.conf
│
├── backend_gateway/             # 2. 后端 FastAPI 中台
│   ├── .env                     # 机密(Dify / RAGFlow / DB / Redis / SSH)
│   ├── config.py                # Pydantic 强校验加载
│   ├── main.py                  # FastAPI app + 中间件
│   ├── api/
│   │   ├── auth.py              # JWT / SSO
│   │   ├── kb.py                # 知识库(代理 RAGFlow)
│   │   ├── diagnose.py          # log 诊断(代理 Dify + SSE)
│   │   ├── jobs.py              # 长任务(机台执行)
│   │   ├── machines.py          # 机台状态
│   │   ├── notify.py            # 钉钉通知
│   │   ├── assets.py            # 资产字典
│   │   └── settings.py          # 配置(钉钉 / 模型 / 提示词)
│   ├── core/
│   │   ├── security.py          # 鉴权 + RBAC
│   │   ├── mutex.py             # 机台互斥锁(Redis + DB)
│   │   ├── whitelist.py         # 指令白名单
│   │   ├── ssh.py               # paramiko 封装
│   │   └── dify_client.py       # httpx 异步调 Dify
│   ├── models/                  # SQLAlchemy ORM
│   ├── schemas/                 # Pydantic 模型
│   ├── db/
│   │   ├── migrations/          # Alembic
│   │   └── session.py
│   ├── workers/                 # Celery(或 BackgroundTasks)
│   ├── tests/                   # pytest
│   ├── Dockerfile
│   └── pyproject.toml
│
├── ai_engine/                   # 3. AI 引擎(Dify + RAGFlow 配置)
│   ├── docker-compose.yml       # Dify + RAGFlow 编排
│   ├── ragflow/
│   │   └── datasets/            # 数据集导出(版本管理)
│   └── dify/
│       └── workflows/           # workflow DSL(YAML 版本管理)
│
├── deploy/                      # 4. 一键部署
│   ├── docker-compose.yml       # 全栈编排
│   ├── .env.template
│   └── README.md
│
├── docs/
│   ├── specs/                   # 设计 / 方案文档
│   └── api/                     # 自动生成 OpenAPI
│
├── scripts/
│   ├── dev.sh                   # Mac 本地一键起
│   └── deploy.sh                # Linux 服务器部署
│
├── .gitignore
└── README.md
```

---

## 6. 数据模型(MySQL / PostgreSQL)

```sql
-- 用户 + 角色(RBAC)
CREATE TABLE users (
  id            BIGINT PRIMARY KEY AUTO_INCREMENT,
  username      VARCHAR(64) UNIQUE NOT NULL,
  password_hash VARCHAR(255) NOT NULL,    -- bcrypt
  role          ENUM('admin','tester','viewer') NOT NULL,
  api_token     VARCHAR(64) UNIQUE,        -- 个人 API token(本地脚本调用)
  created_at    TIMESTAMP NOT NULL,
  updated_at    TIMESTAMP NOT NULL
);

-- 机台资产字典
CREATE TABLE machines (
  id            BIGINT PRIMARY KEY AUTO_INCREMENT,
  name          VARCHAR(64) NOT NULL,
  ip            VARCHAR(45) NOT NULL,
  ssh_port      INT NOT NULL DEFAULT 22,
  ssh_user      VARCHAR(32) NOT NULL,
  ssh_key_path  VARCHAR(255),
  slot          VARCHAR(32),                 -- 物理槽位号
  firmware      VARCHAR(64),
  nand_model    VARCHAR(64),
  status        ENUM('online','offline','busy','error') NOT NULL DEFAULT 'offline',
  last_heartbeat TIMESTAMP,
  created_at    TIMESTAMP NOT NULL,
  updated_at    TIMESTAMP NOT NULL
);

-- 互斥锁(机台 + 任务,防并发)
CREATE TABLE machine_locks (
  machine_id    BIGINT PRIMARY KEY,
  job_id        BIGINT,
  locked_by     BIGINT NOT NULL,
  locked_at     TIMESTAMP NOT NULL,
  expires_at    TIMESTAMP NOT NULL,
  FOREIGN KEY (machine_id) REFERENCES machines(id),
  FOREIGN KEY (locked_by) REFERENCES users(id)
);

-- 指令白名单
CREATE TABLE command_whitelist (
  id            BIGINT PRIMARY KEY AUTO_INCREMENT,
  command_pattern VARCHAR(255) NOT NULL,    -- 正则,如 ^fio\s+
  description   VARCHAR(255),
  enabled       BOOLEAN NOT NULL DEFAULT TRUE,
  created_at    TIMESTAMP NOT NULL
);

-- 长任务(机台执行)
CREATE TABLE jobs (
  id            BIGINT PRIMARY KEY AUTO_INCREMENT,
  user_id       BIGINT NOT NULL,
  machine_id    BIGINT NOT NULL,
  script        TEXT NOT NULL,
  plan          TEXT,
  status        ENUM('queued','running','done','failed','cancelled') NOT NULL,
  stdout        MEDIUMTEXT,
  exit_code     INT,
  started_at    TIMESTAMP,
  finished_at   TIMESTAMP,
  created_at    TIMESTAMP NOT NULL,
  FOREIGN KEY (user_id) REFERENCES users(id),
  FOREIGN KEY (machine_id) REFERENCES machines(id)
);

-- AI 调用日志(审计 + 算力统计)
CREATE TABLE ai_call_logs (
  id            BIGINT PRIMARY KEY AUTO_INCREMENT,
  user_id       BIGINT NOT NULL,
  scenario      VARCHAR(64) NOT NULL,         -- 'log_diagnose' / 'test_case' / 'kb_search'
  prompt_tokens INT,
  completion_tokens INT,
  total_tokens  INT,
  model         VARCHAR(64),
  latency_ms    INT,
  success       BOOLEAN,
  error         TEXT,
  created_at    TIMESTAMP NOT NULL,
  INDEX idx_user_scenario (user_id, scenario, created_at)
);

-- 钉钉配置
CREATE TABLE dingtalk_configs (
  id            BIGINT PRIMARY KEY AUTO_INCREMENT,
  name          VARCHAR(64) UNIQUE NOT NULL,
  webhook_url   VARCHAR(512) NOT NULL,
  secret        VARCHAR(128),
  msg_template  TEXT,
  enabled       BOOLEAN NOT NULL DEFAULT TRUE,
  created_at    TIMESTAMP NOT NULL,
  updated_at    TIMESTAMP NOT NULL
);

-- 通知规则
CREATE TABLE notification_rules (
  id            BIGINT PRIMARY KEY AUTO_INCREMENT,
  scenario      VARCHAR(64) NOT NULL,
  dingtalk_id   BIGINT NOT NULL,
  enabled       BOOLEAN NOT NULL DEFAULT TRUE,
  created_at    TIMESTAMP NOT NULL,
  FOREIGN KEY (dingtalk_id) REFERENCES dingtalk_configs(id)
);

-- 通知历史
CREATE TABLE notification_logs (
  id            BIGINT PRIMARY KEY AUTO_INCREMENT,
  scenario      VARCHAR(64) NOT NULL,
  dingtalk_id   BIGINT NOT NULL,
  payload       TEXT NOT NULL,
  status        ENUM('success','failed') NOT NULL,
  error         TEXT,
  sent_at       TIMESTAMP NOT NULL,
  INDEX idx_sent_at (sent_at)
);

-- 审计日志
CREATE TABLE audit_logs (
  id            BIGINT PRIMARY KEY AUTO_INCREMENT,
  user_id       BIGINT,
  action        VARCHAR(64) NOT NULL,
  target        VARCHAR(255),
  detail        JSON,
  created_at    TIMESTAMP NOT NULL,
  INDEX idx_user_time (user_id, created_at)
);
```

---

## 7. 鉴权与角色(RBAC)

| 角色 | 能做什么 |
|---|---|
| **viewer** | 浏览知识库 / 看历史 log / 查 PM dashboard |
| **tester** | 上传 log 诊断 / 检索协议 / 跑脚本(白名单内)/ 看机台状态 |
| **admin** | 全部 + 改配置 / 部署 FW / 看审计 / 管用户 / 管白名单 |

- **会话鉴权**:JWT(HS256,7 天过期,Refresh token)
- **API 鉴权**:个人 `api_token`(供本地 Python 脚本远程调用,带 `users.api_token` 字段)
- **Dify 调中台**:service token(独立,只允许 `POST /notify` + `POST /kb/ingest`)

---

## 8. 物理世界隔离(防炸机)

### 8.1 三道闸

```
[AI 引擎]                  [中台]                       [硬件]
Dify 输出"rm -rf /"     → FastAPI 白名单校验 ✗        不下发
                          FastAPI 互斥锁申请
                          二次人工确认(Tester 高危命令)
                       → paramiko SSH 执行
                       → 实时回传 stdout
```

### 8.2 互斥锁实现

- **DB 层**:`SELECT ... FOR UPDATE` 锁 `machine_locks` 行
- **Redis 层**:`SET machine:{id}:lock <job_id> NX PX 3600000`(过期 1h 防崩溃死锁)
- **Job 层**:每个 job 持锁期间,其他 job 排队或报错

### 8.3 白名单默认集

```
fio\s+.+
smartctl\s+.+
nvme\s+.+
sg_(read|write|identify|start|stop|test)\s+.+
ssd_tool\s+.+
./run_test\.sh
pytest\s+.+
```

任何不在白名单的命令**必须 Admin 二次确认**才能下发。

---

## 9. 三级配置规范

| 级别 | 入口 | 放什么 | 谁能改 |
|---|---|---|---|
| **系统级** | 左下角齿轮 | 机台字典 / Dify API key / RAGFlow 地址 / DB 账密 / RBAC 角色定义 | Admin |
| **个人级** | 右上角头像 | API token / 界面语言 / 通知订阅偏好 | 本人 |
| **业务级** | 当前模块主页面内(Drawer) | 协议库筛选 / Top-K 调节 / 模型选择 / 提示词参数 | 当前用户 |

**业务级配置**用 Element Plus `<el-drawer>` 从右侧滑出,点空白处自动隐去,绝不打断思考流。

---

## 10. UI / UX 范式

### 10.1 主外壳(`MainLayout.vue`)

```
┌────────────────────────────────────────────────────────────────────┐
│  [Logo] TestMate              🟢 12 Idle | 🔴 1 Error   👤 Jarvis  │  ← 顶栏 56px
├──────┬─────────────────────────────────────────────┬──────────────┤
│      │                                             │              │
│ 📚   │                                             │  📖 协议随身  │  ← 右轴
│ 知识 │           悬浮主工作区(bg-white)            │  ┌────────┐  │     360px
│      │           shadow-floating                   │  │ 搜索框 │  │
│ 📊   │           rounded-2xl                       │  ├────────┤  │
│ 诊断 │           padding 32px                      │  │ 命中   │  │
│      │                                             │  │ 切片   │  │
│ 🧪   │           <router-view />                  │  │ 高亮   │  │
│ 用例 │                                             │  │ PDF    │  │
│      │                                             │  │ 渲染   │  │
│ ⚙   │                                             │  └────────┘  │
│ 运维 │                                             │              │
│      │                                             │              │
│ ──── │                                             │              │
│ ⚙️   │                                             │              │
│ 设置 │                                             │              │
│      │                                             │              │
│ 🟢   │                                             │              │
│ 12  │                                             │              │
│ 🔴 1 │                                             │              │
│      │                                             │              │
└──────┴─────────────────────────────────────────────┴──────────────┘
```

### 10.2 关键组件

- **`<MonacoEditor>`**:等宽字体 / 行号 / 代码高亮 / 只读模式 / diff 模式
- **`<PdfHighlighter>`**:PDF.js 渲染,接收切片坐标,黄色高亮命中段
- **`<MachineStatusCapsule>`**:实时心跳,绿 / 灰 / 红 / 黄四色
- **`<FilterDrawer>`**:从右滑出,筛选 + 高级参数,点空白关闭

### 10.3 视觉规范

- 背景:`bg-slate-50`
- 卡片:`bg-white rounded-2xl shadow-floating`
- 主题色:`indigo-600`(主) / `emerald-500`(成功) / `rose-500`(失败)
- 字体:系统默认 + `JetBrains Mono`(代码)
- 暗色:`class="dark"` 切换,所有颜色走 CSS 变量

---

## 11. 部署

### 11.1 一键起

```bash
git clone git@github.com:jarvs1024/TestMate.git
cd TestMate
cp deploy/.env.template deploy/.env
$EDITOR deploy/.env                 # 填 DB / Redis / Dify / RAGFlow 凭证
docker compose -f deploy/docker-compose.yml up -d
```

启动:

- `frontend_web` (Nginx,port 8080)
- `backend_gateway` (FastAPI + Uvicorn,port 8000)
- `mysql` (port 3306,数据卷)
- `redis` (port 6379)
- `dify` (port 80,含 postgres + weaviate)
- `ragflow` (port 18080,含 ES + MinIO)

### 11.2 数据卷

```
./data/mysql/         MySQL 数据
./data/redis/         Redis 持久化
./data/dify/          Dify 数据集 + workflow
./data/ragflow/       RAGFlow 知识库
```

### 11.3 备份脚本

```bash
#!/bin/bash
DATE=$(date +%F)
# DB
docker compose exec mysql mysqldump -uroot -p"$MYSQL_ROOT_PASSWORD" testmate > backup/testmate-$DATE.sql
# 知识库
docker compose exec ragflow tar czf /backup/ragflow-$DATE.tar.gz /var/lib/ragflow
# Dify workflow
docker compose exec dify tar czf /backup/dify-$DATE.tar.gz /var/lib/dify
```

---

## 12. 实施路线

### P0 — 跑得起来(2 周)

- Monorepo 脚手架(Vue 3 + FastAPI + Dify + RAGFlow 全栈 Docker Compose)
- FastAPI 中台骨架:JWT 鉴权 / 4 张表(users / machines / jobs / ai_call_logs)
- 前端主外壳:三轴布局 + 登录页 + 空状态
- 1 个端到端 demo:上传 log → Dify 诊断 → SSE 流式 → Monaco 显示

### P1 — 核心场景(3 周)

- 协议检索(右轴 RAG + 主区双栏 PDF 高亮)
- 指令白名单 + 互斥锁 + paramiko SSH 下发
- 机台状态实时监控(左轴胶囊)
- 钉钉通知(Dify → 中台 → 群机器人)
- 通知规则 + 历史查询
- 业务级 Drawer(协议库筛选 + Top-K)

### P2 — 增强(2~3 周)

- PM 视角 dashboard(Token 漏斗 / Prompt 灰度 / 团队时间线)
- 用例生成模块(Dify + Monaco 双栏)
- 完整审计日志 + Admin 查询页
- 告警 + Prometheus + Grafana
- 个人 API token(本地脚本调用)

### P3 — 按需

- K8s 化(数据量 / 用户量起来后)
- SSO(LDAP / OAuth)
- 移动端 / 桌面端

---

## 13. 风险与备选

| 风险 | 影响 | 备选 |
|---|---|---|
| LLM 效果不达预期 | 中 | P0 先用 1~2 个高质量场景(协议检索)验证,效果 OK 再扩 |
| Dify 直接调 RAGFlow 出问题 | 中 | 兜底:中台也能直调 RAGFlow,Dify 不通时降级 |
| 钉钉群机器人 URL 泄露 | 低 | 加签 secret 校验 + 定期轮换 |
| 机台互斥锁实现复杂 | 中 | 先用 Redis 简单实现,DB 行锁 P2 加 |
| RAGFlow 知识库更新慢 | 中 | Dify workflow 加 cron 节点,定期触发 ingest |
| 单点故障 | 中 | 数据卷每日备份;P3 升 K8s |
| AI 幻觉下高危命令 | **高** | **互斥锁 + 白名单 + 二次确认三道闸强制** |

---

## 14. 范围之外(明确不做)

- 多租户 / 跨团队共用
- 完整 SSO / OAuth(后期 P3)
- IM 双向消息(只发群机器人)
- 移动端 / 桌面端
- 端到端加密(信任内网)
- 多语言 i18n

---

## 15. 关联文档

- 汇报版:`docs/specs/2026-07-04-testmate-brief.md`
