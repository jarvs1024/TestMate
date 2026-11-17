<template>
  <div class="notif-page">
    <div class="mk-actions">
      <div class="kind-tabs" role="tablist" aria-label="消息筛选">
        <button
          type="button"
          class="kind-tab"
          role="tab"
          :aria-selected="filter === 'all'"
          :class="{ active: filter === 'all' }"
          @click="setFilter('all')"
        >全部</button>
        <button
          type="button"
          class="kind-tab"
          role="tab"
          :aria-selected="filter === 'unread'"
          :class="{ active: filter === 'unread' }"
          @click="setFilter('unread')"
        >未读</button>
      </div>
      <div class="ma-right">
        <span class="nt-count">未读 <b>{{ unread }}</b></span>
        <el-button size="small" :disabled="!unread" @click="readAll">全部标为已读</el-button>
      </div>
    </div>

    <div v-if="loading" class="nt-state">加载中…</div>
    <div v-else-if="loadError" class="nt-state err">
      <span>{{ loadError }}</span>
      <el-button size="small" @click="reload">重试</el-button>
    </div>
    <div v-else-if="!items.length" class="nt-state">{{ filter === 'unread' ? '没有未读消息' : '还没有消息' }}</div>
    <ul v-else class="nt-list">
      <li
        v-for="n in items"
        :key="n.id"
        class="nt-row"
        :class="{ unread: !n.read_at }"
        @click="openItem(n)"
      >
        <span class="nt-dot" aria-hidden="true" />
        <div class="nt-main">
          <div class="nt-title">{{ n.title }}</div>
          <div class="nt-body">{{ n.body }}</div>
          <div class="nt-meta">
            {{ timeText(n.updated_at) }}
            <span v-if="n.event_count > 1"> · {{ n.event_count }} 条新动态</span>
          </div>
        </div>
        <span class="nt-go">查看评论 →</span>
      </li>
    </ul>

    <div v-if="hasMore && !loading" class="nt-more">
      <el-button size="small" @click="loadMore">加载更多</el-button>
    </div>
  </div>
</template>

<script setup lang="ts">
import { computed, onMounted, ref } from 'vue';
import { useRouter } from 'vue-router';
import {
  listNotifications,
  markAllNotificationsRead,
  markNotificationRead,
  type NotificationItem,
} from '@/api/notifications';
import { useNotificationsStore } from '@/stores/notifications';
import { httpErrorText } from '@/utils/httpError';

const PAGE = 20;

const router = useRouter();
const store = useNotificationsStore();

const filter = ref<'all' | 'unread'>('all');
const items = ref<NotificationItem[]>([]);
const total = ref(0);
const loading = ref(false);
const loadError = ref('');

const unread = computed(() => store.unread);
const hasMore = computed(() => items.value.length < total.value);

async function fetchPage(reset: boolean) {
  loading.value = true;
  loadError.value = '';
  try {
    const r = await listNotifications({
      limit: PAGE,
      offset: reset ? 0 : items.value.length,
      ...(filter.value === 'unread' ? { unread_only: true } : {}),
    });
    items.value = reset ? r.items : [...items.value, ...r.items];
    total.value = r.total;
  } catch (e: any) {
    loadError.value = httpErrorText(e?.response?.status, e?.response?.data?.detail, '消息加载失败');
  } finally {
    loading.value = false;
  }
}

function reload() {
  void fetchPage(true);
}

function setFilter(f: 'all' | 'unread') {
  if (filter.value === f) return;
  filter.value = f;
  void fetchPage(true);
}

function loadMore() {
  void fetchPage(false);
}

async function readAll() {
  try {
    await markAllNotificationsRead();
  } catch {
    return;
  }
  const now = new Date().toISOString();
  items.value = items.value.map((n) => ({ ...n, read_at: n.read_at || now }));
  store.unread = 0;
}

async function openItem(n: NotificationItem) {
  if (!n.read_at) {
    try {
      await markNotificationRead(n.id);
      await store.refreshUnread();
    } catch {
      // 已读失败不挡跳转
    }
    n.read_at = new Date().toISOString();
  }
  void router.push({
    name: 'extensions',
    query: { asset: n.asset_code, comment: String(n.comment_id ?? '') },
  });
}

function timeText(s: string | null): string {
  if (!s) return '';
  const d = new Date(s);
  if (Number.isNaN(d.getTime())) return '';
  const pad = (n: number) => String(n).padStart(2, '0');
  return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())} ${pad(d.getHours())}:${pad(d.getMinutes())}`;
}

onMounted(() => {
  void fetchPage(true);
  void store.refreshUnread();
});
</script>

<style scoped>
.notif-page { display: flex; flex-direction: column; gap: 14px; padding: 12px 4px 40px; }
.ma-right { display: flex; align-items: center; gap: 10px; }
.nt-count { color: var(--ink-500); font-size: 12px; }
.nt-count b { color: var(--ink-900); font-weight: 600; }

.nt-state {
  padding: 40px 0;
  text-align: center;
  color: var(--ink-500);
  font-size: 13px;
}
.nt-state.err { color: #c0362c; display: flex; align-items: center; justify-content: center; gap: 10px; }

.nt-list {
  list-style: none;
  margin: 0;
  padding: 0;
  display: flex;
  flex-direction: column;
  gap: 6px;
}
.nt-row {
  display: flex;
  align-items: flex-start;
  gap: 10px;
  padding: 12px 14px;
  background: var(--surface-soft);
  border: 1px solid var(--border);
  border-radius: 10px;
  cursor: pointer;
  transition: border-color .15s ease, background .15s ease;
}
.nt-row:hover { border-color: var(--primary); }
.nt-row.unread { background: color-mix(in srgb, var(--primary) 6%, var(--surface-soft)); }
.nt-dot {
  width: 7px;
  height: 7px;
  border-radius: 50%;
  margin-top: 6px;
  flex-shrink: 0;
  background: transparent;
}
.nt-row.unread .nt-dot { background: var(--primary); }
.nt-main { flex: 1; min-width: 0; }
.nt-title { font-size: 13.5px; font-weight: 600; color: var(--ink-900); }
.nt-body { font-size: 12.5px; color: var(--ink-600); margin-top: 3px; }
.nt-meta { font-size: 11.5px; color: var(--ink-500); margin-top: 4px; }
.nt-go { font-size: 12px; color: var(--primary-2); white-space: nowrap; align-self: center; }
.nt-more { text-align: center; padding-top: 6px; }
</style>
