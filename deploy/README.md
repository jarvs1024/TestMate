# TestMate Linux 一键部署

> 内网 SSD 测试组 AI 工作平台。Vue 3 + FastAPI + Dify + RAGFlow。

## 1. 服务器最低配置

| 角色 | CPU | 内存 | 磁盘 | 备注 |
|---|---|---|---|---|
| P0(仅 TestMate 主栈) | 4 核 | 8 GB | 50 GB | MySQL/Redis 跑本机 |

- OS:Ubuntu 22.04 LTS / Debian 12 / RHEL 9 / Anolis 23 均可,内核 ≥ 5.4
- Docker ≥ 24.0,**Compose v2 优先**(脚本同时兼容 v1)
- 默认端口:8080(前端)/ 18000(后端)/ 43060(MySQL)/ 63790(Redis)
- 时区建议 `Asia/Shanghai`

## 2. 在线一键部署(能上网)

```bash
# 1. 装 docker
curl -fsSL https://get.docker.com | sh
systemctl enable --now docker

# 2. 拉代码 + 改配置
git clone <repo-url> /opt/testmate
cd /opt/testmate
cp deploy/.env.template deploy/.env
$EDITOR deploy/.env   # 必改:MYSQL_ROOT_PASSWORD / JWT_SECRET / ADMIN_DEFAULT_PASSWORD

# 3. 一键起(deploy.sh 强制要求:JWT_SECRET ≥ 32 字节,密码 ≥ 12 字符,不能含占位符)
sudo ./deploy/deploy.sh

# 4. 建 admin 账号(deploy.sh 会自动建,失败再手动)
python3 scripts/create_admin.py --username admin --password '<强密码>' --role admin
```

启动后:

- 前端:`http://<服务器IP>:8080`
- 后端 API 文档:`http://<服务器IP>:8080/docs`(Nginx 反代)
- 健康检查:
  - `GET /api/v1/health` — liveness, 进程活着
  - `GET /api/v1/health/ready` — readiness, MySQL + Redis 全通才 200
  - `GET /api/v1/health/services` — 外部服务(RAGFlow / Dify)状态, 30s 缓存

## 3. 离线一键部署(内网,无外网)

在**能上网的机器**上:

```bash
# 1. 装 docker + clone
git clone <repo-url> /opt/testmate
cd /opt/testmate

# 2. 打包镜像 — backend/frontend 本地 build,其它从 docker.io pull 后 save
#    offline-images.txt 里已经列好 mysql/redis/python3.11/node20/nginx1.27
sudo ./deploy/offline-save.sh /tmp/testmate-images
```

把 `/tmp/testmate-images/` 整个目录 scp 到内网服务器(假设放进 `/tmp/testmate-images`),然后:

```bash
cd /opt/testmate
cp deploy/.env.template deploy/.env && $EDITOR deploy/.env
sudo ./deploy/deploy.sh --offline --offline-dir /tmp/testmate-images
```

## 4. 备份与恢复

### 4.1 备份

```bash
# 默认备份到 /var/backups/testmate/,文件名带时间戳
sudo ./deploy/backup.sh

# 自定义路径
sudo ./deploy/backup.sh /data/backups/testmate

# 配 cron 每天凌晨 3 点
echo "0 3 * * * root /opt/testmate/deploy/backup.sh /var/backups/testmate" | sudo tee /etc/cron.d/testmate-backup
```

产出:
- `mysql-YYYY-MM-DD-HHMM.sql.gz` — mysqldump
- `redis-YYYY-MM-DD-HHMM.rdb` — redis RDB 快照

### 4.2 恢复

```bash
# 1. 先演练(不真改数据)
sudo ./deploy/restore.sh /var/backups/testmate/2026-07-07-0300 --dry-run

# 2. 真恢复 — 会 FLUSHALL redis, 然后把 mysql dump 灌回去
sudo ./deploy/restore.sh /var/backups/testmate/2026-07-07-0300

# 3. 重新拉起应用栈(后端 alembic upgrade head 是幂等的)
sudo ./deploy/deploy.sh
```

恢复脚本会自动验证:
- MySQL 4 张核心表(users/agents/machines/system_settings)的 row count
- Redis PING 返 PONG

## 5. 日常运维

```bash
sudo ./deploy/deploy.sh --status         # 状态
sudo ./deploy/deploy.sh --logs           # 跟踪所有容器日志
sudo ./deploy/deploy.sh --logs backend   # 单容器
sudo ./deploy/deploy.sh --down           # 停整栈(数据卷保留)

# 进入某容器
docker compose -f deploy/docker-compose.yml exec backend bash

# 看 readiness
curl -s http://127.0.0.1:18000/api/v1/health/ready | jq

# 升级
cd /opt/testmate && git pull
sudo ./deploy/deploy.sh                  # 会自动 rebuild backend/frontend(检测源码 mtime)
```

## 6. 数据库迁移(alembic)

```bash
# 自动迁移:deploy.sh 拉起 backend 容器时,lifespan 钩子会跑 alembic upgrade head
# 手动迁移(改 schema 后):
docker compose -f deploy/docker-compose.yml exec backend alembic upgrade head

# 改完 models 后生成新迁移:
docker compose -f deploy/docker-compose.yml exec backend alembic revision --autogenerate -m "add xxx"
```

迁移脚本在 `backend_gateway/alembic/versions/`,**进 git 仓库**。

## 7. 排错速查

| 现象 | 排查 |
|---|---|
| 启动 30s backend 不 health | `--logs backend`,看是不是 MySQL 还没 ready |
| `curl /api/v1/health/ready` 返 503 | 响应里 `checks.mysql.ok=false`,看 err 字段; MySQL 容器是不是 ib_redo 损坏要重建 |
| 浏览器 502 | nginx 反代到 backend:8000 失败,在 frontend 容器内 `curl backend:8000/api/v1/health` |
| 离线 load 失败 | 检查 `docker info` 是否能登入内网 registry;`offline-images.txt` 里 5 个 base 镜像必须都在 |
| admin 账号建不上 | deploy.sh 会自动建;失败时手动 `create_admin.py --password-file /path/to/secret` |
| 容器 ib_redo 损坏 | `docker logs testmate-mysql 2>&1 \| grep ib_redo`;只能 `docker restart testmate-mysql`,**会触发数据库初始化,数据丢** |
| deploy.sh 报 `JWT_SECRET 太短` | `openssl rand -base64 32` 生成一个填到 .env |
| 端口被占 | `ss -tlnp \| grep <port>` 找占用进程,或者改 .env 里的 `*_HOST_PORT` |
| 日志爆炸撑爆磁盘 | docker compose 默认每个容器 max 3x10MB,看 `docker inspect --format='{{.LogPath}}' <container>` |
| 离线缺 base 镜像 | `offline-images.txt` 必须包含:`mysql:8.0` / `redis:7-alpine` / `python:3.11-slim` / `node:20-alpine` / `nginx:1.27-alpine` |

## 8. 文件清单

```
deploy/
├── .env.template             # 环境模板(cp 出 .env)
├── docker-compose.yml        # 主栈(mysql / redis / backend / frontend)
├── deploy.sh                 # Linux 一键部署脚本(在线/离线, 含 JWT/密码强度校验)
├── offline-save.sh           # 离线镜像打包
├── offline-images.txt        # 离线镜像清单(5 个 base + 2 个业务)
├── backup.sh                 # 数据备份(mysqldump + redis rdb)
├── restore.sh                # 数据恢复(配 backup.sh,含 dry-run 模式)
└── README.md                 # 本文件
```

## 9. 安全检查清单(部署完跑一遍)

- [ ] `JWT_SECRET` 至少 32 字节,不是 `change-me` / `dev-secret`
- [ ] `MYSQL_ROOT_PASSWORD` / `ADMIN_DEFAULT_PASSWORD` 至少 12 字符
- [ ] `docker-compose.yml` 里 backend 的 `extra_hosts` 段是注释掉的(只开发场景启用)
- [ ] MySQL 容器的 3306 端口**没暴露到 0.0.0.0**(默认 `MYSQL_HOST_PORT=43060`,改 127.0.0.1 限定)
- [ ] `.env` 不在 git 仓库里(`.gitignore` 已默认忽略,但 double-check)
- [ ] 备份 cron 已配 + 试跑一次 `restore.sh --dry-run` 验证备份能用
- [ ] 日志目录磁盘监控(默认每容器 30MB,长跑需要 logrotate / ELK)
