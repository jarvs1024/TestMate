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
        <div v-else-if="loadError" class="state err">取数失败: {{ loadError }}</div>
        <div v-else-if="!rows.length" class="state">还没有操作记录</div>
        <ul v-else class="log-list">
          <li v-for="r in rows" :key="r.id" :class="['log-item', r.action]">
            <div class="log-hd">
              <span class="log-act">{{ actionLabel(r) }}</span>
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
        <div v-else-if="notifyError" class="state err">取数失败: {{ notifyError }}</div>
        <div v-else-if="!notifies.length" class="state">还没有通知记录</div>
        <ul v-else class="log-list">
          <li v-for="n in notifies" :key="n.id" :class="['log-item', n.status]">
            <div class="log-hd">
              <span class="log-act">{{ eventLabel(n.event) }}</span>
              <code v-if="n.code" class="log-code">{{ n.code }}</code>
              <span class="log-chip" :class="n.status">
                {{ notifyStatusLabel(n.status) }}
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
import { parseApiTime } from '@/utils/format';
import {
  listAudits, listNotifications, type AssetAudit, type AssetNotification,
} from '@/api/assets';

const props = defineProps<{ modelValue: boolean }>();
const emit = defineEmits<{ (e: 'update:modelValue', v: boolean): void }>();

/**
 * 审计动作的**筛选选项**.
 *
 * ⚠️ 这里只是"筛哪些动作"的下拉项 —— 显示的中文由**后端**给 (item.action_label,
 *    见 market_state.audit_action_label), 前端不再自己翻译:
 *    以前两边各写一份, 结果漏了几个动作 (create/update/approve/reject/submit),
 *    还多一个**永远不会出现**的 unpublish_reject (状态机里没这个迁移).
 */
const ACTIONS = [
  { value: 'all', label: '全部' },
  { value: 'conflict_resolved', label: '同步冲突' },
  { value: 'create', label: '新建' },
  { value: 'update', label: '版本更新' },
  { value: 'publish', label: '重新上架' },
  { value: 'submit', label: '提交审核' },
  { value: 'approve', label: '审核通过' },
  { value: 'reject', label: '审核驳回' },
  { value: 'unpublish_request', label: '申请下架' },
  { value: 'unpublish_cancel', label: '撤销下架' },
  { value: 'unpublish_approve', label: '下架通过' },
  { value: 'take_down', label: '自助下架' },
  { value: 'delete', label: '删除' },
];

const tab = ref('audit');
const actFilter = ref('all');
const loading = ref(false);
const notifyLoading = ref(false);
const loadError = ref('');
const notifyError = ref('');
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

/** 动作中文 —— **后端给的** (action_label), 前端只做兜底 */
function actionLabel(r: { action: string; action_label?: string }): string {
  return r.action_label || r.action;
}

/**
 * 通知回执的状态 → 中文.
 *
 * ⚠️ 2026-10-28 加了**聚合**相关状态 (审核类通知的窗口合并):
 *   aggregated      攒着待汇总 (窗口内没单独发, 窗口末会并进汇总)
 *   summary_sent    这条是**汇总消息**本身 (窗口末发的那一条)
 *   aggregated_sent 已被某条汇总涵盖 (发出去了)
 * ⚠️ 以前只认 sent / failed, 其余一律显示「待发送」—— 新状态会显示成"还没发",
 *    看着像通知丢了.
 */
function notifyStatusLabel(status: string): string {
  return ({
    sent: '已送达',
    failed: '发送失败',
    pending: '待发送',
    skipped: '已跳过',
    aggregated: '攒着待汇总',
    summary_sent: '汇总已送达',
    aggregated_sent: '已并入汇总',
  } as Record<string, string>)[status] || status;
}

/**
 * 通知事件 → 中文.
 * ⚠️ 必须跟后端的 _EVENT_TEXT (app/core/dingtalk.py) **一一对应** ——
 *    以前漏了 unpublish_request, 回执列表里直接显示原始 event id.
 */
function eventLabel(e: string): string {
  return ({
    review: '新资产待审核',
    unpublish_request: '申请下架, 待确认',
    publish: '新资产上架',
    update: '版本更新',
    unpublish: '资产已下架',
    reject: '审核未通过',
    delete: '资产已删除',
  } as Record<string, string>)[e] || e;
}

function fmt(iso: string | null): string {
  if (!iso) return '—';
  // ⚠️ 后端给的是 **UTC** —— 走 parseApiTime, 否则本地时区解析会差 8 小时
  const d = parseApiTime(iso);
  if (!d) return iso;
  return d.toLocaleString('zh-CN', { hour12: false });
}

async function load() {
  loading.value = true;
  loadError.value = '';
  try {
    const r = await listAudits();
    audits.value = r.items || [];
  } catch (e: any) {
    // ⚠️ 取数失败不能伪装成「还没有操作记录」—— 那会误导审计结论
    //    (旧实现 catch 里清空数组, 后端挂了抽屉里也显示"没有记录")
    audits.value = [];
    loadError.value = e?.response?.data?.detail || e?.message || '未知错误';
  } finally {
    loading.value = false;
  }
}

async function loadNotify() {
  notifyLoading.value = true;
  notifyError.value = '';
  try {
    const r = await listNotifications();
    notifies.value = r.items || [];
  } catch (e: any) {
    notifies.value = [];
    notifyError.value = e?.response?.data?.detail || e?.message || '未知错误';
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
.state.err { color: var(--err); }

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
