# TestMate 裸机部署 (native)

> 不走 Docker, 直接在机器上跑进程。Linux 用 systemd 管生命周期和开机自启, macOS 用 launchd。
> 适合: 内网服务器不让装 Docker / 机器资源紧张 / 运维只认 systemctl / mac 上要本地跑。

Docker 那套仍然保留 (`deploy/deploy.sh`), 三套并存, 互不影响。见 §8「几种模式怎么选」。

---

## 0. 两种 driver

| | `systemd` driver (Linux) | `local` driver (mac / 任何无 init 的机器) |
|---|---|---|
| 进程管理 | systemd unit | PID 文件 + nohup |
| 开机自启 | `systemctl enable` | launchd (`RunAtLoad`) |
| 崩溃自愈 | systemd `Restart=always` | launchd `KeepAlive` |
| 配置 / venv / 构建 / 健康检查 / doctor / backup | ✅ | ✅ **完全共用** |
| 前端托管 | nginx 独立实例 | nginx 独立实例（同一份模板） |
| MySQL / Redis | 宿主机服务 (脚本装) | 宿主机服务 (brew services / systemd) |
| 运行身份 | 专用系统用户 `testmate` | 当前登录用户（launchd 无 root 版用户 agent） |

自动选择, 也可以显式指定:

```bash
tmctl.sh status              # 自动 (mac 上走 local)
tmctl.sh local status        # 强制 local
```

---

## 1. 一句话上手

**Linux (systemd)**:

```bash
sudo ./deploy/native/tmctl.sh install --auto
```

**macOS (local + launchd)**:

```bash
brew install nginx                              # 前端静态托管
./deploy/native/tmctl.sh local install --auto  # 装 + 起 (--auto 连本机 MySQL/Redis 一起装)
./deploy/native/tmctl.sh launchd install       # 再加开机自启 + 崩溃自愈
```

`install` 会依次做完:

```
1/9 环境体检      → 缺什么装什么 (--auto)
2/9 宿主名解析    → 看一眼 host.docker.internal 在宿主上的状态 (不用管, 后端会自己改写, 见 §5)
3/9 生成配置      → JWT_SECRET / MySQL 口令 / admin 口令 随机生成, 不用手抄
4/9 数据库        → 装 + 起**本机** MySQL 和 Redis, 建 testmate 库 + 用户 (不用任何容器)
5/9 Python 依赖   → 建 venv, 按 requirements.lock 装
6/9 前端构建      → npm ci + vite build, 产物落到 runtime/frontend
7/9 资产市场 SSH  → 拷私钥进 runtime/ssh
8/9 应用配置      → backend.env + nginx.conf (独立实例)
9/9 启动          → 起进程 + 健康校验 + 建 admin
```

---

## 2. 运维命令速查

**只有这一个入口**: `deploy/native/tmctl.sh`。所有动作都从这儿走。

| 命令 | 干什么 | 要 root 吗 |
|---|---|---|
| `check` | 环境体检 —— 只读, 不改任何东西 | 否 |
| `install` | 一键部署 | Linux 要 |
| `start` / `stop` / `restart` | 启 / 停 / 重启 | Linux 要 |
| `reload` | 只重载 nginx 配置 (后端不动) | Linux 要 |
| `status` | 服务 / 端口 / 健康 / 版本 | 否 |
| `logs [-f]` | 看日志 | 否 |
| `enable` / `disable` | 开机自启 开 / 关 | Linux 要 |
| `update` | 升级: 拉代码 → 重建 → 重启 → 健康校验 | 是 |
| `backup` / `restore` | 数据备份 / 恢复 | restore 要 |
| `doctor` | 深度排障 (比 check 看得深) | 否 |
| `admin` | 建 / 改 admin 账号 | 否 |
| `uninstall` | 卸载 (默认保留数据) | 是 |
| **`local <命令>`** | **强制走 local driver** (PID 文件) | 否 |
| **`launchd install`** | **macOS: 装 launchd (开机自启 + 崩溃自愈)** | 否 |
| **`launchd uninstall`** | macOS: 卸载 launchd | 否 |
| **`launchd status`** | macOS: 看 launchd 状态 | 否 |
| **`local hosts check`** | macOS: 看 `host.docker.internal` 在宿主上通不通 | 否 |
| **`local hosts fix`** | macOS: 往宿主 `/etc/hosts` 加映射 (让容器里的地址在宿主上也能用) | 要 |

选项: `--auto` (自动装依赖) `--offline` (离线装) `--yes` (非交互) `--no-start` (装完不启动) `--from REF` (update 指定 ref) `--target UNIT` (logs 只看某个服务)。

```bash
# 开机自启(Linux 用 systemd, install 默认就开了)
sudo ./deploy/native/tmctl.sh enable
sudo ./deploy/native/tmctl.sh disable      # 取消自启, 但服务还跑着

# 重启 / 停止
sudo ./deploy/native/tmctl.sh restart
sudo ./deploy/native/tmctl.sh stop

# macOS: launchd 开机自启 + 崩溃自愈
./deploy/native/tmctl.sh launchd install
./deploy/native/tmctl.sh launchd status

# macOS: 让 host.docker.internal 在宿主上指回 127.0.0.1 (代码检视 / 市场推送要用)
sudo ./deploy/native/tmctl.sh local hosts fix

# 排障
./deploy/native/tmctl.sh check             # 体检
./deploy/native/tmctl.sh doctor            # 更深: 日志错误 / 配置一致性 / 迁移版本
./deploy/native/tmctl.sh logs -f           # 跟日志
```

---

## 3. 装之前先体检

```bash
./deploy/native/tmctl.sh check
```

体检是**只读**的 —— 不装东西、不改文件、不建目录。可以随时跑。

分九组, 每项都给出「怎么修」:

| 组 | 检查什么 |
|---|---|
| 一、系统 | 发行版 / 架构 / 内核 / **systemd 可用** / root 权限 / 包管理器 |
| 二、运行时依赖 | Python ≥ 3.11 / venv 模块 / pip / Node ≥ 18 / npm / gcc / Python.h / **nginx** / git / ssh |
| 三、数据存储 | MySQL 客户端 + 服务 / Redis 客户端 + 服务 |
| 四、端口占用 | 前端 8080 / 后端 8000 / MySQL 3306 / Redis 6379 |
| 五、机器资源 | 磁盘 ≥ 10 GB / 内存 ≥ 4 GB |
| 六、目录与权限 | 源码可读 / 运行时目录可写 |
| 七、部署配置 | `.env` 在不在 / JWT_SECRET 与两个口令的强度 |
| 八、网络 | pypi / npm registry 通不通 |
| 九、Docker 主机名 | **仅 local 模式** —— `host.docker.internal` 在宿主上通不通 (见 §5) |

退出码: 有 FAIL 项 → 1, 否则 0。适合挂到巡检脚本里。

> 体检会**跑完全部组**再汇总 —— 一项不过不会中途掐断。体检的价值就是"一次跑完, 把所有不行的地方和怎么修都列出来"。

---

## 4. 装完长什么样

```
/opt/testmate/                      ← 源码 (git clone 到哪就在哪)
└── deploy/native/
    ├── .env                        ← 部署配置 (含明文口令, 权限 600)
    └── runtime/                    ← 所有运行时产物 (不入 git)
        ├── venv/                   ← Python 虚拟环境
        ├── frontend/               ← 前端构建产物 (nginx 的 root)
        ├── market/                 ← 资产市场 git 工作区 (默认位置; mac 上通常指向共享目录, 见 §5)
        ├── logs/                   ← nginx 日志
        ├── run/                    ← nginx pid / 临时目录
        ├── config/
        │   ├── backend.env         ← 后端环境变量 (600)
        │   ├── nginx.conf          ← nginx 配置 (独立实例)
        │   └── mime.types
        └── ssh/                    ← 资产市场用的 SSH 私钥 (600)
```

两种 driver 的服务:

| driver | 单元 | 干什么 | 端口 |
|---|---|---|---|
| systemd | `testmate-backend.service` | uvicorn 跑 FastAPI | `127.0.0.1:8000` (只监听本机) |
| systemd | `testmate-frontend.service` | nginx 托管前端 + 反代 `/api/` | `0.0.0.0:8080` (对外) |
| launchd | `com.testmate.backend` | 同上, 后端 | `127.0.0.1:8000` |
| launchd | `com.testmate.frontend` | 同上, nginx | `0.0.0.0:8080` |

后端端口**默认只绑 127.0.0.1** —— 外部只能走 nginx, 直连不了后端。要改 `.env` 的 `BIND_ADDR`。

nginx 是**独立实例** (`nginx -c runtime/config/nginx.conf -p runtime/`), 不碰系统自带的 `/etc/nginx/`, 两者可以共存。

mac 上是 local driver, 进程不用 systemd 而用 PID 文件管; 开机自启和崩溃自愈交给 launchd
(`~/Library/LaunchAgents/com.testmate.{backend,frontend}.plist`)。

---

## 5. macOS 用法 (local driver)

```bash
brew install nginx            # 前端静态托管
./deploy/native/tmctl.sh local install     # 装 + 起
./deploy/native/tmctl.sh launchd install   # 再加开机自启 + 崩溃自愈
```

跑起来后: `http://localhost:8081` (端口被占会自动换, 见下)。

### 宿主名 (`host.docker.internal`) —— 后端会自己改写, 不用改 /etc/hosts

Docker 模式里, 后端跑在容器里, 访问宿主用的是 `host.docker.internal` —— 这个名字
在**容器里**指向宿主, 通得很。但 local 模式的进程跑在**宿主上**, 同一个名字在宿主上
解析到的是 Docker 的虚拟网卡 (macOS 上是 `198.18.x.x`), 从宿主侧**连不通**
(TCP 能连上, 但没有服务应答)。

**现在的解法是后端自己改写 (2026-10-27)** —— 按"自己跑在哪"把地址换成能连上的那个:

| 后端在哪 | 填 `127.0.0.1` / `localhost` | 填 `host.docker.internal` |
|---|---|---|
| 容器里 (Docker 模式) | 自动改成 `host.docker.internal` | 原样保留 |
| 宿主上 (裸机 local / systemd) | 原样保留 | 自动改成 `127.0.0.1` |

覆盖两类地址:

- **HTTP** —— 设置页里的代码检视 / RAGFlow 等 (`settings_store.py` 的 `_rewrite_loopback`)
- **git 远端 (SSH)** —— 资产市场的仓库地址 (`git_sync.py` 的 `_rewrite_remote`)

所以**同一个设置值在两种部署模式下都通**: 填 `127.0.0.1` 或填 `host.docker.internal`
都行, 切部署模式不用改设置, 也不用改 `/etc/hosts` (那要 root)。

> ⚠️ 以前这一步必须 `sudo ./deploy/native/tmctl.sh local hosts fix` (往宿主
> `/etc/hosts` 加一行 `127.0.0.1 host.docker.internal`) —— 现在**不再是必需的**。
> 那条命令保留着, 是给"别的工具也要用这个别名"用的 (curl / ssh / 浏览器直接访问):
>
> ```bash
> ./deploy/native/tmctl.sh local hosts check   # 看状态
> sudo ./deploy/native/tmctl.sh local hosts fix # 要修才修 (只改宿主, 容器不受影响)
> ```
>
> 体检里这一项现在只是 **WARN** —— 不修不影响平台功能。

### 设置页里填哪个都行

既然两个方向都自动改写, 设置页里的地址**填 `127.0.0.1` 或 `host.docker.internal`
都能通**。历史数据里两种写法都有, 不用去统一 —— 后端会按当前部署模式处理。

### 数据库和 Redis 都是**本机**的 (不用任何容器)

裸机模式 = 这台机器自己就能跑起来。所以 MySQL 和 Redis 也必须是**本机服务**:

| | macOS (local driver) | Linux (systemd driver) |
|---|---|---|
| MySQL | `brew install mysql` + `brew services start mysql` | `systemctl enable --now mysqld` |
| Redis | `brew install redis` + `brew services start redis` | `systemctl enable --now redis-server` |
| 默认端口 | MySQL `3306` / Redis `6379` | 同左 |
| 自启 | brew services (登录自启) | systemd (开机自启) |

`local install --auto` 会自己装、自己起、自己建库建用户。

> ⚠️ **以前这里是"本机没 MySQL 就复用 Docker 模式那套容器"** —— 现在没有了。
> 容器不是本机服务: Docker Desktop 崩了 / 机器重启 / 有人 `docker compose down`,
> 裸机部署的后端立刻连不上库 —— "非容器部署"名不副实。
> (真踩过: Docker Desktop 重启把 mysql 容器 SIGKILL 掉, 裸机后端直接起不来。)

几个随之而来的变化, 心里有数就行:

- **两种模式的库是各的**。裸机模式有自己的一份 MySQL / Redis, 数据在
  `$(brew --prefix)/var/mysql` (mac) 或系统数据目录 (Linux);
  Docker 模式的数据还在 `deploy/.env` 的 `DATA_ROOT` 卷里。两边互不影响。
- **装的时候会自动把端口调回本机默认端口**。旧配置里可能还指着 Docker 模式
  映射出来的端口 (如 `43060` / `63790`) —— 脚本认得出"监听进程是 docker-proxy
  而不是 mysqld", 会改回 `3306` / `6379` 并写回 `.env`。
- **MySQL 的 root 免密** (brew / socket 认证)。`.env` 里 `MYSQL_ROOT_PASSWORD`
  留空即可 —— 脚本发现 root 其实是免密的, 会把这里清空, 别让配置撒谎。
- **Redis 默认不设口令** (只监听 `127.0.0.1`, 外网够不着)。想让本机 Redis
  真的带口令: 在 Redis 自己的配置里加 `requirepass`, 再把同一个口令填回
  `.env` 的 `REDIS_PASSWORD`。
- **资产市场工作区仍然跟 Docker 模式共用** (`DATA_ROOT/market`) —— 那是 git
  工作区, 共用才能保证两种模式推的是同一个仓库。
  但**两种模式的数据库是分开的**, 所以"已上架的资产"记录各存各的。


### ⚠️ 两个后端不能同时跑

Docker 模式的 backend 和 local 模式的 backend **同时跑**会出事:

> 资产市场的 job 队列是**进程内**的 `asyncio.Queue`, 不跨进程.
> 两个后端各有一份队列, 而且每个进程启动时都 `recover_pending_jobs()`
> → 同一个 job 被两个进程抢 → git `index.lock` 冲突 / 重复推 GitLab.

所以切模式要**二选一**:

```bash
cd deploy && docker compose --env-file .env stop backend frontend   # 停 Docker 的
./deploy/native/tmctl.sh local start                        # 起本地的
# 反过来:
./deploy/native/tmctl.sh local stop
cd deploy && docker compose --env-file .env start backend frontend
```

`local start` 会检查并提醒你 Docker 的 backend 还在跑。

> ⚠️ **Docker 的 frontend 容器也要一起停** —— 只停 backend 的话, 那个端口的
> **页面能打开, 但所有接口都是 502** (nginx 代理不到已经停掉的 backend),
> 看着像"平台坏了", 其实是访问错了端口。
> `tmctl.sh local status` 会主动提醒; Docker 那边 frontend 容器的 healthcheck
> 也已经改成探 `/api/v1/health`, 所以后端一停它就会变成 unhealthy, `docker ps` 里看得见。
>
> 两个模式的端口不同 (Docker 用 `FRONTEND_HOST_PORT`, 本地用 `FRONTEND_PORT`),
> 切换后入口地址会变 —— 以 `tmctl.sh local status` 打印的地址为准。

### 端口冲突自动让路

装的时候如果前端/后端端口被占了(比如 8080 被别的服务绑着), 会**自动往后找一个空闲端口**,
并告诉你改到了哪个。想固定下来就改 `deploy/native/.env` 的 `FRONTEND_PORT` / `BACKEND_PORT`。

> ⚠️ 这里有个坑值得记: 端口"被占"有**两种**情况, 只看"有没有人 listen"是不够的 ——
> 对方绑 `127.0.0.1:8080`、我们绑 `0.0.0.0:8080` 时, nginx 能起来、能通过
> `nginx -t`、端口也"在监听", 但请求**全被对方接走**(更具体的绑定优先).
> 所以健康检查会额外核对响应的 `Server` 头是不是 nginx —— 不是就明确报"被别的服务占着".

---

## 6. 关键设计决定

### 6.1 后端**只能一个 worker**

`BACKEND_WORKERS=1`, 不是保守, 是**必须**:

后端启动时(lifespan 钩子)会拉起三个后台任务 —— 资产市场 job 消费者 / 反向同步 puller / 钉钉重试。
资产 job 走的是**进程内** `asyncio.Queue` + 单消费者队列(设计文档里写得很清楚: git 的 `index.lock` 是仓库级的, 两个 job 并发 commit 必有一个失败), 队列**不跨进程**。

跑多个 worker = 每个进程一份队列, 而且每个进程启动时都 `recover_pending_jobs()` → 同一个 job 被多个进程抢 → `index.lock` 冲突 / 重复推送 GitLab。

要提吞吐请加机器, 不要加 worker。

### 6.2 服务用专用系统用户, 不用 root

**systemd driver**: install 会建 `testmate` 系统用户(nologin, 无 home), 服务以它运行, 运行时目录归它。想换改 `.env` 的 `RUN_USER`。

systemd 单元开了 `NoNewPrivileges` / `ProtectSystem` / `ProtectHome` / `PrivateDevices` 等加固项。

**local driver**(macOS)没有这一层 —— launchd 的用户级 agent 只能以**当前登录用户**身份跑。
这是 launchd 的机制决定的(没有 root 版的用户 agent), 不是没做加固。

### 6.3 口令自动生成, 不让人手抄

install 第一次跑自动生成 `.env`, 并把 `JWT_SECRET` / `MySQL_PASSWORD` / `ADMIN_DEFAULT_PASSWORD` 填成随机值。

强度校验跟 Docker 版**同一口径**: JWT_SECRET ≥ 32 字节且不含 change/placeholder/dev/test 字样; 口令 ≥ 12 字符且不是占位符。

### 6.4 admin 口令走临时文件

`create_admin.py` 用 `--password-file` 传口令, **不进命令行** —— `ps aux` 里别人看不见。

### 6.5 迁移自动跑

后端启动时 `init_db()` 会 `alembic upgrade head`。**只有**「版本表不存在 / 没记录」(老环境用 `create_all` 建的) 才 stamp 兜底 —— 绝不会把版本号盖到 head 把新迁移整段跳过。

### 6.6 资产市场工作区

裸机模式下 `MARKET_DIR` (默认 `runtime/market`) 是**宿主机上的一个目录**, 后端启动时会自己 `git init + remote add + fetch + checkout` 建好仓库 —— 不用脚本预先 clone。

但 SSH 身份必须先备好: install 会把你 `~/.ssh/id_ed25519` 拷进 `runtime/ssh/` (权限 600) 并在 `backend.env` 里配好 `GIT_SSH_COMMAND`。没配 SSH 的话, 仓库能建起来但拉不到远端, 上传推送会失败 —— `tmctl.sh doctor` 能看出来。

mac 上 install 会**优先把 `MARKET_DIR` 对齐到 Docker 模式那份**(同一个 `DATA_ROOT/market`), 这样切模式不用搬数据。

---

## 7. 日常运维

### 升级

```bash
cd /opt/testmate && git pull     # 或者直接:
sudo ./deploy/native/tmctl.sh update
```

`update` = 拉代码 → 重装依赖 → 重建前端 → 重新生成配置 → 重启 → 健康校验。

### 开机自启 (macOS)

```bash
./deploy/native/tmctl.sh launchd install     # 装 launchd (开机自启 + 崩溃自愈)
./deploy/native/tmctl.sh launchd status      # 看状态
./deploy/native/tmctl.sh launchd uninstall   # 卸载 (服务也一并停)
```

> launchd 与 PID 模式是**互斥**的: 装了 launchd 之后, `local stop` 会转成 `launchctl bootout`
> (RunAtLoad+KeepAlive 的服务停不掉只能卸载), `local start` / `restart` 也转去走 launchctl。
> 想回到纯 PID 模式: `launchd uninstall` 再 `local start`。

### 备份

```bash
sudo ./deploy/native/tmctl.sh backup                    # 默认 /var/backups/testmate
sudo ./deploy/native/tmctl.sh backup /data/backups/tm
```

产出 `mysql-<时间>.sql.gz` + `redis-<时间>.rdb` + `env-<时间>.txt`(配置), 保留 14 天。

配 cron:

```bash
echo "0 3 * * * root /opt/testmate/deploy/native/tmctl.sh backup /var/backups/testmate" \
  | sudo tee /etc/cron.d/testmate-backup
```

### 恢复

```bash
sudo ./deploy/native/tmctl.sh restore /var/backups/testmate/2026-07-07-0300
```

会停服务 → 灌 MySQL → 灌 Redis → 起服务 → 健康校验。

### 排障

```bash
./deploy/native/tmctl.sh doctor
```

比 `check` 深: 服务状态 + 最近的 ERROR 日志 + **配置一致性**(`.env` 端口 vs `backend.env` vs `nginx.conf` 三处对不上会直接指出来)+ alembic 迁移版本 + 磁盘/内存/日志占用。

### 改端口

改 `deploy/native/.env` 的 `FRONTEND_PORT`, 然后:

```bash
sudo ./deploy/native/tmctl.sh install    # 重跑一遍 = 重新生成配置 + 重启
```

> 只改 `.env` 不重跑 install 是不生效的 —— 运行时的配置由 `backend.env` / `nginx.conf` 派生。

---

## 8. 几种模式怎么选

| | Docker (`deploy/deploy.sh`) | 裸机 systemd (Linux) | 裸机 local (mac) |
|---|---|---|---|
| 隔离 | 容器级, 不碰宿主 | 进程级, 装在宿主上 | 进程级, 装在宿主上 |
| MySQL / Redis | 容器里跑, 数据在卷 | 本机服务 (脚本装: systemctl) | 本机服务 (脚本装: brew services) |
| 开机自启 | 靠 docker daemon 自启 | `systemctl enable` | `launchd` (RunAtLoad) |
| 崩溃自愈 | docker 的 restart policy | systemd `Restart=always` | launchd `KeepAlive` |
| 资源占用 | 4 个容器 | 2 个进程 + 宿主机 DB | 2 个进程 + 宿主机 DB |
| 升级 | 重建镜像 | `git pull` + 重建 venv/dist | 同左 |
| 适合 | 隔离要求高 / 机器资源足 | 不让装 Docker / 运维只认 systemctl | mac 上的本地部署 |

三套**并存**, 互不干扰:

| 模式 | 配置 | 产物 |
|---|---|---|
| Docker | `deploy/.env` | `deploy/docker-compose.yml` + 数据卷 |
| 裸机 (两种 driver 共用) | `deploy/native/.env` | `deploy/native/runtime/` |

**mac 上的 local 模式跟 Docker 模式各用各的数据库** (见 §5「数据库和 Redis 都是本机的」) ——
裸机模式用本机的 MySQL/Redis, 不碰任何容器; 两者只是**资产市场工作区**共用,
保证两种模式推的是同一个仓库。

---

## 9. 离线安装 (内网无外网)

```bash
# 能上网的机器上准备
pip download -r backend_gateway/requirements.lock -d deploy/native/runtime/wheelhouse
cd frontend_web && npm ci   # 把 node_modules 一起打包带走

# 内网机器上
sudo ./deploy/native/tmctl.sh install --offline
```

`--offline` 时 pip 走 `--no-index --find-links runtime/wheelhouse`, npm 走 `--offline` 缓存。

---

## 10. 已知限制

- **systemd driver 没有在生产环境验证过** —— 这套脚本是照着 Docker 版的行为写的(Docker 版在生产跑着), 但真机首次部署建议先在测试机走一遍 `check` + `install`。
  (mac 上的 local driver **已真机验证过**: 装完能访问 / 启停 / launchd 自启 / 崩溃自愈 / 端口冲突自动让路, 全过。)
- **macOS 上 `check` 报「systemd 不可用」是正常的** —— local driver 不需要 systemd, 体检里那一项会标成「不需要」。
- **macOS: `host.docker.internal` 在宿主上默认是不通的** —— 那是容器里访问宿主用的名字。
  但**不用管它**: 后端会按"自己跑在哪"自动把 `host.docker.internal` ↔ `127.0.0.1`
  双向改写 (HTTP 与 git 远端都算), 所以代码检视、资产市场推送在两种模式下都能用同一个值。
  别的工具 (curl / ssh) 想用这个别名才需要 `sudo ./deploy/native/tmctl.sh local hosts fix`。见 §5。
- **macOS: launchd 的 agent 只能以当前登录用户身份跑** —— 没有 root 版用户 agent, 所以没有 systemd 那层"专用系统用户 + 沙箱加固"。见 §6.2。
- 宿主机自带的 nginx 若也监听 8080, 端口体检会报占用 —— install 会**自动换端口**, 不用手工改。
- `update` 用的是 `git pull --ff-only` —— 生产目录有本地改动时会拒绝, 这是故意的(别让人在生产目录乱改)。
- **源码目录建议放 `/opt/testmate`**。放 `/root` 下的话, 后端单元的 `ProtectHome=read-only` 会挡住运行时目录(`/root` 下) —— 虽然 `ReadWritePaths` 实测能覆盖, 但别赌。
- `admin` / `backup` / `restore` / `logs` 这几个命令的**参数要写在命令后面**(`tmctl.sh admin --username x`), 其余命令的选项前后都行(`tmctl.sh check --auto` 和 `tmctl.sh --auto check` 等价)。
- **两个后端不能同时跑**(Docker 的 + 本地的) —— 见 §5「两个后端不能同时跑」。
- **裸机模式的数据库是本机的, 跟 Docker 模式各存各的** —— 换模式**不会**自动把数据带过去。
  老环境的库要搬过来: `mysqldump` 出来, 再 `./deploy/native/tmctl.sh local db import <dump.sql>`。
  要带就手工 `mysqldump` / `mysql < dump` (或用 `tmctl.sh backup` 出一份)。
  共享的只有**资产市场工作区** (git 仓库), 见 §5。

---

## 11. 自检

部署脚本自己也要能自检 —— 模板写错了、systemd 单元起不来, 都是**上线才发现**的代价。

```bash
# 部署资产自检 (语法 / 模板渲染 / systemd 单元 / nginx 配置 / shellcheck)
./deploy/native/selftest.sh

# systemd 沙箱回归 (要 docker + --privileged)
./deploy/native/sandbox-probe.sh
```

`selftest.sh` 在**纯 Linux 容器**里跑最省事:

```bash
docker run --rm -v "$PWD:/repo" ubuntu:22.04 bash -c \
  'apt-get update -qq && apt-get install -y -qq systemd nginx-light shellcheck && \
   bash /repo/deploy/native/selftest.sh'
```

`sandbox-probe.sh` 验的是**单元在 systemd 沙箱下能不能真的起来**, 以及加固项有没有误伤 —— 最要紧的一条是:

> `ReadWritePaths` 能不能覆盖 `ProtectHome=read-only`?
> 覆盖不了的话, 装在 `/home` 下的部署会**静默地写不了**资产市场的 git 工作区
> (上传 / 推送全挂, 而且报错点离根因很远)。实测 systemd 249 上是**能覆盖**的,
> 但这条每个 systemd 版本行为都可能变, 所以留了回归测试。

---

## 12. 文件清单

```
deploy/native/
├── tmctl.sh                          # 唯一入口 (运维只记这一个)
├── lib.sh                            # 公共函数: 日志/系统探测/版本比较/端口/包管理器
│                                    #   + 本机服务管理 (systemd / brew 双通道)
│                                    #   + local driver 的 PID 进程管理 + launchd 封装
│                                    #   + Docker 宿主名映射 (host.docker.internal)
├── preflight.sh                      # 环境体检 (check 的实现, install 也复用)
├── selftest.sh                       # 部署资产自检 (模板 + systemd + nginx + shellcheck
│                                    #   + .env 解析 + 宿主名映射)
├── sandbox-probe.sh                  # systemd 沙箱回归 (单元真能起来吗)
├── .env.template                     # 部署配置模板
├── units/
│   ├── testmate-backend.service.tpl  # systemd 单元模板 (后端)
│   ├── testmate-frontend.service.tpl # systemd 单元模板 (nginx)
│   ├── nginx.conf.tpl                # nginx 配置模板 (独立实例)
│   └── launchd/
│       ├── com.testmate.backend.plist.tpl   # launchd 单元 (macOS 后端)
│       └── com.testmate.frontend.plist.tpl  # launchd 单元 (macOS nginx)
└── README.md                         # 本文件
```
