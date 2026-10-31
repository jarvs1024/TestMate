# TestMate 前端 nginx 配置 (裸机模式) —— 由 install 生成, 勿手改
#
# 这是个**独立实例**: nginx -c <本文件> -p <prefix>
# → 跟系统自带的 nginx 共存, 不动 /etc/nginx/ 下任何东西.
#
# 端口: @@FRONTEND_PORT@@ (对外)     后端: @@BACKEND_PORT@@ (只监听 127.0.0.1)

worker_processes auto;
pid @@RUN_DIR@@/nginx.pid;
error_log @@LOG_DIR@@/nginx-error.log warn;

events {
    worker_connections 1024;
}

http {
    # mime.types 由 install 从系统拷贝过来 (或生成最小版) —— SPA 的 ES module
    # 靠正确的 MIME 才肯加载, 少了这行前端会白屏
    include @@NGINX_CONF_DIR@@/mime.types;
    default_type application/octet-stream;

    access_log @@LOG_DIR@@/nginx-access.log;

    # 临时目录全塞进运行时目录 —— 跟系统 nginx 彻底隔离
    client_body_temp_path @@RUN_DIR@@/client_temp;
    proxy_temp_path       @@RUN_DIR@@/proxy_temp;
    fastcgi_temp_path     @@RUN_DIR@@/fastcgi_temp;
    uwsgi_temp_path       @@RUN_DIR@@/uwsgi_temp;
    scgi_temp_path        @@RUN_DIR@@/scgi_temp;

    sendfile on;
    tcp_nopush on;
    keepalive_timeout 65;
    server_tokens off;
    client_max_body_size 200m;   # 上架资产包可能不小

    server {
        listen @@FRONTEND_PORT@@;
        server_name _;

        root @@FRONTEND_DIR@@;
        index index.html;

        # 前端是 SPA + 频繁改版本 —— 一律不缓存, 免得用户拿到旧 bundle
        add_header Cache-Control "no-store, no-cache, must-revalidate" always;
        add_header Pragma "no-cache" always;
        add_header Expires "0" always;

        location / {
            try_files $uri $uri/ /index.html;
        }

        location /api/ {
            proxy_pass http://127.0.0.1:@@BACKEND_PORT@@;
            proxy_http_version 1.1;
            proxy_set_header Host $host;
            # ⚠️ 2026-10-31 (第十三轮): 通知里的链接要**动态**取实际访问地址.
            #    `Host $host` **不含端口** (访问 http://ip:8081 时后端只看到 `ip`),
            #    拼出来的链接会丢掉 :8081 → 点不开.
            #    $http_host 是原始 Host 头, **含端口** —— 补一个专门的头传过去.
            proxy_set_header X-Forwarded-Host $http_host;
            proxy_set_header X-Real-IP $remote_addr;
            proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
            proxy_set_header X-Forwarded-Proto $scheme;
            proxy_read_timeout 300s;
            proxy_send_timeout 300s;
            proxy_buffering off;
        }

        # 资产包的下载走同一个后端 —— 大文件别缓冲
        location ~* ^/api/assets/.+\.(zip|tar\.gz|tgz)$ {
            proxy_pass http://127.0.0.1:@@BACKEND_PORT@@;
            proxy_set_header Host $host;
            # ⚠️ 2026-10-31 (第十三轮): 通知里的链接要**动态**取实际访问地址.
            #    `Host $host` **不含端口** (访问 http://ip:8081 时后端只看到 `ip`),
            #    拼出来的链接会丢掉 :8081 → 点不开.
            #    $http_host 是原始 Host 头, **含端口** —— 补一个专门的头传过去.
            proxy_set_header X-Forwarded-Host $http_host;
            proxy_set_header X-Real-IP $remote_addr;
            proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
            proxy_buffering off;
            proxy_read_timeout 600s;
        }

        # ===== 软件库 (2026-10-27) =====
        # 软件包最大 5G, 跟上面 /api/ 段的 client_max_body_size 200m 不是一回事 ——
        # 这个 location **单独放大** body 上限, 否则 5G 传到 nginx 就被 413 掐掉.
        #
        # ⚠️ proxy_request_buffering off 是**关键**: 默认 nginx 会先把整个 body
        #    收进 client_body_temp_path 再转给后端 —— 5G 会在临时目录**再存一份**,
        #    磁盘翻倍, 而且后端拿到的还是"已缓冲完"的一坨, 流式落盘的意义就没了.
        #
        # ⚠️ 路径必须是 /api/v1/software (带 v1) —— 后端挂的是 /api/v1/software.
        #
        # ⚠️ **结尾不能带斜杠** —— nginx 对 "location /xxx/" 有一条自动行为:
        #    请求 "/xxx" 时它会 **301 补上斜杠** (像访问目录一样).
        #    而 FastAPI 的路由是 "/api/v1/software" (没斜杠) → 又会 307 弹回来.
        #    两边一撞就成了**重定向死循环**, 而且 nginx 改写 Location 时还会把端口吞掉
        #    (127.0.0.1:8081 → localhost:80) → 最后 ERR_CONNECTION_REFUSED.
        #    写成不带斜杠的前缀: /api/v1/software 与 /api/v1/software/xxx 都命中, 且不会触发补斜杠.
        location /api/v1/software {
            proxy_pass http://127.0.0.1:@@BACKEND_PORT@@;
            proxy_http_version 1.1;
            proxy_set_header Host $host;
            # ⚠️ 2026-10-31 (第十三轮): 通知里的链接要**动态**取实际访问地址.
            #    `Host $host` **不含端口** (访问 http://ip:8081 时后端只看到 `ip`),
            #    拼出来的链接会丢掉 :8081 → 点不开.
            #    $http_host 是原始 Host 头, **含端口** —— 补一个专门的头传过去.
            proxy_set_header X-Forwarded-Host $http_host;
            proxy_set_header X-Real-IP $remote_addr;
            proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
            proxy_set_header X-Forwarded-Proto $scheme;
            # 5G 包 + 余量 (超过就 413, 不会白收)
            client_max_body_size 6g;
            proxy_request_buffering off;
            proxy_send_timeout 3600s;
            proxy_read_timeout 3600s;
            # 下载同样不缓冲 —— 边下边写盘
            proxy_buffering off;
        }
    }
}
