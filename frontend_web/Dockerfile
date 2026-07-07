# TestMate Frontend Dockerfile
# 多阶段 build: 阶段1 用 node 编译 Vue dist, 阶段2 用 nginx 静态服务
# node / nginx 都 pin 具体 patch 版本,保证 reproducible build

# ===== Stage 1: builder =====
FROM node:20.18.1-alpine AS builder

WORKDIR /app

# 先 COPY package.json + lockfile 利用 npm ci 层缓存
COPY package.json package-lock.json ./

# npm ci 比 npm install 更严格,完全按 lockfile 装,适合 CI / 生产
RUN npm ci --no-audit --no-fund

# 复制源码
COPY . .

# build: vue-tsc 类型检查 + vite build
RUN npm run build

# ===== Stage 2: runtime (nginx 静态服务) =====
FROM nginx:1.27.4-alpine

# 复制构建产物
COPY --from=builder /app/dist /usr/share/nginx/html

# 覆盖 nginx 配置: SPA 路由 + /api/ 反代到 backend:8000
COPY nginx.conf /etc/nginx/conf.d/default.conf

EXPOSE 80

CMD ["nginx", "-g", "daemon off;"]
