#!/usr/bin/env bash
# TestMate 裸机部署 —— 统一运维入口
#
# 这是**运维唯一要记的命令**: 部署 / 启停 / 自启 / 状态 / 日志 / 升级 / 备份 都在这儿.
#
# 用法:
#   sudo ./deploy/native/tmctl.sh <命令> [选项]
#
# 命令:
#   check       环境体检 (只读, 不改任何东西)
#   install     一键部署 (体检 → 装依赖 → 建库 → 装服务 → 自启 → 健康校验 → 建 admin)
#   start       启动服务
#   stop        停止服务
#   restart     重启服务
#   reload      重载 nginx 配置 (后端不动)
#   status      看状态 (服务 / 端口 / 健康)
#   logs        看日志 (journalctl)
#   enable      开机自启动
#   disable     取消开机自启动
#   update      升级 (拉新代码 → 重建 → 重启 → 健康校验)
#   backup      备份数据 (MySQL + Redis + 配置)
#   restore     从备份恢复
#   doctor      深度排障 (比 check 看得深)
#   admin       建 / 改 admin 账号
#   uninstall   卸载 (默认保留数据)
#   help        本帮助
#
# 选项:
#   --auto        install/check 时自动装缺失的依赖
#   --offline     离线装 (用 runtime/wheelhouse 里的离线包)
#   --yes         非交互 (该问的都默认)
#   --no-start    install 完不启动
#   --force       重置所有口令 (其它配置保留)
#   --from REF    update 用的 git ref (默认当前分支的远端)
#
# ⚠️ 选项在命令**前后**都行: `check --auto` 与 `--auto check` 等价.
#    但 admin / backup / restore / logs 这几个命令自己的参数要写在命令**后面**
#    (如 `admin --username admin --password 'xxx'`) —— 那几个参数不是全局选项.
#
# 示例:
#   sudo ./deploy/native/tmctl.sh check
#   sudo ./deploy/native/tmctl.sh install --auto
#   sudo ./deploy/native/tmctl.sh restart
#   sudo ./deploy/native/tmctl.sh status
#   ./deploy/native/tmctl.sh logs -f

set -euo pipefail

# ==================== 引导 ====================
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
NATIVE_DIR="$SCRIPT_DIR"
REPO_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"
RUNTIME_DIR="$NATIVE_DIR/runtime"
ENV_FILE="$NATIVE_DIR/.env"

# shellcheck source=lib.sh
source "$SCRIPT_DIR/lib.sh"
# shellcheck source=preflight.sh
source "$SCRIPT_DIR/preflight.sh"

# 包管理器 —— 体检和装依赖都要用, 提前探好
PKG_MGR="$(detect_pkg_mgr)"

# systemd 单元名
BACKEND_UNIT="testmate-backend"
FRONTEND_UNIT="testmate-frontend"
UNIT_DIR="/etc/systemd/system"

# 全局选项
OPT_AUTO=0
OPT_OFFLINE=0
OPT_YES=0
OPT_NO_START=0
OPT_FORCE=0
OPT_FROM=""
OPT_FOLLOW=0
OPT_TARGET=""

usage() {
  sed -n '2,45p' "$0" | sed 's/^# \{0,1\}//'
}

# ==================== 参数解析 ====================
# ⚠️ 选项**在命令前后都能写** —— `tmctl.sh check --auto` 和 `tmctl.sh --auto check`
#    都得能用. 早先只认命令前的选项, 结果 `check --auto` 里的 --auto 被当成
#    命令的参数吞掉, --auto 静默失效 (看着像"自动装依赖没生效", 实际是没解析到).
#
# 有自己参数的命令 (admin / backup / restore / logs) —— 命令名之后的参数原样留给它,
# 不再走全局选项解析 (否则 admin --username 会被当成未知全局选项报错).
CMD_TAKES_ARGS="no"
case "${1:-}" in
  admin|backup|restore|logs) CMD_TAKES_ARGS="yes" ;;
esac

ACTION=""
declare -a REST=()
while [[ $# -gt 0 ]]; do
  # 命令之后的参数 → 原样留给命令自己
  if [[ "$CMD_TAKES_ARGS" == "yes" && -n "$ACTION" ]]; then
    REST+=("$1"); shift; continue
  fi
  case "$1" in
    --auto)      OPT_AUTO=1; shift ;;
    --offline)   OPT_OFFLINE=1; shift ;;
    --yes|-y)    OPT_YES=1; shift ;;
    --no-start)  OPT_NO_START=1; shift ;;
    --force)     OPT_FORCE=1; shift ;;
    --from)      OPT_FROM="${2:-}"; shift 2 ;;
    -f|--follow) OPT_FOLLOW=1; shift ;;
    --target)    OPT_TARGET="${2:-}"; shift 2 ;;
    -h|--help)   usage; exit 0 ;;
    -*)          die "未知选项: $1 (用 --help 看用法)" ;;
    *)
      if [[ -z "$ACTION" ]]; then
        ACTION="$1"; shift
      else
        REST+=("$1"); shift
      fi ;;
  esac
done
ACTION="${ACTION:-help}"

# ==================== 通用工具 ====================

cfg() {
  local key="$1" def="${2:-}" v
  v="$(env_get "$ENV_FILE" "$key" || true)"
  if [[ -z "$v" ]]; then printf '%s' "$def"; else printf '%s' "$v"; fi
}

need_root() {
  local what="${1:-这个操作}"
  is_root || die "$what 要 root: sudo $0 ${2:-}"
}

need_systemd() {
  have_cmd systemctl || die "没装 systemd —— 裸机模式不可用, 请用 Docker 模式 (deploy/deploy.sh)"
  systemd_available || die "systemd 没在跑 (PID 1 不是 systemd) —— 容器里请用 Docker 模式"
}

confirm() {
  local msg="$1"
  if [[ $OPT_YES -eq 1 ]]; then return 0; fi
  if [[ ! -t 0 ]]; then
    warn "$msg —— 非交互环境, 自动继续 (加 --yes 显式确认)"
    return 0
  fi
  local ans
  read -rp "  $msg [y/N] " ans
  [[ "$ans" =~ ^[Yy]$ ]]
}

# 模板渲染 (占位符 @@KEY@@)
render_template() {
  local tpl="$1" out="$2"; shift 2
  local content
  content="$(cat "$tpl")"
  while [[ $# -gt 0 ]]; do
    local k="$1" v="$2"; shift 2
    content="${content//@@${k}@@/${v}}"
  done
  printf '%s' "$content" > "$out"
}

# 找出系统的 mime.types (SPA 的 ES module 靠它)
find_mime_types() {
  local c
  for c in /etc/nginx/mime.types /usr/local/nginx/conf/mime.types /usr/share/nginx/mime.types; do
    [[ -f "$c" ]] && { printf '%s' "$c"; return 0; }
  done
  if have_cmd nginx; then
    local conf
    conf="$(nginx -V 2>&1 | grep -oE 'conf-path=[^ ]+' | cut -d= -f2 || true)"
    if [[ -n "$conf" ]]; then
      local dir
      dir="$(dirname "$conf")"
      for c in "$dir/mime.types" "$dir/../mime.types"; do
        [[ -f "$c" ]] && { printf '%s' "$c"; return 0; }
      done
    fi
  fi
  return 1
}

# 找不到 mime.types 时用的最小版 —— 少了 JS/CSS 的正确类型, 浏览器会拒绝加载 ES module
write_minimal_mime_types() {
  cat > "$1" <<'MIMEEOF'
types {
    text/html                             html htm;
    text/css                              css;
    text/xml                              xml;
    text/plain                            txt;
    application/javascript                js mjs;
    application/json                      json map;
    application/manifest+json             webmanifest;
    application/xml                       rss atom;
    application/pdf                       pdf;
    application/zip                       zip;
    application/gzip                      gz;
    application/x-tar                     tar;
    application/octet-stream              bin exe dll;
    application/wasm                      wasm;
    image/png                             png;
    image/jpeg                            jpeg jpg;
    image/gif                             gif;
    image/svg+xml                         svg svgz;
    image/webp                            webp;
    image/x-icon                          ico;
    font/woff                             woff;
    font/woff2                            woff2;
    font/ttf                              ttf;
    font/otf                              otf;
    audio/mpeg                            mp3;
    video/mp4                             mp4;
}
MIMEEOF
}

# ==================== 部署步骤 ====================

# ---- 配置 ----
ensure_env_file() {
  if [[ -f "$ENV_FILE" ]]; then
    if [[ $OPT_FORCE -eq 1 ]]; then
      # --force = **重置所有口令**, 其它配置(端口 / 仓库地址 / 时区)原样保留.
      # 不做"整个文件重生成" —— 那会把用户改过的 MARKET_GIT_REMOTE 之类冲掉.
      log "--force: 重置所有口令 (其它配置保留)"
      env_set "$ENV_FILE" "JWT_SECRET"     "$(gen_secret 32)"
      env_set "$ENV_FILE" "MYSQL_PASSWORD"  "$(gen_secret 18)"
      env_set "$ENV_FILE" "ADMIN_DEFAULT_PASSWORD" "$(gen_secret 18)"
      chmod 600 "$ENV_FILE"
      ok "口令已重置"
      echo "    admin 口令: $(cfg ADMIN_DEFAULT_PASSWORD)"
      echo
    else
      ok "配置已存在: $ENV_FILE"
    fi
    # 路径写死了就以实际为准 (仓库被挪过家的情况)
    if [[ "$(cfg REPO_ROOT)" != "$REPO_ROOT" ]]; then
      env_set "$ENV_FILE" "REPO_ROOT" "$REPO_ROOT"
      ok "  已同步 REPO_ROOT -> $REPO_ROOT"
    fi
    return 0
  fi

  log "生成配置: $ENV_FILE"
  cp "$NATIVE_DIR/.env.template" "$ENV_FILE"
  env_set "$ENV_FILE" "REPO_ROOT" "$REPO_ROOT"
  env_set "$ENV_FILE" "RUNTIME_DIR" "$RUNTIME_DIR"
  # 口令随机生成 —— 不让人手抄, 也不留弱口令
  env_set "$ENV_FILE" "JWT_SECRET"     "$(gen_secret 32)"
  env_set "$ENV_FILE" "MYSQL_PASSWORD"  "$(gen_secret 18)"
  env_set "$ENV_FILE" "ADMIN_DEFAULT_PASSWORD" "$(gen_secret 18)"
  chmod 600 "$ENV_FILE"
  # sudo 跑的时候文件会归 root —— 归给发起 sudo 的人, 否则他之后不带 sudo 也读不了
  if [[ -n "${SUDO_USER:-}" && "$SUDO_USER" != "root" ]]; then
    chown "$SUDO_USER" "$ENV_FILE" 2>/dev/null || true
  fi
  ok "已生成 (JWT_SECRET / MySQL 口令 / admin 口令 都是随机值)"
  echo
  echo "    ⚠️ admin 登录口令在文件里, 现在就记下来:"
  echo "       用户: $(cfg ADMIN_DEFAULT_USER admin)"
  echo "       口令: $(cfg ADMIN_DEFAULT_PASSWORD)"
  echo
  echo "    改口令: $0 admin --username $(cfg ADMIN_DEFAULT_USER admin) --password '<新口令>'"
  echo
}

# ---- 服务用户 ----
ensure_run_user() {
  local u g
  u="$(cfg RUN_USER testmate)"
  g="$(cfg RUN_GROUP "$u")"
  if id "$u" >/dev/null 2>&1; then
    ok "服务用户: $u (已存在)"
    return 0
  fi
  need_root
  log "创建服务用户: $u"
  if useradd --system --no-create-home --shell /usr/sbin/nologin "$u" 2>/dev/null \
     || useradd --system --no-create-home --shell /sbin/nologin "$u" 2>/dev/null; then
    ok "服务用户已创建: $u"
  else
    die "创建用户 $u 失败 —— 改 .env 里的 RUN_USER 成一个已存在的账号"
  fi
  if ! getent group "$g" >/dev/null 2>&1; then
    groupadd --system "$g" 2>/dev/null || true
  fi
}

# ---- MySQL ----
ensure_mysql() {
  local host port db user pass root_user root_pass svc
  host="$(cfg MYSQL_HOST 127.0.0.1)"
  port="$(cfg MYSQL_PORT 3306)"
  db="$(cfg MYSQL_DATABASE testmate)"
  user="$(cfg MYSQL_USER testmate)"
  pass="$(cfg MYSQL_PASSWORD)"
  root_user="$(cfg MYSQL_ROOT_USER root)"
  root_pass="$(cfg MYSQL_ROOT_PASSWORD)"

  local mycli
  mycli="$(mysql_client_cmd)"
  if [[ -z "$mycli" && $OPT_AUTO -eq 1 && -n "$PKG_MGR" ]]; then
    log "装 MySQL 客户端 ..."
    if ! pkg_install mysql "$PKG_MGR"; then
      warn "自动装 MySQL 客户端失败 —— 安装日志尾部:"
      pkg_log_tail
    fi
    mycli="$(mysql_client_cmd)"
  fi
  if [[ -z "$mycli" ]]; then
    die "没有 mysql 客户端 —— 装: ${PKG_MGR:-apt-get} install $(pkg_name mysql "${PKG_MGR:-apt-get}") (或 mariadb-server), 然后重跑 install"
  fi

  # 1. 服务在跑吗
  svc="$(mysql_service_name)"
  if ! unit_active "${svc}.service"; then
    log "启动 MySQL (${svc}.service) ..."
    systemctl enable --now "${svc}.service" >/dev/null 2>&1 \
      || warn "启动 ${svc}.service 失败 —— 手动看看: systemctl status ${svc}"
    # 等它起来
    local i
    for i in $(seq 1 30); do
      unit_active "${svc}.service" && break
      sleep 1
    done
  fi
  unit_active "${svc}.service" && ok "MySQL 服务: 运行中" || warn "MySQL 服务没起来 —— 装 MySQL: ${PKG_MGR:+$(pkg_name mysql "$PKG_MGR")}"

  # 2. 能连上吗 —— 先试免密, 再试带口令
  local root_cmd=("$mycli" "-u" "$root_user" "--protocol=TCP" "-h" "127.0.0.1" "-P" "$port")
  if [[ -n "$root_pass" ]]; then
    root_cmd+=("-p${root_pass}")
  fi
  if "${root_cmd[@]}" -e "SELECT 1" >/dev/null 2>&1; then
    ok "MySQL 连接: 正常 (用户 $root_user)"
  else
    # 退一步: socket 连接 (Linux 上 root 常走 socket 免密)
    if "$mycli" -u "$root_user" -e "SELECT 1" >/dev/null 2>&1; then
      root_cmd=("$mycli" "-u" "$root_user")
      ok "MySQL 连接: 正常 (socket)"
    else
      die "连不上 MySQL —— 填 .env 里的 MYSQL_ROOT_PASSWORD, 或先用 '$mycli -u $root_user' 手工连一次"
    fi
  fi

  # 3. 建库建用户
  # 口令转义成 SQL 字面量 (单引号要翻倍)
  local pass_sql
  pass_sql="$(printf '%s' "$pass" | sed "s/'/''/g")"
  log "建库建用户: $db / $user"
  "${root_cmd[@]}" <<SQL
CREATE DATABASE IF NOT EXISTS \`${db}\` CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;
CREATE USER IF NOT EXISTS '${user}'@'localhost' IDENTIFIED BY '${pass_sql}';
CREATE USER IF NOT EXISTS '${user}'@'127.0.0.1' IDENTIFIED BY '${pass_sql}';
ALTER USER '${user}'@'localhost' IDENTIFIED BY '${pass_sql}';
ALTER USER '${user}'@'127.0.0.1' IDENTIFIED BY '${pass_sql}';
GRANT ALL PRIVILEGES ON \`${db}\`.* TO '${user}'@'localhost';
GRANT ALL PRIVILEGES ON \`${db}\`.* TO '${user}'@'127.0.0.1';
FLUSH PRIVILEGES;
SQL
  ok "数据库就绪: $db (用户 $user)"
}

# ---- Redis ----
ensure_redis() {
  local host port pass svc
  host="$(cfg REDIS_HOST 127.0.0.1)"
  port="$(cfg REDIS_PORT 6379)"
  pass="$(cfg REDIS_PASSWORD)"
  svc="$(redis_service_name)"

  if ! unit_active "${svc}.service"; then
    log "启动 Redis (${svc}.service) ..."
    systemctl enable --now "${svc}.service" >/dev/null 2>&1 \
      || warn "启动 ${svc}.service 失败 —— 装 Redis: ${PKG_MGR:+$(pkg_name redis "$PKG_MGR")}"
    local i
    for i in $(seq 1 15); do
      unit_active "${svc}.service" && break
      sleep 1
    done
  fi

  if ! have_cmd redis-cli; then
    if [[ $OPT_AUTO -eq 1 && -n "$PKG_MGR" ]]; then
      log "装 redis-cli ..."
      if ! pkg_install redis "$PKG_MGR"; then
        warn "自动装 redis-cli 失败 —— 安装日志尾部:"
        pkg_log_tail
      fi
    fi
  fi
  if ! have_cmd redis-cli; then
    warn "没有 redis-cli —— 装: ${PKG_MGR:+$(pkg_name redis "$PKG_MGR")}; 服务可能仍然正常跑着"
    return 0
  fi

  local rc=(redis-cli -h "$host" -p "$port")
  [[ -n "$pass" ]] && rc+=(-a "$pass" --no-auth-warning)
  if "${rc[@]}" ping 2>/dev/null | grep -q PONG; then
    ok "Redis 连接: 正常"
  else
    warn "Redis 连不上 ($host:$port) —— 装/起: systemctl enable --now ${svc}.service"
  fi
}

# ---- Python venv ----
build_venv() {
  local venv="$RUNTIME_DIR/venv"
  log "准备 Python 虚拟环境"
  if [[ ! -x "$venv/bin/python" ]]; then
    python3 -m venv "$venv" || die "创建 venv 失败 —— 装 python3-venv"
  fi
  "$venv/bin/pip" install -q --upgrade pip setuptools wheel

  local req="$REPO_ROOT/backend_gateway/requirements.lock"
  if [[ $OPT_OFFLINE -eq 1 ]]; then
    local wh="$RUNTIME_DIR/wheelhouse"
    if [[ -d "$wh" ]]; then
      log "离线安装依赖 (wheelhouse: $wh)"
      "$venv/bin/pip" install -q --no-index --find-links "$wh" -r "$req"
    else
      die "--offline 需要先准备离线包: 把 wheel 放进 $RUNTIME_DIR/wheelhouse"
    fi
  else
    "$venv/bin/pip" install -q -r "$req"
  fi
  ok "依赖就绪 ($(cd "$venv" && du -sh . 2>/dev/null | cut -f1))"
}

# ---- 前端 ----
build_frontend() {
  log "构建前端"
  cd "$REPO_ROOT/frontend_web"
  if [[ $OPT_OFFLINE -eq 1 ]]; then
    local cache="$RUNTIME_DIR/npm-cache"
    mkdir -p "$cache"
    npm ci --offline --cache "$cache" --no-audit --no-fund 2>/dev/null \
      || npm ci --prefer-offline --cache "$cache" --no-audit --no-fund
  else
    if [[ ! -d node_modules ]] || [[ package-lock.json -nt node_modules ]]; then
      npm ci --no-audit --no-fund
    else
      npm install --no-audit --no-fund --prefer-offline
    fi
  fi
  npm run build
  rm -rf "$RUNTIME_DIR/frontend"
  mkdir -p "$RUNTIME_DIR/frontend"
  cp -R dist/. "$RUNTIME_DIR/frontend/"
  ok "前端产物就绪 ($RUNTIME_DIR/frontend)"
  cd "$REPO_ROOT"
}

# ---- SSH key ----
ensure_market_ssh() {
  local key known key_dest known_dest
  key="$(cfg MARKET_SSH_KEY)"
  known="$(cfg MARKET_SSH_KNOWN_HOSTS)"
  key_dest="$RUNTIME_DIR/ssh/id_ed25519"
  known_dest="$RUNTIME_DIR/ssh/known_hosts"

  mkdir -p "$RUNTIME_DIR/ssh"
  chmod 700 "$RUNTIME_DIR/ssh"

  if [[ -z "$key" ]]; then
    local cand
    for cand in "$HOME/.ssh/id_ed25519" "$HOME/.ssh/id_rsa"; do
      if [[ -f "$cand" ]]; then key="$cand"; break; fi
    done
  fi
  if [[ -z "$key" || ! -f "$key" ]]; then
    warn "没找到资产市场用的 SSH 私钥 —— 上架/推送会失败; 装好后填 .env 的 MARKET_SSH_KEY"
    echo "" > "$known_dest"
    return 0
  fi

  cp -f "$key" "$key_dest"
  chmod 600 "$key_dest"
  if [[ -n "$known" && -f "$known" ]]; then
    cp -f "$known" "$known_dest"
  else
    # 没给 known_hosts 就把目标的 host key 记下来 (StrictHostKeyChecking=accept-new)
    : > "$known_dest"
  fi
  chmod 600 "$known_dest"
  ok "SSH 身份就绪: $key -> $key_dest"
}

# ---- 生成 systemd 单元 + nginx 配置 ----
render_configs() {
  local runtime run_user run_group be_port fe_port bind_addr workers
  local backend_env nginx_conf nginx_prefix nginx_bin
  runtime="$RUNTIME_DIR"
  run_user="$(cfg RUN_USER testmate)"
  run_group="$(cfg RUN_GROUP "$run_user")"
  be_port="$(cfg BACKEND_PORT 8000)"
  fe_port="$(cfg FRONTEND_PORT 8080)"
  bind_addr="$(cfg BIND_ADDR 127.0.0.1)"
  workers="$(cfg BACKEND_WORKERS 1)"
  if [[ "$workers" != "1" ]]; then
    warn "BACKEND_WORKERS=$workers —— ⚠️ **大于 1 会出大问题**:"
    warn "  后端的后台任务(资产市场 job 消费者 / 反向同步)走**进程内**队列, 不跨进程."
    warn "  多 worker = 每个进程一份队列, 且每个进程启动都 recover_pending_jobs()"
    warn "  → 同一个 job 被多个进程抢 → git 的 index.lock 冲突 / 重复推 GitLab."
    warn "  要提吞吐请加机器, 不要加 worker. 已按你填的值继续, 改回来改 .env 的 BACKEND_WORKERS."
  fi

  mkdir -p "$runtime"/{config,logs,run,data,frontend,market}
  # ⚠️ MARKET_DIR 也得建 —— systemd 的 ReadWritePaths 指向的路径不存在时,
  #    单元会直接起不来 (Failed to set up mount namespacing)
  local market_dir
  market_dir="$(cfg MARKET_DIR "$runtime/market")"
  mkdir -p "$market_dir"
  backend_env="$runtime/config/backend.env"
  nginx_conf="$runtime/config/nginx.conf"
  nginx_prefix="$runtime"
  nginx_bin="$(command -v nginx || echo /usr/sbin/nginx)"

  # ---- backend.env ----
  log "生成后端环境文件: $backend_env"
  {
    echo "# TestMate 后端环境变量 —— 由 tmctl.sh install 生成, 勿手改"
    echo "# 改了配置记得重跑 install (或 systemctl restart $BACKEND_UNIT)"
    echo
    echo "APP_NAME=TestMate Gateway"
    echo "APP_VERSION=0.1.0"
    echo "DEBUG=false"
    echo "HOST=${bind_addr}"
    echo "PORT=${be_port}"
    echo "TZ=$(cfg TIMEZONE Asia/Shanghai)"
    echo
    echo "JWT_SECRET=$(cfg JWT_SECRET)"
    echo "JWT_EXPIRE_MINUTES=$(cfg JWT_EXPIRE_MINUTES 10080)"
    echo "AUTH_EMAIL_DOMAIN=$(cfg AUTH_EMAIL_DOMAIN @twsc.com.cn)"
    echo
    echo "MYSQL_HOST=$(cfg MYSQL_HOST 127.0.0.1)"
    echo "MYSQL_PORT=$(cfg MYSQL_PORT 3306)"
    echo "MYSQL_USER=$(cfg MYSQL_USER testmate)"
    echo "MYSQL_PASSWORD=$(cfg MYSQL_PASSWORD)"
    echo "MYSQL_DATABASE=$(cfg MYSQL_DATABASE testmate)"
    echo
    echo "REDIS_HOST=$(cfg REDIS_HOST 127.0.0.1)"
    echo "REDIS_PORT=$(cfg REDIS_PORT 6379)"
    echo "REDIS_DB=$(cfg REDIS_DB 0)"
    [[ -n "$(cfg REDIS_PASSWORD)" ]] && echo "REDIS_PASSWORD=$(cfg REDIS_PASSWORD)"
    echo
    echo "CORS_ORIGINS=[\"http://localhost:${fe_port}\",\"http://127.0.0.1:${fe_port}\"]"
    echo
    echo "MARKET_WORKSPACE=$(cfg MARKET_DIR "$runtime/market")"
    echo "MARKET_GIT_REMOTE=$(cfg MARKET_GIT_REMOTE)"
    echo "MARKET_GIT_BRANCH=$(cfg MARKET_GIT_BRANCH main)"
    echo "MARKET_SYNC_INTERVAL_SECONDS=$(cfg MARKET_SYNC_INTERVAL_SECONDS 30)"
    if [[ -f "$runtime/ssh/id_ed25519" ]]; then
      echo "GIT_SSH_COMMAND=\"ssh -i $runtime/ssh/id_ed25519 -o IdentitiesOnly=yes -o StrictHostKeyChecking=accept-new -o UserKnownHostsFile=$runtime/ssh/known_hosts -o BatchMode=yes\""
    fi
    echo
    echo "RAGFLOW_BASE_URL=$(cfg RAGFLOW_BASE_URL)"
    echo "RAGFLOW_API_KEY=$(cfg RAGFLOW_API_KEY)"
    echo "REVIEW_AGENT_BASE_URL=$(cfg REVIEW_AGENT_BASE_URL)"
    echo "REVIEW_AGENT_API_TOKEN=$(cfg REVIEW_AGENT_API_TOKEN)"
    echo "DINGTALK_DEFAULT_WEBHOOK=$(cfg DINGTALK_DEFAULT_WEBHOOK)"
    echo "ADMIN_DEFAULT_PASSWORD=$(cfg ADMIN_DEFAULT_PASSWORD)"
  } > "$backend_env"
  chmod 600 "$backend_env"
  ok "后端环境文件就绪"

  # ---- nginx ----
  log "生成 nginx 配置: $nginx_conf"
  local mime_src
  if ! mime_src="$(find_mime_types)"; then
    write_minimal_mime_types "$runtime/config/mime.types"
    warn "系统里没找到 mime.types —— 用内置最小版 (只覆盖前端用到的类型)"
  else
    cp -f "$mime_src" "$runtime/config/mime.types"
  fi
  render_template "$NATIVE_DIR/units/nginx.conf.tpl" "$nginx_conf" \
    "FRONTEND_PORT" "$fe_port" \
    "BACKEND_PORT" "$be_port" \
    "FRONTEND_DIR" "$runtime/frontend" \
    "RUN_DIR" "$runtime/run" \
    "LOG_DIR" "$runtime/logs" \
    "NGINX_CONF_DIR" "$runtime/config"
  ok "nginx 配置就绪"

  # ---- systemd 单元 ----
  need_root
  log "写 systemd 单元"
  render_template "$NATIVE_DIR/units/testmate-backend.service.tpl" "$UNIT_DIR/${BACKEND_UNIT}.service" \
    "REPO_ROOT" "$REPO_ROOT" \
    "BACKEND_DIR" "$REPO_ROOT/backend_gateway" \
    "BACKEND_ENV" "$backend_env" \
    "VENV_BIN" "$runtime/venv/bin" \
    "RUN_USER" "$run_user" \
    "RUN_GROUP" "$run_group" \
    "BIND_ADDR" "$bind_addr" \
    "BACKEND_PORT" "$be_port" \
    "WORKERS" "$workers" \
    "FORWARDED_ALLOW" "127.0.0.1" \
    "TIMEZONE" "$(cfg TIMEZONE Asia/Shanghai)" \
    "MEM_LIMIT" "$(cfg BACKEND_MEM_LIMIT 2G)" \
    "CPU_QUOTA" "$(cfg BACKEND_CPU_QUOTA 200%)" \
    "RUNTIME_DIR" "$runtime" \
    "DATA_DIR" "$runtime/data" \
    "LOG_DIR" "$runtime/logs" \
    "MARKET_DIR" "$market_dir" \
    "RUN_DIR" "$runtime/run"

  render_template "$NATIVE_DIR/units/testmate-frontend.service.tpl" "$UNIT_DIR/${FRONTEND_UNIT}.service" \
    "REPO_ROOT" "$REPO_ROOT" \
    "NGINX_BIN" "$nginx_bin" \
    "NGINX_CONF" "$nginx_conf" \
    "NGINX_PREFIX" "$nginx_prefix" \
    "RUN_DIR" "$runtime/run" \
    "LOG_DIR" "$runtime/logs" \
    "RUNTIME_DIR" "$runtime" \
    "RUN_USER" "$run_user" \
    "RUN_GROUP" "$run_group"

  # 目录归属给服务用户
  chown -R "$run_user:$run_group" "$runtime" 2>/dev/null || true
  # ⚠️ MARKET_DIR 可能在 runtime 之外 (用户自定义路径) —— 上面的 chown -R 覆盖不到,
  #    而它是资产市场 git 工作区, 服务用户必须能写 (后端会自己 init + fetch 建仓库,
  #    写不了的话上传/推送全挂).
  [[ "$market_dir" != "$runtime"/* ]] && chown -R "$run_user:$run_group" "$market_dir" 2>/dev/null || true

  # ---- 单元自检 ----
  # ⚠️ systemd 对**非法 / 不存在**的 ReadWritePaths 只警告并忽略那一项, 单元照样起得来 ——
  #    但对应目录随后就是只读的. 资产市场工作区在那儿 → 上传/推送全挂, 而且报错点离根因极远.
  #    所以装的时候就地验一遍, 别等开机才发现.
  if have_cmd systemd-analyze; then
    local vout
    vout="$(systemd-analyze verify "$UNIT_DIR/${BACKEND_UNIT}.service" 2>&1 \
            | grep -vE 'Command .* is not executable|not found' || true)"
    if [[ -n "$(echo "$vout" | tr -d '[:space:]')" ]]; then
      warn "后端单元有告警 —— 起不来时先看这里:"
      echo "$vout" | sed 's/^/      /' | head -10
    else
      ok "后端单元校验通过"
    fi
    vout="$(systemd-analyze verify "$UNIT_DIR/${FRONTEND_UNIT}.service" 2>&1 \
            | grep -vE 'Command .* is not executable|not found' || true)"
    if [[ -n "$(echo "$vout" | tr -d '[:space:]')" ]]; then
      warn "前端单元有告警:"
      echo "$vout" | sed 's/^/      /' | head -10
    else
      ok "前端单元校验通过"
    fi
  fi

  systemctl daemon-reload
  ok "systemd 单元就绪: $BACKEND_UNIT / $FRONTEND_UNIT"
}

# ---- 等健康 ----
wait_healthy() {
  local be_port fe_port
  be_port="$(cfg BACKEND_PORT 8000)"
  fe_port="$(cfg FRONTEND_PORT 8080)"
  log "等后端就绪 (最多 120s) ..."
  local i
  for i in $(seq 1 60); do
    if curl -fsS -o /dev/null --max-time 3 "http://127.0.0.1:${be_port}/api/v1/health" 2>/dev/null; then
      ok "后端已响应 (${i}s)"
      break
    fi
    sleep 2
    if [[ $i -eq 60 ]]; then
      fail "后端 120s 还没起来 —— 看日志: $0 logs -f $BACKEND_UNIT"
      return 1
    fi
  done

  log "等 readiness (MySQL/Redis 全通才算 ready) ..."
  for i in $(seq 1 30); do
    if curl -fsS -o /dev/null --max-time 3 "http://127.0.0.1:${be_port}/api/v1/health/ready" 2>/dev/null; then
      ok "后端 ready (${i}s)"
      break
    fi
    sleep 2
    if [[ $i -eq 30 ]]; then
      warn "readiness 还没过 —— 可能 MySQL/Redis 没通: $0 doctor"
      return 0
    fi
  done

  if curl -fsS -o /dev/null --max-time 5 "http://127.0.0.1:${fe_port}/" 2>/dev/null; then
    ok "前端已响应"
  else
    warn "前端没响应 —— 看日志: $0 logs $FRONTEND_UNIT"
  fi
}

# ---- admin ----
create_admin_account() {
  local user pass venv
  user="$(cfg ADMIN_DEFAULT_USER admin)"
  pass="$(cfg ADMIN_DEFAULT_PASSWORD)"
  venv="$RUNTIME_DIR/venv/bin/python"
  [[ -x "$venv" ]] || { warn "venv 没建好, 跳过 admin 创建"; return 0; }

  # 口令走临时文件, 不进命令行 (ps 里别人看得见)
  local pf
  pf="$(mktemp)"
  chmod 600 "$pf"
  printf '%s' "$pass" > "$pf"

  log "建 admin 账号: $user"
  if (cd "$REPO_ROOT" && "$venv" "$REPO_ROOT/scripts/create_admin.py" \
        --env-file "$ENV_FILE" \
        --username "$user" \
        --password-file "$pf" \
        --role admin) >/tmp/tm-admin-create.log 2>&1; then
    ok "admin 账号就绪"
  else
    warn "admin 自动创建失败, 日志:"
    sed 's/^/    /' /tmp/tm-admin-create.log 2>/dev/null | head -15
    echo "    手动: sudo -u $(cfg RUN_USER testmate) $venv $REPO_ROOT/scripts/create_admin.py --env-file $ENV_FILE --username $user --password '<口令>' --role admin"
  fi
  rm -f "$pf"
}

# ==================== 命令实现 ====================

cmd_check() {
  # shellcheck disable=SC2034  # PREFLIGHT_AUTO 是给 source 进来的 preflight.sh 用的
  PREFLIGHT_AUTO="$OPT_AUTO"
  preflight_run
  # ⚠️ 退出码要透传 —— 体检没过就该非 0, 好让 CI / 巡检脚本用得上
  chk_summary || return 1
  return 0
}

cmd_install() {
  need_systemd
  need_root "安装服务"
  log "TestMate 裸机部署 (native / systemd)"
  echo

  log "1/9 环境体检"
  # shellcheck disable=SC2034  # PREFLIGHT_AUTO 是给 source 进来的 preflight.sh 用的
  PREFLIGHT_AUTO="$OPT_AUTO"
  preflight_run || true
  echo
  if [[ $CHK_FAIL -gt 0 ]]; then
    if [[ $OPT_AUTO -eq 1 ]]; then
      warn "还有 $CHK_FAIL 项没过 —— 装完再体检一次; 要是缺依赖, 先手工装上再重跑"
    else
      confirm "体检没全过, 继续?" || die "已中止 (加 --auto 让脚本自己装依赖)"
    fi
  fi

  log "2/9 生成配置"
  ensure_env_file

  log "3/9 服务用户"
  ensure_run_user

  log "4/9 数据库"
  ensure_mysql

  log "5/9 Redis"
  ensure_redis

  log "6/9 Python 依赖"
  build_venv

  log "7/9 前端构建"
  build_frontend

  log "8/9 资产市场 SSH 身份"
  ensure_market_ssh

  log "9/9 注册 systemd 服务"
  render_configs

  systemctl enable "$BACKEND_UNIT" "$FRONTEND_UNIT" >/dev/null 2>&1 \
    || warn "设开机自启失败 —— 手动: systemctl enable $BACKEND_UNIT $FRONTEND_UNIT"

  if [[ $OPT_NO_START -eq 1 ]]; then
    ok "装完了 (没启动) —— 起: $0 start"
    return 0
  fi

  log "启动服务"
  systemctl restart "$BACKEND_UNIT" || die "后端起不来 —— 看日志: $0 logs $BACKEND_UNIT"
  systemctl restart "$FRONTEND_UNIT" || warn "前端起不来 —— 看日志: $0 logs $FRONTEND_UNIT"

  wait_healthy
  create_admin_account

  local fe_port be_port ip
  fe_port="$(cfg FRONTEND_PORT 8080)"
  be_port="$(cfg BACKEND_PORT 8000)"
  ip="$(hostname -I 2>/dev/null | awk '{print $1}' || echo '<服务器IP>')"

  echo
  ok "部署完成"
  echo "  前端:       http://${ip}:${fe_port}"
  echo "  API 文档:   http://${ip}:${fe_port}/docs"
  echo "  后端直连:   http://127.0.0.1:${be_port}/docs   (只监听本机)"
  echo "  开机自启:   已启用"
  echo
  echo "  状态: $0 status"
  echo "  日志: $0 logs -f"
  echo "  重启: $0 restart"
  echo "  停止: $0 stop"
}

cmd_start() {
  need_systemd
  need_root "启动服务"
  log "启动服务"
  # 后端先起 —— 前端起来但后端没起的话, 页面会是一片 502
  systemctl start "$BACKEND_UNIT"
  systemctl start "$FRONTEND_UNIT"
  wait_healthy
}

cmd_stop() {
  need_systemd
  need_root "停止服务"
  log "停止服务"
  systemctl stop "$FRONTEND_UNIT" "$BACKEND_UNIT"
  ok "已停止 (数据保留)"
}

cmd_restart() {
  need_systemd
  need_root "重启服务"
  log "重启服务"
  systemctl restart "$BACKEND_UNIT" "$FRONTEND_UNIT"
  wait_healthy
}

cmd_reload() {
  need_systemd
  need_root "重载配置"
  log "重载 nginx 配置"
  nginx -t -c "$RUNTIME_DIR/config/nginx.conf" -p "$RUNTIME_DIR" || die "nginx 配置有错"
  systemctl reload "$FRONTEND_UNIT"
  ok "已重载"
}

cmd_status() {
  need_systemd
  local be_port fe_port
  be_port="$(cfg BACKEND_PORT 8000)"
  fe_port="$(cfg FRONTEND_PORT 8080)"

  echo "${C_BOLD}TestMate 服务状态${C_OFF}"
  echo
  printf "  %-22s %-12s %-12s\n" "服务" "运行" "开机自启"
  local u
  for u in "$BACKEND_UNIT" "$FRONTEND_UNIT"; do
    local act ena
    act="$(systemctl is-active "$u" 2>/dev/null || echo inactive)"
    ena="$(systemctl is-enabled "$u" 2>/dev/null || echo disabled)"
    local mark=" "
    [[ "$act" == "active" ]] && mark="${C_GREEN}✓${C_OFF}"
    [[ "$ena" == "enabled" ]] || ena="${C_YELLOW}${ena}${C_OFF}"
    printf "  %-22s %b %-12s %s\n" "$u" "$mark" "$act" "$ena"
  done

  echo
  echo "  端口:"
  local p
  for p in "$fe_port:前端(nginx)" "$be_port:后端(uvicorn)"; do
    local port="${p%%:*}" label="${p##*:}"
    if port_in_use "$port"; then
      printf "    %-20s %b %s\n" "$label" "${C_GREEN}✓${C_OFF}" "$port (监听中)"
    else
      printf "    %-20s %b %s\n" "$label" "${C_RED}✗${C_OFF}" "$port (没监听)"
    fi
  done

  echo
  echo "  健康检查:"
  if curl -fsS --max-time 5 "http://127.0.0.1:${be_port}/api/v1/health" >/dev/null 2>&1; then
    ok "backend liveness: OK"
  else
    fail "backend liveness: 不通"
  fi
  local ready
  ready="$(curl -fsS --max-time 5 "http://127.0.0.1:${be_port}/api/v1/health/ready" 2>/dev/null || true)"
  if [[ -n "$ready" ]]; then
    ok "backend readiness: OK"
  else
    fail "backend readiness: 不通 (MySQL 或 Redis 没连上)"
  fi
  local code
  code="$(curl -fsS -o /dev/null -w '%{http_code}' --max-time 5 "http://127.0.0.1:${fe_port}/" 2>/dev/null || echo 000)"
  if [[ "$code" == "200" ]]; then
    ok "frontend: HTTP $code"
  else
    fail "frontend: HTTP $code"
  fi

  echo
  echo "  版本:"
  local rev
  rev="$(cd "$REPO_ROOT" && git rev-parse --short HEAD 2>/dev/null || echo '?')"
  echo "    代码: $rev ($(cd "$REPO_ROOT" && git rev-parse --abbrev-ref HEAD 2>/dev/null || echo '?'))"
  local deployed_at
  if [[ "$(uname -s)" == "Darwin" ]]; then
    deployed_at="$(stat -f '%Sm' -t '%Y-%m-%d %H:%M' "$RUNTIME_DIR/config/backend.env" 2>/dev/null || echo '?')"
  else
    deployed_at="$(stat -c '%y' "$RUNTIME_DIR/config/backend.env" 2>/dev/null | cut -d. -f1 || echo '?')"
  fi
  echo "    部署于: $deployed_at"
}

cmd_logs() {
  need_systemd
  # 先把命令自己的参数吃掉 (-f / --follow / 服务名), 再决定看哪些服务
  local a
  for a in "$@"; do
    case "$a" in
      -f|--follow) OPT_FOLLOW=1 ;;
      *) [[ -z "$OPT_TARGET" ]] && OPT_TARGET="$a" ;;
    esac
  done

  local -a units
  if [[ -n "$OPT_TARGET" ]]; then
    units=("$OPT_TARGET")
  else
    units=("$BACKEND_UNIT" "$FRONTEND_UNIT")
  fi

  local -a jargs=()
  local u
  for u in "${units[@]}"; do
    jargs+=(-u "$u")
  done
  if [[ $OPT_FOLLOW -eq 1 ]]; then
    journalctl "${jargs[@]}" -f -n 100 --no-pager
  else
    journalctl "${jargs[@]}" -n 100 --no-pager
  fi
}

cmd_enable() {
  need_systemd
  need_root "设置开机自启"
  systemctl enable "$BACKEND_UNIT" "$FRONTEND_UNIT"
  ok "已设开机自启"
}

cmd_disable() {
  need_systemd
  need_root "取消开机自启"
  systemctl disable "$BACKEND_UNIT" "$FRONTEND_UNIT"
  ok "已取消开机自启 (服务还在跑)"
}

cmd_update() {
  need_root
  log "1/5 拉新代码"
  cd "$REPO_ROOT"
  local before
  before="$(git rev-parse --short HEAD 2>/dev/null || echo '?')"
  if [[ -n "$OPT_FROM" ]]; then
    git fetch --all --tags 2>/dev/null || true
    git checkout "$OPT_FROM" || die "切不到 $OPT_FROM"
    git pull 2>/dev/null || true
  else
    git pull --ff-only || warn "git pull 不是快进 —— 有本地改动? 手工处理: cd $REPO_ROOT && git status"
  fi
  local after
  after="$(git rev-parse --short HEAD 2>/dev/null || echo '?')"
  if [[ "$before" == "$after" ]]; then
    info "代码没变 ($after) —— 继续重建 (可能只是想重装依赖)"
  else
    ok "代码: $before -> $after"
  fi

  log "2/5 重建依赖"
  build_venv

  log "3/5 重建前端"
  build_frontend

  log "4/5 重启服务"
  render_configs
  systemctl restart "$BACKEND_UNIT" "$FRONTEND_UNIT"

  log "5/5 健康校验"
  wait_healthy
  ok "升级完成"
}

cmd_backup() {
  local dest="${1:-/var/backups/testmate}"
  local stamp mycli host port db user pass
  stamp="$(date +%F-%H%M)"
  mkdir -p "$dest"

  mycli="$(mysql_client_cmd)"
  host="$(cfg MYSQL_HOST 127.0.0.1)"
  port="$(cfg MYSQL_PORT 3306)"
  db="$(cfg MYSQL_DATABASE testmate)"
  user="$(cfg MYSQL_USER testmate)"
  pass="$(cfg MYSQL_PASSWORD)"

  # ⚠️ 口令走 defaults 文件, **不进命令行** —— `-p密码` 在 ps 里谁都能看见
  local defaults
  defaults="$(mktemp)"; chmod 600 "$defaults"
  printf '[client]\nuser=%s\npassword=%s\nhost=%s\nport=%s\n' \
    "$user" "$pass" "$host" "$port" > "$defaults"

  log "1/3 MySQL dump"
  if have_cmd mysqldump; then
    if mysqldump --defaults-extra-file="$defaults" \
        --single-transaction --routines --triggers "$db" 2>/dev/null | gzip > "$dest/mysql-${stamp}.sql.gz"; then
      ok "MySQL -> $dest/mysql-${stamp}.sql.gz"
    else
      rm -f "$dest/mysql-${stamp}.sql.gz"
      fail "mysqldump 失败 —— 手工试: mysqldump --defaults-extra-file=<文件> $db"
    fi
  else
    warn "没有 mysqldump —— 跳过 MySQL 备份"
  fi
  rm -f "$defaults"

  log "2/3 Redis 快照"
  if have_cmd redis-cli; then
    local rc=(redis-cli -h "$host" -p "$(cfg REDIS_PORT 6379)")
    [[ -n "$(cfg REDIS_PASSWORD)" ]] && rc+=(-a "$(cfg REDIS_PASSWORD)" --no-auth-warning)
    "${rc[@]}" save >/dev/null 2>&1 || warn "redis save 没成功"
    "${rc[@]}" --rdb "$dest/redis-${stamp}.rdb" >/dev/null 2>&1 \
      && ok "Redis -> $dest/redis-${stamp}.rdb" \
      || warn "redis --rdb 导出失败"
  else
    warn "没有 redis-cli —— 跳过 Redis 备份"
  fi

  log "3/3 配置"
  cp -f "$ENV_FILE" "$dest/env-${stamp}.txt"
  chmod 600 "$dest/env-${stamp}.txt"
  cp -f "$RUNTIME_DIR/config/backend.env" "$dest/backend-${stamp}.env" 2>/dev/null || true
  ok "配置 -> $dest/env-${stamp}.txt"

  find "$dest" -type f -mtime +14 -name '*testmate*' -delete 2>/dev/null || true
  echo
  ok "备份完成: $dest"
  ls -lh "$dest"/*"${stamp}"* 2>/dev/null || true
}

cmd_restore() {
  local src="$1"
  [[ -n "$src" ]] || die "用法: $0 restore <备份目录或文件前缀>"
  need_root
  confirm "这会**覆盖**现有数据, 确定?" || die "已中止"

  local myfile redisfile
  myfile="$(ls -1 "$src"/mysql-*.sql.gz 2>/dev/null | tail -1 || true)"
  redisfile="$(ls -1 "$src"/redis-*.rdb 2>/dev/null | tail -1 || true)"
  [[ -n "$myfile" ]] || die "在 $src 里找不到 mysql-*.sql.gz"

  log "停服务"
  systemctl stop "$FRONTEND_UNIT" "$BACKEND_UNIT"

  log "恢复 MySQL"
  local mycli host port db user pass
  mycli="$(mysql_client_cmd)"
  host="$(cfg MYSQL_HOST 127.0.0.1)"
  port="$(cfg MYSQL_PORT 3306)"
  db="$(cfg MYSQL_DATABASE testmate)"
  user="$(cfg MYSQL_USER testmate)"
  pass="$(cfg MYSQL_PASSWORD)"
  # 口令走 defaults 文件, 不进命令行
  local defaults
  defaults="$(mktemp)"; chmod 600 "$defaults"
  printf '[client]\nuser=%s\npassword=%s\nhost=%s\nport=%s\n' \
    "$user" "$pass" "$host" "$port" > "$defaults"
  if gunzip -c "$myfile" | "$mycli" --defaults-extra-file="$defaults" "$db"; then
    ok "MySQL 恢复完成"
  else
    rm -f "$defaults"
    die "MySQL 恢复失败"
  fi
  rm -f "$defaults"

  log "恢复 Redis"
  if [[ -n "$redisfile" ]] && have_cmd redis-cli; then
    local rc=(redis-cli -h "$host" -p "$(cfg REDIS_PORT 6379)")
    [[ -n "$(cfg REDIS_PASSWORD)" ]] && rc+=(-a "$(cfg REDIS_PASSWORD)" --no-auth-warning)
    "${rc[@]}" FLUSHALL >/dev/null 2>&1 || true
    "${rc[@]}" --pipe < "$redisfile" >/dev/null 2>&1 && ok "Redis 恢复完成" || warn "Redis 恢复失败 (不影响主流程)"
  fi

  log "起服务"
  systemctl start "$BACKEND_UNIT" "$FRONTEND_UNIT"
  wait_healthy
  ok "恢复完成"
}

cmd_doctor() {
  need_systemd
  echo "${C_BOLD}TestMate 深度排障${C_OFF}"
  echo

  echo "── 1. 服务状态 ──"
  cmd_status

  echo
  echo "── 2. 最近的错误日志 ──"
  journalctl -u "$BACKEND_UNIT" -p err -n 20 --no-pager 2>/dev/null | sed 's/^/  /' || true
  journalctl -u "$FRONTEND_UNIT" -p err -n 10 --no-pager 2>/dev/null | sed 's/^/  /' || true

  echo
  echo "── 3. 配置一致性 ──"
  local be_port fe_port be_env
  be_port="$(cfg BACKEND_PORT 8000)"
  fe_port="$(cfg FRONTEND_PORT 8080)"
  be_env="$RUNTIME_DIR/config/backend.env"
  if [[ -f "$be_env" ]]; then
    local env_port
    env_port="$(env_get "$be_env" "PORT" || echo '?')"
    [[ "$env_port" == "$be_port" ]] \
      && ok "端口一致 (backend.env PORT=$env_port)" \
      || fail "端口不一致 —— .env 是 $be_port, backend.env 是 $env_port (重跑 install)"
    if grep -q "^MYSQL_PASSWORD=." "$be_env"; then
      ok "后端环境文件带 MySQL 口令"
    else
      fail "后端环境文件缺 MYSQL_PASSWORD"
    fi
  else
    fail "后端环境文件不存在: $be_env (重跑 install)"
  fi
  if [[ -f "$RUNTIME_DIR/config/nginx.conf" ]]; then
    grep -q "listen ${fe_port};" "$RUNTIME_DIR/config/nginx.conf" \
      && ok "nginx 监听端口一致 ($fe_port)" \
      || fail "nginx 监听端口跟 .env 对不上"
  else
    fail "nginx 配置不存在"
  fi

  echo
  echo "── 4. 数据库版本 ──"
  local mycli
  mycli="$(mysql_client_cmd)"
  if [[ -n "$mycli" ]]; then
    local rev
    local defaults
    defaults="$(mktemp)"; chmod 600 "$defaults"
    printf '[client]\nuser=%s\npassword=%s\nhost=%s\nport=%s\n' \
      "$(cfg MYSQL_USER testmate)" "$(cfg MYSQL_PASSWORD)" \
      "$(cfg MYSQL_HOST 127.0.0.1)" "$(cfg MYSQL_PORT 3306)" > "$defaults"
    rev="$("$mycli" --defaults-extra-file="$defaults" -N -B \
          -e "SELECT version_num FROM alembic_version LIMIT 1" \
          "$(cfg MYSQL_DATABASE testmate)" 2>/dev/null || true)"
    rm -f "$defaults"
    if [[ -n "$rev" ]]; then
      ok "alembic 版本: $rev"
    else
      warn "读不到 alembic_version —— 表还没建 (后端没起过?)"
    fi
  fi

  echo
  echo "── 5. 资源 ──"
  echo "  磁盘: $(df -h "$REPO_ROOT" 2>/dev/null | awk 'NR==2 {print $4" 可用 / "$2}')"
  echo "  内存: $(free -h 2>/dev/null | awk '/^Mem:/ {print $7" 可用 / "$2}')"
  if [[ -d "$RUNTIME_DIR/logs" ]]; then
    echo "  日志: $(du -sh "$RUNTIME_DIR/logs" 2>/dev/null | cut -f1)"
  fi
  echo
  echo "提示: 更细的日志用 $0 logs -f"
}

cmd_admin() {
  local user="" pass="" role="admin" pwfile=""
  while [[ $# -gt 0 ]]; do
    case "$1" in
      --username) user="$2"; shift 2 ;;
      --password) pass="$2"; shift 2 ;;
      --password-file) pwfile="$2"; shift 2 ;;
      --role) role="$2"; shift 2 ;;
      *) die "未知参数: $1" ;;
    esac
  done
  user="${user:-$(cfg ADMIN_DEFAULT_USER admin)}"

  local venv="$RUNTIME_DIR/venv/bin/python"
  [[ -x "$venv" ]] || die "venv 没建好 —— 先跑 $0 install"

  local pf="" tmp_pf=0
  if [[ -n "$pwfile" ]]; then
    pf="$pwfile"
  elif [[ -n "$pass" ]]; then
    pf="$(mktemp)"; chmod 600 "$pf"; printf '%s' "$pass" > "$pf"; tmp_pf=1
  else
    pf="$(mktemp)"; chmod 600 "$pf"; printf '%s' "$(cfg ADMIN_DEFAULT_PASSWORD)" > "$pf"; tmp_pf=1
  fi

  set +e
  (cd "$REPO_ROOT" && "$venv" "$REPO_ROOT/scripts/create_admin.py" \
     --env-file "$ENV_FILE" --username "$user" --password-file "$pf" --role "$role")
  local admin_rc=$?
  set -e
  [[ $tmp_pf -eq 1 ]] && rm -f "$pf"
  return $admin_rc
}

cmd_uninstall() {
  need_root
  confirm "卸载会停服务并删掉 systemd 单元 (数据默认保留), 确定?" || die "已中止"
  systemctl stop "$FRONTEND_UNIT" "$BACKEND_UNIT" 2>/dev/null || true
  systemctl disable "$FRONTEND_UNIT" "$BACKEND_UNIT" 2>/dev/null || true
  rm -f "$UNIT_DIR/${BACKEND_UNIT}.service" "$UNIT_DIR/${FRONTEND_UNIT}.service"
  systemctl daemon-reload
  systemctl reset-failed 2>/dev/null || true
  ok "已卸载 (数据留在 $RUNTIME_DIR, 要删自己 rm -rf)"
  echo "  手动清理: rm -rf $RUNTIME_DIR && rm -f $ENV_FILE"
}

# ==================== 分发 ====================
case "$ACTION" in
  check)    cmd_check ;;
  install)  cmd_install ;;
  start)    cmd_start ;;
  stop)     cmd_stop ;;
  restart)  cmd_restart ;;
  reload)   cmd_reload ;;
  status)   cmd_status ;;
  logs)     cmd_logs ${REST[@]+"${REST[@]}"} ;;
  enable)   cmd_enable ;;
  disable)  cmd_disable ;;
  update)   cmd_update ;;
  backup)   cmd_backup ${REST[@]+"${REST[@]}"} ;;
  restore)  cmd_restore ${REST[@]+"${REST[@]}"} ;;
  doctor)   cmd_doctor ;;
  admin)    cmd_admin ${REST[@]+"${REST[@]}"} ;;
  uninstall) cmd_uninstall ;;
  help|-h|--help) usage ;;
  *)        die "未知命令: $ACTION (用 --help 看用法)" ;;
esac
