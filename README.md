# TestMate · SSD 测试伙伴

> SSD 测试组的内网 AI 工作平台,基于 Vue 3 + FastAPI + RAGFlow。

## 项目状态

- 当前阶段:**P0 已完成,P1 部分完成**(2026-07-07)
- 仓库:`github.com/jarvs1024/TestMate`
- 详细方案:`docs/specs/2026-07-04-testmate-design.md`
- 汇报版:`docs/specs/2026-07-04-testmate-brief.md`
- P0 进度:`docs/specs/2026-07-04-p0-progress.md`

## 一句话

前店后厂:Vue 3 **能力墙**前端(一张卡 = 一项能力,分工具/看板/底座三种角色)+ FastAPI 中台(完全包裹 AI 引擎 + 触达硬件)+ 内置 AI 引擎 + RAGFlow 知识库,部署在内网,服务 SSD 测试组日常工作。

> 2026-10-25 起首页不再是「智能体广场」——卡片不全是智能体(代码检视是看板、资产市场与知识库是底座),统一叫「能力」;角色只回答「干活 / 看数 / 供料」,细分信息由业务域标签承担,详见 [能力墙重构设计](docs/specs/2026-10-25-capability-wall-design.md)。

## 核心特性

- **协议检索**:NVMe / JEDEC 等规范 PDF 切片 + 高亮问答
- **log 诊断**:上传 PCIe / 串口 log,AI 提取 assert,对比历史缺陷图谱
- **用例生成**:输入需求,自动生成符合 `import ssd_tool` 规范的 pytest 脚本
- **机台三道闸**:互斥锁 + 指令白名单 + 二次确认,防止 AI 幻觉炸机
- **钉钉通知**:能力跑完 → 中台转发 → 群机器人单向推送
- **PM dashboard**:Token 漏斗、Prompt 灰度、团队时间线

## 技术栈

**前端**: Vue 3.5 + Vite 5.4 + TypeScript 5.5 + Element Plus 2.8 + Tailwind 3.4 + Pinia 2.2 + monaco-editor 0.50
**后端**: Python 3.11 + FastAPI 0.115 + SQLAlchemy 2.0(async) + alembic 1.13 + aiomysql + redis.asyncio
**认证**: python-jose JWT + passlib/bcrypt,7 天 token,RBAC 三级(admin / tester / viewer)
  · 账号**必须管理员先建过**才能登录(建号入口: 设置页「👥 用户管理」)
  · 普通用户: 公司邮箱(后缀固定 @twsc.com.cn),建号时没设密码就是**免密登录**
  · 管理员: 账号名 + 密码(一律必填)
**AI 集成**: httpx 调 RAGFlow / ReviewAgent / GitLab,外部服务不可达时降级
**硬件触达**: paramiko SSH 2.x
**数据**: MySQL 8.0(主数据)+ Redis 7-alpine(缓存 / 互斥锁)
**可观测性**: structlog 24.1 JSON 日志
**部署**: docker compose v2(自动 v1 fallback),4 容器(mysql / redis / backend / frontend)

## 目录结构

```
TestMate/
├── backend_gateway/                # FastAPI 后端
│   ├── app/
│   │   ├── api/                    # 路由模块(全部路由见此目录:health / auth / agents / marketplace / kb / machines / notify / settings / pr_agent / review_agent)
│   │   ├── core/                   # 配置 / 安全 / 日志 + 外部服务客户端 + 资产市场策略(全部见 app/core/)
│   │   ├── db/                     # SQLAlchemy async session
│   │   ├── models/                 # ORM 模型(表名见各文件的 __tablename__)
│   │   ├── schemas/                # Pydantic 请求/响应(agent / asset / auth / system_setting)
│   │   ├── workers/                # (预留异步任务)
│   │   └── main.py                 # FastAPI 入口 + lifespan + structlog
│   ├── alembic/versions/           # 数据库迁移(0001_initial ~ 0021_user_account_control)
│   ├── tests/                      # pytest 用例(见 tests/ 目录)
│   ├── Dockerfile                  # multi-stage build
│   └── requirements.txt
├── frontend_web/                   # Vue 3 前端
│   ├── src/
│   │   ├── api/                    # axios 客户端(assets / capabilities / kb / pragent / reviewagent / settings / users)
│   │   ├── components/             # 通用组件
│   │   ├── constants/              # 能力种类常量
│   │   ├── layouts/                # MainLayout
│   │   ├── router/                 # 路由表
│   │   ├── stores/                 # pinia stores(capabilities / theme / user)
│   │   ├── styles/                 # 全局 CSS + design tokens
│   │   ├── types/                  # TS 类型
│   │   ├── utils/                  # request.ts(axios 拦截器)+ 通用工具
│   │   └── views/                  # 路由页面
│   │       ├── Home/               # 首页 · 能力墙 (CapabilityCard)
│   │       ├── Capability/         # 能力详情: ToolRunner / BoardView / Catalog / Library
│   │       ├── Login/
│   │       └── Settings/
│   ├── e2e.mjs                     # playwright 冒烟脚本
│   ├── Dockerfile                  # node build → nginx 静态
│   └── package.json
├── deploy/                         # 一键部署
│   ├── docker-compose.yml          # 4 服务编排
│   ├── deploy.sh                   # 主入口(在线 / 离线 / JWT 校验 / admin 自动建)
│   ├── offline-save.sh             # 离线镜像打包
│   ├── offline-images.txt          # 离线镜像清单
│   ├── backup.sh                   # 数据备份(mysqldump + redis rdb)
│   ├── restore.sh                  # 数据恢复(配 backup.sh)
│   ├── native/                     # 裸机模式 (systemd, 不走 Docker)
│   │   ├── tmctl.sh                # 运维唯一入口(check/install/start/stop/restart/…)
│   │   ├── preflight.sh            # 环境体检
│   │   ├── selftest.sh             # 部署资产自检(模板 + systemd + nginx)
│   │   └── units/                  # systemd 单元 + nginx 配置模板
│   └── README.md                   # 部署文档
├── scripts/                        # 辅助脚本(开发 / 部署 / e2e / 种子数据)
│   ├── check_deploy.sh             # 部署一致性自检(前端特征串 + 后端 sha256)
│   ├── create_admin.py             # 手动建 admin(显式 --mysql-* + --password-file)
│   ├── deploy.sh                   # 部署前端 / 后端
│   ├── dev.sh                      # 本地开发
│   ├── start.sh / stop.sh          # 本地一键起 / 停
│   ├── seed_market.py              # 资产市场种子数据
│   ├── make_real_packages.py       # 生成真实安装包(联调用)
│   └── e2e_*.js                    # playwright 端到端脚本
└── docs/                           # 文档
    └── specs/                      # 设计 / 方案 / 进度(见 docs/specs/)
```

## 文档索引

| 文档 | 用途 |
|---|---|
| `docs/specs/2026-07-04-testmate-brief.md` | 老板汇报(归档) |
| `docs/specs/2026-07-04-testmate-design.md` | 完整技术方案(归档) |
| `docs/specs/2026-07-04-p0-progress.md` | P0 进度笔记(2026-07-04,归档) |
| `docs/specs/2026-07-07-p0-progress.md` | P0 进度笔记(2026-07-07,归档) |
| `docs/specs/2026-08-18-issue-helper-design.md` | 辅助提单系统方案(P0 设计稿) |
| `docs/specs/2026-10-14-agent-marketplace-design.md` | 智能体市场设计(执行注册表模型) |
| `docs/specs/2026-10-22-ai-asset-market-overview.md` | AI 资产市场总览 |
| `docs/specs/2026-10-23-asset-market-verification.md` | 资产市场验证记录 |
| `docs/specs/2026-10-25-capability-wall-design.md` | 能力墙重构设计 (首页信息架构 / 角色模型 / 文案对照 / Dify 下线) |
| `deploy/README.md` | 一键部署实操(在线 / 离线 / 备份 / 排错) — Docker 模式 |
| `deploy/native/README.md` | 一键部署实操 — 裸机 systemd 模式 (环境体检 / 开机自启 / 一键启停 / 升级 / 备份) |

## 快速部署

两种模式, 都一键, 互不干扰:

```bash
# ===== 模式 A: Docker (默认, 生产在跑) =====
cd deploy && cp .env.template .env && $EDITOR .env
sudo ./deploy.sh              # 在线;离线见 deploy/README.md §3

# ===== 模式 B: 裸机 systemd (Linux 直接跑进程) =====
sudo ./deploy/native/tmctl.sh install --auto

# ===== 模式 C: 裸机 local (macOS, 无 systemd) =====
brew install nginx
./deploy/native/tmctl.sh local install      # 装 + 起
sudo ./deploy/native/tmctl.sh local hosts fix   # 让容器里的地址在宿主上也能用
./deploy/native/tmctl.sh launchd install    # 开机自启 + 崩溃自愈
```

> 模式 C 为什么要多一条 `local hosts fix`? 因为 `host.docker.internal` 是**容器里**
> 访问宿主用的名字 —— 本地部署的进程跑在**宿主**上, 不修的话代码检视连不上、
> 资产市场也推不到 GitLab。详见 `deploy/native/README.md` §5。

裸机模式**运维只记一个命令** `deploy/native/tmctl.sh`（有 systemd 走 systemd, 没有自动走 local）:

```bash
sudo ./deploy/native/tmctl.sh check      # 环境体检 (只读)
sudo ./deploy/native/tmctl.sh install    # 一键部署 (含开机自启)
sudo ./deploy/native/tmctl.sh restart    # 一键重启
sudo ./deploy/native/tmctl.sh stop       # 一键停止
sudo ./deploy/native/tmctl.sh enable     # 开机自启
sudo ./deploy/native/tmctl.sh status     # 状态
sudo ./deploy/native/tmctl.sh doctor     # 深度排障
sudo ./deploy/native/tmctl.sh update     # 升级
sudo ./deploy/native/tmctl.sh backup     # 备份
```

详见 `deploy/native/README.md`。

## 当前进度(2026-07-07)

- ✅ P0 全栈可起 + API 路由(app/api/)+ ORM 模型(app/models/)+ monorepo 完整
- ✅ 86 服务器部署上线(8080 前端 / 18000 后端 / 43060 MySQL / 63790 Redis,见 `deploy/.env.template`)
- ✅ admin 账号已建(初始密码见 `deploy/.env` 的 `ADMIN_DEFAULT_PASSWORD`,生产部署后请立即修改)
- ✅ Docker 化加固 12 项(commit f0ef182):compose v1/v2 兼容 / 密码强度 / offline-images 补全 / multi-stage build / alembic / health 分层 / structlog / restore.sh 等
- ⏳ P1 核心场景(机台三道闸 / 协议检索 / 用例生成 / 钉钉通知)— 部分模块代码已有,待补外部 AI 推理接入 + 真实机台联调
- ⏳ P1 前端 monaco 接入(包已装,组件未接)
- ⏳ P1 真实 SSD 测试机台联调(paramiko 已接,机台字典已建)
