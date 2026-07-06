# TestMate Linux 一键部署

> 内网 SSD 测试组 AI 工作平台。Vue 3 + FastAPI + Dify + RAGFlow。

## 1. 服务器最低配置

| 角色 | CPU | 内存 | 磁盘 | 备注 |
|---|---|---|---|---|
| P0(仅 TestMate 主栈) | 4 核 | 8 GB | 50 GB | MySQL/Redis 跑本机 |

- OS:Ubuntu 22.04 LTS / Debian 12 / RHEL 9 均可,内核 ≥ 5.4
- Docker ≥ 24.0 + Compose v2
- 端口:8080(前端)/ 18000(后端,默认)/ 43060(MySQL)/ 63790(Redis)
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
$EDITOR deploy/.env          # 改 MYSQL_ROOT_PASSWORD / JWT_SECRET / ADMIN_DEFAULT_PASSWORD

# 3. 一键起
sudo ./deploy/deploy.sh

# 4. 建 admin 账号(host 上跑一次,连 docker 暴露的 33060)
MYSQL_HOST=127.0.0.1 MYSQL_PORT=33060 \
MYSQL_USER=testmate MYSQL_PASSWORD=<同 .env> MYSQL_DATABASE=testmate \
python3 scripts/create_admin.py --username admin --password '<强密码>' --role admin
```

启动后:

- 前端:`http://<服务器IP>:8080`
- 后端 API 文档:`http://<服务器IP>:8080/docs`(Nginx 反代到 backend)
- 日志:`./deploy/deploy.sh --logs`

## 3. 离线一键部署(内网,无外网)

在**能上网的机器**上:

```bash
# 打包镜像(backend/frontend 会本地 build;其它从 docker.io pull 后 save)
cd /opt/testmate
sudo ./deploy/offline-save.sh /tmp/testmate-images
```

把 `/tmp/testmate-images/` 整个目录 scp 到内网服务器(假设放进 `/tmp/testmate-images`),然后:

```bash
cd /opt/testmate
sudo ./deploy/deploy.sh --offline --offline-dir /tmp/testmate-images
```

## 4. 文件清单

## 4. 常用运维

```bash
sudo ./deploy/deploy.sh --status         # 状态
sudo ./deploy/deploy.sh --logs           # 跟踪所有容器日志
sudo ./deploy/deploy.sh --logs backend   # 单容器
sudo ./deploy/deploy.sh --down           # 停整栈(数据卷保留)

# 数据备份(cron:0 3 * * *)
sudo ./deploy/backup.sh /var/backups/testmate

# 进入某容器
docker compose -f deploy/docker-compose.yml exec backend bash

# 升级
cd /opt/testmate && git pull
sudo ./deploy/deploy.sh                  # 会自动 rebuild backend/frontend
```

## 5. 文件清单

```
deploy/
├── .env.template             # 环境模板(cp 出 .env)
├── docker-compose.yml        # 主栈(mysql / redis / backend / frontend)
├── deploy.sh                 # Linux 一键部署脚本(在线/离线)
├── offline-save.sh           # 离线镜像打包
├── offline-images.txt        # 离线镜像清单
├── backup.sh                 # 数据备份
└── README.md                 # 本文件
```

## 6. 排错速查

| 现象 | 排查 |
|---|---|
| 启动 30s backend 不 health | `--logs backend`,看是不是 MySQL 还没 ready(已经用 healthcheck 兜底) |
| 浏览器 502 | nginx 反代到 backend:8000 失败,先 `curl backend:8000/api/v1/health` 在 frontend 容器内 |
| 离线 load 失败 | 检查 `docker info` 是否能登入内网 registry,或 `docker load -i` 看 tar 是否完整 |
| admin 账号建不上 | 确认 `MYSQL_PASSWORD` 跟 `.env` 一致;`mysql -h127.0.0.1 -P33060 -utestmate -p` 先手测 |
| 磁盘满 | `du -sh /opt/testmate/data/*`,优先看 `mysql/` |
