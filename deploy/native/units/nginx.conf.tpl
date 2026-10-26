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
            proxy_set_header X-Real-IP $remote_addr;
            proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
            proxy_buffering off;
            proxy_read_timeout 600s;
        }
    }
}
