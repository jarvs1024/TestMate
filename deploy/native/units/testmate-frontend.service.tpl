[Unit]
Description=TestMate Frontend (nginx — 静态资源 + 反代 /api/)
Documentation=file://@@REPO_ROOT@@/deploy/native/README.md
After=network-online.target testmate-backend.service
Wants=network-online.target

[Service]
# nginx 自己会 fork worker, 所以 Type=forking + PIDFile
Type=forking
PIDFile=@@RUN_DIR@@/nginx.pid

# 独立实例: -c 指定自己的配置文件, -p 指定自己的前缀目录
# → 跟系统自带的 nginx 共存, 互不干扰 (端口不同即可)
ExecStartPre=@@NGINX_BIN@@ -t -c @@NGINX_CONF@@ -p @@NGINX_PREFIX@@
ExecStart=@@NGINX_BIN@@ -c @@NGINX_CONF@@ -p @@NGINX_PREFIX@@
ExecReload=@@NGINX_BIN@@ -s reload -c @@NGINX_CONF@@ -p @@NGINX_PREFIX@@
ExecStop=@@NGINX_BIN@@ -s quit -c @@NGINX_CONF@@ -p @@NGINX_PREFIX@@
Restart=on-failure
RestartSec=5

# 不需要 root —— 前端端口默认 8080 (>1024), 用普通用户跑更安全
User=@@RUN_USER@@
Group=@@RUN_GROUP@@

# nginx 会写临时目录/日志, 这些要在 RUNTIME_DIR 里
ReadWritePaths=@@RUNTIME_DIR@@ @@LOG_DIR@@ @@RUN_DIR@@
NoNewPrivileges=true
PrivateTmp=false

[Install]
WantedBy=multi-user.target
