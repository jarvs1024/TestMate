#!/usr/bin/env bash
# TestMate Linux 服务器一键部署
#
# 用法:
#   sudo ./deploy/deploy.sh                        # 在线模式(从 docker.io / ghcr 拉镜像)
#   sudo ./deploy/deploy.sh --offline              # 离线模式(从本地镜像包 load)
#   sudo ./deploy/deploy.sh --offline-dir /tmp/imgs # 离线镜像包目录
#   sudo ./deploy/deploy.sh --down                 # 停止整栈
#   sudo ./deploy/deploy.sh --status               # 查看状态
#   sudo ./deploy/deploy.sh --logs [service]       # 跟踪日志
#
# 前置:已在 deploy/.env 填好真实配置

set -euo pipefail

# ---------- 参数 ----------
MODE="online"
OFFLINE_DIR=""
ACTION="up"

while [[ $# -gt 0 ]]; do
  case "$1" in
    --offline)        MODE="offline"; shift ;;
    --offline-dir)    OFFLINE_DIR="$2"; shift 2 ;;
    --down)           ACTION="down"; shift ;;
    --status)         ACTION="status"; shift ;;
    --logs)           ACTION="logs"; shift; LOG_TARGET="${1:-}"; [[ -n "${LOG_TARGET:-}" ]] && shift ;;
    -h|--help)
      sed -n '2,16p' "$0"; exit 0 ;;
    *) echo "未知参数: $1"; exit 1 ;;
  esac
done

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
cd "$SCRIPT_DIR"

# ---------- 颜色 ----------
if [[ -t 1 ]]; then
  C_RED=$'\033[31m'; C_GREEN=$'\033[32m'; C_YELLOW=$'\033[33m'; C_BLUE=$'\033[34m'; C_OFF=$'\033[0m'
else
  C_RED=""; C_GREEN=""; C_YELLOW=""; C_BLUE=""; C_OFF=""
fi
log()   { echo "${C_BLUE}[deploy]${C_OFF} $*"; }
ok()    { echo "${C_GREEN}  ✓${C_OFF} $*"; }
warn()  { echo "${C_YELLOW}  !${C_OFF} $*"; }
die()   { echo "${C_RED}  ✗${C_OFF} $*" >&2; exit 1; }

# ---------- 前置检查 ----------
require_root() {
  # Linux 服务器要 root(mac Docker Desktop 不需要,Docker Desktop 用当前用户跑 daemon)
  [[ "${SKIP_ROOT:-0}" == "1" ]] && return 0
  [[ "$(uname -s)" == "Darwin" ]] && return 0
  [[ $EUID -eq 0 ]] || die "请用 root 跑: sudo $0 $*  (mac 上 Docker Desktop 可直接跑,或 SKIP_ROOT=1)"
}

require_docker() {
  command -v docker >/dev/null 2>&1 || die "未安装 docker,先跑: curl -fsSL https://get.docker.com | sh"
  # 兼容 docker compose v2 (内置子命令) 和 v1 (docker-compose 独立命令)
  if docker compose version >/dev/null 2>&1; then
    COMPOSE_BIN="docker compose"
  elif command -v docker-compose >/dev/null 2>&1; then
    COMPOSE_BIN="docker-compose"
  else
    die "缺 docker compose,装 v2 插件或 v1 (apt install docker-compose)"
  fi
  docker info >/dev/null 2>&1 || die "docker daemon 没起来,先: systemctl start docker"
}

ensure_env() {
  [[ -f .env ]] || die "缺少 deploy/.env,先: cp deploy/.env.template deploy/.env && $EDITOR deploy/.env"

  # 占位符检测 — change-me / please-generate / ChangeMe@ 等
  if grep -q "change-me\|please-generate\|please-change-me-32\|ChangeMe@" .env; then
    warn ".env 里还有占位符(change-me / please-generate / ChangeMe@)"
    warn "生产环境必须先改 JWT_SECRET、MYSQL_ROOT_PASSWORD、ADMIN_DEFAULT_PASSWORD"
    if [[ "${SKIP_PLACEHOLDER_CHECK:-0}" != "1" ]]; then
      read -rp "  继续部署? [y/N] " ans
      [[ "$ans" =~ ^[Yy]$ ]] || die "已中止"
    fi
  fi

  # JWT_SECRET 强度校验 — 至少 32 字节 + 不能含 change/placeholder/dev/test 子串
  JWT_VAL="$(grep '^JWT_SECRET=' .env | cut -d= -f2- | tr -d '\"'\'\'' )"
  if [[ -z "$JWT_VAL" ]]; then
    die "JWT_SECRET 未设置"
  fi
  if [[ ${#JWT_VAL} -lt 32 ]]; then
    die "JWT_SECRET 太短 (${#JWT_VAL} 字节),至少 32 字节,推荐: openssl rand -base64 32"
  fi
  if echo "$JWT_VAL" | grep -qiE 'change|placeholder|please|dev-secret|test-secret|example'; then
    die "JWT_SECRET 含占位符字面量 (change/placeholder/please/dev/test/example),生产前必须改"
  fi

  # MYSQL_ROOT_PASSWORD / ADMIN_DEFAULT_PASSWORD 长度校验(弱密码不可接受)
  for key in MYSQL_ROOT_PASSWORD ADMIN_DEFAULT_PASSWORD; do
    val="$(grep "^${key}=" .env | cut -d= -f2- | tr -d '\"'\'\'' )"
    if [[ -z "$val" ]]; then
      die "${key} 未设置"
    fi
    if [[ ${#val} -lt 12 ]]; then
      die "${key} 太短 (${#val} 字符),至少 12 字符"
    fi
  done
}

# 走 .env 调用 compose(v1/v2 都吃 --env-file)
compose_cmd() {
  $COMPOSE_BIN --env-file .env "$@"
}

# ---------- 主流程 ----------
do_up() {
  log "1/5 检查环境..."
  require_docker
  ensure_env

  log "2/5 创建数据目录..."
  DATA_ROOT_VAL="$(grep '^DATA_ROOT=' .env | cut -d= -f2-)"
  DATA_ROOT_VAL="${DATA_ROOT_VAL:-/opt/testmate/data}"
  mkdir -p "$DATA_ROOT_VAL"/{mysql,redis,logs}
  ok "数据目录: $DATA_ROOT_VAL"

  if [[ "$MODE" == "offline" ]]; then
    log "3/5 离线模式 — 从镜像包加载..."
    load_offline_images
  else
    log "3/5 在线模式 — 拉取/构建镜像..."
    compose_cmd pull mysql redis || true
    # build backend/frontend:有 SKIP_BUILD=1 或镜像已存在且 Dockerfile 未变 -> 跳过
    if [[ "${SKIP_BUILD:-0}" == "1" ]]; then
      log "  SKIP_BUILD=1,跳过 build"
    else
      NEED_BUILD=0
      for img in test-mate-backend:latest test-mate-frontend:latest; do
        if ! docker image inspect "$img" >/dev/null 2>&1; then
          log "  $img 不存在,需要 build"
          NEED_BUILD=1
          continue
        fi
        # 源码比镜像新 -> 源码改了,自动 rebuild(set -e 下要小心空输出,跨 mac/linux)
        # 用 python 处理 ISO 时间 -> epoch,避免 mac BSD date 不支持 -d
        img_created="$(docker inspect -f '{{.Created}}' "$img" 2>/dev/null | cut -d. -f1)"
        img_ts="$(python3 -c "from datetime import datetime; print(int(datetime.fromisoformat('$img_created').timestamp()))" 2>/dev/null || echo 0)"
        src_mtime="$(find ../backend_gateway ../frontend_web -type f \( -name '*.py' -o -name '*.vue' -o -name '*.ts' -o -name '*.json' -o -name 'Dockerfile' \) -newer "$SCRIPT_DIR/docker-compose.yml" -printf '%T@\n' 2>/dev/null | sort -nr | head -1 | cut -d. -f1 || true)"
        src_mtime="${src_mtime:-0}"
        if [[ "$src_mtime" != "0" && "$img_ts" != "0" && "$src_mtime" -gt "$img_ts" ]]; then
          log "  $img 源码比镜像新,自动 rebuild"
          NEED_BUILD=1
        fi
      done
      if [[ $NEED_BUILD -eq 1 ]]; then
        compose_cmd build backend frontend
      else
        log "  backend/frontend 镜像已存在且源码未变,跳过 build(强制重建: $0 --rebuild 或删镜像)"
      fi
    fi
  fi

  log "4/5 启动整栈..."
  log "5/5 等待 backend 健康..."
  BE_PORT="$(grep '^BACKEND_HOST_PORT=' .env | cut -d= -f2-)"
  BE_PORT="${BE_PORT:-18000}"
  for i in $(seq 1 30); do
    if curl -fsS "http://127.0.0.1:${BE_PORT}/api/v1/health" >/dev/null 2>&1; then
      ok "backend healthy (耗时 ${i}s)"
      break
    fi
    sleep 2
    if [[ $i -eq 30 ]]; then
      warn "backend 30s 还没 health,看一眼日志: $0 --logs backend"
    fi
  done

  log "6/5 创建 admin 账号..."
  # admin 创建失败不影响主流程(用户可手动建)
  set +e
  ADMIN_USER="$(grep '^ADMIN_DEFAULT_USER=' .env 2>/dev/null | cut -d= -f2- || true)"
  ADMIN_USER="${ADMIN_USER:-admin}"
  ADMIN_PASS="$(grep '^ADMIN_DEFAULT_PASSWORD=' .env | cut -d= -f2-)"
  ADMIN_PASS="${ADMIN_PASS:-ChangeMe@2026}"

  # 通过 docker exec 在 backend 容器内跑(里面有 sqlalchemy / app 模型)
  # 凭证通过环境变量传(避免 heredoc 变量展开的转义问题)
  if compose_cmd exec -T -e ADMIN_USER="$ADMIN_USER" -e ADMIN_PASS="$ADMIN_PASS"       backend python - >/dev/null 2>&1 <<'PYEOF'
import asyncio, os
from sqlalchemy import select
from app.core.security import hash_password
from app.db.session import AsyncSessionLocal, init_db
from app.models.user import User, UserRole

ADMIN_USER = os.environ["ADMIN_USER"]
ADMIN_PASS = os.environ["ADMIN_PASS"]

async def main():
    await init_db()
    async with AsyncSessionLocal() as s:
        r = await s.execute(select(User).where(User.username == ADMIN_USER))
        u = r.scalar_one_or_none()
        if u:
            u.password_hash = hash_password(ADMIN_PASS)
            u.role = UserRole.admin
            await s.commit()
            print("updated")
        else:
            u = User(
                username=ADMIN_USER,
                password_hash=hash_password(ADMIN_PASS),
                role=UserRole.admin,
            )
            s.add(u); await s.commit()
            print("created")
asyncio.run(main())
PYEOF
  then
    ok "admin 账号就绪(用户: $ADMIN_USER,密码见 .env 的 ADMIN_DEFAULT_PASSWORD)"
  else
    warn "admin 自动建失败,可手动: docker compose exec backend python ...  (见 README)"
  fi

  FE_PORT="$(grep '^FRONTEND_HOST_PORT=' .env | cut -d= -f2-)"
  FE_PORT="${FE_PORT:-8080}"
  BE_PORT="$(grep -E '^\"?8000:?8000' docker-compose.yml >/dev/null 2>&1 && echo 8000 || echo 8000)"

  set -e
  echo
  ok "整栈已起"
  echo "  前端(浏览器):     http://<服务器IP>:${FE_PORT}"
  echo "  后端 API 文档:    http://<服务器IP>:${FE_PORT}/docs  (nginx 反代)"
  echo "  后端直连(调试):   http://<服务器IP>:8000/docs"
  echo "  日志:             $0 --logs"
  echo "  停止:             $0 --down"
}

load_offline_images() {
  local dir="${OFFLINE_DIR:-./offline-images}"
  [[ -d "$dir" ]] || die "找不到离线镜像目录: $dir (先用 deploy/offline-save.sh 打包)"
  shopt -s nullglob
  for tar in "$dir"/*.tar; do
    log "  load $(basename "$tar")"
    docker load -i "$tar"
  done
  ok "镜像加载完成"
}

do_down() {
  log "停止 TestMate 整栈..."
  compose_cmd down
  ok "已停止(数据卷保留)"
}

do_status() {
  compose_cmd ps
  echo
  echo "--- 健康检查 ---"
  curl -fsS http://127.0.0.1:8000/api/v1/health 2>/dev/null && echo "  backend: OK" || echo "  backend: DOWN"
  curl -fsS -o /dev/null -w "  frontend(Nginx): HTTP %{http_code}\n" http://127.0.0.1:8080/ 2>/dev/null || echo "  frontend: DOWN"
}

do_logs() {
  if [[ -n "${LOG_TARGET:-}" ]]; then
    compose_cmd logs -f "$LOG_TARGET"
  else
    compose_cmd logs -f
  fi
}

# ---------- 入口 ----------
case "$ACTION" in
  up)     require_root; do_up ;;
  down)   require_root; do_down ;;
  status) do_status ;;
  logs)   do_logs ;;
esac
