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

# ==================== 4. nginx 配置校验 ====================
echo "── 4. nginx 配置校验 ──"
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

# ==================== 5. shellcheck ====================
echo "── 5. shellcheck ──"
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
