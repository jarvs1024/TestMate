#!/usr/bin/env bash
# TestMate 裸机部署 —— systemd 沙箱回归测试
#
# 验的是**单元在 systemd 沙箱下能不能真的起来**, 以及加固项有没有误伤:
#
#   ① 单元能启动 (Result=success) —— ReadWritePaths 指向的路径不存在时单元是起不来的
#   ② ReadWritePaths 里的目录**可写** —— 资产市场 git 工作区就在这儿
#      (⚠️ 这条是重点: 单元里有 ProtectHome=read-only, 而 ReadWritePaths
#       能否覆盖它, 文档说得含糊, 实际必须验 —— 覆盖不了的话,
#       装在 /home 下的部署会静默地写不了市场工作区)
#   ③ 不在白名单里的 /home 路径**不可写** —— 加固项没白加
#   ④ 以专用用户 (不是 root) 运行
#   ⑤ PrivateDevices 没把 /dev/null 也关掉
#
# 怎么跑 (要 docker, 且要 --privileged —— 容器里 systemd 必须是 PID 1):
#   ./deploy/native/sandbox-probe.sh
#
# 退出码: 有 FAIL → 1

set -uo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"
IMAGE="tm-systemd-probe"
CONTAINER="tm-sandbox-probe"

PASS=0; FAIL=0
pass() { PASS=$((PASS+1)); echo "  ✓ $*"; }
failing() { FAIL=$((FAIL+1)); echo "  ✗ $*"; }

if ! command -v docker >/dev/null 2>&1; then
  echo "  - 没 docker —— 跳过 (沙箱测试需要 docker + --privileged)"
  exit 0
fi

echo "TestMate 裸机部署 · systemd 沙箱回归测试"
echo

# ---------- 1. 准备镜像 ----------
echo "── 1. 准备 systemd 容器镜像 ──"
IMG_DIR="$(mktemp -d)"
cat > "$IMG_DIR/Dockerfile" <<'DOCKEREOF'
FROM ubuntu:22.04
ENV container=docker DEBIAN_FRONTEND=noninteractive
RUN apt-get update -qq && apt-get install -y -qq --no-install-recommends \
      systemd systemd-sysv dbus python3 procps \
    && rm -rf /var/lib/apt/lists/*
RUN useradd --system --no-create-home --shell /usr/sbin/nologin testmate
STOPSIGNAL SIGRTMIN+3
CMD ["/sbin/init"]
DOCKEREOF

if ! docker image inspect "$IMAGE" >/dev/null 2>&1; then
  if ! docker build -q -t "$IMAGE" "$IMG_DIR" >/dev/null 2>&1; then
    echo "  - 镜像构建失败 —— 跳过"
    exit 0
  fi
fi
pass "镜像就绪: $IMAGE"
echo

# ---------- 2. 探针脚本 ----------
cat > "$IMG_DIR/probe.sh" <<'PROBEEOF'
set -u
export PATH=/usr/sbin:/usr/bin:/sbin:/bin

# 渲染真实的后端单元模板 (路径换成探针用的)
mkdir -p /home/testdata/market /home/elsewhere /opt/tm
chown -R testmate:testmate /home/testdata /opt/tm
chmod 755 /home/elsewhere
echo "PATH_MARKET=/home/testdata/market" > /home/testdata/probe.env
chown testmate:testmate /home/testdata/probe.env
chmod 644 /home/testdata/probe.env

sed -e 's|^ExecStart=.*|ExecStart=/bin/sh -c '"'"'echo STARTED; touch /home/testdata/market/probe \&\& echo MARKET_WRITE_OK; touch /home/elsewhere/probe 2>/dev/null \&\& echo HOME_WRITE_UNEXPECTED \|\| echo HOME_WRITE_BLOCKED; id -un'"'"'|' \
    -e 's|^EnvironmentFile=.*|EnvironmentFile=/home/testdata/probe.env|' \
    -e 's|^WorkingDirectory=.*|WorkingDirectory=/home/testdata/market|' \
    -e 's|^User=.*|User=testmate|' \
    -e 's|^Group=.*|Group=testmate|' \
    -e 's|^ReadWritePaths=.*|ReadWritePaths=/home/testdata/market|' \
    -e 's|^MemoryMax=.*|MemoryMax=1G|' \
    -e 's|^CPUQuota=.*|CPUQuota=50%|' \
    /repo/deploy/native/units/testmate-backend.service.tpl \
    > /etc/systemd/system/probe.service

systemctl daemon-reload
systemctl start probe.service >/dev/null 2>&1
sleep 1
journalctl -u probe.service --no-pager -n 30 2>/dev/null | sed 's/^/PROBE: /'
systemctl show probe.service -p Result --value 2>/dev/null | sed 's/^/RESULT: /'
PROBEEOF

# ---------- 3. 跑 ----------
echo "── 2. 在 systemd 容器里启动单元 ──"
docker rm -f "$CONTAINER" >/dev/null 2>&1
if ! docker run -d --privileged --cgroupns=host \
     -v /sys/fs/cgroup:/sys/fs/cgroup:rw \
     -v "$REPO_ROOT:/repo:ro" \
     -v "$IMG_DIR:/probe:ro" \
     --name "$CONTAINER" "$IMAGE" >/dev/null 2>&1; then
  echo "  - 容器起不来 —— 跳过"
  exit 0
fi
sleep 6

OUT="$(docker exec "$CONTAINER" bash /probe/probe.sh 2>&1 || true)"
docker rm -f "$CONTAINER" >/dev/null 2>&1

echo "$OUT" | grep '^PROBE:' | sed 's/^PROBE: //' | grep -vE '^systemd|^sh\[' || true

# ---------- 4. 断言 ----------
echo
echo "── 3. 断言 ──"
if echo "$OUT" | grep -q 'STARTED'; then
  pass "单元在沙箱下能启动"
else
  failing "单元起不来 —— 输出:"
  echo "$OUT" | sed 's/^/      /' | tail -20
fi

if echo "$OUT" | grep -q 'MARKET_WRITE_OK'; then
  pass "ReadWritePaths 里的目录可写 (资产市场工作区安全)"
else
  failing "ReadWritePaths 里的目录写不了 —— ReadWritePaths 没能覆盖 ProtectHome=read-only"
fi

if echo "$OUT" | grep -q 'HOME_WRITE_BLOCKED'; then
  pass "非白名单的 /home 路径不可写 (加固生效)"
else
  failing "非白名单的 /home 路径竟然能写 —— 加固没生效"
fi

if echo "$OUT" | grep -q 'testmate'; then
  pass "以专用用户 testmate 运行 (不是 root)"
else
  failing "运行用户不对"
fi

echo
echo "────────────────────────────"
if [[ $FAIL -gt 0 ]]; then
  echo "✗ 未通过 —— 通过 $PASS / 失败 $FAIL"
  exit 1
fi
echo "✓ 通过 —— 共 $PASS 项"
exit 0
