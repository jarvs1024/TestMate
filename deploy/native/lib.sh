#!/usr/bin/env bash
# shellcheck disable=SC2034
# ↑ 文件级: 本文件是**库**, 有些变量 (OS_* / PKG_MGR) 是给 source 进来的
#   preflight.sh 用的, shellcheck 看不到跨文件的引用, 会误报"未使用".
#   放在文件头 (第一个命令之前) 才是文件级生效 —— 放在函数里只对下一行生效.
#
# TestMate 裸机部署 —— 公共函数库
#
# 被 tmctl.sh / preflight.sh source 进来. **不要**直接执行.
#
# 设计约束:
#   · bash 3.2 兼容 (macOS 自带 bash 3.2) —— 本地能 `bash -n` 自检, 不必非要 Linux
#   · 不依赖任何第三方工具 (jq / shellcheck / yq 都没有) —— 内网机器常常装不了
#   · 所有探测都只读 —— check 绝不能改系统状态

# ---------- 路径 ----------
# 由调用方 (tmctl.sh) 设置:
#   NATIVE_DIR   deploy/native 绝对路径
#   REPO_ROOT    仓库根绝对路径
#   RUNTIME_DIR  deploy/native/runtime 绝对路径

# ---------- 颜色 ----------
if [[ -t 1 ]]; then
  C_RED=$'\033[31m'; C_GREEN=$'\033[32m'; C_YELLOW=$'\033[33m'
  C_BLUE=$'\033[36m'; C_BOLD=$'\033[1m'; C_OFF=$'\033[0m'
else
  C_RED=""; C_GREEN=""; C_YELLOW=""; C_BLUE=""; C_BOLD=""; C_OFF=""
fi

log()   { echo "${C_BLUE}[testmate]${C_OFF} $*"; }
ok()    { echo "  ${C_GREEN}✓${C_OFF} $*"; }
warn()  { echo "  ${C_YELLOW}!${C_OFF} $*"; }
fail()  { echo "  ${C_RED}✗${C_OFF} $*"; }
info()  { echo "  ${C_BLUE}·${C_OFF} $*"; }
die()   { echo "${C_RED}[testmate] 致命:${C_OFF} $*" >&2; exit 1; }

section() {
  echo
  echo "${C_BOLD}$*${C_OFF}"
}

# ---------- 计数 ----------
# check 用: PASS / WARN / FAIL 三个计数器
CHK_PASS=0
CHK_WARN=0
CHK_FAIL=0

chk_pass() { CHK_PASS=$((CHK_PASS + 1)); ok "$*"; }
chk_warn() { CHK_WARN=$((CHK_WARN + 1)); warn "$*"; }
chk_fail() { CHK_FAIL=$((CHK_FAIL + 1)); fail "$*"; }

chk_summary() {
  echo
  if [[ $CHK_FAIL -gt 0 ]]; then
    echo "${C_RED}✗ 未通过${C_OFF} —— 通过 $CHK_PASS / 警告 $CHK_WARN / 失败 $CHK_FAIL"
    return 1
  fi
  if [[ $CHK_WARN -gt 0 ]]; then
    echo "${C_YELLOW}✓ 通过 (有警告)${C_OFF} —— 通过 $CHK_PASS / 警告 $CHK_WARN / 失败 $CHK_FAIL"
    return 0
  fi
  echo "${C_GREEN}✓ 全部通过${C_OFF} —— 共 $CHK_PASS 项"
  return 0
}

# ---------- 基础探测 ----------

have_cmd() { command -v "$1" >/dev/null 2>&1; }

# 命令版本号 -> 纯数字串, 便于比较
cmd_version() {
  local c="$1" v
  v="$("$c" --version 2>/dev/null | head -1)" || return 1
  # 取第一个像 3.11.4 / 20.11.0 / 8.0.32 的串
  echo "$v" | grep -oE '[0-9]+(\.[0-9]+)*' | head -1
}

# 版本比较: ver_ge 3.11  -> 当前 >= 3.11
# 用 sort -V (coreutils, macOS 自带), 取不到就退回简单比较
ver_ge() {
  local have="$1" want="$2"
  [[ -z "$have" ]] && return 1
  if printf '%s\n%s\n' "$want" "$have" | sort -V 2>/dev/null | head -1 | grep -qx "$want"; then
    return 0
  fi
  # sort -V 不可用时的兜底: 拆成数字数组比
  local -a a b
  IFS='.' read -r -a a <<< "$have"
  IFS='.' read -r -a b <<< "$want"
  local i
  for i in 0 1 2; do
    local x="${a[$i]:-0}" y="${b[$i]:-0}"
    [[ "$x" =~ ^[0-9]+$ ]] || x=0
    [[ "$y" =~ ^[0-9]+$ ]] || y=0
    [[ "$x" -gt "$y" ]] && return 0
    [[ "$x" -lt "$y" ]] && return 1
  done
  return 0
}

# 端口是否被占 (有人 listen 着)
#
# ⚠️ macOS 的 `netstat -ltn` **不能用** —— 它的 -l 不是"只看监听", 而是显示 listen
#    队列长度, 结果 LISTEN 的行全被过滤掉了 (macOS 上 `netstat -ltn | grep LISTEN`
#    一条都没有). 以前拿 netstat 判断端口, mac 上就永远返回"空闲" ——
#    结果装的时候把 nginx 叠在别的服务上, 请求全被对方接走 (真踩过:
#    机器上有个 Qoder 服务早就占着 127.0.0.1:8080, 而我们的 nginx 绑 0.0.0.0:8080,
#    更具体的绑定优先 → 端口"看起来是 nginx 的", 实际应答的是别人).
#
# 现在按可靠度排: ss (Linux 最干净) → lsof (mac/Linux 都准) → netstat -an (兜底) → /dev/tcp
port_in_use() {
  local port="$1"
  if have_cmd ss; then
    ss -ltn 2>/dev/null | awk 'NR>1 {print $4}' | grep -qE "[:.]${port}\$" && return 0
    return 1
  fi
  if have_cmd lsof; then
    lsof -nP -iTCP:"$port" -sTCP:LISTEN >/dev/null 2>&1 && return 0
    return 1
  fi
  if have_cmd netstat; then
    # ⚠️ 用 `-an` 而不是 `-ltn` —— macOS 的 -ltn 过滤不出 LISTEN
    netstat -an 2>/dev/null | grep LISTEN | grep -qE "[:.]${port}[[:space:]]" && return 0
    return 1
  fi
  (exec 3<>"/dev/tcp/127.0.0.1/$port") 2>/dev/null && { exec 3<&- 3>&-; return 0; }
  return 1
}

# systemd 服务是否存在 (可以是 .service 或 .socket)
unit_exists() {
  local u="$1"
  [[ -z "$u" ]] && return 1
  if have_cmd systemctl; then
    systemctl list-unit-files 2>/dev/null | grep -q "^${u}\." && return 0
    systemctl list-units --all 2>/dev/null | grep -q "^${u}\." && return 0
  fi
  return 1
}

# 服务是否在跑
unit_active() {
  have_cmd systemctl || return 1
  systemctl is-active --quiet "$1" 2>/dev/null
}

# systemd 是否可用 (PID 1 是 systemd)
systemd_available() {
  have_cmd systemctl || return 1
  [[ "$(ps -p 1 -o comm= 2>/dev/null | tr -d ' ')" == "systemd" ]] && return 0
  # 容器里 PID1 可能不是 systemd, 但 systemctl 二进制存在 (有 systemctl-analyze)
  return 1
}

# ==================== 本机服务管理 (systemd / brew 双通道) ====================
#
# 裸机部署的 MySQL / Redis 必须是**本机服务** —— 不能靠容器.
#   macOS  : brew services (launchd 托管, 登录自启, 崩了会被拉起来)
#   Linux  : systemd (enable --now, 开机自启)
#
# 为什么不复用 Docker 模式那套 mysql/redis 容器:
#   ① 容器不是"本机服务" —— Docker Desktop 崩了 / 机器重启 / 有人 docker compose down,
#      裸机部署的后端就再也连不上库 (真踩过: Docker Desktop 重启把 mysql 容器
#      SIGKILL 掉, 裸机后端直接起不来).
#   ② 两种模式共用一份库 = 改密码 / 改数据会互相顶掉, 运维分不清是谁的锅.
#   ③ 裸机模式的意义就是"这台机器自己就能跑" —— 挂着容器就名不副实.

# 用哪套服务管理 (systemd / brew / 都没有)
service_backend() {
  if systemd_available; then echo systemd; return 0; fi
  if have_cmd brew; then echo brew; return 0; fi
  echo ""
}

# 逻辑服务名 -> brew formula 名
brew_formula_name() {
  case "$1" in
    mysql) echo "mysql" ;;
    mariadb) echo "mariadb" ;;
    redis) echo "redis" ;;
    *) echo "$1" ;;
  esac
}

# brew formula 装没装
#
# ⚠️ `brew list --formula` 有时候会因为 brew 自己在后台更新而**偶发失败**
#    (输出空 → grep 不中 → 误判成"没装"). 拿不到结果时再问一次
#    `brew list --versions <formula>` —— 那个不做更新, 稳得多.
brew_formula_installed() {
  local f="$1"
  have_cmd brew || return 1
  if brew list --formula 2>/dev/null | grep -qx "$f"; then
    return 0
  fi
  brew list --versions "$f" 2>/dev/null | grep -q "^$f " && return 0
  return 1
}

# 装一个 brew formula —— 日志留在 PKG_LOG 里, 由调用方打出来
# ⚠️ 别把输出丢了 —— brew 装不上的时候, 用户需要看到真实报错
brew_install_formula() {
  local f="$1"
  have_cmd brew || return 1
  PKG_LOG="$(mktemp)"
  brew install "$f" >"$PKG_LOG" 2>&1
}

# brew 服务在跑吗
#
# ⚠️ 要看**状态列**, 不能只看名字在不在列表里 ——
#    `brew services list` 里 "none" 表示"已注册但没跑", 只比名字会误判成在跑.
#    (真踩过: 装完第一次 start 没成功, 脚本却以为服务在跑, 结果后端连不上库.)
#
# `brew services list` 的输出:
#   Name        Status   User  File
#   mysql       started  user  ~/Library/LaunchAgents/sh.brew.mysql.plist
brew_service_running() {
  local f="$1"
  have_cmd brew || return 1
  brew services list 2>/dev/null | awk -v n="$f" 'NR>1 && $1==n {print $2; exit}' | grep -qx "started"
}

# brew 服务状态 (started / stopped / none / error)
brew_service_status() {
  local f="$1"
  have_cmd brew || return 1
  brew services list 2>/dev/null | awk -v n="$f" 'NR>1 && $1==n {print $2; exit}'
}

# 起一个 brew 服务 (登录自启)
# ⚠️ 失败时把 brew 的原话打出来 —— 吞掉的话只剩一句"启动失败", 没法查
brew_service_start() {
  local f="$1" out
  have_cmd brew || return 1
  out="$(brew services start "$f" 2>&1)" || { printf '%s\n' "$out" >&2; return 1; }
  printf '%s\n' "$out" >/dev/null
  return 0
}

brew_service_restart() {
  local f="$1" out
  have_cmd brew || return 1
  out="$(brew services restart "$f" 2>&1)" || { printf '%s\n' "$out" >&2; return 1; }
  printf '%s\n' "$out" >/dev/null
  return 0
}


# ---------- 系统识别 ----------

detect_os() {
  OS_ID="unknown"; OS_NAME="unknown"; OS_VERSION="unknown"; OS_ARCH="$(uname -m)"
  if [[ -r /etc/os-release ]]; then
    # shellcheck disable=SC1091
    . /etc/os-release
    OS_ID="${ID:-unknown}"
    OS_NAME="${PRETTY_NAME:-${NAME:-unknown}}"
    OS_VERSION="${VERSION_ID:-unknown}"
  elif [[ -r /etc/redhat-release ]]; then
    OS_ID="rhel"; OS_NAME="$(cat /etc/redhat-release)"; OS_VERSION="unknown"
  elif [[ -r /etc/debian_version ]]; then
    OS_ID="debian"; OS_NAME="Debian $(cat /etc/debian_version)"; OS_VERSION="$(cat /etc/debian_version)"
  fi
}

# 包管理器: dnf / yum / apt-get / zypper / pacman —— 都没有则空
detect_pkg_mgr() {
  if have_cmd dnf; then echo dnf
  elif have_cmd yum; then echo yum
  elif have_cmd apt-get; then echo apt-get
  elif have_cmd zypper; then echo zypper
  elif have_cmd pacman; then echo pacman
  else echo ""
  fi
}

# 内核版本 -> epoch, 用来判断 >= 5.4
kernel_epoch() {
  local v
  v="$(uname -r | grep -oE '^[0-9]+(\.[0-9]+)*' || echo 0)"
  local -a a
  IFS='.' read -r -a a <<< "$v"
  echo $(( ${a[0]:-0} * 1000000 + ${a[1]:-0} * 1000 + ${a[2]:-0} ))
}

# ---------- .env 读取 ----------

# 从 .env 文件读一个 key 的原始值 (不做 shell 展开, 不 source 整个文件)
env_get() {
  local file="$1" key="$2"
  [[ -f "$file" ]] || return 1
  local line
  line="$(grep -E "^${key}=" "$file" 2>/dev/null | tail -1)" || return 1
  [[ -z "$line" ]] && return 1
  local v="${line#*=}"
  # 去首尾空白
  v="$(printf '%s' "$v" | sed -e 's/^[[:space:]]*//' -e 's/[[:space:]]*$//')"
  # ⚠️ **行内注释必须剥, 但不能一刀切** ——
  #    模板里写的是 `FRONTEND_PORT=8080        # 对外访问端口 (nginx)`,
  #    不剥的话端口会被读成 "8080        # 对外访问端口 (nginx)" → nginx 配置直接废掉.
  #    但口令里可能带 # (随机生成的口令就有), 所以只有"空白 + #"且**值没被引号包住**
  #    时才当注释.
  case "$v" in
    \"*)
      # 被双引号包住 → 取第一对引号**里面**的, 后面(引号外的注释)全丢
      v="$(printf '%s' "$v" | sed -e 's/^"\([^"]*\)".*$/\1/')" ;;
    \'*)
      v="$(printf '%s' "$v" | sed -e "s/^'\([^']*\)'.*$/\1/")" ;;
    *)
      # 无引号 → 第一个 "空白 + #" 之后都是注释
      v="$(printf '%s' "$v" | sed -e 's/[[:space:]]#.*$//' -e 's/[[:space:]]*$//')" ;;
  esac
  printf '%s' "$v"
}

# 判断 .env 里 key 是否存在
env_has() {
  local file="$1" key="$2"
  [[ -f "$file" ]] && grep -qE "^${key}=" "$file"
}

# 设值 (已存在则替换整行)
env_set() {
  local file="$1" key="$2" val="$3"
  if grep -qE "^${key}=" "$file" 2>/dev/null; then
    # 用 awk 精确替换, 避免 val 里的 / & 被 sed 吃掉
    local tmp
    tmp="$(mktemp)"
    KEY="$key" VAL="$val" awk -F= '
      BEGIN { k = ENVIRON["KEY"]; v = ENVIRON["VAL"]; done = 0 }
      $0 ~ "^" k "=" { print k "=" v; done = 1; next }
      { print }
      END { if (!done) print k "=" v }
    ' "$file" > "$tmp" && mv "$tmp" "$file"
  else
    printf '%s=%s\n' "$key" "$val" >> "$file"
  fi
}

# 口令强度检查 (跟 Docker 版 deploy.sh 同一口径)
# 用法: pw_check "<值>" "<键名>"  -> 返回 0 通过
pw_check() {
  local val="$1" key="$2"
  if [[ -z "$val" ]]; then
    echo "${key} 未设置"
    return 1
  fi
  if [[ ${#val} -lt 12 ]]; then
    echo "${key} 太短 (${#val} 字符), 至少 12 字符, 推荐: openssl rand -base64 18"
    return 1
  fi
  if echo "$val" | grep -qiE 'change-me|change_me|please-change|changeme|please-generate'; then
    echo "${key} 还是占位符, 必须换成自己的强口令"
    return 1
  fi
  return 0
}

# JWT_SECRET 强度 (跟 Docker 版同一口径)
jwt_check() {
  local val="$1"
  if [[ -z "$val" ]]; then echo "JWT_SECRET 未设置"; return 1; fi
  if [[ ${#val} -lt 32 ]]; then
    echo "JWT_SECRET 太短 (${#val} 字节), 至少 32 字节, 推荐: openssl rand -base64 32"
    return 1
  fi
  if echo "$val" | grep -qiE 'change|placeholder|please|dev-secret|test-secret|example'; then
    echo "JWT_SECRET 含占位符字面量, 生产前必须改"
    return 1
  fi
  return 0
}

# 生成随机口令
gen_secret() {
  local n="${1:-32}"
  if have_cmd openssl; then
    openssl rand -base64 "$n" | tr -d '\n' | tr '/+' '_-'
  else
    head -c $(( n * 3 / 4 )) /dev/urandom | base64 | tr -d '\n' | tr '/+' '_-'
  fi
}

# ---------- 数据库 ----------

mysql_client_cmd() {
  if have_cmd mysql; then echo mysql
  elif have_cmd mariadb; then echo mariadb
  else echo ""
  fi
}

mysql_service_name() {
  # 返回宿主机上 MySQL/MariaDB 的 systemd unit 名, 都没有则空
  local u
  for u in mysqld mariadb mysql; do
    unit_exists "$u.service" && { echo "$u"; return 0; }
  done
  # 有客户端但服务名不认识 —— 装一个常见的
  echo "mysqld"
}

# ===== MySQL 调用: 一律走**本机**客户端 =====
#
# ⚠️ 这里以前有个"宿主机没客户端就 docker compose exec 进容器里跑"的兜底 ——
#    那等于把裸机部署吊在 Docker 上: 容器一停 (Docker Desktop 崩了 / 机器重启 /
#    有人 docker compose down) , 裸机部署的后端就再也连不上库.
#    裸机模式必须是**自己的一套**: 本机 MySQL + 本机 Redis + 本机进程.
#    所以这里没有 Docker 兜底 —— 没客户端就装客户端, 装不上就报错.

# 在 MySQL 上执行 SQL (从 stdin 读)
# 用法: mysql_exec <端口> <root口令> <<SQL ... SQL
# ⚠️ stdin 接 /dev/null —— 万一 root 要口令, mysql 会等着敲键盘, 脚本就卡死了.
mysql_exec() {
  local port="$1" root_pwd="$2"
  local mycli
  mycli="$(mysql_client_cmd)"
  [[ -n "$mycli" ]] || return 1
  if [[ -n "$root_pwd" ]]; then
    "$mycli" -h 127.0.0.1 -P "$port" -u root "-p${root_pwd}" 2>/dev/null </dev/null
  else
    "$mycli" -h 127.0.0.1 -P "$port" -u root 2>/dev/null </dev/null
  fi
}

# MySQL 是否活着
mysql_ping() {
  local port="$1" root_pwd="$2"
  local mycli
  mycli="$(mysql_client_cmd)"
  [[ -n "$mycli" ]] || return 1
  if [[ -n "$root_pwd" ]]; then
    mysqladmin -h 127.0.0.1 -P "$port" -u root "-p${root_pwd}" ping >/dev/null 2>&1 </dev/null
  else
    mysqladmin -h 127.0.0.1 -P "$port" -u root ping >/dev/null 2>&1 </dev/null
  fi
}

redis_service_name() {
  local u
  for u in redis redis-server; do
    unit_exists "$u.service" && { echo "$u"; return 0; }
  done
  echo "redis-server"
}

# ---------- 其它 ----------

# 是不是 root
is_root() { [[ ${EUID:-$(id -u)} -eq 0 ]]; }

# 磁盘剩余 GB (取整)
disk_free_gb() {
  local p="${1:-/}"
  df -Pk "$p" 2>/dev/null | awk 'NR==2 {printf "%d", $4/1024/1024}'
}

# 内存 GB
mem_total_gb() {
  if have_cmd free; then
    free -g 2>/dev/null | awk '/^Mem:/ {print $2}'
  elif [[ -r /proc/meminfo ]]; then
    awk '/MemTotal/ {printf "%d", $2/1024/1024}' /proc/meminfo
  elif have_cmd sysctl; then
    # macOS 没有 /proc 也没有 free
    sysctl -n hw.memsize 2>/dev/null | awk '{printf "%d", $1/1024/1024/1024}'
  else
    echo ""
  fi
}

# 最近的**已存在**的可写祖先目录 (用来在不创建目录的前提下判断能不能写)
nearest_writable_ancestor() {
  local d="$1"
  while [[ -n "$d" && ! -e "$d" ]]; do
    d="$(dirname "$d")"
  done
  if [[ -d "$d" && -w "$d" ]]; then
    printf '%s' "$d"
    return 0
  fi
  return 1
}

# 端口占用者 (给人看的: 进程名)
port_owner() {
  local port="$1" owner=""
  if have_cmd ss; then
    owner="$(ss -ltnp "sport = :$port" 2>/dev/null | tail -n +2 \
             | sed -E 's/.*users:\(\("([^"]+)".*/\1/' | head -1)"
    # ⚠️ 抠不出进程名时 sed 会**原样输出整行** (没权限看别人的进程时就是那样)
    #    —— 那不是进程名, 得当"没查到".
    [[ "$owner" == *"users:"* || "$owner" == *"LISTEN"* ]] && owner=""
  fi
  if [[ -z "$owner" ]] && have_cmd lsof; then
    owner="$(lsof -nP -iTCP:"$port" -sTCP:LISTEN 2>/dev/null | awk 'NR==2 {print $1}')"
  fi
  printf '%s' "$owner"
}

# 端口后面是不是这个进程 (按进程名匹配)
#
# ⚠️ 不能只看"端口有没有被占" —— Docker 模式映射出来的端口**也**有人听
#    (监听者是 docker-proxy / com.docker.backend), 但那不是本机 MySQL.
#    判断"这台机器自己有没有 MySQL"只能看监听进程是谁.
port_owned_by() {
  local port="$1" pattern="$2" owner
  owner="$(port_owner "$port")"
  [[ -n "$owner" ]] || return 1
  echo "$owner" | grep -qiE "$pattern"
}

# 本机 MySQL (或 MariaDB) 在这个端口上?
native_mysql_on() { port_owned_by "$1" 'mysql|maria'; }

# 本机 Redis 在这个端口上?
native_redis_on() { port_owned_by "$1" 'redis'; }

# 这个端口后面是不是**本部署自己**的进程?
#
# 用途: 体检时别把"服务正在跑"当成"端口被别人占了" ——
# 自己的 nginx (runtime/config/nginx.conf) 与自己的 uvicorn (runtime/venv)
# 当然是该占着的, 报 FAIL 会让人以为装不了.
#
# 判据: 监听进程的**命令行**里带着 RUNTIME_DIR —— 只认自己 runtime 目录下的进程,
# 别的 nginx / 别的 python 一律不算.
port_owned_by_ours() {
  local port="$1" pid cmd
  have_cmd lsof || return 1
  pid="$(lsof -nP -iTCP:"$port" -sTCP:LISTEN -t 2>/dev/null | head -1)"
  [[ -n "$pid" ]] || return 1
  cmd="$(ps -p "$pid" -o command= 2>/dev/null)"
  [[ -n "$cmd" ]] || return 1
  [[ -n "$RUNTIME_DIR" ]] || return 1
  [[ "$cmd" == *"$RUNTIME_DIR"* ]]
}

# 端口占用者的 PID (拿不到就空)
port_owner_pid() {
  local port="$1"
  if have_cmd lsof; then
    lsof -nP -iTCP:"$port" -sTCP:LISTEN 2>/dev/null | awk 'NR==2 {print $2}'
  elif have_cmd ss; then
    ss -ltnp "sport = :$port" 2>/dev/null | grep -oE 'pid=[0-9]+' | head -1 | cut -d= -f2
  else
    echo ""
  fi
}

# ---------- Docker 专用主机名 ----------
#
# `host.docker.internal` 是**容器里**访问宿主机的名字 —— 在容器里它解析到 Docker 的
# 虚拟网关 (macOS 上是 198.18.x.x), 通得很.
#
# 但 local driver 的进程是**跑在宿主上**的: 同一个名字在宿主上也解析到那个虚拟网关,
# 而那个地址从宿主侧**连不通**. 于是本地部署会出现"看着配了, 就是连不上":
#   · 代码检视 (ReviewAgent) 连不上   → http://host.docker.internal:3000
#   · 资产市场推不到 GitLab             → ssh://git@host.docker.internal:8922
#   · 设置页里填的任何 host.docker.internal 地址都连不上
#
# 解法是一行: 宿主的 /etc/hosts 里让它指回自己 (127.0.0.1).
# **容器不受影响** —— 容器有自己的 /etc/hosts, 走 Docker 的内嵌 DNS.
DOCKER_HOST_ALIASES=(host.docker.internal host.containers.internal host-gateway gateway.docker.internal)

# 主机名 → IP 列表 (一行一个). macOS 用 dscacheutil (它也读 /etc/hosts), Linux 用 getent
resolve_host_ips() {
  local name="$1"
  if have_cmd dscacheutil; then
    dscacheutil -q host -a name "$name" 2>/dev/null | awk '/ip_address:/{print $2}'
    return 0
  fi
  if have_cmd getent; then
    getent ahosts "$name" 2>/dev/null | awk '{print $1}' | sort -u
    return 0
  fi
  if have_cmd host; then
    host "$name" 2>/dev/null | awk '/has address/{print $NF}'
  fi
}

# 这个别名在宿主上是不是"坏的":
#   解析不到, 或解析到的**全是**非回环地址 → 坏
#   只要有一个回环地址 → 好 (/etc/hosts 已经指回自己了)
host_alias_broken() {
  local name="$1" ip any=0
  while read -r ip; do
    [[ -z "$ip" ]] && continue
    any=1
    case "$ip" in
      127.*|::1|0:0:0:0:0:0:0:1) return 1 ;;
    esac
  done < <(resolve_host_ips "$name")
  [[ $any -eq 0 ]] && return 0
  return 0
}

# /etc/hosts 里有没有写过这个别名 (按字段比, 免得正则里的点号出岔)
# ⚠️ HOSTS_FILE 可被环境变量覆盖 —— 只给自检用 (拿临时文件当 hosts 测逻辑),
#    正常跑的时候永远是 /etc/hosts.
hosts_file_has_alias() {
  local name="$1" file="${HOSTS_FILE:-/etc/hosts}"
  [[ -f "$file" ]] || return 1
  awk -v n="$name" '
    /^[[:space:]]*#/ { next }
    { for (i = 2; i <= NF; i++) if ($i == n) found = 1 }
    END { exit(found ? 0 : 1) }
  ' "$file"
}

# 要往 hosts 文件里追加的内容 (自检也用它 —— 保证"写什么"和"测什么"是同一份)
hosts_aliases_block() {
  local name
  echo ""
  echo "# TestMate 本地部署 (local driver): 进程跑在宿主上, 这些名字得指回自己"
  for name in "$@"; do
    echo "127.0.0.1 $name"
  done
}

# ---------- local driver (无 init 系统: mac / 任何 POSIX) ----------
#
# macOS 没有 systemd (PID 1 是 launchd), 但"本地部署"照样能做:
#   · 进程管理 = PID 文件 + nohup
#   · 开机自启 / 崩溃自愈 = launchd (见 launchd_* 函数)
#
# 这两个 driver 共用同一份配置渲染 / venv / 构建 / 健康检查逻辑,
# 只有"怎么起进程、怎么停进程"这一层不同.

# 某个 local 服务的 PID 文件
local_pid_file() {
  printf '%s/run/%s.pid' "$RUNTIME_DIR" "$1"
}

# 读 PID 文件里的进程号 (进程没在跑就返回非 0)
local_pid() {
  local name="$1" pf pid
  pf="$(local_pid_file "$name")"
  [[ -f "$pf" ]] || return 1
  pid="$(cat "$pf" 2>/dev/null || true)"
  [[ -n "$pid" ]] || return 1
  kill -0 "$pid" 2>/dev/null || return 1
  printf '%s' "$pid"
}

# 后台起一个进程, PID 记到文件里
# 用法: local_spawn <名字> <工作目录> <命令...>
# ⚠️ 必须指定工作目录 —— uvicorn 的 `app.main:app` 是相对模块路径,
#    没有 cwd 就 import 不到.
local_spawn() {
  local name="$1" workdir="$2"; shift 2
  local pf logf
  pf="$(local_pid_file "$name")"
  logf="$RUNTIME_DIR/logs/${name}.log"
  mkdir -p "$RUNTIME_DIR/run" "$RUNTIME_DIR/logs"
  if local_pid "$name" >/dev/null 2>&1; then
    echo "  $name 已在跑 (PID $(local_pid "$name"))"
    return 0
  fi
  # ⚠️ 用 ( cd X && exec nohup ... ) & 而不是 nohup ... & ——
  #    后者没有 cwd, 前者 exec 之后 PID 不变, $! 拿到的就是真正的进程号.
  ( cd "$workdir" && exec nohup "$@" >>"$logf" 2>&1 ) &
  echo $! > "$pf"
  sleep 0.5
  if local_pid "$name" >/dev/null 2>&1; then
    echo "  $name 起好了 (PID $(local_pid "$name"))"
    return 0
  fi
  echo "  $name 没起来 —— 看日志: $RUNTIME_DIR/logs/${name}.log"
  tail -n 15 "$logf" 2>/dev/null | sed 's/^/      /'
  return 1
}

# 停一个 local 服务 (先 SIGTERM, 超时再 SIGKILL)
local_kill() {
  local name="$1" pf pid
  pf="$(local_pid_file "$name")"
  if ! pid="$(local_pid "$name")"; then
    rm -f "$pf"
    echo "  $name 本来就没跑"
    return 0
  fi
  kill "$pid" 2>/dev/null || true
  local i
  for i in $(seq 1 15); do
    kill -0 "$pid" 2>/dev/null || break
    sleep 1
  done
  if kill -0 "$pid" 2>/dev/null; then
    kill -9 "$pid" 2>/dev/null || true
    sleep 1
  fi
  rm -f "$pf"
  echo "  $name 停了 (PID $pid)"
}

# ==================== launchd (macOS) ====================

# launchd 的用户域 gui/<uid>
launchd_domain() { printf 'gui/%s' "$(id -u)"; }

# plist 装到哪
launchd_plist_dir() { printf '%s/Library/LaunchAgents' "$HOME"; }
# ⚠️ 参数是**完整 Label** —— launchd 要求 plist 文件名跟 Label 一致,
#    对不上会被 launchd 拒掉 (Load failed)。
launchd_plist_path() { printf '%s/%s.plist' "$(launchd_plist_dir)" "$1"; }

# launchd 服务是否已装载
launchd_loaded() {
  local label="$1"
  have_cmd launchctl || return 1
  launchctl print "$(launchd_domain)/$label" >/dev/null 2>&1
}

# 装载 plist (macOS 现代接口; 老系统回退 load -w)
launchd_load() {
  local plist="$1"
  have_cmd launchctl || return 1
  if launchctl bootstrap "$(launchd_domain)" "$plist" 2>/dev/null; then
    return 0
  fi
  # 已经装过了 → 先卸再装 (用 launchd_unload, 它会等卸载真正完成)
  local label
  label="$(basename "$plist" .plist)"
  launchd_unload "$label" 2>/dev/null || true
  launchctl bootstrap "$(launchd_domain)" "$plist" 2>/dev/null && return 0
  launchctl load -w "$plist" 2>/dev/null
}

launchd_unload() {
  local label="$1" i
  have_cmd launchctl || return 1
  if launchctl bootout "$(launchd_domain)/$label" 2>/dev/null; then
    # ⚠️ `launchctl bootout` 是**异步**的 —— 它返回时进程可能还在退, label 也还挂着.
    #    不等的话, 紧接着的下一条命令会看到"label 还在" → 以为服务还活着, 其实正在死,
    #    于是去等一个正在死掉的后端, 白等 120s.
    #    所以这里轮询到 label 真的消失为止.
    for i in $(seq 1 40); do
      launchd_loaded "$label" || return 0
      sleep 0.5
    done
    return 0
  fi
  launchctl unload -w "$(launchd_plist_path "$label")" 2>/dev/null && return 0
  return 1
}

# launchd 管的进程的 PID (没在跑就返回空)
launchd_pid() {
  local label="$1"
  have_cmd launchctl || return 1
  launchctl print "$(launchd_domain)/$label" 2>/dev/null \
    | grep -E '^[[:space:]]+pid = ' | head -1 | tr -dc '0-9'
}

# 等待 HTTP 端点返回 200
# 用法: wait_http <url> <timeout_s>
wait_http() {
  local url="$1" timeout="${2:-60}" i=0
  while [[ $i -lt $timeout ]]; do
    if curl -fsS -o /dev/null --max-time 3 "$url" 2>/dev/null; then
      return 0
    fi
    sleep 1
    i=$((i + 1))
  done
  return 1
}
