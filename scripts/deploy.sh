#!/bin/bash
# 部署 (docker 模式) —— 改完代码**必须**走这个脚本, 别手动只 copy dist.
#
# ⚠️ 2026-10-25 踩过的坑: 之前用 /tmp 下的简化 Dockerfile ("FROM 旧镜像 + COPY dist")
#    部署前端, 结果改了源码忘了 npm run build → **线上跑的还是旧 bundle** →
#    e2e 三轮全绿, 但测的是旧代码, 一个已修的 bug 其实还在线上.
#    现在统一走 compose 的多阶段构建 (镜像里自己 npm run build), 源头唯一.
#
# 用法:
#   scripts/deploy.sh              # 前后端都部署
#   scripts/deploy.sh frontend     # 只前端
#   scripts/deploy.sh backend      # 只后端
set -e
cd "$(dirname "$0")/.."

WHAT="${1:-all}"
do_frontend=0
do_backend=0
case "$WHAT" in
  frontend) do_frontend=1 ;;
  backend)  do_backend=1 ;;
  all)      do_frontend=1; do_backend=1 ;;
  *) echo "用法: $0 [frontend|backend|all]"; exit 2 ;;
esac

if [ "$do_frontend" -eq 1 ]; then
  echo "=== 前端: 本地 build 一次 (让 dist 与源码一致, 便于本地排查) ==="
  (cd frontend_web && npm run build)
  echo "=== 前端: compose 从源码重建镜像 (镜像内自己 npm run build) ==="
  docker compose -f deploy/docker-compose.yml up -d --build frontend
fi

if [ "$do_backend" -eq 1 ]; then
  echo "=== 后端: 重建镜像 ==="
  (cd backend_gateway && docker build -f Dockerfile -t test-mate-backend:official .)
  docker tag test-mate-backend:official test-mate-backend:latest
  docker compose -f deploy/docker-compose.yml up -d --no-build backend
  echo "=== 后端: 补测试依赖 (镜像里没带 pytest) ==="
  docker exec test-mate-backend-1 pip install -q pytest pytest-asyncio || true
fi

echo
echo "✅ 部署完成"
echo "  前端: http://localhost:8090    后端: http://localhost:18000"
echo "  ⚠️ 改前端后请确认线上 bundle 已更新:"
echo "     docker exec test-mate-frontend-1 ls -lt /usr/share/nginx/html/assets | head -3"
