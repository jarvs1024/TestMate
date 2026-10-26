# TestMate · SSD 测试伙伴

> SSD 测试组的内网 AI 工作平台 —— Vue 3 + FastAPI，部署在内网。

## 一句话

前店后厂：**能力墙**前端（一张卡 = 一项能力，分工具 / 看板 / 底座三种角色）+ FastAPI 中台 + 内置 AI 引擎 + RAGFlow 知识库，服务 SSD 测试组日常工作。

> 2026-10-25 起首页不再是「智能体广场」——卡片不全是智能体（代码检视是看板、资产市场与知识库是底座），统一叫「能力」；角色只回答「干活 / 看数 / 供料」，细分信息由业务域标签承担。详见 [能力墙重构设计](docs/specs/2026-10-25-capability-wall-design.md)。

## 项目状态

- **生产在跑**：Docker 模式，内网 SSD 测试组日常使用
- **能力墙重构完成**：首页与设置页口径统一为「能力」，Dify 已整个下线
- **账号体系**：账号须管理员先建过才能登录；普通用户用公司邮箱免密登录，管理员一律要密码
- **三种部署模式并存**：Docker / 裸机 systemd / 裸机 local(macOS)，互不干扰

## 平台提供什么

| 能力 | 位置 | 干什么 |
|---|---|---|
| **工作台（能力墙）** | 首页 `/` | 按工具 / 看板 / 底座三种角色陈列能力，点卡片直接进 |
| **代码检视看板** | `/code-review` | MR 生命周期、建议采纳率、规则命中、作者分布、周报 |
| **能力详情（工具运行）** | `/c/:code` | 填参数 → 出结果，附 run 全量日志与时间线 |
| **AI 资产市场** | `/market` | 能力目录、打包发布、审核下架、版本、任务队列、审计 |
| **知识库** | `/kb-manage` | RAGFlow 数据集 / 文档 / 分段，检索即用 |
| **账号管理** | 设置页「👥 用户管理」 | 管理员建号、改角色、停用 |
| **平台配置** | 设置页 | RAGFlow / ReviewAgent / GitLab / 钉钉，改完立刻生效，不需重启 |
| **机台管理** | `/api/v1/machines` | 机台字典（SSD 测试机台接入） |

> 协议检索、log 诊断、用例生成这些**不是平台内置功能**——它们是市场上架的能力卡，装了才有。

## 技术栈

**前端**：Vue 3.5 + Vite 5.4 + TypeScript 5.5 + Element Plus 2.8 + Tailwind 3.4 + Pinia 2.2 + monaco-editor 0.50
**后端**：Python 3.11+ + FastAPI 0.115 + SQLAlchemy 2.0(async) + alembic 1.13 + aiomysql + redis 5
**认证**：python-jose JWT + bcrypt，7 天 token，RBAC 三级（admin / tester / viewer）
  · 账号**必须管理员先建过**才能登录（建号入口：设置页「👥 用户管理」）
  · 普通用户：公司邮箱（后缀固定 @twsc.com.cn），建号时没设密码就是**免密登录**
  · 管理员：账号名 + 密码（一律必填）
**AI 集成**：httpx 调 RAGFlow / ReviewAgent / GitLab，外部服务不可达时降级
**硬件触达**：paramiko SSH 3.x
**数据**：MySQL 8.0（主数据）+ Redis 7-alpine（缓存 / 互斥锁）
**可观测性**：structlog JSON 日志
**部署**：三种模式并存，互不干扰
  · **Docker**（`deploy/deploy.sh`，生产在跑）—— 4 容器：mysql / redis / backend / frontend
  · **裸机 systemd**（`deploy/native/tmctl.sh`，Linux）—— 零容器：本机 MySQL/Redis + 本机进程
  · **裸机 local**（`deploy/native/tmctl.sh`，macOS，launchd 管开机自启与崩溃自愈）—— 零容器：本机 MySQL/Redis + 本机进程

## 目录结构

```
TestMate/
├── backend_gateway/                # FastAPI 后端
│   ├── app/
│   │   ├── api/                    # 路由模块: health / auth / machines / kb / notify
│   │   │                           #   / agents(能力) / settings / review_agent / marketplace
│   │   ├── core/                   # 配置 / 安全 / 日志 / 外部服务客户端 / 资产市场策略
│   │   ├── db/                     # SQLAlchemy async session
│   │   ├── models/                 # ORM 模型(表名见各文件的 __tablename__)
│   │   ├── schemas/                # Pydantic 请求/响应(agent / asset / auth / system_setting)
│   │   └── main.py                 # FastAPI 入口 + lifespan + structlog
│   ├── alembic/versions/           # 数据库迁移(0001_initial ~ 0022_user_token_version)
│   ├── tests/                      # pytest 用例
│   ├── Dockerfile                  # multi-stage build
│   └── requirements.txt / .lock
├── frontend_web/                   # Vue 3 前端
│   ├── src/
│   │   ├── api/                    # axios 客户端(assets / capabilities / kb / reviewagent
│   │   │                           #   / settings / users)
│   │   ├── components/             # 通用组件
│   │   ├── constants/              # 能力种类常量
│   │   ├── layouts/                # MainLayout
│   │   ├── router/                 # 路由表
│   │   ├── stores/                 # pinia stores(capabilities / theme / user)
│   │   ├── styles/                 # 全局 CSS + design tokens
│   │   ├── types/                  # TS 类型
│   │   ├── utils/                  # request.ts(axios 拦截器)+ 通用工具
│   │   └── views/
│   │       ├── Home/               # 工作台 · 能力墙
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
│   ├── backup.sh / restore.sh      # 数据备份 / 恢复
│   ├── native/                     # 裸机模式(不走 Docker)
│   │   ├── tmctl.sh                # 运维唯一入口(check/install/start/stop/…)
│   │   ├── lib.sh                  # 公共函数 + local driver 进程管理 + launchd 封装
│   │   ├── preflight.sh            # 环境体检
│   │   ├── selftest.sh             # 部署资产自检(模板 + systemd + nginx + shellcheck)
│   │   ├── sandbox-probe.sh        # systemd 沙箱回归
│   │   └── units/                  # systemd 单元 + nginx 配置 + launchd 单元模板
│   └── README.md                   # Docker 模式部署文档
├── scripts/                        # 辅助脚本(开发 / 部署 / e2e / 种子数据)
│   ├── check_deploy.sh             # 部署一致性自检(前端特征串 + 后端 sha256)
│   ├── create_admin.py             # 手动建 admin(显式 --mysql-* + --password-file)
│   ├── deploy.sh                   # 部署前端 / 后端
│   ├── dev.sh / start.sh / stop.sh # 本地开发与一键起停
│   ├── seed_market.py              # 资产市场种子数据
│   ├── make_real_packages.py       # 生成真实安装包(联调用)
│   └── e2e_*.js                    # playwright 端到端脚本
└── docs/specs/                     # 设计 / 方案文档
```

## 文档索引

| 文档 | 用途 |
|---|---|
| [能力墙重构设计](docs/specs/2026-10-25-capability-wall-design.md) | **当前主设计** —— 信息架构 / 角色模型 / 文案对照 / Dify 下线 / 发布权限 |
| [AI 资产市场总览](docs/specs/2026-10-22-ai-asset-market-overview.md) | 资产市场的能力模型与上架流程 |
| [资产市场验证记录](docs/specs/2026-10-23-asset-market-verification.md) | 验证用例与结论 |
| [智能体市场设计](docs/specs/2026-10-14-agent-marketplace-design.md) | 执行注册表模型(资产市场的前身) |
| [辅助提单系统方案](docs/specs/2026-08-18-issue-helper-design.md) | 提单方向设计稿 |
| [deploy/README.md](deploy/README.md) | Docker 模式部署实操(在线 / 离线 / 备份 / 排错) |
| [deploy/native/README.md](deploy/native/README.md) | 裸机模式部署实操(systemd / macOS local，含环境体检 / 开机自启 / 升级 / 备份) |

> 2026-07 的立项与 P0 进度笔记（`2026-07-04-*` / `2026-07-07-*`）已归档在 `docs/specs/`，只作历史留档，现状以本文件与上面几份为准。

## 快速部署

三种模式，都一键，互不干扰：

```bash
# ===== 模式 A: Docker (默认, 生产在跑) =====
cd deploy && cp .env.template .env && $EDITOR .env
sudo ./deploy.sh              # 在线;离线见 deploy/README.md §3

# ===== 模式 B: 裸机 systemd (Linux 直接跑进程) =====
sudo ./deploy/native/tmctl.sh install --auto

# ===== 模式 C: 裸机 local (macOS, 无 systemd) =====
brew install nginx
./deploy/native/tmctl.sh local install --auto  # 装 + 起 (--auto 连本机 MySQL/Redis 一起装)
sudo ./deploy/native/tmctl.sh local hosts fix  # 让容器里的地址在宿主上也能用
./deploy/native/tmctl.sh launchd install       # 开机自启 + 崩溃自愈
```

> 裸机模式**不碰任何容器** —— MySQL 和 Redis 也是这台机器自己的服务
> (macOS 走 `brew services`, Linux 走 `systemd`)。所以 Docker Desktop 崩了、
> 机器重启都不影响它。详见 [deploy/native/README.md §5](deploy/native/README.md)。

> 模式 C 为什么多一条 `local hosts fix`？`host.docker.internal` 是**容器里**访问宿主用的名字，
> 本地部署的进程跑在**宿主**上，不修的话代码检视连不上、资产市场也推不到 GitLab。详见 [deploy/native/README.md §5](deploy/native/README.md)。

裸机模式**运维只记一个命令** `deploy/native/tmctl.sh`（有 systemd 走 systemd，没有自动走 local）：

```bash
./deploy/native/tmctl.sh check      # 环境体检 (只读)
./deploy/native/tmctl.sh install    # 一键部署 (含开机自启)
./deploy/native/tmctl.sh restart    # 一键重启
./deploy/native/tmctl.sh stop       # 一键停止
./deploy/native/tmctl.sh enable     # 开机自启
./deploy/native/tmctl.sh status     # 状态
./deploy/native/tmctl.sh doctor     # 深度排障
./deploy/native/tmctl.sh update     # 升级
./deploy/native/tmctl.sh backup     # 备份
```

> **同一台机器上 Docker 模式和裸机 local 不能同时跑**（两个后端会抢同一批资产市场 job），
> 切模式要把另一套停干净——**包括 frontend 容器**，否则那个端口会变成「页面能开、接口全 502」的假象。
> 具体命令见 [deploy/README.md §0](deploy/README.md)。

详见 [deploy/native/README.md](deploy/native/README.md)。
