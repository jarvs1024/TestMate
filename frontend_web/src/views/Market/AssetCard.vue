<template>
  <div class="asset-card" :class="{ 'is-installed': item.installed }"
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
        <span v-if="item.publish_status === 'pending'" class="ac-badge pending"
              title="已提交, 等待管理员审核; 通过后才在市场里可见">📋 待审核</span>
        <span v-else-if="item.publish_status === 'rejected'" class="ac-badge rejected"
              :title="item.review_note || '审核未通过'">❌ 已驳回</span>
        <span v-else-if="item.publish_status === 'unpublished'" class="ac-badge off"
              title="已从市场下架, 文件仍保留">⚠️ 已下架</span>
        <span v-if="item.updatable" class="ac-badge updatable"
              title="已安装, 但仓库里有了新版本">↑ 可更新</span>
        <span v-else-if="item.installed" class="ac-badge installed"
              title="已安装到本机">✓ 已安装</span>
        <span v-if="item.sync_status === 'staged'" class="ac-badge staged"
              title="已保存到本地工作区, 正在同步到 GitLab">🕐 待同步</span>
        <span v-else-if="item.sync_status === 'failed'" class="ac-badge failed"
              :title="item.last_error || '同步到 GitLab 失败, 点击卡片查看详情'">❌ 同步失败</span>
      </div>
    </div>

    <p class="ac-summary">{{ item.summary }}</p>

    <div class="ac-tags">
      <span v-for="t in item.tags.slice(0, 3)" :key="t" class="tag">#{{ t }}</span>
      <span v-if="permBadge" class="tag tag-perm" :title="permTitle">🔐 {{ permBadge }}</span>
    </div>

    <div class="ac-meta">
      <span class="meta-item">⬇ {{ item.install_count }}</span>
      <span class="meta-item">· {{ item.author || '未知' }}</span>
      <span class="meta-item">· {{ shortDate(item.updated_at) }}</span>
    </div>
  </div>
</template>

<script setup lang="ts">
import { computed } from 'vue';
import type { AssetItem } from '@/api/assets';

const props = defineProps<{ item: AssetItem }>();
const emit = defineEmits<{ (e: 'open', item: AssetItem): void }>();

function shortDate(iso: string | null): string {
  if (!iso) return '—';
  return iso.slice(0, 10);
}

/** 权限摘要角标: 有敏感权限才提示, 纯文本技能不显示。
 *  后端 permissions 是自由 dict, 各 key 可能缺失, 一律用 ?? [] 兜底. */
const permCount = computed(() => {
  const p = props.item.permissions ?? {};
  return (
    (p.filesystem_read?.length ?? 0) + (p.filesystem_write?.length ?? 0) +
    (p.network?.length ?? 0) + (p.process_exec?.length ?? 0) +
    (p.secrets?.length ?? 0)
  );
});
const permBadge = computed(() => (permCount.value > 0 ? `${permCount.value} 项权限` : ''));
const permTitle = computed(() => {
  const p = props.item.permissions ?? {};
  const lines: string[] = [];
  if (p.filesystem_read?.length) lines.push(`读取: ${p.filesystem_read.join(', ')}`);
  if (p.filesystem_write?.length) lines.push(`写入: ${p.filesystem_write.join(', ')}`);
  if (p.network?.length) lines.push(`网络: ${p.network.join(', ')}`);
  if (p.process_exec?.length) lines.push(`执行: ${p.process_exec.join(', ')}`);
  if (p.secrets?.length) lines.push(`凭据: ${p.secrets.join(', ')}`);
  return lines.join('\n');
});
</script>

<style scoped>
.asset-card {
  cursor: pointer;
  transition: transform 0.15s ease, box-shadow 0.15s ease, border-color 0.15s ease;
  display: flex;
  flex-direction: column;
  gap: 11px;
  min-height: 178px;
}
.asset-card:hover {
  transform: translateY(-2px);
  border-color: var(--primary);
  box-shadow: 0 8px 24px rgba(59, 130, 246, 0.12), 0 0 0 3px var(--primary-soft);
}
.asset-card:focus-visible {
  outline: 2px solid var(--primary);
  outline-offset: 2px;
}

.ac-hd { display: flex; align-items: flex-start; gap: 12px; }
.ac-icon {
  width: 40px; height: 40px;
  border-radius: 11px;
  background: linear-gradient(135deg, var(--primary), var(--primary-2));
  display: flex; align-items: center; justify-content: center;
  font-size: 20px;
  flex-shrink: 0;
  box-shadow: var(--primary-shadow);
}
.ac-title { flex: 1; min-width: 0; }
.ac-name {
  font-size: 15px; font-weight: 700; color: var(--ink-900); line-height: 1.25;
  overflow: hidden; text-overflow: ellipsis; white-space: nowrap;
}
.ac-ver {
  font-size: 11px; color: var(--ink-500); margin-top: 3px;
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
.ac-badge.installed { background: rgba(16, 185, 129, 0.12); color: var(--ok); }
.ac-badge.updatable { background: rgba(245, 158, 11, 0.14); color: var(--warn); }
.ac-badge.staged { background: rgba(245, 158, 11, 0.12); color: var(--warn); }
.ac-badge.failed { background: rgba(239, 68, 68, 0.12); color: var(--err); }
.ac-badge.pending { background: rgba(59, 130, 246, 0.14); color: var(--primary); }
.ac-badge.rejected { background: rgba(239, 68, 68, 0.12); color: var(--err); }
.ac-badge.off { background: rgba(107, 114, 128, 0.14); color: var(--ink-600, #6b7280); }

.ac-summary {
  margin: 0;
  font-size: 13px;
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
  font-size: 10.5px;
  color: var(--ink-500);
  background: var(--surface-sunken);
  padding: 2px 7px;
  border-radius: var(--radius-sm);
  font-family: var(--font-mono);
}
.tag-perm { color: var(--warn); background: rgba(245, 158, 11, 0.10); }

.ac-meta {
  display: flex; gap: 5px; flex-wrap: wrap;
  padding-top: 9px;
  border-top: 1px dashed var(--border);
  font-size: 10.5px;
  color: var(--ink-500);
  font-family: var(--font-mono);
}
.meta-item { display: inline-flex; align-items: center; gap: 3px; }
.meta-item.ok { color: var(--ok); }
</style>
