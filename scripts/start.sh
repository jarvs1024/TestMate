#!/bin/bash
# TestMate 一键启动
# 用法:
#   ./scripts/start.sh                  # 默认 docker 模式(整栈起)
#   ./scripts/start.sh --local          # 本地直跑(只起 MySQL/Redis 在 docker,后端前端在 host)
#   ./scripts/start.sh --docker         # 显式 docker 模式
#   ./scripts/start.sh --down           # docker 模式停止
#   ./scripts/start.sh --logs           # 跟踪 docker 模式日志
#   ./scripts/start.sh --rebuild        # docker 模式强制重建镜像
#   ./scripts/start.sh --admin          # 创建 admin 账号(交互式,问账号密码)
#   ./scripts/start.sh --admin --username admin --password xxx  # 一次给齐
set -e
cd "$(dirname "$0")/.."

MODE="docker"           # docker | local
ACTION="up"             # up | down | logs | admin
REBUILD=0
ADMIN_USER=""
ADMIN_PASS=""

while [[ $# -gt 0 ]]; do
  case "$1" in
    --local) MODE="local"; shift ;;
    --docker) MODE="docker"; shift ;;
    --down) ACTION="down"; shift ;;
    --logs) ACTION="logs"; shift ;;
    --rebuild) REBUILD=1; shift ;;
    --admin) ACTION="admin"; shift ;;
    --username) ADMIN_USER="$2"; shift 2 ;;
    --password) ADMIN_PASS="$2"; shift 2 ;;
    -h|--help)
      sed -n '2,12p' "$0"; exit 0 ;;
    *) echo "未知参数: $1"; exit 1 ;;
  esac
done

# ---------------- admin 动作 ----------------
if [[ "$ACTION" == "admin" ]]; then
  echo "=== 创建 admin 账号 ==="
  cd "$(dirname "$0")/.."
  ARGS=()
  [[ -n "$ADMIN_USER" ]] && ARGS+=(--username "$ADMIN_USER")
  [[ -n "$ADMIN_PASS" ]] && ARGS+=(--password "$ADMIN_PASS")
  # docker 模式:django 容器还没起,直接跑本地脚本
  # 优先用 .env.local(本地直跑)
  if [[ -f .env.local ]]; then
    echo "  使用 .env.local 配置"
    ARGS+=(--env-file .env.local)
  fi
  python3 scripts/create_admin.py "${ARGS[@]}"
  exit $?
fi

# ---------------- docker 模式 ----------------
if [[ "$MODE" == "docker" ]]; then
  COMPOSE="docker compose -f deploy/docker-compose.yml"
  case "$ACTION" in
    down)
      echo "=== 停止 TestMate 整栈 ==="
      $COMPOSE down
      echo "✅ 已停止(数据卷保留:deploy/.env 里的 volumes)"
      exit 0
      ;;
    logs)
      $COMPOSE logs -f
      exit 0
      ;;
    up)
      # 自动选 env 文件:根 .env.docker 优先,没有就用 .env.example 复制出来的临时文件
      if [[ -f .env.docker ]]; then
        echo "  使用 .env.docker 配置"
        $COMPOSE --env-file .env.docker up -d $EXTRA
      else
        echo "  ⚠️  未找到 .env.docker,使用 compose 默认值"
        $COMPOSE up -d
      fi
      if [[ $REBUILD -eq 1 ]]; then
        echo "  强制重建镜像..."
        $COMPOSE build --no-cache
        $COMPOSE up -d
      fi
      echo
      echo "✅ 启动完成(docker 模式)"
      echo "  前端:http://localhost:8080"
      echo "  后端:http://localhost:8000  (API 文档 /docs)"
      echo "  日志:./scripts/start.sh --logs"
      exit 0
      ;;
  esac
fi

# ---------------- local 模式 ----------------
echo "=== 1. 起 MySQL + Redis(用 docker) ==="
docker compose -f deploy/docker-compose.yml up -d mysql redis

echo "=== 2. 准备本地 .env.local(本地直跑,host=localhost) ==="
if [[ ! -f .env.local ]]; then
  if [[ -f .env.example.local ]]; then
    cp .env.example.local .env.local
    echo "  已从 .env.example.local 复制"
  else
    echo "  ⚠️  未找到 .env.example.local,跳过(后端将用 docker 默认 host)"
  fi
fi

echo "=== 3. 装后端依赖 ==="
cd backend_gateway
[ ! -d .venv ] && python3 -m venv .venv
source .venv/bin/activate
pip install -q -r requirements.txt
cd ..

echo "=== 4. 装前端依赖 ==="
cd frontend_web
[ ! -d node_modules ] && npm install --silent
cd ..

echo "=== 5. 启后端(后台) ==="
cd backend_gateway
source .venv/bin/activate
# 用 .env.local 覆盖默认值
if [[ -f ../.env.local ]]; then
  set -a; source ../.env.local; set +a
fi
nohup uvicorn app.main:app --reload --port 8000 > /tmp/testmate-backend.log 2>&1 &
echo $! > /tmp/testmate-backend.pid
cd ..

echo "=== 6. 启前端(后台) ==="
cd frontend_web
nohup npm run dev > /tmp/testmate-frontend.log 2>&1 &
echo $! > /tmp/testmate-frontend.pid
cd ..

sleep 3
echo
echo "✅ 启动完成(local 模式)"
echo "  前端:http://localhost:5173"
echo "  后端:http://localhost:8000  (API 文档 /docs)"
echo "  日志:tail -f /tmp/testmate-*.log"
echo "  停止:./scripts/stop.sh"
