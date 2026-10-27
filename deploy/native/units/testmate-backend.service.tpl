[Unit]
Description=TestMate Backend (FastAPI + uvicorn)
Documentation=file://@@REPO_ROOT@@/deploy/native/README.md
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
User=@@RUN_USER@@
Group=@@RUN_GROUP@@
WorkingDirectory=@@BACKEND_DIR@@

# 所有配置走这一个文件 (install 生成, 权限 600)
EnvironmentFile=@@BACKEND_ENV@@

Environment=PYTHONUNBUFFERED=1
Environment=PYTHONDONTWRITEBYTECODE=1
Environment=TZ=@@TIMEZONE@@

# ⚠️ **只能一个 worker** ——
#    后端的 lifespan 钩子会拉起三个后台任务: 资产市场 job 消费者 / 反向同步 puller /
#    钉钉重试. 资产 job 走的是**进程内** asyncio.Queue + 单消费者 (git 的 index.lock 是
#    仓库级的, 两个 job 并发 commit 必有一个失败), 队列不跨进程.
#    跑多 worker = 每个进程一份队列 + 每个进程都 recover_pending_jobs()
#    → 同一个 job 被多个进程抢 → index.lock 冲突 / 重复推送 GitLab.
#    要提吞吐请加机器, 不要加 worker.
ExecStart=@@VENV_BIN@@/uvicorn app.main:app --host @@BIND_ADDR@@ --port @@BACKEND_PORT@@ --workers @@WORKERS@@ --proxy-headers --forwarded-allow-ips=@@FORWARDED_ALLOW@@

Restart=always
RestartSec=5
# 给 alembic upgrade + seed 留时间 (首次启动要建表)
TimeoutStartSec=180
TimeoutStopSec=30
KillSignal=SIGTERM

# 日志进 journald: journalctl -u testmate-backend -f
StandardOutput=journal
StandardError=journal
SyslogIdentifier=testmate-backend

# 资源上限 (安装时按机器填)
MemoryMax=@@MEM_LIMIT@@
CPUQuota=@@CPU_QUOTA@@

# ===== 安全加固 =====
NoNewPrivileges=true
PrivateTmp=true
PrivateDevices=true
ProtectSystem=full
ProtectHome=read-only
ProtectKernelTunables=true
ProtectKernelModules=true
ProtectControlGroups=true
RestrictSUIDSGID=true
RestrictNamespaces=true
LockPersonality=true
# 这些目录要可写: 运行时目录(日志/market 工作区/临时文件/软件库存放目录)
# ⚠️ SOFTWARE_DIR 是软件包的落盘目录 (最多 5G/个) —— 必须可写,
#    否则后端一传文件就报 "存储目录不可写".
ReadWritePaths=@@RUNTIME_DIR@@ @@DATA_DIR@@ @@LOG_DIR@@ @@MARKET_DIR@@ @@SOFTWARE_DIR@@ @@RUN_DIR@@

[Install]
WantedBy=multi-user.target
