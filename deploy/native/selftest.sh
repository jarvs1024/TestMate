#!/usr/bin/env bash
# TestMate 裸机部署 —— 部署资产自检
#
# 干什么:
#   ① 三个脚本的 bash 语法
#   ② 渲染 systemd 单元 + nginx 配置 (用真模板 + 假路径)
#   ③ systemd-analyze verify 校验单元 (装了 systemd 才有)
#   ④ nginx -t 校验 nginx 配置 (装了 nginx 才有)
#   ⑤ shellcheck 静态检查 (装了才有)
#
# 纯静态检查 —— **不改系统任何东西**, 不装任何东西.
# 在 ubuntu 容器里跑最省事:
#   docker run --rm -v "$PWD:/repo" ubuntu:22.04 bash -c \
#     'apt-get update -qq && apt-get install -y -qq systemd nginx-light && bash /repo/deploy/native/selftest.sh'
#
# 退出码: 有 FAIL → 1

set -uo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

PASS=0; FAIL=0; SKIP=0
pass() { PASS=$((PASS+1)); echo "  ✓ $*"; }
failing() { FAIL=$((FAIL+1)); echo "  ✗ $*"; }
skip() { SKIP=$((SKIP+1)); echo "  - $* (跳过)"; }

echo "TestMate 裸机部署 · 部署资产自检"
echo

# ==================== 1. bash 语法 ====================
echo "── 1. bash 语法 ──"
for f in lib.sh preflight.sh tmctl.sh selftest.sh sandbox-probe.sh; do
  if [[ -f "$SCRIPT_DIR/$f" ]]; then
    if bash -n "$SCRIPT_DIR/$f" 2>/tmp/tm-syn.err; then
      pass "$f 语法正确"
    else
      failing "$f 语法错误:"; sed 's/^/      /' /tmp/tm-syn.err
    fi
  fi
done
echo

# ==================== 2. 渲染模板 ====================
echo "── 2. 渲染模板 ──"
TMP="$(mktemp -d)"
trap 'rm -rf "$TMP"' EXIT

# 用真实模板 + 假路径 —— 只验语法结构, 不需要真的装好
cat > "$TMP/render.sh" <<'RENDEREOF'
set -euo pipefail
NATIVE_DIR="$1"; OUT="$2"
mkdir -p "$OUT"/{config,logs,run,data,frontend,market,venv/bin,backend_gateway}

render() {
  local tpl="$1" out="$2"; shift 2
  local content; content="$(cat "$tpl")"
  while [[ $# -gt 0 ]]; do
    local k="$1" v="$2"; shift 2
    content="${content//@@${k}@@/${v}}"
  done
  printf '%s' "$content" > "$out"
}

render "$NATIVE_DIR/units/testmate-backend.service.tpl" "$OUT/testmate-backend.service" \
  "REPO_ROOT" "/opt/testmate" "BACKEND_DIR" "/opt/testmate/backend_gateway" \
  "BACKEND_ENV" "$OUT/config/backend.env" "VENV_BIN" "$OUT/venv/bin" \
  "RUN_USER" "testmate" "RUN_GROUP" "testmate" \
  "BIND_ADDR" "127.0.0.1" "BACKEND_PORT" "8000" "WORKERS" "1" \
  "FORWARDED_ALLOW" "127.0.0.1" "TIMEZONE" "Asia/Shanghai" \
  "MEM_LIMIT" "2G" "CPU_QUOTA" "200%" \
  "RUNTIME_DIR" "$OUT" "DATA_DIR" "$OUT/data" "LOG_DIR" "$OUT/logs" \
  "MARKET_DIR" "$OUT/market" "RUN_DIR" "$OUT/run"

render "$NATIVE_DIR/units/testmate-frontend.service.tpl" "$OUT/testmate-frontend.service" \
  "REPO_ROOT" "/opt/testmate" "NGINX_BIN" "/usr/sbin/nginx" \
  "NGINX_CONF" "$OUT/config/nginx.conf" "NGINX_PREFIX" "$OUT" \
  "RUN_DIR" "$OUT/run" "LOG_DIR" "$OUT/logs" "RUNTIME_DIR" "$OUT" \
  "RUN_USER" "testmate" "RUN_GROUP" "testmate"

render "$NATIVE_DIR/units/nginx.conf.tpl" "$OUT/config/nginx.conf" \
  "FRONTEND_PORT" "8080" "BACKEND_PORT" "8000" "FRONTEND_DIR" "$OUT/frontend" \
  "RUN_DIR" "$OUT/run" "LOG_DIR" "$OUT/logs" "NGINX_CONF_DIR" "$OUT/config"

# mime.types —— 没系统那份就写个最小的
if [[ -f /etc/nginx/mime.types ]]; then
  cp /etc/nginx/mime.types "$OUT/config/mime.types"
else
  printf 'types {\n text/html html;\n text/css css;\n application/javascript js;\n application/json json;\n}\n' > "$OUT/config/mime.types"
fi

# ExecStart 指向的 uvicorn 得存在, 否则 verify 会报 "not executable"
printf '#!/bin/sh\nexit 0\n' > "$OUT/venv/bin/uvicorn"
chmod +x "$OUT/venv/bin/uvicorn"
mkdir -p "$OUT/backend_gateway"
RENDEREOF

if bash "$TMP/render.sh" "$SCRIPT_DIR" "$TMP" 2>"$TMP/render.err"; then
  pass "模板渲染成功"
  for f in testmate-backend.service testmate-frontend.service config/nginx.conf; do
    [[ -s "$TMP/$f" ]] && pass "生成 $f" || failing "生成 $f 失败"
  done
else
  failing "模板渲染失败:"; sed 's/^/      /' "$TMP/render.err"
fi
echo

# ==================== 3. systemd 单元校验 ====================
echo "── 3. systemd 单元校验 ──"
if command -v systemd-analyze >/dev/null 2>&1; then
  for u in testmate-backend.service testmate-frontend.service; do
    out="$(systemd-analyze verify "$TMP/$u" 2>&1)"
    # 过滤掉"可执行文件不存在"这类环境类抱怨 —— 那是没真装, 不是模板错
    real="$(echo "$out" | grep -vE 'Command .* is not executable|No such file or directory|not found|does not exist' || true)"
    if [[ -z "$(echo "$real" | tr -d '[:space:]')" ]]; then
      pass "$u 单元合法"
    else
      failing "$u 单元有问题:"; echo "$real" | sed 's/^/      /'
    fi
  done
  # 反向依赖名对不对 (这两个单元不该互相 After 自己)
  for u in testmate-backend.service testmate-frontend.service; do
    if grep -qE "^After=.*${u}" "$TMP/$u" 2>/dev/null && [[ "$u" == "testmate-backend.service" ]]; then
      failing "$u 依赖了自己"
    else
      pass "$u 依赖关系正常"
    fi
  done
else
  skip "systemd-analyze 没装 —— 单元未校验"
fi
echo

# ==================== 4. env_get 行内注释 ====================
echo "── 4. .env 解析 (行内注释) ──"
ENVTEST="$(mktemp)"
cat > "$ENVTEST" <<'ENVEOF'
FRONTEND_PORT=8080        # 对外访问端口 (nginx)
QUOTED="a b c"            # 引号外的注释
PW_HASH=abc#def
PW_SPACED=x #y
ENVEOF

# shellcheck disable=SC1091
. "$SCRIPT_DIR/lib.sh"
ENVFILE="$ENVTEST"

t_env() {
  local key="$1" want="$2" got
  got="$(env_get "$ENVFILE" "$key")"
  if [[ "$got" == "$want" ]]; then
    pass "env_get $key → [$got]"
  else
    failing "env_get $key → [$got], 期望 [$want]"
  fi
}

t_env FRONTEND_PORT "8080"      # 行内注释要剥 —— 不剥的话端口读成 "8080  # 对外访问端口" → nginx 配置直接废
t_env QUOTED "a b c"             # 引号里的值 + 引号外的注释
t_env PW_HASH "abc#def"          # 口令里的 # 不是注释
t_env PW_SPACED "x"              # 空白 + # 才是注释
rm -f "$ENVTEST"
echo

# ==================== 5. Docker 主机名 (宿主名解析) ====================
echo "── 5. Docker 主机名映射 ──"
HOSTSTEST="$(mktemp)"
cat > "$HOSTSTEST" <<'HOSTEOF'
##
# Host Database
##
127.0.0.1	localhost
::1             localhost
255.255.255.255	broadcasthost
HOSTEOF

# hosts_file_has_alias: 按字段比, 不能把注释行里的名字当命中
export HOSTS_FILE="$HOSTSTEST"
if hosts_file_has_alias "localhost"; then
  pass "hosts_file_has_alias: 能认出已写好的 localhost"
else
  failing "hosts_file_has_alias: 没认出 localhost"
fi
if hosts_file_has_alias "host.docker.internal"; then
  failing "hosts_file_has_alias: 误报 (文件里根本没这个名字)"
else
  pass "hosts_file_has_alias: 没写的名字不误报"
fi

# 写进去的那几行 —— 内容不对的话, 修完还是不通用
BLOCK="$(hosts_aliases_block host.docker.internal host.containers.internal)"
if [[ "$BLOCK" == *"127.0.0.1 host.docker.internal"* ]] \
   && [[ "$BLOCK" == *"127.0.0.1 host.containers.internal"* ]]; then
  pass "hosts_aliases_block: 写出的映射格式对"
else
  failing "hosts_aliases_block: 格式不对 —— [$BLOCK]"
fi

# 追加到文件后, hosts_file_has_alias 应该能认出来 (写和读是同一套逻辑)
printf '%s\n' "$BLOCK" >> "$HOSTSTEST"
if hosts_file_has_alias "host.docker.internal"; then
  pass "hosts_aliases_block: 追加后能被 hosts_file_has_alias 认出"
else
  failing "hosts_aliases_block: 追加后认不出来"
fi
unset HOSTS_FILE
rm -f "$HOSTSTEST"

# host_alias_broken: 解析到非回环地址 = 坏 (容器里访问宿主用的名字, 在宿主上不通)
if host_alias_broken "host.docker.internal"; then
  pass "host_alias_broken: 认出 host.docker.internal 在宿主上是坏的 (除非本机已修好)"
else
  pass "host_alias_broken: host.docker.internal 在本机已指回 127.0.0.1 (修过了)"
fi

# ---- 整个修复流程 (假 sudo + 临时 hosts 文件, 不碰真的 /etc/hosts) ----
FIXTEST_DIR="$(mktemp -d)"
FIXTEST_HOSTS="$FIXTEST_DIR/hosts"
cat > "$FIXTEST_HOSTS" <<'EOF'
127.0.0.1	localhost
EOF
mkdir -p "$FIXTEST_DIR/bin"
cat > "$FIXTEST_DIR/bin/sudo" <<'EOF'
#!/bin/sh
# 假 sudo —— 直接执行 (自检不该真去改 /etc/hosts)
exec "$@"
EOF
chmod +x "$FIXTEST_DIR/bin/sudo"

# hosts_do_fix 在 tmctl.sh 里 —— 这里只取它用到的两个函数
# (直接 source 整个 tmctl.sh 会有副作用, 所以只 source 需要的部分)
FUNCS_ONLY="$FIXTEST_DIR/funcs.sh"
{
  echo 'RUNTIME_DIR="'"$FIXTEST_DIR"'/runtime"'
  echo 'ok() { echo "    ✓ $*"; }'
  echo 'warn() { echo "    ! $*"; }'
  echo 'fail() { echo "    ✗ $*"; }'
  echo 'log() { echo "  > $*"; }'
  echo 'have_cmd() { command -v "$1" >/dev/null 2>&1; }'
  sed -n '/^hosts_do_fix() {/,/^}/p' "$SCRIPT_DIR/tmctl.sh"
} > "$FUNCS_ONLY"

PATH="$FIXTEST_DIR/bin:$PATH" HOSTS_FILE="$FIXTEST_HOSTS" bash -c "
  . '$SCRIPT_DIR/lib.sh'
  . '$FUNCS_ONLY'
  hosts_do_fix >/dev/null 2>&1
" >/dev/null 2>&1

if grep -q '^127\.0\.0\.1[[:space:]]\+host\.docker\.internal' "$FIXTEST_HOSTS"; then
  pass "hosts_do_fix: 真的把映射写进了 hosts 文件"
else
  failing "hosts_do_fix: 没写进去 —— 内容: $(head -5 "$FIXTEST_HOSTS" | tr '\n' '|')"
fi
if [[ -n "$(ls -1 "$FIXTEST_DIR"/runtime/hosts.backup.* 2>/dev/null | head -1)" ]]; then
  pass "hosts_do_fix: 改之前留了备份"
else
  failing "hosts_do_fix: 没留备份"
fi
rm -rf "$FIXTEST_DIR"
echo

# ==================== 6. nginx 配置校验 ====================
echo "── 6. nginx 配置校验 ──"
if command -v nginx >/dev/null 2>&1; then
  mkdir -p "$TMP"/{client_temp,proxy_temp,fastcgi_temp,uwsgi_temp,scgi_temp}
  if out="$(nginx -t -c "$TMP/config/nginx.conf" -p "$TMP" 2>&1)"; then
    pass "nginx 配置合法"
  else
    failing "nginx 配置有问题:"; echo "$out" | sed 's/^/      /'
  fi
else
  skip "nginx 没装 —— 配置未校验"
fi
echo

# ==================== 7. 裸机模式零容器 ====================
echo "── 7. 裸机模式零容器 ──"
#
# 裸机部署的前提: MySQL / Redis 都是**本机服务**, 不用任何容器.
# 以前这里是"连不上就 docker compose exec 进容器里跑" / "复用 Docker 模式的
# mysql/redis 容器" —— 容器一停 (Docker Desktop 崩了 / 机器重启), 裸机后端
# 就再也连不上库 —— "非容器部署" 名不副实.
#
# 这里用断言守住: 以后谁再往数据库路径里塞 docker, 自检立刻红.

# 7.1 lib.sh 的 mysql 调用里不能再有 docker
mysql_funcs="$(sed -n '/^mysql_exec() {/,/^}/p;/^mysql_ping() {/,/^}/p' "$SCRIPT_DIR/lib.sh")"
if echo "$mysql_funcs" | grep -qi 'docker'; then
  failing "lib.sh 的 mysql 调用里还有 docker —— 裸机部署不能靠容器"
else
  pass "lib.sh 的 mysql 调用不碰 docker"
fi

# 7.2 tmctl.sh 里不能再有 ensure_docker_db
if grep -q 'ensure_docker_db' "$SCRIPT_DIR/tmctl.sh"; then
  failing "tmctl.sh 里还有 ensure_docker_db —— 裸机部署不能复用 Docker 模式的库"
else
  pass "tmctl.sh 没有 ensure_docker_db"
fi

# 7.3 不能有 "docker compose exec/run mysql|redis" 这类兜底
if grep -nE 'docker[^#]*(exec|run)[^#]*(mysql|redis)' "$SCRIPT_DIR/tmctl.sh" "$SCRIPT_DIR/lib.sh" >/dev/null 2>&1; then
  failing "还有 docker exec/run mysql/redis 的兜底 —— 裸机部署不能靠容器"
else
  pass "没有 docker exec/run mysql/redis 的兜底"
fi

# 7.4 本机服务的双通道助手得在 (mac 走 brew, Linux 走 systemd)
for fn in service_backend brew_formula_name brew_formula_installed brew_service_running brew_service_start brew_install_formula; do
  if grep -q "^${fn}()" "$SCRIPT_DIR/lib.sh"; then
    pass "lib.sh 有 $fn"
  else
    failing "lib.sh 缺 $fn —— mac 上装不了本机 MySQL/Redis"
  fi
done

# 7.5 端口判定: 能分清"本机 mysqld"和"别的进程"
#     (Docker 模式映射出来的端口**也**有人听, 但监听者是 docker-proxy —— 不能当成本机 MySQL)
FAKE_PORT=""
if command -v python3 >/dev/null 2>&1; then
  FAKE_PORT="$(python3 - <<'PY'
import socket
s = socket.socket()
s.bind(("127.0.0.1", 0))
print(s.getsockname()[1])
s.close()
PY
)"
fi
if [[ -n "$FAKE_PORT" ]]; then
  python3 -c "
import socket, time
s = socket.socket(); s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
s.bind(('127.0.0.1', $FAKE_PORT)); s.listen(1); time.sleep(20)
" &
  FAKE_PID=$!
  sleep 1
  if port_in_use "$FAKE_PORT"; then
    pass "port_in_use: 认出端口 $FAKE_PORT 有人在听"
  else
    failing "port_in_use: 没认出端口 $FAKE_PORT"
  fi
  if native_mysql_on "$FAKE_PORT"; then
    failing "native_mysql_on: 把普通进程当成了 MySQL"
  else
    pass "native_mysql_on: 普通进程不算本机 MySQL"
  fi
  if native_redis_on "$FAKE_PORT"; then
    failing "native_redis_on: 把普通进程当成了 Redis"
  else
    pass "native_redis_on: 普通进程不算本机 Redis"
  fi
  kill "$FAKE_PID" 2>/dev/null || true
  wait "$FAKE_PID" 2>/dev/null || true
else
  skip "python3 没装 —— 端口判定没实测"
fi

# 7.6 .env 模板里的 MySQL/Redis 必须是本机默认端口 (不是 Docker 映射的那些)
TPL_PORT_MY="$(env_get "$SCRIPT_DIR/.env.template" "MYSQL_PORT" || echo "")"
TPL_PORT_RD="$(env_get "$SCRIPT_DIR/.env.template" "REDIS_PORT" || echo "")"
if [[ "$TPL_PORT_MY" == "3306" && "$TPL_PORT_RD" == "6379" ]]; then
  pass ".env 模板用的是本机默认端口 (MySQL 3306 / Redis 6379)"
else
  failing ".env 模板的端口不对 (MySQL=$TPL_PORT_MY Redis=$TPL_PORT_RD) —— 应该用本机默认端口"
fi

# 7.7 装的时候要把"指着容器端口"的配置改回本机端口
if grep -q 'native_mysql_on' "$SCRIPT_DIR/tmctl.sh" && grep -q 'native_redis_on' "$SCRIPT_DIR/tmctl.sh"; then
  pass "tmctl.sh 按监听进程判断本机 MySQL/Redis (不会误连容器端口)"
else
  failing "tmctl.sh 没按监听进程判断 —— 端口被 Docker 映射时会把容器当本机库"
fi
echo

# ==================== 8. shellcheck ====================
echo "── 8. shellcheck ──"
if command -v shellcheck >/dev/null 2>&1; then
  for f in lib.sh preflight.sh tmctl.sh selftest.sh sandbox-probe.sh; do
    if out="$(shellcheck -S warning -e SC1091 "$SCRIPT_DIR/$f" 2>&1)"; then
      pass "$f 无 warning 级问题"
    else
      failing "$f 有问题:"; echo "$out" | head -40 | sed 's/^/      /'
    fi
  done
else
  skip "shellcheck 没装 —— 未静态检查"
fi
echo

# ==================== 汇总 ====================
echo "────────────────────────────"
if [[ $FAIL -gt 0 ]]; then
  echo "✗ 未通过 —— 通过 $PASS / 跳过 $SKIP / 失败 $FAIL"
  exit 1
fi
echo "✓ 通过 —— 通过 $PASS / 跳过 $SKIP / 失败 $FAIL"
exit 0
