#!/usr/bin/env bash
# 把整套 TestMate 依赖的 docker 镜像打包成 .tar,搬到内网服务器 load 进去。
# 用法:
#   在能上网的机器上: ./deploy/offline-save.sh /tmp/testmate-images
#   拷贝 /tmp/testmate-images 到内网服务器,执行:
#     sudo ./deploy/deploy.sh --offline --offline-dir /tmp/testmate-images
#
# 镜像列表在 deploy/offline-images.txt,缺啥加啥。

set -euo pipefail

OUT_DIR="${1:-./offline-images}"
mkdir -p "$OUT_DIR"

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
LIST_FILE="$SCRIPT_DIR/offline-images.txt"

[[ -f "$LIST_FILE" ]] || { echo "缺 $LIST_FILE"; exit 1; }

log() { echo "[offline-save] $*"; }

# 先 build,确保 backend / frontend 镜像本地有
log "构建 backend / frontend 本地镜像..."
(cd "$SCRIPT_DIR/.." && docker compose -f deploy/docker-compose.yml build backend frontend)

# 读镜像清单,把 backend/frontend 加进去(因为是 build 出来的,本地才有)
{
  cat "$LIST_FILE"
  echo "test-mate-backend:latest"
  echo "test-mate-frontend:latest"
} > "$OUT_DIR/_list.txt"

log "拉取 / save 镜像到 $OUT_DIR..."
while read -r img; do
  [[ -z "$img" || "$img" =~ ^# ]] && continue
  log "  pull $img"
  docker pull "$img"
  safe_name="$(echo "$img" | tr '/: ' '___')"
  log "  save -> $OUT_DIR/${safe_name}.tar"
  docker save -o "$OUT_DIR/${safe_name}.tar" "$img"
done < "$OUT_DIR/_list.txt"

rm -f "$OUT_DIR/_list.txt"

log "完成。镜像包列表:"
ls -lh "$OUT_DIR"
echo
echo "下一步: 拷贝 $OUT_DIR 到目标服务器,然后:"
echo "  sudo ./deploy/deploy.sh --offline --offline-dir $OUT_DIR"
