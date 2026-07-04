#!/bin/bash
# Mac 本地一键起(开发用,不用 docker)
set -e
cd "$(dirname "$0")/.."

echo "=== 1. 起 MySQL + Redis(用 docker) ==="
docker compose -f deploy/docker-compose.yml up -d mysql redis

echo "=== 2. 装后端依赖 ==="
cd backend_gateway
[ ! -d .venv ] && python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cd ..

echo "=== 3. 装前端依赖 ==="
cd frontend_web
[ ! -d node_modules ] && npm install
cd ..

echo "=== 4. 启后端(后台) ==="
cd backend_gateway
source .venv/bin/activate
nohup uvicorn app.main:app --reload --port 8000 > /tmp/testmate-backend.log 2>&1 &
echo $! > /tmp/testmate-backend.pid
cd ..

echo "=== 5. 启前端(后台) ==="
cd frontend_web
nohup npm run dev > /tmp/testmate-frontend.log 2>&1 &
echo $! > /tmp/testmate-frontend.pid
cd ..

sleep 3
echo
echo "✅ 启动完成"
echo "  前端:http://localhost:5173"
echo "  后端:http://localhost:8000"
echo "  日志:tail -f /tmp/testmate-*.log"
