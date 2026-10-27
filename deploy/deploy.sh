#!/usr/bin/env bash
# TestMate Linux 服务器一键部署
#
# 用法:
#   sudo ./deploy/deploy.sh                        # 在线模式(从 docker.io / ghcr 拉镜像)
#   sudo ./deploy/deploy.sh --offline              # 离线模式(从本地镜像包 load)
#   sudo ./deploy/deploy.sh --offline-dir /tmp/imgs # 离线镜像包目录
#   sudo ./deploy/deploy.sh --down                 # 停止整栈
#   sudo ./deploy/deploy.sh --restart              # 重启整栈(改完代码后用这个)
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
    --restart)        ACTION="restart"; shift ;;
    --status)         ACTION="status"; shift ;;
    --logs)           ACTION="logs"; shift; LOG_TARGET="${1:-}"; [[ -n "${LOG_TARGET:-}" ]] && shift ;;
    -h|--help)
      sed -n '2,17p' "$0"; exit 0 ;;
    *) echo "未知参数: $1"; exit 1 ;;
  esac
done

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
cd "$SCRIPT_DIR"


# 去字符串首尾的引号 (单/双) — 替换原来有 bug 的 tr -d '"'\'\'\'\'
_strip_quotes() { awk '{ sub(/^["\047]/, ""); sub(/["\047]$/, ""); print }'; }

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
  JWT_VAL="$(grep '^JWT_SECRET=' .env | cut -d= -f2- | _strip_quotes )"
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
  # ⚠️ 门槛 **9** 字符 —— 2026-10-27 从 12 降下来的 (运维决定保留已知的
  #    "Admin@123", 正好 9 字符). 跟 deploy/native/lib.sh 的 MIN_PASSWORD_LEN 同一口径.
  #    代价: 弱口令能过检查, 而它还在仓库历史里出现过. 想收紧就把这里改回 12
  #    并把两个 .env 里的口令换掉 (裸机模式还要 `tmctl.sh admin` 改库里那个账号).
  MIN_PASSWORD_LEN=9
  for key in MYSQL_ROOT_PASSWORD ADMIN_DEFAULT_PASSWORD; do
    val="$(grep "^${key}=" .env | cut -d= -f2- | _strip_quotes )"
    if [[ -z "$val" ]]; then
      die "${key} 未设置"
    fi
    if [[ ${#val} -lt $MIN_PASSWORD_LEN ]]; then
      die "${key} 太短 (${#val} 字符),至少 $MIN_PASSWORD_LEN 字符,推荐: openssl rand -base64 18"
    fi
    # 占位符原样放行会让"忘了改"变成"带着占位符上线"
    if echo "$val" | grep -qiE 'change-me|change_me|please-change|changeme'; then
      die "${key} 还是占位符 (change-me...),必须换成自己的强口令"
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
  # ⚠️ software 是**软件包的存放目录** (挂给后端容器的 /data/software).
  #    不提前建出来的话, Docker 会用 root 身份自动建 —— 能用, 但运维看不见,
  #    也没法提前给它挂盘/设配额. market 是资产市场的 git 工作区, 同样提前建好.
  mkdir -p "$DATA_ROOT_VAL"/{mysql,redis,logs,market,software}
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
  set +e   # backend 第一次启动会失败(init_db 因表已存在崩溃),不要让 set -e 杀进程
  compose_cmd up -d
  set -e

  # 4.5/5 老数据卷兼容: **仅当版本表为空**时才 stamp head.
  #
  # ⚠️ 2026-10-25 修: 原来这里是**无条件** `alembic stamp head` ——
  #    它把版本直接盖到 head, 新迁移被整段跳过, 结果是"迁移文件写了但 schema 没变"
  #    (加 agents.kind 那一版就是这么差点翻车的: schema 缺列, 后端报 Unknown column).
  #    正确做法: 让 backend 自己的 init_db() 跑 upgrade head;
  #    只有"版本表不存在 / 没记录"(老环境用 create_all 建的) 才 stamp 兜底.
  #    后端 init_db() 里已经有一模一样的判断, 这里只是提前一步, 避免首启失败.
  log "  检查 alembic 版本表(老数据卷兼容)..."
  set +e
  NEED_STAMP="$(compose_cmd run --rm --no-deps --entrypoint "" backend python -c "
import asyncio
from sqlalchemy import text
from app.db.session import engine

async def main():
    async with engine.connect() as c:
        r = await c.execute(text(\"SHOW TABLES LIKE 'alembic_version'\"))
        if not r.first():
            print('YES')
            return
        r = await c.execute(text('SELECT version_num FROM alembic_version'))
        rows = [x[0] for x in r.fetchall()]
        print('YES' if not rows else 'NO')

asyncio.run(main())
" 2>/dev/null | tail -1)"
  set -e
  if [[ "$NEED_STAMP" == "YES" ]]; then
    log "  版本表不存在/为空 → stamp head(老数据卷兜底)"
    set +e
    compose_cmd run --rm --no-deps --entrypoint "" backend alembic stamp head >/dev/null 2>&1
    set -e
  else
    log "  版本表已有记录 → 跳过 stamp(让 upgrade head 正常跑新迁移)"
  fi

  # 重启 backend 让 init_db() 重新跑(版本表正常的话 upgrade head 应该 no-op)
  compose_cmd restart backend >/dev/null 2>&1 || true

  log "5/5 等待 backend healthy..."
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
  ADMIN_PASS="${ADMIN_PASS:-Admin@123}"

  # 通过 docker exec 在 backend 容器内跑(里面有 sqlalchemy / app 模型)
  # 凭证通过环境变量传(避免 heredoc 变量展开的转义问题)
  if compose_cmd exec -T -e ADMIN_USER="$ADMIN_USER" -e ADMIN_PASS="$ADMIN_PASS"       backend python - >/tmp/admin_create.log 2>&1 <<'PYEOF'
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
    warn "admin 自动建失败,日志:"
    if [[ -s /tmp/admin_create.log ]]; then
      sed 's/^/    /' /tmp/admin_create.log | head -20
    else
      echo "    /tmp/admin_create.log 空(可能 backend 没 ready,等 30s 再试)"
    fi
    echo "    手动建: docker compose exec backend python  (见 README)"
  fi

  FE_PORT="$(grep '^FRONTEND_HOST_PORT=' .env | cut -d= -f2-)"
  FE_PORT="${FE_PORT:-8080}"

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

do_restart() {
  log "重启 TestMate 整栈..."
  compose_cmd restart
  ok "已重启"
  # 重启完顺手看一眼健康 —— 不然"重启成功"和"服务能用"是两回事
  local be_port
  be_port="$(grep '^BACKEND_HOST_PORT=' .env 2>/dev/null | cut -d= -f2- || true)"
  be_port="${be_port:-18000}"
  local i
  for i in $(seq 1 30); do
    if curl -fsS "http://127.0.0.1:${be_port}/api/v1/health" >/dev/null 2>&1; then
      ok "backend healthy (耗时 ${i}s)"
      break
    fi
    sleep 2
    if [[ $i -eq 30 ]]; then
      warn "backend 30s 还没 health,看一眼日志: $0 --logs backend"
    fi
  done
}

do_status() {
  compose_cmd ps
  echo
  echo "--- 健康检查 ---"
  # ⚠️ 端口要从 .env 读 —— 原来写死 8000/8080, 而实际部署用的是
  #    BACKEND_HOST_PORT / FRONTEND_HOST_PORT (本机是 18000 / 8090),
  #    结果 --status 永远报 DOWN, 让人以为服务挂了.
  BE_PORT="$(grep '^BACKEND_HOST_PORT=' .env 2>/dev/null | cut -d= -f2- || true)"
  BE_PORT="${BE_PORT:-8000}"
  FE_PORT="$(grep '^FRONTEND_HOST_PORT=' .env 2>/dev/null | cut -d= -f2- || true)"
  FE_PORT="${FE_PORT:-8080}"
  curl -fsS "http://127.0.0.1:${BE_PORT}/api/v1/health" 2>/dev/null && echo "  backend(${BE_PORT}): OK" || echo "  backend(${BE_PORT}): DOWN"
  curl -fsS -o /dev/null -w "  frontend(${FE_PORT}, Nginx): HTTP %{http_code}\n" "http://127.0.0.1:${FE_PORT}/" 2>/dev/null || echo "  frontend(${FE_PORT}): DOWN"
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
  up)      require_root; do_up ;;
  down)    require_root; do_down ;;
  restart) require_root; do_restart ;;
  status)  do_status ;;
  logs)    do_logs ;;
esac
