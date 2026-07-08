# TestMate 智能测试辅助平台

> SSD 测试组的内网 AI 工作平台,基于 Vue 3 + FastAPI + Dify + RAGFlow。

## 项目状态

- 当前阶段:**P0 已完成,P1 部分完成**(2026-07-07)
- 仓库:`github.com/jarvs1024/TestMate`
- 详细方案:`docs/specs/2026-07-04-testmate-design.md`
- 汇报版:`docs/specs/2026-07-04-testmate-brief.md`
- P0 进度:`docs/specs/2026-07-04-p0-progress.md`

## 一句话

前店后厂:Vue 3 结构化卡片前端 + FastAPI 中台(完全包裹 AI 引擎 + 触达硬件)+ Dify agent 编排 + RAGFlow 知识库,部署在内网,服务 SSD 测试组日常工作。

## 核心特性

- **协议检索**:NVMe / JEDEC 等规范 PDF 切片 + 高亮问答
- **log 诊断**:上传 PCIe / 串口 log,AI 提取 assert,对比历史缺陷图谱
- **用例生成**:输入需求,自动生成符合 `import ssd_tool` 规范的 pytest 脚本
- **机台三道闸**:互斥锁 + 指令白名单 + 二次确认,防止 AI 幻觉炸机
- **钉钉通知**:Dify 触发 → 中台转发 → 群机器人单向推送
- **PM dashboard**:Token 漏斗、Prompt 灰度、团队时间线

## 技术栈

**前端**: Vue 3.5 + Vite 5.4 + TypeScript 5.5 + Element Plus 2.8 + Tailwind 3.4 + Pinia 2.2 + monaco-editor 0.50
**后端**: Python 3.11 + FastAPI 0.115 + SQLAlchemy 2.0(async) + alembic 1.13 + aiomysql + redis.asyncio
**认证**: python-jose JWT + passlib/bcrypt,7 天 token,RBAC 三级(admin / tester / viewer)
**AI 集成**: httpx 调 Dify / RAGFlow,DIFY_MOCK 沙箱降级
**硬件触达**: paramiko SSH 2.x
**数据**: MySQL 8.0(主数据)+ Redis 7-alpine(缓存 / 互斥锁)
**可观测性**: structlog 24.1 JSON 日志
**部署**: docker compose v2(自动 v1 fallback),4 容器(mysql / redis / backend / frontend)

## 目录结构

```
TestMate/
├── backend_gateway/           # FastAPI 后端
│   ├── app/
│   │   ├── api/               # 8 个路由(health / auth / agents / kb / machines / diagnose / notify / settings)
│   │   ├── core/              # config / security / logging / dify_client / ragflow_client / settings_store
│   │   ├── db/                # SQLAlchemy async session
│   │   ├── models/            # 4 张表(user / agent / machine / system_setting)
│   │   ├── schemas/           # Pydantic 请求/响应
│   │   ├── workers/           # (预留异步任务)
│   │   └── main.py            # FastAPI 入口 + lifespan + structlog
│   ├── alembic/               # 数据库迁移
│   │   └── versions/0001_initial.py
│   ├── Dockerfile             # multi-stage build
│   └── requirements.txt
├── frontend_web/              # Vue 3 前端
│   ├── src/
│   │   ├── api/               # axios 客户端
│   │   ├── components/        # 通用组件
│   │   ├── views/             # 路由页面(Login / Plaza / AgentRunner / KnowledgeManage / Settings)
│   │   ├── layouts/           # MainLayout
│   │   ├── router/            # 路由表
│   │   ├── stores/            # pinia stores
│   │   ├── styles/            # 全局 CSS + design tokens
│   │   └── utils/             # request.ts(axios 拦截器)
│   ├── Dockerfile             # node build → nginx 静态
│   └── package.json
├── deploy/                    # 一键部署
│   ├── docker-compose.yml     # 4 服务编排
│   ├── deploy.sh              # 主入口(在线 / 离线 / JWT 校验 / admin 自动建)
│   ├── offline-save.sh        # 离线镜像打包
│   ├── offline-images.txt     # 离线镜像清单
│   ├── backup.sh              # 数据备份(mysqldump + redis rdb)
│   ├── restore.sh             # 数据恢复(配 backup.sh)
│   └── README.md              # 部署文档
├── scripts/                   # 辅助脚本
│   ├── create_admin.py        # 手动建 admin(显式 --mysql-* + --password-file)
│   ├── start.sh               # 本地开发一键起
│   └── stop.sh
└── docs/                      # 文档
    └── specs/                 # 设计 / 方案 / 进度
        ├── 2026-07-04-testmate-brief.md
        ├── 2026-07-04-testmate-design.md
        └── 2026-07-04-p0-progress.md
```

## 文档索引

| 文档 | 用途 |
|---|---|
| `docs/specs/2026-07-04-testmate-brief.md` | 老板汇报 |
| `docs/specs/2026-07-04-testmate-design.md` | 完整技术方案 |
| `docs/specs/2026-07-04-p0-progress.md` | P0 进度笔记(2026-07-04) |
| `deploy/README.md` | 一键部署实操(在线 / 离线 / 备份 / 排错) |
| `C:\Users\2268\testmate_stack.md` | 完整技术栈全景(本地笔记) |
| `C:\Users\2268\testmate_docker_review.md` | Docker 化改进报告(本地笔记) |

## 快速部署

```bash
cd deploy && cp .env.template .env && $EDITOR .env
sudo ./deploy/deploy.sh        # 在线;离线见 deploy/README.md §3
```

详见 `deploy/README.md`。

## 当前进度(2026-07-07)

- ✅ P0 全栈可起 + 8 个 API 路由 + 4 张表 + monorepo 完整
- ✅ 86 服务器部署上线(8090 前端 / 8000 后端 / 3306 MySQL / 6379 Redis)
- ✅ admin 账号已建(admin / Admin@123)
- ✅ Docker 化加固 12 项(commit f0ef182):compose v1/v2 兼容 / 密码强度 / offline-images 补全 / multi-stage build / alembic / health 分层 / structlog / restore.sh 等
- ⏳ P1 核心场景(机台三道闸 / 协议检索 / 用例生成 / 钉钉通知)— 部分模块代码已有,待补 Dify workflow 配置 + 真实机台联调
- ⏳ P1 前端 monaco 接入(包已装,组件未接)
- ⏳ P1 真实 SSD 测试机台联调(paramiko 已接,机台字典已建)
