<template>
  <div class="asset-card"
       role="button" :tabindex="0"
       @click="emit('open', item)"
       @keydown.enter="emit('open', item)"
       @keydown.space.prevent="emit('open', item)">
    <div class="ac-hd">
      <div class="ac-icon">{{ item.icon }}</div>
      <div class="ac-title">
        <div class="ac-name">{{ item.name }}</div>
        <div class="ac-ver">{{ item.version }} · {{ item.category }}</div>
      </div>
      <!-- 状态是**每张卡片自己的属性**, 不再做成视图筛选 -->
      <div class="ac-badges">
        <!-- 适用项目: 项目特有的才标 (通用的不占地方) -->
        <span v-if="item.project" class="ac-badge proj"
              :title="`只对 ${item.project} 项目有意义`">📁 {{ item.project }} 项目</span>
        <span v-if="item.publish_status === 'pending'" class="ac-badge pending"
              title="已提交, 等待管理员审核; 通过后才在市场里可见">📋 待审核</span>
        <span v-else-if="item.publish_status === 'rejected'" class="ac-badge rejected"
              :title="item.review_note || '审核未通过'">❌ 已驳回</span>
        <span v-else-if="item.publish_status === 'unpublished'" class="ac-badge off"
              title="已从市场下架, 文件仍保留">⚠️ 已下架</span>
        <span v-else-if="item.publish_status === 'unpublish_pending'" class="ac-badge unp"
              title="已申请下架, 等管理员确认; 确认后资产会被彻底删除">⏳ 待下架审核</span>
        <span v-if="item.sync_status === 'staged'" class="ac-badge staged"
              title="已保存到本地工作区, 正在同步到 GitLab">🕐 待同步</span>
        <span v-else-if="item.sync_status === 'failed'" class="ac-badge failed"
              :title="item.last_error || '同步到 GitLab 失败, 点击卡片查看详情'">❌ 同步失败</span>
      </div>
    </div>

    <p class="ac-summary">{{ item.summary }}</p>

    <div class="ac-tags">
      <span v-for="t in item.tags.slice(0, 3)" :key="t" class="tag">#{{ t }}</span>
      <!-- ⚠️ 权限角标去掉了 (2026-10-25 用户要求): 卡片是"这资产有什么用"的门面,
           权限这种"安装前要看的东西"放卡片上只会让人觉得有风险, 详情页/安装说明里说就行.
           permissions 字段后端仍保留 —— 只是不展示了. -->
    </div>

    <div class="ac-meta">
      <span class="meta-item" :title="`已下载 ${item.download_count || 0} 次`">⬇ {{ item.download_count || 0 }}</span>
      <span class="meta-item">{{ item.author || '未知' }}</span>
      <span class="meta-item">· {{ shortDate(item.updated_at) }}</span>
    </div>
  </div>
</template>

<script setup lang="ts">
import type { AssetItem } from '@/api/assets';

defineProps<{ item: AssetItem }>();
const emit = defineEmits<{ (e: 'open', item: AssetItem): void }>();

function shortDate(iso: string | null): string {
  if (!iso) return '—';
  return iso.slice(0, 10);
}
</script>

<style scoped>
/* ⚠️ 市场页的卡片是**扁平紧凑列表卡** (4 列) ——
   跟首页能力墙的"白底浮动大卡片" (3 列, 全局 .card) 拉开密度差, 一眼能分清两个页面. */
.asset-card {
  cursor: pointer;
  transition: box-shadow 0.15s ease, border-color 0.15s ease;
  display: flex;
  flex-direction: column;
  gap: 9px;
  min-height: 150px;
}
.asset-card:hover {
  /* ⚠️ 刻意**不抬升** (没有 translateY) —— 能力墙卡片是浮起来的, 这里保持"列表感" */
  border-color: var(--primary);
  box-shadow: 0 4px 14px rgba(59, 130, 246, 0.10);
}
.asset-card:focus-visible {
  outline: 2px solid var(--primary);
  outline-offset: 2px;
}

.ac-hd { display: flex; align-items: flex-start; gap: 10px; }
.ac-icon {
  width: 34px; height: 34px;
  border-radius: 9px;
  background: linear-gradient(135deg, var(--primary), var(--primary-2));
  display: flex; align-items: center; justify-content: center;
  font-size: 17px;
  flex-shrink: 0;
  box-shadow: var(--primary-shadow);
}
.ac-title { flex: 1; min-width: 0; }
.ac-name {
  font-size: 14px; font-weight: 700; color: var(--ink-900); line-height: 1.25;
  overflow: hidden; text-overflow: ellipsis; white-space: nowrap;
}
.ac-ver {
  font-size: 10.5px; color: var(--ink-500); margin-top: 2px;
  font-family: var(--font-mono);
  overflow: hidden; text-overflow: ellipsis; white-space: nowrap;
}

/* 状态徽标: 一张卡片可能同时带多个 (已安装 + 待审核 …) */
.ac-badges {
  display: flex; align-items: center; gap: 5px; flex-wrap: wrap;
  justify-content: flex-end; flex-shrink: 0; max-width: 46%;
}
.ac-badge {
  display: inline-flex; align-items: center;
  padding: 3px 8px; border-radius: var(--radius-pill);
  font-size: 10.5px; font-weight: 600; white-space: nowrap;
}
.ac-badge.staged { background: rgba(245, 158, 11, 0.12); color: var(--warn); }
.ac-badge.failed { background: rgba(239, 68, 68, 0.12); color: var(--err); }
.ac-badge.pending { background: rgba(59, 130, 246, 0.14); color: var(--primary); }
.ac-badge.rejected { background: rgba(239, 68, 68, 0.12); color: var(--err); }
.ac-badge.off { background: rgba(107, 114, 128, 0.14); color: var(--ink-600, #6b7280); }
.ac-badge.unp { background: rgba(245, 158, 11, 0.14); color: var(--warn); }
/* 适用项目: 项目特有 —— 用中性蓝, 跟状态徽标(红/黄/蓝)区分开 */
.ac-badge.proj { background: rgba(20, 184, 166, 0.14); color: var(--primary-2); }

.ac-summary {
  margin: 0;
  font-size: 12.5px;
  color: var(--ink-700);
  line-height: 1.55;
  flex: 1;
  display: -webkit-box;
  -webkit-line-clamp: 2;
  line-clamp: 2;
  -webkit-box-orient: vertical;
  overflow: hidden;
}

.ac-tags { display: flex; flex-wrap: wrap; gap: 5px; }
.tag {
  font-size: 10px;
  color: var(--ink-500);
  background: var(--surface-sunken);
  padding: 2px 6px;
  border-radius: var(--radius-sm);
  font-family: var(--font-mono);
}

.ac-meta {
  display: flex; gap: 5px; flex-wrap: wrap;
  padding-top: 8px;
  border-top: 1px dashed var(--border);
  font-size: 10px;
  color: var(--ink-500);
  font-family: var(--font-mono);
}
.meta-item { display: inline-flex; align-items: center; gap: 3px; }
.meta-item.ok { color: var(--ok); }
</style>
