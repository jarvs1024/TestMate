# TestMate 裸机部署 (native / systemd)

> 不走 Docker, 直接在 Linux 上跑进程。用 systemd 管生命周期和开机自启。
> 适合: 内网服务器不让装 Docker / 机器资源紧张 / 运维只认 systemctl。

Docker 那套仍然保留 (`deploy/deploy.sh`), 两套并存, 互不影响。见文末「两种模式怎么选」。

---

## 1. 一句话上手

```bash
sudo ./deploy/native/tmctl.sh install --auto
```

完事。`install` 会依次做完:

```
1/9 环境体检      → 缺什么装什么 (--auto)
2/9 生成配置      → JWT_SECRET / MySQL 口令 / admin 口令 随机生成, 不用手抄
3/9 服务用户      → 建专用系统用户 testmate (不用 root 跑服务)
4/9 数据库        → 建 testmate 库 + 用户
5/9 Redis         → 确认在跑
6/9 Python 依赖   → 建 venv, 按 requirements.lock 装
7/9 前端构建      → npm ci + vite build, 产物落到 runtime/frontend
8/9 资产市场 SSH  → 拷私钥进 runtime/ssh
9/9 注册 systemd  → 写 unit + nginx 配置, enable 开机自启, 启动, 健康校验, 建 admin
```

---

## 2. 运维命令速查

**只有这一个入口**: `deploy/native/tmctl.sh`。所有动作都从这儿走。

| 命令 | 干什么 | 要 root 吗 |
|---|---|---|
| `check` | 环境体检 —— 只读, 不改任何东西 | 否 |
| `install` | 一键部署 | 是 |
| `start` / `stop` / `restart` | 启 / 停 / 重启 | 是 |
| `reload` | 只重载 nginx 配置 (后端不动) | 是 |
| `status` | 服务 / 端口 / 健康 / 版本 | 否 |
| `logs [-f]` | 看日志 (journalctl) | 否 |
| `enable` / `disable` | 开机自启 开 / 关 | 是 |
| `update` | 升级: 拉代码 → 重建 → 重启 → 健康校验 | 是 |
| `backup` / `restore` | 数据备份 / 恢复 | restore 要 |
| `doctor` | 深度排障 (比 check 看得深) | 否 |
| `admin` | 建 / 改 admin 账号 | 否 |
| `uninstall` | 卸载 (默认保留数据) | 是 |

选项: `--auto` (自动装依赖) `--offline` (离线装) `--yes` (非交互) `--no-start` (装完不启动) `--from REF` (update 指定 ref) `--target UNIT` (logs 只看某个服务)。

```bash
# 开机自启(默认 install 就开了)
sudo ./deploy/native/tmctl.sh enable
sudo ./deploy/native/tmctl.sh disable      # 取消自启, 但服务还跑着

# 重启 / 停止
sudo ./deploy/native/tmctl.sh restart
sudo ./deploy/native/tmctl.sh stop

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

分八组, 每项都给出「怎么修」:

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

退出码: 有 FAIL 项 → 1, 否则 0。适合挂到巡检脚本里。

---

## 4. 装完长什么样

```
/opt/testmate/                      ← 源码 (git clone 到哪就在哪)
└── deploy/native/
    ├── .env                        ← 部署配置 (含明文口令, 权限 600)
    └── runtime/                    ← 所有运行时产物 (不入 git)
        ├── venv/                   ← Python 虚拟环境
        ├── frontend/               ← 前端构建产物 (nginx 的 root)
        ├── market/                 ← 资产市场 git 工作区
        ├── logs/                   ← nginx 日志
        ├── run/                    ← nginx pid / 临时目录
        ├── config/
        │   ├── backend.env         ← 后端环境变量 (600)
        │   ├── nginx.conf          ← nginx 配置 (独立实例)
        │   └── mime.types
        └── ssh/                    ← 资产市场用的 SSH 私钥 (600)
```

两个 systemd 服务:

| 单元 | 干什么 | 端口 |
|---|---|---|
| `testmate-backend.service` | uvicorn 跑 FastAPI | `127.0.0.1:8000` (只监听本机) |
| `testmate-frontend.service` | nginx 托管前端 + 反代 `/api/` | `0.0.0.0:8080` (对外) |

后端端口**默认只绑 127.0.0.1** —— 外部只能走 nginx, 直连不了后端。要改 `.env` 的 `BIND_ADDR`。

nginx 是**独立实例** (`nginx -c runtime/config/nginx.conf -p runtime/`), 不碰系统自带的 `/etc/nginx/`, 两者可以共存。

---

## 5. 关键设计决定

### 5.1 后端**只能一个 worker**

`BACKEND_WORKERS=1`, 不是保守, 是**必须**:

后端启动时(lifespan 钩子)会拉起三个后台任务 —— 资产市场 job 消费者 / 反向同步 puller / 钉钉重试。
资产 job 走的是**进程内** `asyncio.Queue` + 单消费者队列(设计文档里写得很清楚: git 的 `index.lock` 是仓库级的, 两个 job 并发 commit 必有一个失败), 队列**不跨进程**。

跑多个 worker = 每个进程一份队列, 而且每个进程启动时都 `recover_pending_jobs()` → 同一个 job 被多个进程抢 → `index.lock` 冲突 / 重复推送 GitLab。

要提吞吐请加机器, 不要加 worker。

### 5.2 服务用专用系统用户, 不用 root

install 会建 `testmate` 系统用户(nologin, 无 home), 服务以它运行, 运行时目录归它。想换改 `.env` 的 `RUN_USER`。

systemd 单元开了 `NoNewPrivileges` / `ProtectSystem` / `ProtectHome` / `PrivateDevices` 等加固项。

### 5.3 口令自动生成, 不让人手抄

install 第一次跑自动生成 `.env`, 并把 `JWT_SECRET` / `MySQL_PASSWORD` / `ADMIN_DEFAULT_PASSWORD` 填成随机值。

强度校验跟 Docker 版**同一口径**: JWT_SECRET ≥ 32 字节且不含 change/placeholder/dev/test 字样; 口令 ≥ 12 字符且不是占位符。

### 5.4 admin 口令走临时文件

`create_admin.py` 用 `--password-file` 传口令, **不进命令行** —— `ps aux` 里别人看不见。

### 5.5 迁移自动跑

后端启动时 `init_db()` 会 `alembic upgrade head`。**只有**「版本表不存在 / 没记录」(老环境用 `create_all` 建的) 才 stamp 兜底 —— 绝不会把版本号盖到 head 把新迁移整段跳过。

### 5.6 资产市场工作区

裸机模式下 `MARKET_DIR` (默认 `runtime/market`) 是**宿主机上的一个目录**, 后端启动时会自己 `git init + remote add + fetch + checkout` 建好仓库 —— 不用脚本预先 clone。

但 SSH 身份必须先备好: install 会把你 `~/.ssh/id_ed25519` 拷进 `runtime/ssh/` (权限 600) 并在 `backend.env` 里配好 `GIT_SSH_COMMAND`。没配 SSH 的话, 仓库能建起来但拉不到远端, 上传推送会失败 —— `tmctl.sh doctor` 能看出来。

---

## 6. 日常运维

### 升级

```bash
cd /opt/testmate && git pull     # 或者直接:
sudo ./deploy/native/tmctl.sh update
```

`update` = 拉代码 → 重装依赖 → 重建前端 → 重新生成配置 → 重启 → 健康校验。

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

## 7. 两种模式怎么选

| | Docker (`deploy/deploy.sh`) | 裸机 (`deploy/native/tmctl.sh`) |
|---|---|---|
| 隔离 | 容器级, 不碰宿主 | 进程级, 装在宿主上 |
| MySQL / Redis | 容器里跑, 数据在卷 | 复用宿主机服务 (或脚本装) |
| 开机自启 | 靠 docker daemon 自启 | `systemctl enable`, 独立可控 |
| 资源占用 | 4 个容器 | 2 个进程 + 宿主机 DB |
| 升级 | 重建镜像 | `git pull` + 重建 venv/dist |
| 适合 | 隔离要求高 / 机器资源足 | 不让装 Docker / 资源紧张 / 运维只认 systemctl |

两套**并存**, 互不干扰: Docker 模式用 `deploy/.env` + `deploy/docker-compose.yml`, 裸机模式用 `deploy/native/.env` + `deploy/native/runtime/`。

---

## 8. 离线安装 (内网无外网)

```bash
# 能上网的机器上准备
pip download -r backend_gateway/requirements.lock -d deploy/native/runtime/wheelhouse
cd frontend_web && npm ci   # 把 node_modules 一起打包带走

# 内网机器上
sudo ./deploy/native/tmctl.sh install --offline
```

`--offline` 时 pip 走 `--no-index --find-links runtime/wheelhouse`, npm 走 `--offline` 缓存。

---

## 9. 已知限制

- **裸机模式没有在生产环境验证过** —— 这套脚本是照着 Docker 版的行为写的(Docker 版在生产跑着), 但真机首次部署建议先在测试机走一遍 `check` + `install`。
- `check` 在 **macOS 上必然报 systemd 不可用** —— macOS 不是部署目标, 只用来本地看脚本跑不跑得通。
- 宿主机自带的 nginx 若也监听 8080, 端口体检会报占用, 改 `.env` 的 `FRONTEND_PORT`。
- `update` 用的是 `git pull --ff-only` —— 生产目录有本地改动时会拒绝, 这是故意的(别让人在生产目录乱改)。
- **源码目录建议放 `/opt/testmate`**。放 `/root` 下的话, 后端单元的 `ProtectHome=read-only` 会挡住运行时目录(`/root` 下) —— 虽然 `ReadWritePaths` 实测能覆盖, 但别赌。
- `admin` / `backup` / `restore` / `logs` 这几个命令的**参数要写在命令后面**(`tmctl.sh admin --username x`), 其余命令的选项前后都行(`tmctl.sh check --auto` 和 `tmctl.sh --auto check` 等价)。

---

## 10. 自检

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

## 11. 文件清单

```
deploy/native/
├── tmctl.sh                          # 唯一入口 (运维只记这一个)
├── lib.sh                            # 公共函数: 日志/系统探测/版本比较/端口/包管理器
├── preflight.sh                      # 环境体检 (check 的实现, install 也复用)
├── selftest.sh                       # 部署资产自检 (模板 + systemd + nginx + shellcheck)
├── sandbox-probe.sh                  # systemd 沙箱回归 (单元真能起来吗)
├── .env.template                     # 部署配置模板
├── units/
│   ├── testmate-backend.service.tpl  # systemd 单元模板 (后端)
│   ├── testmate-frontend.service.tpl # systemd 单元模板 (nginx)
│   └── nginx.conf.tpl                # nginx 配置模板 (独立实例)
└── README.md                         # 本文件
```
