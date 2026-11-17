<template>
  <el-popover
    v-if="loggedIn"
    ref="popRef"
    trigger="click"
    placement="bottom-end"
    :width="380"
    popper-class="nt-popper"
    @after-enter="load"
  >
    <template #reference>
      <button class="tm-bell" type="button" aria-label="消息" :title="unread ? `${unread} 条未读消息` : '消息'" @click="load">
        <svg width="17" height="17" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">
          <path d="M18 8a6 6 0 0 0-12 0c0 7-3 9-3 9h18s-3-2-3-9" />
          <path d="M13.7 21a2 2 0 0 1-3.4 0" />
        </svg>
        <span v-if="unread > 0" class="badge">{{ unread > 99 ? '99+' : unread }}</span>
      </button>
    </template>

    <div class="nt-panel">
      <div class="nt-head">
        <b>消息</b>
        <button v-if="unread > 0" type="button" class="nt-link" @click="readAll">全部已读</button>
      </div>
      <div v-if="loading" class="nt-empty">加载中…</div>
      <div v-else-if="!items.length" class="nt-empty">还没有新消息</div>
      <ul v-else class="nt-list">
        <li
          v-for="n in items"
          :key="n.id"
          class="nt-item"
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
        </li>
      </ul>
      <div class="nt-foot">
        <button type="button" class="nt-link" @click="viewAll">查看全部消息</button>
      </div>
    </div>
  </el-popover>
</template>

<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref } from 'vue';
import { useRouter } from 'vue-router';
import {
  listNotifications,
  markAllNotificationsRead,
  markNotificationRead,
  type NotificationItem,
} from '@/api/notifications';
import { useUserStore } from '@/stores/user';
import { useNotificationsStore } from '@/stores/notifications';
import { useAssetDeepLinkStore } from '@/stores/assetDeepLink';

const router = useRouter();
const userStore = useUserStore();
const store = useNotificationsStore();
const deepLink = useAssetDeepLinkStore();

const loggedIn = computed(() => userStore.isLoggedIn);
const unread = computed(() => store.unread);

const popRef = ref<{ hide: () => void } | null>(null);
const loading = ref(false);
const items = ref<NotificationItem[]>([]);

async function load() {
  loading.value = true;
  try {
    const r = await listNotifications({ limit: 5 });
    items.value = r.items;
  } catch {
    // 面板拉不到就保持空态, 不弹全局错误
  } finally {
    loading.value = false;
  }
}

async function readAll() {
  try {
    await markAllNotificationsRead();
  } catch {
    return;
  }
  items.value = items.value.map((n) => ({ ...n, read_at: n.read_at || new Date().toISOString() }));
  store.unread = 0;
}

async function openItem(n: NotificationItem) {
  popRef.value?.hide();
  if (!n.read_at) {
    try {
      await markNotificationRead(n.id);
      await store.refreshUnread();
    } catch {
      // 已读失败不挡跳转 —— 用户先看到评论更要紧
    }
  }
  const target = {
    name: 'extensions',
    query: { asset: n.asset_code, comment: String(n.comment_id ?? '') },
  };
  // 已经停在这条深链上时, push 是同地址导航 —— 路由不跳也不通知页面;
  // 通过 store 再发一次, 让扩展库重新打开抽屉并定位评论.
  if (router.currentRoute.value.fullPath === router.resolve(target).fullPath) {
    deepLink.open(n.asset_code, n.comment_id);
  }
  void router.push(target);
}

function viewAll() {
  popRef.value?.hide();
  void router.push({ name: 'notifications' });
}

function timeText(s: string | null): string {
  if (!s) return '';
  const d = new Date(s);
  if (Number.isNaN(d.getTime())) return '';
  const pad = (n: number) => String(n).padStart(2, '0');
  const now = new Date();
  const sameDay = d.getFullYear() === now.getFullYear()
    && d.getMonth() === now.getMonth() && d.getDate() === now.getDate();
  const hm = `${pad(d.getHours())}:${pad(d.getMinutes())}`;
  return sameDay ? hm : `${pad(d.getMonth() + 1)}-${pad(d.getDate())} ${hm}`;
}

onMounted(() => {
  if (loggedIn.value) store.startPolling();
});
onBeforeUnmount(() => store.stopPolling());
</script>

<style scoped>
.tm-bell {
  position: relative;
  width: 32px;
  height: 32px;
  display: inline-grid;
  place-items: center;
  background: var(--surface-soft);
  border: 1px solid var(--border);
  color: var(--ink-700);
  border-radius: 8px;
  cursor: pointer;
  transition: border-color .15s ease, color .15s ease;
}
.tm-bell:hover { border-color: var(--primary); color: var(--ink-900); }
.badge {
  position: absolute;
  top: -5px;
  right: -5px;
  min-width: 16px;
  height: 16px;
  padding: 0 4px;
  box-sizing: border-box;
  border-radius: 8px;
  background: #e5484d;
  color: #fff;
  font-size: 10px;
  font-weight: 700;
  line-height: 16px;
  text-align: center;
  box-shadow: 0 0 0 2px var(--surface-soft);
}

.nt-panel { display: flex; flex-direction: column; }
.nt-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 2px 2px 8px;
  border-bottom: 1px solid var(--border);
  font-size: 13px;
  color: var(--ink-900);
}
.nt-link {
  border: none;
  background: none;
  color: var(--primary-2);
  font-size: 12px;
  cursor: pointer;
  padding: 2px 4px;
  font-family: inherit;
}
.nt-link:hover { text-decoration: underline; }
.nt-empty {
  padding: 24px 8px;
  text-align: center;
  color: var(--ink-500);
  font-size: 12.5px;
}
.nt-list {
  list-style: none;
  margin: 0;
  padding: 4px 0 0;
  max-height: 360px;
  overflow-y: auto;
}
.nt-item {
  display: flex;
  gap: 8px;
  padding: 9px 8px;
  border-radius: 8px;
  cursor: pointer;
  transition: background .12s ease;
}
.nt-item:hover { background: color-mix(in srgb, var(--primary) 6%, transparent); }
.nt-dot {
  width: 6px;
  height: 6px;
  border-radius: 50%;
  margin-top: 6px;
  flex-shrink: 0;
  background: transparent;
}
.nt-item.unread .nt-dot { background: var(--primary); }
.nt-main { min-width: 0; flex: 1; }
.nt-title {
  font-size: 12.5px;
  font-weight: 600;
  color: var(--ink-900);
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.nt-body {
  font-size: 12px;
  color: var(--ink-600);
  margin-top: 2px;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.nt-meta { font-size: 11px; color: var(--ink-500); margin-top: 3px; }
.nt-foot {
  border-top: 1px solid var(--border);
  margin-top: 6px;
  padding-top: 8px;
  text-align: center;
}
</style>
