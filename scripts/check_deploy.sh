#!/usr/bin/env bash
# 部署一致性自检 —— **源码改了, 线上 bundle 是不是也跟着改了?**
#
# ⚠️ 2026-10-25 踩过的坑: 改了前端源码却忘了 npm run build → 线上跑的还是旧
#    bundle → e2e 三轮全绿, 测的却是旧代码, 一个已修的 bug 其实还在线上.
#    这个脚本就是拿来当场揭穿这种漂移的.
#
# 用法: scripts/check_deploy.sh
set -e
cd "$(dirname "$0")/.."

CONTAINER="${CONTAINER:-test-mate-frontend-1}"
HTML_DIR="/usr/share/nginx/html"

# 从源码里挑几个**只在前端源码出现**的特征串 (要够独特, 别用通用词)
FEATURES=(
  "安装包名长度要在"          # assetForm.ts: code 长度校验
  "资产 code 必须与安装包名一致"  # assetForm.ts: 一致性校验
  "code 与名称一致"           # 上传抽屉: 缺项清单
  "不会跟现有资产重复"         # 图标提示
  "只填一段 MCP JSON 配置"     # kindMeta.ts
  "选择安装包"                 # 上传抽屉: 自定义的文件选择按钮
  "自动取安装包名"             # 资产 code 的派生来源说明
  "适用项目"                  # 2026-10-25: 「适用范围」改名
  "选好包后自动生成"            # 2026-10-25: 没选包时 code 显示占位, 不露初始 dml-
  "的名字只能用小写字母/数字/连字符 (如 my-connector)"   # 2026-10-25: 更新存量连接器时不强制 dml- 前缀
  "搜索名称、说明、标签或项目号"    # 2026-10-25: 搜索支持按项目
  "本页上次刷新"               # 2026-10-25: 市场页自动刷新 + 页脚时间戳
  "导入这个压缩包即可安装"        # 2026-10-25: 下载提示通用化
  "全部项目"                  # 2026-10-25: 项目+排序合并成一个下拉
)

echo "=== 源码里有没有这些特征串 (确认我们测的是当前代码) ==="
missing_src=0
for f in "${FEATURES[@]}"; do
  if grep -rq "$f" frontend_web/src 2>/dev/null; then
    printf "  ✓ %s\n" "$f"
  else
    printf "  ✗ %s  ← 源码里没有, 特征串可能过期了\n" "$f"
    missing_src=1
  fi
done
if [ "$missing_src" -ne 0 ]; then
  echo "❌ 特征串与源码对不上 —— 先更新 scripts/check_deploy.sh 里的 FEATURES"
  exit 2
fi

echo
echo "=== 线上 bundle 里有没有 (确认部署跟上了源码) ==="
if ! docker ps --format '{{.Names}}' | grep -qx "$CONTAINER"; then
  echo "❌ 容器 $CONTAINER 不在跑"
  exit 2
fi

missing=0
for f in "${FEATURES[@]}"; do
  if docker exec "$CONTAINER" sh -lc "grep -rl '$f' $HTML_DIR/assets/*.js >/dev/null 2>&1"; then
    printf "  ✓ %s\n" "$f"
  else
    printf "  ✗ %s  ← 线上 bundle 里没有! 该重新部署\n" "$f"
    missing=1
  fi
done

echo
if [ "$missing" -ne 0 ]; then
  echo "❌ 线上 bundle 与源码漂移 —— 跑 scripts/deploy.sh frontend 再验证"
  exit 1
fi
echo "✅ 线上 bundle 与源码一致"

# ---------- 后端: 源码 ↔ 容器 ----------
# ⚠️ 前端有特征串可查, 后端没有 —— 以前改了后端忘部署, 查不出来.
#    这里直接比 sha256: 源码跟容器里的文件不一致 = 漂移.
BACKEND_CONTAINER="${BACKEND_CONTAINER:-test-mate-backend-1}"
BACKEND_FILES=(
  app/api/marketplace.py
  app/core/dingtalk.py
  app/core/market_state.py
  app/core/market_notify.py
  app/core/mcp_config.py
  app/schemas/asset.py
)
echo
echo "=== 后端: 容器里的代码跟源码对得上吗 ==="
if ! docker ps --format '{{.Names}}' | grep -qx "$BACKEND_CONTAINER"; then
  echo "❌ 容器 $BACKEND_CONTAINER 不在跑"
  exit 2
fi
drift=0
for f in "${BACKEND_FILES[@]}"; do
  local_sum=$(shasum -a 256 "backend_gateway/$f" | cut -d' ' -f1)
  ctr_sum=$(docker exec "$BACKEND_CONTAINER" sh -lc "sha256sum /app/$f 2>/dev/null | cut -d' ' -f1")
  if [ "$local_sum" = "$ctr_sum" ]; then
    printf "  ✓ %s\n" "$f"
  else
    printf "  ✗ %s  ← 容器里跟源码不一样! 该重新部署后端\n" "$f"
    drift=1
  fi
done
if [ "$drift" -ne 0 ]; then
  echo "❌ 后端容器与源码漂移 —— 跑 scripts/deploy.sh backend 再验证"
  exit 1
fi
echo "✅ 后端容器与源码一致"
