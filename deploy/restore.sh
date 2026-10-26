#!/usr/bin/env bash
# TestMate 数据恢复 — 把 backup.sh 产生的备份反向灌回去
#
# 用法:
#   sudo ./deploy/restore.sh /var/backups/testmate
#   sudo ./deploy/restore.sh /var/backups/testmate --dry-run
#
# ⚠️ 传的是**备份目录本身** (backup.sh 的产物直接平铺在目录里, 不带日期子目录),
#    脚本在目录里挑 mysql-* / redis-* 最新的那份恢复.
#
# 行为:
#   1. 验证目标目录里 mysql-*.sql.gz + redis-*.rdb 都在
#   2. 在跑着的 mysql 容器里 source SQL(不会 drop 现有库,只是把数据写进去;
#      如果想完全替换,先 truncate)
#   3. redis: stop 容器 → 换 dump.rdb → 清 AOF → start (AOF 优先于 RDB, 不清等于没恢复)
#   4. 跑 SELECT 1 + 关键表 row count 验证恢复成功
#
# 跟 backup.sh 配对使用。

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
cd "$SCRIPT_DIR"

BACKUP_DIR="${1:-}"
DRY_RUN=0
if [[ -z "$BACKUP_DIR" ]]; then
  echo "用法: $0 <备份目录> [--dry-run]" >&2
  echo "示例: $0 /var/backups/testmate" >&2
  exit 2
fi
if [[ "${2:-}" == "--dry-run" ]]; then
  DRY_RUN=1
fi

if [[ ! -d "$BACKUP_DIR" ]]; then
  echo "❌ 备份目录不存在: $BACKUP_DIR" >&2
  exit 2
fi

# shellcheck disable=SC1091
[[ -f .env ]] || { echo "❌ 缺 deploy/.env,先 cp deploy/.env.template deploy/.env && \$EDITOR deploy/.env" >&2; exit 1; }
set -a; source .env; set +a

# 目录里找最新一份 (按文件名排序, backup.sh 命名带时间戳)
shopt -s nullglob
MYSQL_FILES=("$BACKUP_DIR"/mysql-*.sql.gz)
REDIS_FILES=("$BACKUP_DIR"/redis-*.rdb)
shopt -u nullglob

if [[ ${#MYSQL_FILES[@]} -eq 0 ]]; then
  echo "❌ 备份目录里没有 mysql-*.sql.gz: $BACKUP_DIR" >&2
  exit 2
fi
if [[ ${#REDIS_FILES[@]} -eq 0 ]]; then
  echo "❌ 备份目录里没有 redis-*.rdb: $BACKUP_DIR" >&2
  exit 2
fi

# 取最新的(按文件名排序,backup.sh 命名带时间戳)
MYSQL_FILE="$(ls -1 "${MYSQL_FILES[@]}" | sort | tail -1)"
REDIS_FILE="$(ls -1 "${REDIS_FILES[@]}" | sort | tail -1)"

echo "[restore] 备份目录: $BACKUP_DIR"
echo "[restore] MySQL 备份: $MYSQL_FILE ($(stat -c %s "$MYSQL_FILE") bytes)"
echo "[restore] Redis 备份: $REDIS_FILE ($(stat -c %s "$REDIS_FILE") bytes)"
echo

if [[ $DRY_RUN -eq 1 ]]; then
  echo "[restore] --dry-run: 不执行任何写入,只显示将做什么"
  echo "  - 校验: gunzip -t $MYSQL_FILE (sql 完整性)"
  echo "  - mysql 容器内: gunzip | mysql -uroot -p... $MYSQL_DATABASE"
  echo "  - redis 容器: stop → cp dump.rdb → 清 AOF → start"
  echo "  - 验证: SELECT 1 + 关键表 row count"
  exit 0
fi

COMPOSE="docker compose --env-file .env"

# 校验 SQL 完整性
echo "[restore] 1/4 校验 SQL 完整性..."
gunzip -t "$MYSQL_FILE" || { echo "❌ SQL 文件不完整"; exit 1; }
echo "  ✓ SQL 文件完整"

# MySQL 灌回去
echo "[restore] 2/4 MySQL 恢复..."
gunzip -c "$MYSQL_FILE" | $COMPOSE exec -T mysql mysql \
  -uroot -p"${MYSQL_ROOT_PASSWORD}" \
  "${MYSQL_DATABASE}"
echo "  ✓ MySQL 数据已恢复"

# Redis 灌回去 — 备份是 RDB 快照, 必须**停服换文件**:
#   ① stop 容器  ② 拷 dump.rdb 进去  ③ 清掉 AOF  ④ 再 start
# ⚠️ redis 容器开着 `--appendonly yes` (docker-compose.yml), **AOF 优先级高于 RDB** ——
#    不清 AOF 就重启的话, redis 加载的是旧 AOF (还是空库), 刚拷进去的 RDB 被无视,
#    旧实现 `FLUSHALL + cp + restart` 恢复后就是空库 (FLUSHALL 还写进了 AOF).
echo "[restore] 3/4 Redis 恢复..."
$COMPOSE stop redis >/dev/null
# 把 rdb 复制进容器,替换 dump.rdb (stop 状态下 cp 一样可用)
$COMPOSE cp "$REDIS_FILE" redis:/data/dump.rdb
# 清 AOF: redis 7 的多段 AOF 在 /data/appendonlydir/, 老版单文件是 appendonly.aof —— 两个都清
$COMPOSE run --rm --no-deps --entrypoint sh redis -c \
  "rm -rf /data/appendonlydir /data/appendonly.aof" >/dev/null
$COMPOSE start redis
echo "  ✓ Redis 数据已恢复"

# 验证
echo "[restore] 4/4 验证恢复结果..."
HEALTH_JSON=$($COMPOSE exec -T mysql mysql -uroot -p"${MYSQL_ROOT_PASSWORD}" "${MYSQL_DATABASE}" -e "
  SELECT 'users_count', COUNT(*) FROM users
  UNION ALL
  SELECT 'agents_count', COUNT(*) FROM agents
  UNION ALL
  SELECT 'machines_count', COUNT(*) FROM machines
  UNION ALL
  SELECT 'system_settings_count', COUNT(*) FROM system_settings;
" 2>&1)
echo "$HEALTH_JSON" | grep -v "Using a password" | head -10

REDIS_PONG=$($COMPOSE exec -T redis redis-cli ping 2>&1 | tr -d '\r')
if [[ "$REDIS_PONG" == "PONG" ]]; then
  echo "  ✓ Redis PING OK"
else
  echo "  ❌ Redis 验证失败: $REDIS_PONG"
  exit 1
fi

echo
echo "[restore] ✅ 恢复完成"
echo "  - MySQL: 4 个核心表 row count 已输出"
echo "  - Redis: PING OK"
echo "  - 下一步: 跑 deploy.sh 重新拉起应用栈,后端 alembic upgrade head 会幂等"
