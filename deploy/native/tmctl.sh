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
#   logs        看日志
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
# 驱动 (自动选, 有 systemd 用 systemd, 没有用 local):
#   local <命令>        强制走 local driver (PID 文件管进程, mac 用)
#   launchd install     macOS: 装 launchd (开机自启 + 崩溃自愈)
#   launchd uninstall   macOS: 卸载 launchd
#   launchd status      macOS: 看 launchd 状态
#   local hosts check   macOS: 看 host.docker.internal 在宿主上通不通
#   local hosts fix     macOS: 往宿主 /etc/hosts 加映射 (代码检视 / 市场推送要用)
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

# 驱动: systemd (Linux) / local (mac 等无 init 系统的机器)
# 自动选 —— 有 systemd 走 systemd, 没有走 local.
# 运维不用记两套命令: `tmctl.sh start` 在哪台机器上都对.
DRIVER=""

detect_driver() {
  if systemd_available; then
    DRIVER="systemd"
  else
    DRIVER="local"
  fi
}

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
  admin|backup|restore|logs|local|launchd) CMD_TAKES_ARGS="yes" ;;
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

# ---- 前缀处理 ----
# `local <命令>`   强制走 local driver (mac 等没有 systemd 的机器)
# `launchd <命令>` launchd 管理 (mac 开机自启 + 崩溃自愈)
if [[ "$ACTION" == "local" ]]; then
  DRIVER="local"
  ACTION="${REST[0]:-help}"
  if [[ ${#REST[@]} -gt 0 ]]; then REST=("${REST[@]:1}"); else REST=(); fi
fi

detect_driver
if [[ "$ACTION" == "launchd" ]]; then
  # launchd 是 mac 专属, 不走 driver 分派
  DRIVER="launchd"
fi

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
  # ⚠️ macOS 的 homebrew nginx 路径跟 Linux 不一样, 漏了会退化到内置最小版
  for c in /etc/nginx/mime.types \
           /usr/local/nginx/conf/mime.types \
           /usr/share/nginx/mime.types \
           /opt/homebrew/etc/nginx/mime.types \
           /usr/local/etc/nginx/mime.types; do
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
  # ⚠️ admin 口令**不要**在这里打印 —— 复用 Docker 模式的数据库时, 它会被换成
  #    deploy/.env 里那个 (不改现有 admin 的密码). 提前打印等于骗人.
  #    最终口令在 install 收尾时统一打印.
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

# ---- 生成应用配置 (backend.env + nginx.conf) ----
# systemd 与 local 两种 driver **共用这一份** —— 差别只在"谁来起进程".
render_app_configs() {
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

# 往 backend.env 写一行 —— ⚠️ 值里有空格就必须加引号
#    (`APP_NAME=TestMate Gateway` 不加引号, 被 bash source 时会把 Gateway 当命令执行)
emit_env() {
  local k="$1" v="$2"
  case "$v" in
    *[[:space:]]*|*'"'*|*"'"*)
      printf '%s="%s"\n' "$k" "$v" ;;
    *)
      printf '%s=%s\n' "$k" "$v" ;;
  esac
}

# ---- backend.env ----
  log "生成后端环境文件: $backend_env"
  {
    echo "# TestMate 后端环境变量 —— 由 tmctl.sh install 生成, 勿手改"
    echo "# 改了配置记得重跑 install (或 systemctl restart $BACKEND_UNIT)"
    echo
    emit_env APP_NAME "TestMate Gateway"
    emit_env APP_VERSION "0.1.0"
    emit_env DEBUG "false"
    emit_env HOST "$bind_addr"
    emit_env PORT "$be_port"
    emit_env TZ "$(cfg TIMEZONE Asia/Shanghai)"
    echo
    emit_env JWT_SECRET "$(cfg JWT_SECRET)"
    emit_env JWT_EXPIRE_MINUTES "$(cfg JWT_EXPIRE_MINUTES 10080)"
    emit_env AUTH_EMAIL_DOMAIN "$(cfg AUTH_EMAIL_DOMAIN @twsc.com.cn)"
    echo
    emit_env MYSQL_HOST "$(cfg MYSQL_HOST 127.0.0.1)"
    emit_env MYSQL_PORT "$(cfg MYSQL_PORT 3306)"
    emit_env MYSQL_USER "$(cfg MYSQL_USER testmate)"
    emit_env MYSQL_PASSWORD "$(cfg MYSQL_PASSWORD)"
    emit_env MYSQL_DATABASE "$(cfg MYSQL_DATABASE testmate)"
    echo
    emit_env REDIS_HOST "$(cfg REDIS_HOST 127.0.0.1)"
    emit_env REDIS_PORT "$(cfg REDIS_PORT 6379)"
    emit_env REDIS_DB "$(cfg REDIS_DB 0)"
    [[ -n "$(cfg REDIS_PASSWORD)" ]] && emit_env REDIS_PASSWORD "$(cfg REDIS_PASSWORD)"
    echo
    emit_env CORS_ORIGINS "[\"http://localhost:${fe_port}\",\"http://127.0.0.1:${fe_port}\"]"
    echo
    emit_env MARKET_WORKSPACE "$(cfg MARKET_DIR "$runtime/market")"
    emit_env MARKET_GIT_REMOTE "$(cfg MARKET_GIT_REMOTE)"
    emit_env MARKET_GIT_BRANCH "$(cfg MARKET_GIT_BRANCH main)"
    emit_env MARKET_SYNC_INTERVAL_SECONDS "$(cfg MARKET_SYNC_INTERVAL_SECONDS 30)"
    if [[ -f "$runtime/ssh/id_ed25519" ]]; then
      emit_env GIT_SSH_COMMAND "ssh -i $runtime/ssh/id_ed25519 -o IdentitiesOnly=yes -o StrictHostKeyChecking=accept-new -o UserKnownHostsFile=$runtime/ssh/known_hosts -o BatchMode=yes"
    fi
    echo
    emit_env RAGFLOW_BASE_URL "$(cfg RAGFLOW_BASE_URL)"
    emit_env RAGFLOW_API_KEY "$(cfg RAGFLOW_API_KEY)"
    emit_env REVIEW_AGENT_BASE_URL "$(cfg REVIEW_AGENT_BASE_URL)"
    emit_env REVIEW_AGENT_API_TOKEN "$(cfg REVIEW_AGENT_API_TOKEN)"
    emit_env DINGTALK_DEFAULT_WEBHOOK "$(cfg DINGTALK_DEFAULT_WEBHOOK)"
    emit_env ADMIN_DEFAULT_PASSWORD "$(cfg ADMIN_DEFAULT_PASSWORD)"
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
}

# ---- 生成 systemd 单元 (只有 systemd driver 用得到) ----
render_systemd_configs() {
  local runtime run_user run_group be_port bind_addr workers
  local backend_env nginx_conf nginx_prefix nginx_bin market_dir
  runtime="$RUNTIME_DIR"
  run_user="$(cfg RUN_USER testmate)"
  run_group="$(cfg RUN_GROUP "$run_user")"
  be_port="$(cfg BACKEND_PORT 8000)"
  bind_addr="$(cfg BIND_ADDR 127.0.0.1)"
  workers="$(cfg BACKEND_WORKERS 1)"
  backend_env="$runtime/config/backend.env"
  nginx_conf="$runtime/config/nginx.conf"
  nginx_prefix="$runtime"
  nginx_bin="$(command -v nginx || echo /usr/sbin/nginx)"
  market_dir="$(cfg MARKET_DIR "$runtime/market")"

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

# 前端到底是不是**我们的** nginx 应答的?
# ⚠️ 光看"有没有响应"不够 —— 端口上可能还绑着**别的**服务, 而且绑的是更具体的地址
#    (127.0.0.1:x 优先于 0.0.0.0:x). 那时请求全被对方接走,
#    我们的 nginx 看起来"起来了", 实际一个请求都收不到 —— 端口是通的, 页面却是别人的.
verify_frontend() {
  local fe_port="$1"
  local hdr
  hdr="$(curl -sS -o /dev/null -D - --max-time 5 "http://127.0.0.1:${fe_port}/" 2>/dev/null | tr -d '\r')"
  if [[ -z "$hdr" ]]; then
    warn "前端没响应 —— 看日志: $0 logs $FRONTEND_UNIT"
    return 1
  fi
  local server
  server="$(printf '%s' "$hdr" | grep -i '^server:' | head -1 | cut -d' ' -f2-)"
  if [[ "$server" != "nginx" ]]; then
    fail "端口 $fe_port 被**别的服务**占着 (应答来自: ${server:-未知服务})"
    echo "      对方绑的是 127.0.0.1:$fe_port, 我们的是 0.0.0.0:$fe_port ——"
    echo "      更具体的绑定优先, 所以请求全被对方接走, 我们的 nginx 一个都收不到."
    echo "      换端口: 改 deploy/native/.env 的 FRONTEND_PORT, 然后重跑 install"
    return 1
  fi
  ok "前端已响应 (nginx)"
  return 0
}

# 从 start 起找一个空闲端口
pick_free_port() {
  local start="$1" count="${2:-30}" p
  for (( p=start; p<start+count; p++ )); do
    port_in_use "$p" || { printf '%s' "$p"; return 0; }
  done
  return 1
}

# 端口冲突时自动换一个空闲的 (让 install 真正做到"一键")
# 占着这个端口的**是不是我们自己起的服务**?
# ⚠️ 不看这个的话, 服务在跑的时候重跑 install 会把自己的端口当成"被别人占了",
#    自动跳到下一个端口 —— 用户会发现"我啥也没改, 端口怎么变了".
port_is_own_service() {
  local port="$1" pid own p
  pid="$(port_owner_pid "$port")"
  [[ -n "$pid" ]] || return 1
  for own in backend frontend; do
    p="$(local_pid "$own" 2>/dev/null || true)"
    [[ -n "$p" && "$p" == "$pid" ]] && return 0
    p="$(launchd_pid "com.testmate.$own" 2>/dev/null || true)"
    [[ -n "$p" && "$p" == "$pid" ]] && return 0
  done
  return 1
}

resolve_port_conflicts() {
  local fe_port be_port np
  fe_port="$(cfg FRONTEND_PORT 8080)"
  be_port="$(cfg BACKEND_PORT 8000)"

  if port_in_use "$fe_port"; then
    if port_is_own_service "$fe_port"; then
      ok "前端端口 $fe_port 已经是本服务在用 —— 保持不变"
    elif np="$(pick_free_port "$fe_port")"; then
      warn "前端端口 $fe_port 被占用 —— 自动改用 $np"
      env_set "$ENV_FILE" "FRONTEND_PORT" "$np"
      echo "      (占用者: $(port_owner "$fe_port"); 固定下来改 .env 的 FRONTEND_PORT)"
    else
      die "前端端口 $fe_port 被占用, 且往后 30 个端口都占着 —— 手工改 .env 的 FRONTEND_PORT"
    fi
  fi

  if port_in_use "$be_port"; then
    if port_is_own_service "$be_port"; then
      ok "后端端口 $be_port 已经是本服务在用 —— 保持不变"
    elif np="$(pick_free_port "$be_port")"; then
      warn "后端端口 $be_port 被占用 —— 自动改用 $np"
      env_set "$ENV_FILE" "BACKEND_PORT" "$np"
      echo "      (占用者: $(port_owner "$be_port"))"
    else
      die "后端端口 $be_port 被占用, 且往后 30 个端口都占着 —— 手工改 .env 的 BACKEND_PORT"
    fi
  fi
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

  verify_frontend "$fe_port"
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

# ==================== local driver (mac / 无 init 系统) ====================
#
# macOS 没有 systemd, 但"本地部署"照样能做:
#   · 进程管理 = PID 文件 + nohup (local_spawn / local_kill)
#   · 开机自启 + 崩溃自愈 = launchd (见 launchd_* 函数)
#
# 与 systemd driver 的差别**只有一层**: 怎么起进程、怎么停进程.
# 配置 / venv / 构建 / 健康检查 / doctor / backup 全部共用.

# 把 backend.env 里的变量导出到当前 shell (起进程前调用)
# ⚠️ **不 source 整个文件** —— source 的话 bash 会拿文件内容当脚本解析,
#    任何没加引号的空格都会变成"命令找不到"(踩过: APP_NAME=TestMate Gateway).
#    自己逐行解析 + export, 语义清楚且不会误伤.
local_env_export() {
  local f="$RUNTIME_DIR/config/backend.env"
  [[ -f "$f" ]] || return 0
  local line k v
  while IFS= read -r line || [[ -n "$line" ]]; do
    case "$line" in
      ''|'#'*) continue ;;
    esac
    [[ "$line" == *=* ]] || continue
    k="${line%%=*}"
    v="${line#*=}"
    k="$(printf '%s' "$k" | tr -d '[:space:]')"
    [[ -z "$k" ]] && continue
    # 去首尾空白 + 去成对引号
    v="$(printf '%s' "$v" | sed -e 's/^[[:space:]]*//' -e 's/[[:space:]]*$//' -e 's/^"//' -e 's/"$//' -e "s/^'//" -e "s/'$//")"
    export "$k=$v"
  done < "$f"
}

local_nginx_bin() { command -v nginx || echo /usr/local/bin/nginx; }

# 起后端
local_start_backend() {
  local venv="$RUNTIME_DIR/venv/bin/uvicorn"
  if [[ ! -x "$venv" ]]; then
    warn "venv 没建好 —— 先跑: $0 local install"
    return 1
  fi
  local be_port bind workers
  be_port="$(cfg BACKEND_PORT 8000)"
  bind="$(cfg BIND_ADDR 127.0.0.1)"
  workers="$(cfg BACKEND_WORKERS 1)"
  local_env_export
  # shellcheck disable=SC2086
  local_spawn backend "$REPO_ROOT/backend_gateway" \
    "$venv" app.main:app --host "$bind" --port "$be_port" --workers "$workers" \
    --proxy-headers --forwarded-allow-ips=127.0.0.1
}

# 起前端 (nginx 独立实例, 前台跑 —— 这样 PID 文件管得住它)
local_start_frontend() {
  local nginx_bin conf prefix fe_port
  nginx_bin="$(local_nginx_bin)"
  conf="$RUNTIME_DIR/config/nginx.conf"
  prefix="$RUNTIME_DIR"
  fe_port="$(cfg FRONTEND_PORT 8080)"
  if [[ ! -x "$nginx_bin" ]]; then
    warn "没找到 nginx —— 装: brew install nginx   (Linux: apt install nginx / dnf install nginx)"
    return 1
  fi
  if [[ ! -f "$conf" ]]; then
    warn "nginx 配置不存在 —— 先跑: $0 local install"
    return 1
  fi
  # 配置有错就别起了, 不然报一堆看不懂的
  if ! "$nginx_bin" -t -c "$conf" -p "$prefix" >/dev/null 2>&1; then
    fail "nginx 配置有错:"
    "$nginx_bin" -t -c "$conf" -p "$prefix" 2>&1 | sed 's/^/      /'
    return 1
  fi
  mkdir -p "$RUNTIME_DIR"/{run,logs} "$RUNTIME_DIR"/{client_temp,proxy_temp,fastcgi_temp,uwsgi_temp,scgi_temp}
  # ⚠️ `-g "daemon off;"` —— 必须前台跑. 后台模式下 nginx 会 fork 完就退出,
  #    我们拿到的 PID 是那个已退出的父进程, 之后 stop 停不掉真的 nginx.
  local_spawn frontend "$RUNTIME_DIR" \
    "$nginx_bin" -c "$conf" -p "$prefix" -g "daemon off;"
}

# Docker 模式的 backend 也在跑的话, 提醒一下 —— 两个后端会互相抢 job
warn_concurrent_backend() {
  local compose_file="$REPO_ROOT/deploy/docker-compose.yml"
  local deploy_env="$REPO_ROOT/deploy/.env"
  [[ -f "$compose_file" && -f "$deploy_env" ]] || return 0
  have_cmd docker || return 0
  local cid running
  cid="$(docker compose -f "$compose_file" --env-file "$deploy_env" ps -q backend 2>/dev/null || true)"
  [[ -n "$cid" ]] || return 0
  running="$(docker inspect -f '{{.State.Running}}' "$cid" 2>/dev/null || echo false)"
  [[ "$running" == "true" ]] || return 0
  warn "⚠️ Docker 模式的 backend 容器也在跑 —— 两个后端会**同时**消费资产市场的 job 队列"
  warn "   (队列是进程内的, 不跨进程) → 同一个 job 被两个进程抢 → git index.lock 冲突 / 重复推 GitLab."
  warn "   建议先停它:  cd deploy && docker compose --env-file .env stop backend"
  warn "   (mysql/redis 容器别停 —— 本地模式要连它们)"
  echo
}

# Docker 模式的 frontend 容器还在跑, 但它的 backend 停了 → 那个端口的接口全是 502.
#
# ⚠️ 这个状态特别有迷惑性: 页面能打开 (静态文件在容器里), 但所有接口 502
#    (nginx 代理不到已经停掉的 backend) —— 看起来像"平台坏了", 实际是端口用错了.
#    本地模式下 Docker 的 backend **必须**停 (两个后端不能同时跑), 所以要提醒.
warn_docker_frontend() {
  local compose_file="$REPO_ROOT/deploy/docker-compose.yml"
  local deploy_env="$REPO_ROOT/deploy/.env"
  [[ -f "$compose_file" && -f "$deploy_env" ]] || return 0
  have_cmd docker || return 0

  local fe_cid fe_running be_cid be_running fe_port local_port
  fe_cid="$(docker compose -f "$compose_file" --env-file "$deploy_env" ps -q frontend 2>/dev/null || true)"
  [[ -n "$fe_cid" ]] || return 0
  fe_running="$(docker inspect -f '{{.State.Running}}' "$fe_cid" 2>/dev/null || echo false)"
  [[ "$fe_running" == "true" ]] || return 0

  # backend 也在跑 → Docker 模式是完整的一套, 不用管
  be_cid="$(docker compose -f "$compose_file" --env-file "$deploy_env" ps -q backend 2>/dev/null || true)"
  if [[ -n "$be_cid" ]]; then
    be_running="$(docker inspect -f '{{.State.Running}}' "$be_cid" 2>/dev/null || echo false)"
    [[ "$be_running" == "true" ]] && return 0
  fi

  fe_port="$(env_get "$deploy_env" "FRONTEND_HOST_PORT" || echo 8080)"
  local_port="$(cfg FRONTEND_PORT 8080)"
  warn "⚠️ Docker 模式的 frontend 容器还在跑 (端口 $fe_port), 但它的 backend 容器没在跑"
  warn "   → 那个地址的**页面能打开, 但所有接口都是 502** (nginx 代理不到后端), 看着像平台坏了"
  warn "   本地模式的入口是: http://localhost:$local_port"
  warn "   想让 $fe_port 那个端口也别报错, 停掉它:"
  warn "     cd deploy && docker compose --env-file .env stop frontend"
  echo
}

# 服务是不是由 launchd 接管了
local_launchd_loaded() {
  launchd_loaded "com.testmate.backend" 2>/dev/null && return 0
  launchd_loaded "com.testmate.frontend" 2>/dev/null && return 0
  return 1
}

# ---- Docker 专用主机名 (local driver 专属) ----
#
# 背景见 lib.sh 的说明: `host.docker.internal` 是**容器里**访问宿主用的名字.
# 本地部署的进程跑在**宿主**上, 同一个名字在宿主上连不通 —— 于是代码检视连不上、
# 资产市场推不到 GitLab、设置页里填的这类地址也全连不上.
#
# 解法: 宿主的 /etc/hosts 里让它指回 127.0.0.1. 容器不受影响 (容器有自己的 hosts).
hosts_do_check() {
  local name broken=0 cur
  echo "${C_BOLD}宿主名解析${C_OFF}  ${C_BLUE}(local driver —— 进程跑在宿主上)${C_OFF}"
  echo
  for name in "${DOCKER_HOST_ALIASES[@]}"; do
    if host_alias_broken "$name"; then
      broken=1
      cur="$(resolve_host_ips "$name" | tr '\n' ' ')"
      [[ -z "$cur" ]] && cur="(解析不到)"
      printf "    %-26s %b %s  → %s\n" "$name" "${C_RED}✗${C_OFF}" "不通" "$cur"
    else
      printf "    %-26s %b %s\n" "$name" "${C_GREEN}✓${C_OFF}" "正常 (指回 127.0.0.1)"
    fi
  done
  echo
  if [[ $broken -eq 1 ]]; then
    warn "这些名字是**容器里**访问宿主用的 —— 本地部署的进程在宿主上, 用它们连不通."
    echo "    后果: 代码检视连不上 / 资产市场推不到 GitLab / 设置页里填的这类地址都连不上"
    echo
    echo "    修 (只改宿主的 /etc/hosts, 容器不受影响):"
    echo "      sudo $0 local hosts fix"
    echo
    return 1
  fi
  ok "没问题 —— 容器里的地址在宿主上也能用"
  return 0
}

hosts_do_fix() {
  local name bak hosts_file="${HOSTS_FILE:-/etc/hosts}"
  local -a need=()
  for name in "${DOCKER_HOST_ALIASES[@]}"; do
    host_alias_broken "$name" && need+=("$name")
  done
  if [[ ${#need[@]} -eq 0 ]]; then
    ok "不用改 —— 这些名字在宿主上已经指回 127.0.0.1 了"
    return 0
  fi

  have_cmd sudo || { fail "没有 sudo 命令 —— 请手工编辑 $hosts_file, 加这几行:"; printf '127.0.0.1 %s\n' "${need[@]}"; return 1; }

  log "往 $hosts_file 里加 ${#need[@]} 条映射 (需要 sudo)"

  # 先备份 —— hosts 文件是系统文件, 改坏了得能退回去
  mkdir -p "$RUNTIME_DIR"
  bak="$RUNTIME_DIR/hosts.backup.$(date +%Y%m%d-%H%M%S)"
  sudo cp "$hosts_file" "$bak" || { fail "备份 $hosts_file 失败 (权限?)"; return 1; }
  ok "已备份: $bak"

  hosts_aliases_block "${need[@]}" | sudo tee -a "$hosts_file" >/dev/null || { fail "写 $hosts_file 失败"; return 1; }

  ok "已写入 /etc/hosts"
  echo

  # 验证 —— 有些系统有 DNS 缓存, 写完不一定立刻生效
  local fix_failed=0
  for name in "${need[@]}"; do
    if host_alias_broken "$name"; then
      fail "$name 仍不通 —— 清一下 DNS 缓存再试: sudo dscacheutil -flushcache (macOS) / sudo systemd-resolve --flush-caches (Linux)"
      fix_failed=1
    else
      ok "$name 已指回 127.0.0.1"
    fi
  done
  return $fix_failed
}

cmd_hosts() {
  case "${REST[0]:-check}" in
    check) hosts_do_check ;;
    fix)   hosts_do_fix ;;
    *) die "hosts 子命令: check | fix" ;;
  esac
}

local_do_start() {
  # 两条路径都要提醒 (launchd 接管 / PID 模式) —— 端口用错是本地部署最容易踩的坑
  warn_docker_frontend
  if local_launchd_loaded; then
    log "服务由 launchd 接管 —— 已经在跑了"
    wait_healthy
    return 0
  fi
  log "启动服务 (local driver · PID 文件)"
  warn_concurrent_backend
  local_start_backend || return 1
  local_start_frontend || return 1
  wait_healthy
}

local_do_stop() {
  if local_launchd_loaded; then
    # launchd 的 RunAtLoad + KeepAlive 服务**没法"暂停"** —— 停了它就立刻被拉回来.
    # 所以"停" = 卸载 (bootout), 开机自启也一并没了; 要恢复: $0 launchd install
    log "服务由 launchd 接管 —— 用 launchctl 卸载来停"
    echo "  (RunAtLoad+KeepAlive 的服务停不掉只能卸载; 恢复自启: $0 launchd install)"
    launchd_unload "com.testmate.frontend" >/dev/null 2>&1 || true
    launchd_unload "com.testmate.backend" >/dev/null 2>&1 || true
    ok "已停止 (launchd 已卸载, 开机自启一并取消)"
    return 0
  fi
  log "停止服务 (local driver · PID 文件)"
  local_kill frontend
  local_kill backend
  ok "已停止 (数据保留)"
}

local_do_restart() {
  if local_launchd_loaded; then
    log "重启服务 (launchd)"
    launchctl kickstart -k "$(launchd_domain)/com.testmate.backend" >/dev/null 2>&1 || true
    launchctl kickstart -k "$(launchd_domain)/com.testmate.frontend" >/dev/null 2>&1 || true
    wait_healthy
    return 0
  fi
  local_do_stop
  local_do_start
}

local_do_status() {
  local be_port fe_port
  be_port="$(cfg BACKEND_PORT 8000)"
  fe_port="$(cfg FRONTEND_PORT 8080)"

  local driver_label="local driver · PID 文件"
  local_launchd_loaded && driver_label="local driver · launchd 接管"
  echo "${C_BOLD}TestMate 服务状态${C_OFF}  ${C_BLUE}(${driver_label})${C_OFF}"
  echo
  echo "  进程:"
  local n pid
  for n in backend frontend; do
    if local_launchd_loaded; then
      # launchd 接管时 PID 文件是陈旧的 —— 看 launchd 自己的状态
      pid="$(launchd_pid "com.testmate.$n")"
      if [[ -n "$pid" ]]; then
        printf "    %-12s %b %s (PID %s)\n" "$n" "${C_GREEN}✓${C_OFF}" "运行中" "$pid"
      else
        printf "    %-12s %b %s\n" "$n" "${C_YELLOW}!${C_OFF}" "launchd 已装载但进程没在跑"
      fi
    elif pid="$(local_pid "$n")"; then
      printf "    %-12s %b %s (PID %s)\n" "$n" "${C_GREEN}✓${C_OFF}" "运行中" "$pid"
    else
      printf "    %-12s %b %s\n" "$n" "${C_RED}✗${C_OFF}" "没跑"
    fi
  done

  echo
  echo "  端口:"
  local p
  for p in "$fe_port:前端(nginx)" "$be_port:后端(uvicorn)"; do
    local port="${p%%:*}" label="${p##*:}"
    if port_in_use "$port"; then
      printf "    %-20s %b %s (监听中)\n" "$label" "${C_GREEN}✓${C_OFF}" "$port"
    else
      printf "    %-20s %b %s (没监听)\n" "$label" "${C_RED}✗${C_OFF}" "$port"
    fi
  done

  # Docker 的 frontend 容器还在跑 → 那个端口的页面能开, 但接口全 502.
  # 不说的话用户一定会去访问那个地址, 然后以为平台坏了.
  echo
  warn_docker_frontend

  echo
  echo "  健康检查:"
  if curl -fsS --max-time 5 "http://127.0.0.1:${be_port}/api/v1/health" >/dev/null 2>&1; then
    ok "backend liveness: OK"
  else
    fail "backend liveness: 不通"
  fi
  if curl -fsS --max-time 5 "http://127.0.0.1:${be_port}/api/v1/health/ready" >/dev/null 2>&1; then
    ok "backend readiness: OK (MySQL/Redis 全通)"
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
  echo "  launchd (开机自启):"
  if [[ "$(uname -s)" != "Darwin" ]]; then
    echo "    (非 macOS, 开机自启走 systemd)"
  elif launchd_loaded "com.testmate.backend"; then
    ok "com.testmate.backend: 已装载"
    launchd_loaded "com.testmate.frontend" \
      && ok "com.testmate.frontend: 已装载" \
      || warn "com.testmate.frontend: 没装载"
  else
    echo "    没装 launchd —— 要开机自启 + 崩溃自愈: $0 launchd install"
  fi

  echo
  echo "  宿主名解析 (代码检视 / 资产市场推送要用):"
  local alias
  for alias in "${DOCKER_HOST_ALIASES[@]}"; do
    if host_alias_broken "$alias"; then
      printf "    %-26s %b %s\n" "$alias" "${C_RED}✗${C_OFF}" "不通 (修: sudo $0 local hosts fix)"
    else
      printf "    %-26s %b %s\n" "$alias" "${C_GREEN}✓${C_OFF}" "正常"
    fi
  done

  echo
  echo "  版本:"
  local rev
  rev="$(cd "$REPO_ROOT" && git rev-parse --short HEAD 2>/dev/null || echo '?')"
  echo "    代码: $rev ($(cd "$REPO_ROOT" && git rev-parse --abbrev-ref HEAD 2>/dev/null || echo '?'))"
}

local_do_logs() {
  local n
  echo "── 后端 ($RUNTIME_DIR/logs/backend.log) ──"
  tail -n 60 "$RUNTIME_DIR/logs/backend.log" 2>/dev/null || echo "  (还没日志)"
  echo
  echo "── 前端 ($RUNTIME_DIR/logs/frontend.log) ──"
  tail -n 40 "$RUNTIME_DIR/logs/frontend.log" 2>/dev/null || echo "  (还没日志)"
  if [[ $OPT_FOLLOW -eq 1 ]]; then
    echo
    echo "── 跟日志 (Ctrl-C 退出) ──"
    tail -f "$RUNTIME_DIR/logs/backend.log" "$RUNTIME_DIR/logs/frontend.log" 2>/dev/null
  fi
}

# mac 上没有 mysql/redis 服务时, 复用 Docker 模式那套 mysql/redis 容器
# —— 好处是**数据是同一份** (同一个 DATA_ROOT 下的卷), 两种模式随时切.
ensure_docker_db() {
  local compose_file="$REPO_ROOT/deploy/docker-compose.yml"
  local deploy_env="$REPO_ROOT/deploy/.env"
  if [[ ! -f "$compose_file" || ! -f "$deploy_env" ]]; then
    return 1
  fi
  have_cmd docker || return 1

  local root_pwd my_port rd_port
  root_pwd="$(env_get "$deploy_env" "MYSQL_ROOT_PASSWORD" || true)"
  my_port="$(env_get "$deploy_env" "MYSQL_HOST_PORT" || true)"; my_port="${my_port:-43060}"
  rd_port="$(env_get "$deploy_env" "REDIS_HOST_PORT" || true)"; rd_port="${rd_port:-63790}"
  [[ -n "$root_pwd" ]] || return 1

  log "复用 Docker 模式的 MySQL/Redis (数据跟 Docker 模式共享)"
  docker compose -f "$compose_file" --env-file "$deploy_env" up -d mysql redis >/dev/null 2>&1 \
    || { warn "起 mysql/redis 容器失败"; return 1; }

  # ⚠️⚠️ 共享数据库 = **必须沿用 Docker 模式的账号和口令**, 不能各用各的 ——
  #    MySQL 的 testmate 用户和 users 表里的 admin 是**同一个**:
  #      · 口令不一样 → 改密码会把 Docker 模式的 backend 顶掉 (它连不上库了)
  #      · admin 口令不一样 → create_admin 会把现有 admin 的密码改掉, 运维当场登不进去
  #    所以这里把凭据一起对齐 —— 两种模式共用同一套账号.
  local d_user d_pass d_db d_admin
  d_user="$(env_get "$deploy_env" "MYSQL_USER" || true)"; d_user="${d_user:-testmate}"
  d_pass="$(env_get "$deploy_env" "MYSQL_PASSWORD" || true)"
  d_db="$(env_get "$deploy_env" "MYSQL_DATABASE" || true)"; d_db="${d_db:-testmate}"
  d_admin="$(env_get "$deploy_env" "ADMIN_DEFAULT_PASSWORD" || true)"
  if [[ -n "$d_pass" ]]; then
    env_set "$ENV_FILE" "MYSQL_USER" "$d_user"
    env_set "$ENV_FILE" "MYSQL_PASSWORD" "$d_pass"
    env_set "$ENV_FILE" "MYSQL_DATABASE" "$d_db"
    ok "沿用 Docker 模式的数据库账号 ($d_user) 与口令 —— 两种模式共用同一套凭据"
  fi
  if [[ -n "$d_admin" ]]; then
    env_set "$ENV_FILE" "ADMIN_DEFAULT_PASSWORD" "$d_admin"
    ok "沿用 Docker 模式的 admin 口令 —— **不会**改动现有 admin 的密码"
  fi

  # 把 native 的 .env 对齐到容器暴露的端口
  env_set "$ENV_FILE" "MYSQL_HOST" "127.0.0.1"
  env_set "$ENV_FILE" "MYSQL_PORT" "$my_port"
  env_set "$ENV_FILE" "REDIS_HOST" "127.0.0.1"
  env_set "$ENV_FILE" "REDIS_PORT" "$rd_port"

  # ⚠️ 资产市场的 git 工作区也要跟 Docker 模式**同一个** ——
  #    两个后端各推各的仓库到同一个 GitLab 远端 → 互相覆盖 / index.lock 冲突.
  #    compose 里容器路径 /workspace 对应宿主 ${DATA_ROOT}/market.
  local data_root market_host
  data_root="$(env_get "$deploy_env" "DATA_ROOT" || true)"
  if [[ -n "$data_root" ]]; then
    market_host="$data_root/market"
    if [[ -d "$market_host" ]]; then
      env_set "$ENV_FILE" "MARKET_DIR" "$market_host"
      ok "资产市场工作区跟 Docker 模式共用: $market_host"
    else
      warn "Docker 模式的市场工作区还没建 ($market_host) —— 本地模式用自己的 runtime/market"
    fi
  fi

  # 等 MySQL 起来
  local i
  for i in $(seq 1 30); do
    if mysql_ping "$my_port" "$root_pwd"; then
      break
    fi
    sleep 1
  done

  # 建库建用户 (口令取 native .env 的 MYSQL_PASSWORD)
  local db user pass pass_sql
  db="$(cfg MYSQL_DATABASE testmate)"
  user="$(cfg MYSQL_USER testmate)"
  pass="$(cfg MYSQL_PASSWORD)"
  pass_sql="$(printf '%s' "$pass" | sed "s/'/''/g")"
  if ! mysql_exec "$my_port" "$root_pwd" <<SQL
CREATE DATABASE IF NOT EXISTS \`${db}\` CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;
CREATE USER IF NOT EXISTS '${user}'@'localhost' IDENTIFIED BY '${pass_sql}';
CREATE USER IF NOT EXISTS '${user}'@'127.0.0.1' IDENTIFIED BY '${pass_sql}';
ALTER USER '${user}'@'localhost' IDENTIFIED BY '${pass_sql}';
ALTER USER '${user}'@'127.0.0.1' IDENTIFIED BY '${pass_sql}';
GRANT ALL PRIVILEGES ON \`${db}\`.* TO '${user}'@'localhost';
GRANT ALL PRIVILEGES ON \`${db}\`.* TO '${user}'@'127.0.0.1';
FLUSH PRIVILEGES;
SQL
  then
    warn "建库建用户失败 —— 手工执行:"
    echo "      CREATE DATABASE IF NOT EXISTS \`${db}\`;"
    echo "      CREATE USER '${user}'@'127.0.0.1' IDENTIFIED BY '<口令>';"
    return 1
  fi
  ok "MySQL 就绪 (127.0.0.1:${my_port}, 库 $db)"
  ok "Redis 就绪 (127.0.0.1:${rd_port})"
  return 0
}

# local 模式的数据库准备: 先试 .env 里的, 连不上再试 Docker, 都没有就报错
ensure_db_local() {
  local host port mycli
  host="$(cfg MYSQL_HOST 127.0.0.1)"
  port="$(cfg MYSQL_PORT 3306)"
  mycli="$(mysql_client_cmd)"

  if [[ -n "$mycli" ]] && "$mycli" -h "$host" -P "$port" -u "$(cfg MYSQL_USER testmate)" \
       "-p$(cfg MYSQL_PASSWORD)" -e "SELECT 1" "$(cfg MYSQL_DATABASE testmate)" >/dev/null 2>&1; then
    ok "MySQL 连得上 ($host:$port)"
    return 0
  fi

  if [[ -z "$mycli" ]]; then
    log "宿主机上没有 mysql 客户端 —— 试 Docker 模式的容器..."
  else
    log "MySQL 连不上 ($host:$port) —— 试 Docker 模式的容器..."
  fi
  if ensure_docker_db; then
    return 0
  fi
  die "没有可用的 MySQL. 三选一:
  ① 装本机服务: brew install mysql redis && brew services start mysql && brew services start redis
  ② 复用 Docker 模式的容器 (需要 deploy/.env 里有 MYSQL_ROOT_PASSWORD)
  ③ 手工起一个 MySQL, 然后把 deploy/native/.env 的 MYSQL_HOST/PORT/USER/PASSWORD 填对"
}

local_install() {
  log "TestMate 本地部署 (local driver —— 无 init 系统, 进程用 PID 文件管)"
  echo

  log "1/9 环境体检"
  PREFLIGHT_AUTO="$OPT_AUTO"
  PREFLIGHT_DRIVER="local"
  preflight_run || true
  echo
  if [[ $CHK_FAIL -gt 0 ]]; then
    if [[ $OPT_AUTO -eq 1 ]]; then
      warn "还有 $CHK_FAIL 项没过 —— 装完再体检一次"
    else
      confirm "体检没全过, 继续?" || die "已中止 (加 --auto 让脚本自己装依赖)"
    fi
  fi

  # ⚠️ 这一步不是"可选" —— 不修的话, 代码检视连不上、资产市场也推不到 GitLab
  log "2/9 宿主名解析"
  if ! hosts_do_check; then
    if [[ $OPT_AUTO -eq 1 ]]; then
      echo
      hosts_do_fix || warn "没能自动修好 —— 手工加一行就行 (见上面的命令)"
    else
      echo
      warn "这一步建议先修掉 —— 不修的话代码检视和资产市场推送都用不了"
    fi
  fi
  echo

  log "3/9 生成配置"
  ensure_env_file
  resolve_port_conflicts

  log "4/9 数据库"
  ensure_db_local

  log "5/9 Python 依赖"
  build_venv

  log "6/9 前端构建"
  build_frontend

  log "7/9 资产市场 SSH 身份"
  ensure_market_ssh

  log "8/9 生成应用配置"
  render_app_configs

  if [[ $OPT_NO_START -eq 1 ]]; then
    ok "装完了 (没启动) —— 起: $0 local start"
    return 0
  fi

  log "9/9 启动服务"
  local_do_start
  create_admin_account

  local fe_port be_port
  fe_port="$(cfg FRONTEND_PORT 8080)"
  be_port="$(cfg BACKEND_PORT 8000)"
  echo
  ok "本地部署完成"
  echo "  前端:       http://localhost:${fe_port}"
  echo "  API 文档:   http://localhost:${fe_port}/docs"
  echo "  后端直连:   http://127.0.0.1:${be_port}/docs"
  echo
  echo "  admin 账号: $(cfg ADMIN_DEFAULT_USER admin)"
  echo "  admin 口令: $(cfg ADMIN_DEFAULT_PASSWORD)"
  echo "              (在 $ENV_FILE 里; 改: $0 admin --username <用户名> --password '<新口令>')"
  echo
  echo "  开机自启:   $0 launchd install   (macOS: 开机自启 + 崩溃自愈)"
  echo "  状态: $0 local status"
  echo "  日志: $0 local logs"
  echo "  重启: $0 local restart"
  echo "  停止: $0 local stop"
}

local_update() {
  log "1/4 拉新代码"
  cd "$REPO_ROOT"
  local before after
  before="$(git rev-parse --short HEAD 2>/dev/null || echo '?')"
  if [[ -n "$OPT_FROM" ]]; then
    git fetch --all --tags 2>/dev/null || true
    git checkout "$OPT_FROM" || die "切不到 $OPT_FROM"
    git pull 2>/dev/null || true
  else
    git pull --ff-only || warn "git pull 不是快进 —— 有本地改动? 手工处理: cd $REPO_ROOT && git status"
  fi
  after="$(git rev-parse --short HEAD 2>/dev/null || echo '?')"
  [[ "$before" == "$after" ]] && info "代码没变 ($after)" || ok "代码: $before -> $after"

  log "2/4 重建依赖"
  build_venv

  log "3/4 重建前端"
  build_frontend

  log "4/4 重启"
  render_app_configs
  local_do_restart
  ok "升级完成"
}

local_uninstall() {
  confirm "卸载会停服务并删掉 launchd 单元 (数据默认保留), 确定?" || die "已中止"
  if [[ "$(uname -s)" == "Darwin" ]]; then
    launchd_unload "com.testmate.backend" 2>/dev/null || true
    launchd_unload "com.testmate.frontend" 2>/dev/null || true
    rm -f "$(launchd_plist_path com.testmate.backend)" "$(launchd_plist_path com.testmate.frontend)"
  fi
  local_do_stop
  ok "已卸载 (数据留在 $RUNTIME_DIR, 要删自己 rm -rf)"
  echo "  手动清理: rm -rf $RUNTIME_DIR && rm -f $ENV_FILE"
}

# ==================== launchd (macOS 开机自启 + 崩溃自愈) ====================

# backend.env → plist 的 EnvironmentVariables 字典
plist_env_vars() {
  local f="$RUNTIME_DIR/config/backend.env"
  # ⚠️ launchd 的默认 PATH 只有 /usr/bin:/bin —— homebrew 的 git / ssh / nginx 都在
  #    /opt/homebrew/bin. 不给的话, 资产市场的 git push 会 "command not found"
  #    (systemd 那边默认 PATH 够宽, 所以只有 launchd 需要显式给).
  printf '        <key>PATH</key>\n        <string>%s</string>\n' \
    "/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin:/usr/sbin:/sbin"
  [[ -f "$f" ]] || return 0
  local line k v
  while IFS= read -r line; do
    [[ "$line" =~ ^[[:space:]]*# ]] && continue
    [[ "$line" == *=* ]] || continue
    k="${line%%=*}"
    v="${line#*=}"
    k="$(printf '%s' "$k" | tr -d '[:space:]')"
    # 去首尾引号
    v="$(printf '%s' "$v" | sed -e 's/^[[:space:]]*//' -e 's/[[:space:]]*$//' -e 's/^"//' -e 's/"$//' -e "s/^'//" -e "s/'$//")"
    [[ -z "$k" ]] && continue
    # XML 转义 (& < >)
    v="$(printf '%s' "$v" | sed -e 's/&/\&amp;/g' -e 's/</\&lt;/g' -e 's/>/\&gt;/g')"
    printf '        <key>%s</key>\n        <string>%s</string>\n' "$k" "$v"
  done < "$f"
}

launchd_do_install() {
  if [[ "$(uname -s)" != "Darwin" ]]; then
    die "launchd 是 macOS 专属 —— Linux 上开机自启用 systemctl (tmctl.sh enable)"
  fi
  have_cmd launchctl || die "没找到 launchctl"

  local venv="$RUNTIME_DIR/venv/bin/uvicorn"
  if [[ ! -x "$venv" ]]; then
    die "venv 没建好 —— 先跑: $0 local install"
  fi
  local nginx_bin
  nginx_bin="$(local_nginx_bin)"
  if [[ ! -x "$nginx_bin" ]]; then
    die "没找到 nginx —— brew install nginx"
  fi
  [[ -f "$RUNTIME_DIR/config/backend.env" ]] || die "配置还没生成 —— 先跑: $0 local install"
  [[ -f "$RUNTIME_DIR/config/nginx.conf" ]] || die "nginx 配置还没生成 —— 先跑: $0 local install"

  local dir be_port bind workers fe_port
  dir="$(launchd_plist_dir)"
  mkdir -p "$dir"
  be_port="$(cfg BACKEND_PORT 8000)"
  bind="$(cfg BIND_ADDR 127.0.0.1)"
  workers="$(cfg BACKEND_WORKERS 1)"
  fe_port="$(cfg FRONTEND_PORT 8080)"

  log "生成 launchd 单元"
  local env_vars
  env_vars="$(plist_env_vars)"
  render_template "$NATIVE_DIR/units/launchd/com.testmate.backend.plist.tpl" \
    "$(launchd_plist_path com.testmate.backend)" \
    "VENV_BIN" "$RUNTIME_DIR/venv/bin" \
    "BACKEND_DIR" "$REPO_ROOT/backend_gateway" \
    "BIND_ADDR" "$bind" \
    "BACKEND_PORT" "$be_port" \
    "WORKERS" "$workers" \
    "FORWARDED_ALLOW" "127.0.0.1" \
    "LOG_DIR" "$RUNTIME_DIR/logs" \
    "ENV_VARS" "$env_vars"

  render_template "$NATIVE_DIR/units/launchd/com.testmate.frontend.plist.tpl" \
    "$(launchd_plist_path com.testmate.frontend)" \
    "NGINX_BIN" "$nginx_bin" \
    "NGINX_CONF" "$RUNTIME_DIR/config/nginx.conf" \
    "NGINX_PREFIX" "$RUNTIME_DIR" \
    "LOG_DIR" "$RUNTIME_DIR/logs"

  # plist 语法自检 —— 写错了 launchd 会静默不加载
  if have_cmd plutil; then
    local p
    for p in "$(launchd_plist_path com.testmate.backend)" "$(launchd_plist_path com.testmate.frontend)"; do
      if ! plutil -lint "$p" >/dev/null 2>&1; then
        fail "plist 语法有问题: $p"
        plutil -lint "$p" 2>&1 | sed 's/^/      /'
        die "已中止"
      fi
    done
    ok "plist 语法校验通过"
  fi

  log "装载 launchd 服务"
  # 先把 PID 模式起的进程停掉 —— 两边不能同时管同一个服务
  local_do_stop >/dev/null 2>&1 || true
  launchd_unload "com.testmate.backend" >/dev/null 2>&1 || true
  launchd_unload "com.testmate.frontend" >/dev/null 2>&1 || true

  launchd_load "$(launchd_plist_path com.testmate.backend)" || die "装载 com.testmate.backend 失败"
  launchd_load "$(launchd_plist_path com.testmate.frontend)" || die "装载 com.testmate.frontend 失败"
  ok "launchd 已装载 (开机自启 + 崩溃自动拉起)"

  wait_healthy

  echo
  ok "launchd 安装完成"
  echo "  后端: com.testmate.backend"
  echo "  前端: com.testmate.frontend"
  echo "  状态: $0 launchd status"
  echo "  卸载: $0 launchd uninstall"
  echo
  echo "  前台地址: http://localhost:${fe_port}"
}

launchd_do_uninstall() {
  log "卸载 launchd 服务"
  launchd_unload "com.testmate.backend" && ok "com.testmate.backend 已卸载" || warn "com.testmate.backend 本来就没装"
  launchd_unload "com.testmate.frontend" && ok "com.testmate.frontend 已卸载" || warn "com.testmate.frontend 本来就没装"
  rm -f "$(launchd_plist_path com.testmate.backend)" "$(launchd_plist_path com.testmate.frontend)"
  ok "plist 文件已删除 (数据保留在 $RUNTIME_DIR)"
}

launchd_do_status() {
  if [[ "$(uname -s)" != "Darwin" ]]; then
    die "launchd 是 macOS 专属 —— Linux 上看 systemctl status $BACKEND_UNIT"
  fi
  local l
  for l in com.testmate.backend com.testmate.frontend; do
    echo
    echo "── $l ──"
    if launchd_loaded "$l"; then
      ok "已装载"
      if have_cmd launchctl; then
        launchctl print "$(launchd_domain)/$l" 2>/dev/null \
          | grep -E '^\s+(state|pid|last exit code|program) ' | sed 's/^/    /'
      fi
    else
      echo "  没装 —— $0 launchd install"
    fi
  done
}

# ==================== 命令实现 ====================

cmd_check() {
  # shellcheck disable=SC2034  # PREFLIGHT_AUTO 是给 source 进来的 preflight.sh 用的
  PREFLIGHT_AUTO="$OPT_AUTO"
  # shellcheck disable=SC2034  # PREFLIGHT_DRIVER 同上 —— 给 preflight.sh 判断该查 systemd 还是 launchd
  PREFLIGHT_DRIVER="$DRIVER"
  # ⚠️ 必须带 `|| true` —— 脚本开着 `set -e`, 体检里**任何一项**没过都会把整个
  #    函数中途掐掉, 后面的章节压根不跑. 而体检的价值恰恰是"一次跑完, 把所有
  #    不行的地方和怎么修都列出来" —— 跑一半就退等于没体检.
  #    (挂在 `||` 后面会让 set -e 在函数体内失效, 这正是这里要的)
  preflight_run || true
  # ⚠️ 退出码要透传 —— 体检没过就该非 0, 好让 CI / 巡检脚本用得上
  chk_summary || return 1
  return 0
}

cmd_install() {
  if [[ "$DRIVER" == "local" ]]; then local_install; return; fi
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
  resolve_port_conflicts

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
  render_app_configs
  render_systemd_configs

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
  if [[ "$DRIVER" == "local" ]]; then local_do_start; return; fi
  need_systemd
  need_root "启动服务"
  log "启动服务"
  # 后端先起 —— 前端起来但后端没起的话, 页面会是一片 502
  systemctl start "$BACKEND_UNIT"
  systemctl start "$FRONTEND_UNIT"
  wait_healthy
}

cmd_stop() {
  if [[ "$DRIVER" == "local" ]]; then local_do_stop; return; fi
  need_systemd
  need_root "停止服务"
  log "停止服务"
  systemctl stop "$FRONTEND_UNIT" "$BACKEND_UNIT"
  ok "已停止 (数据保留)"
}

cmd_restart() {
  if [[ "$DRIVER" == "local" ]]; then local_do_restart; return; fi
  need_systemd
  need_root "重启服务"
  log "重启服务"
  systemctl restart "$BACKEND_UNIT" "$FRONTEND_UNIT"
  wait_healthy
}

cmd_reload() {
  if [[ "$DRIVER" == "local" ]]; then
    local nginx_bin
    nginx_bin="$(local_nginx_bin)"
    "$nginx_bin" -t -c "$RUNTIME_DIR/config/nginx.conf" -p "$RUNTIME_DIR" || die "nginx 配置有错"
    "$nginx_bin" -s reload -c "$RUNTIME_DIR/config/nginx.conf" -p "$RUNTIME_DIR" || die "重载失败"
    ok "已重载 nginx 配置"
    return
  fi
  need_systemd
  need_root "重载配置"
  log "重载 nginx 配置"
  nginx -t -c "$RUNTIME_DIR/config/nginx.conf" -p "$RUNTIME_DIR" || die "nginx 配置有错"
  systemctl reload "$FRONTEND_UNIT"
  ok "已重载"
}

cmd_status() {
  if [[ "$DRIVER" == "local" ]]; then local_do_status; return; fi
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
  if [[ "$DRIVER" == "local" ]]; then
    local a
    for a in "$@"; do
      case "$a" in
        -f|--follow) OPT_FOLLOW=1 ;;
      esac
    done
    local_do_logs
    return
  fi
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
  if [[ "$DRIVER" == "local" ]]; then
    log "local 模式的开机自启 = launchd"
    launchd_do_install
    return
  fi
  need_systemd
  need_root "设置开机自启"
  systemctl enable "$BACKEND_UNIT" "$FRONTEND_UNIT"
  ok "已设开机自启"
}

cmd_disable() {
  if [[ "$DRIVER" == "local" ]]; then
    launchd_do_uninstall
    return
  fi
  need_systemd
  need_root "取消开机自启"
  systemctl disable "$BACKEND_UNIT" "$FRONTEND_UNIT"
  ok "已取消开机自启 (服务还在跑)"
}

cmd_update() {
  if [[ "$DRIVER" == "local" ]]; then local_update; return; fi
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
  if [[ "$DRIVER" == "local" ]]; then local_uninstall; return; fi
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
  launchd)
    case "${REST[0]:-status}" in
      install)   launchd_do_install ;;
      uninstall) launchd_do_uninstall ;;
      status)    launchd_do_status ;;
      *) die "launchd 子命令: install | uninstall | status" ;;
    esac ;;
  hosts)   cmd_hosts ${REST[@]+"${REST[@]}"} ;;
  help|-h|--help) usage ;;
  *)        die "未知命令: $ACTION (用 --help 看用法)" ;;
esac
