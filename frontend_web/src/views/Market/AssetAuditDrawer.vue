<template>
  <el-drawer :model-value="modelValue" size="680px" direction="rtl"
             title="市场操作记录" @update:model-value="emit('update:modelValue', $event)">
    <el-tabs v-model="tab" class="ad-tabs">
      <!-- ===== 操作审计 ===== -->
      <el-tab-pane label="操作审计" name="audit">
        <div class="filter-row">
          <button v-for="a in ACTIONS" :key="a.value"
                  class="chip" :class="{ active: actFilter === a.value }"
                  @click="actFilter = a.value">
            {{ a.label }}
            <span v-if="a.value !== 'all'" class="count">{{ countBy(a.value) }}</span>
          </button>
          <button class="reset" @click="load">刷新</button>
        </div>

        <div v-if="loading" class="state">读取中…</div>
        <div v-else-if="!rows.length" class="state">还没有操作记录</div>
        <ul v-else class="log-list">
          <li v-for="r in rows" :key="r.id" :class="['log-item', r.action]">
            <div class="log-hd">
              <span class="log-act">{{ actionLabel(r.action) }}</span>
              <code v-if="r.code" class="log-code">{{ r.code }}</code>
              <span v-if="r.actor_name" class="log-actor">{{ r.actor_name }}</span>
              <span class="log-time mono">{{ fmt(r.created_at) }}</span>
            </div>
            <div v-if="r.comment" class="log-comment">{{ r.comment }}</div>
            <pre v-if="r.detail && Object.keys(r.detail).length" class="log-detail mono">{{
              JSON.stringify(r.detail, null, 2)
            }}</pre>
          </li>
        </ul>
      </el-tab-pane>

      <!-- ===== 通知回执 ===== -->
      <el-tab-pane label="通知回执" name="notify">
        <div class="filter-row">
          <span class="muted-note">
            钉钉通知的送达情况 —— 失败会自动重试, 这里能看见到底送没送到。
          </span>
          <button class="reset" @click="loadNotify">刷新</button>
        </div>

        <div v-if="notifyLoading" class="state">读取中…</div>
        <div v-else-if="!notifies.length" class="state">还没有通知记录</div>
        <ul v-else class="log-list">
          <li v-for="n in notifies" :key="n.id" :class="['log-item', n.status]">
            <div class="log-hd">
              <span class="log-act">{{ eventLabel(n.event) }}</span>
              <code v-if="n.code" class="log-code">{{ n.code }}</code>
              <span class="log-chip" :class="n.status">
                {{ n.status === 'sent' ? '已送达' : n.status === 'failed' ? '发送失败' : '待发送' }}
              </span>
              <span class="log-time mono">{{ fmt(n.last_attempt_at || n.created_at) }}</span>
            </div>
            <div class="log-sub">
              尝试 {{ n.attempts }} 次<span v-if="n.error"> · {{ n.error }}</span>
            </div>
          </li>
        </ul>
      </el-tab-pane>
    </el-tabs>
  </el-drawer>
</template>

<script setup lang="ts">
import { computed, ref, watch } from 'vue';
import {
  listAudits, listNotifications, type AssetAudit, type AssetNotification,
} from '@/api/assets';

const props = defineProps<{ modelValue: boolean }>();
const emit = defineEmits<{ (e: 'update:modelValue', v: boolean): void }>();

const ACTIONS = [
  { value: 'all', label: '全部' },
  { value: 'conflict_resolved', label: '同步冲突' },
  { value: 'publish', label: '上架' },
  { value: 'unpublish', label: '下架' },
  { value: 'delete', label: '删除' },
  { value: 'install', label: '安装' },
  { value: 'uninstall', label: '卸载' },
];

const tab = ref('audit');
const actFilter = ref('all');
const loading = ref(false);
const notifyLoading = ref(false);
const audits = ref<AssetAudit[]>([]);
const notifies = ref<AssetNotification[]>([]);

const rows = computed(() =>
  actFilter.value === 'all'
    ? audits.value
    : audits.value.filter((a) => a.action === actFilter.value),
);

function countBy(action: string): number {
  return audits.value.filter((a) => a.action === action).length;
}

function actionLabel(a: string): string {
  return ACTIONS.find((x) => x.value === a)?.label || a;
}

function eventLabel(e: string): string {
  return ({
    publish: '新资产上架',
    update: '版本更新',
    unpublish: '资产下架',
    delete: '资产删除',
  } as Record<string, string>)[e] || e;
}

function fmt(iso: string | null): string {
  if (!iso) return '—';
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return iso;
  return d.toLocaleString('zh-CN', { hour12: false });
}

async function load() {
  loading.value = true;
  try {
    const r = await listAudits();
    audits.value = r.items || [];
  } catch {
    audits.value = [];
  } finally {
    loading.value = false;
  }
}

async function loadNotify() {
  notifyLoading.value = true;
  try {
    const r = await listNotifications();
    notifies.value = r.items || [];
  } catch {
    notifies.value = [];
  } finally {
    notifyLoading.value = false;
  }
}

watch(() => props.modelValue, (open) => {
  if (!open) return;
  if (tab.value === 'audit') load();
  else loadNotify();
});

watch(tab, (t) => {
  if (t === 'audit') load();
  else loadNotify();
});
</script>

<style scoped>
.ad-tabs { margin-top: -8px; }
.filter-row {
  display: flex; align-items: center; gap: 6px; flex-wrap: wrap; margin-bottom: 12px;
}
.chip {
  background: transparent; border: 1px solid var(--border);
  padding: 4px 11px; border-radius: var(--radius-pill);
  font-size: 12px; color: var(--ink-700); cursor: pointer; font-family: inherit;
  display: inline-flex; align-items: center; gap: 4px;
}
.chip:hover { background: var(--surface-sunken); color: var(--ink-900); }
.chip.active { background: var(--primary-grad); border-color: transparent; color: #fff; font-weight: 600; }
.chip .count {
  font-size: 10.5px; background: rgba(255, 255, 255, 0.25);
  padding: 0 5px; border-radius: var(--radius-pill);
}
.reset {
  margin-left: auto; background: transparent; border: 1px solid var(--border);
  padding: 4px 12px; border-radius: var(--radius-pill);
  font-size: 12px; color: var(--ink-700); cursor: pointer; font-family: inherit;
}
.reset:hover { border-color: var(--primary); color: var(--ink-900); }
.muted-note { font-size: 11.5px; color: var(--ink-500); flex: 1; min-width: 200px; }

.state { padding: 40px 0; text-align: center; color: var(--ink-500); font-size: 13px; }

.log-list { list-style: none; margin: 0; padding: 0; display: flex; flex-direction: column; gap: 8px; }
.log-item {
  border: 1px solid var(--border); border-left: 3px solid var(--border);
  border-radius: var(--radius-sm); padding: 9px 12px; background: var(--surface-soft);
}
.log-item.conflict_resolved { border-left-color: var(--warn); background: rgba(245, 158, 11, 0.06); }
.log-item.delete { border-left-color: var(--err); background: rgba(239, 68, 68, 0.06); }
.log-item.publish { border-left-color: var(--ok); }
.log-item.unpublish { border-left-color: var(--ink-500); }
.log-item.sent { border-left-color: var(--ok); }
.log-item.failed { border-left-color: var(--err); background: rgba(239, 68, 68, 0.06); }
.log-hd { display: flex; align-items: center; gap: 8px; flex-wrap: wrap; }
.log-act { font-size: 12.5px; font-weight: 700; color: var(--ink-900); }
.log-code {
  font-family: var(--font-mono); font-size: 11px; color: var(--ink-700);
  background: var(--surface-sunken); padding: 1px 6px; border-radius: 4px;
}
.log-actor { font-size: 11.5px; color: var(--ink-500); }
.log-time { font-size: 11px; color: var(--ink-500); margin-left: auto; }
.log-comment { margin-top: 4px; font-size: 12px; color: var(--ink-700); }
.log-sub { margin-top: 3px; font-size: 11.5px; color: var(--ink-500); }
.log-detail {
  margin: 6px 0 0; font-size: 10.5px; color: var(--ink-700);
  background: var(--surface-sunken); padding: 6px 8px; border-radius: 4px;
  max-height: 140px; overflow: auto;
}
.log-chip {
  font-size: 10.5px; font-weight: 600; padding: 1px 8px;
  border-radius: var(--radius-pill);
}
.log-chip.sent { background: rgba(16, 185, 129, 0.14); color: var(--ok); }
.log-chip.failed { background: rgba(239, 68, 68, 0.14); color: var(--err); }
.log-chip.pending { background: rgba(245, 158, 11, 0.14); color: var(--warn); }
</style>
