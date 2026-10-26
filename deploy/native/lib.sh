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

# 端口是否被占 (优先 ss, 退化 netstat, 再退化 /dev/tcp)
port_in_use() {
  local port="$1"
  if have_cmd ss; then
    ss -ltn "sport = :$port" 2>/dev/null | tail -n +2 | grep -q . && return 0
    return 1
  fi
  if have_cmd netstat; then
    netstat -ltn 2>/dev/null | grep -qE "[:.]${port}[[:space:]]" && return 0
    return 1
  fi
  # 最后的办法: 试着连一下
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
  # 去首尾引号与空白
  v="$(echo "$v" | sed -e 's/^[[:space:]]*//' -e 's/[[:space:]]*$//' -e 's/^"//' -e 's/"$//' -e "s/^'//" -e "s/'$//")"
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

# 端口占用者 (给人看的)
port_owner() {
  local port="$1"
  if have_cmd ss; then
    ss -ltnp "sport = :$port" 2>/dev/null | tail -n +2 | sed -E 's/.*users:\(\("([^"]+)".*/\1/' | head -1
  elif have_cmd lsof; then
    lsof -i :"$port" -sTCP:LISTEN -t 2>/dev/null | head -1
  else
    echo ""
  fi
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
