#!/usr/bin/env bash
# TestMate 数据备份(对齐设计文档 §11.3)
# 用法:
#   sudo ./deploy/backup.sh                  # 备份到默认 /var/backups/testmate
#   sudo ./deploy/backup.sh /path/to/backup  # 自定义备份目录
# 配合 cron 每天凌晨 3 点:
#   0 3 * * * /opt/testmate/deploy/backup.sh /var/backups/testmate

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
cd "$SCRIPT_DIR"

BACKUP_DIR="${1:-/var/backups/testmate}"
DATE="$(date +%F-%H%M)"
mkdir -p "$BACKUP_DIR"

log() { echo "[backup] $*"; }

[[ -f .env ]] || { echo "缺 .env,先 cp .env.template .env"; exit 1; }

# shellcheck disable=SC1091
set -a; source .env; set +a

COMPOSE="docker compose --env-file .env"

log "1/2 MySQL dump..."
$COMPOSE exec -T mysql mysqldump \
  -uroot -p"${MYSQL_ROOT_PASSWORD}" \
  --single-transaction --routines --triggers \
  "${MYSQL_DATABASE}" | gzip > "$BACKUP_DIR/mysql-${DATE}.sql.gz"

log "2/2 Redis snapshot..."
$COMPOSE exec -T redis sh -c "redis-cli save && cat /data/dump.rdb" \
  > "$BACKUP_DIR/redis-${DATE}.rdb"

# 保留最近 14 天,清理旧的
find "$BACKUP_DIR" -type f -mtime +14 -name 'testmate-*' -delete 2>/dev/null || true

ls -lh "$BACKUP_DIR"/*"${DATE}"*
log "备份完成 -> $BACKUP_DIR"
