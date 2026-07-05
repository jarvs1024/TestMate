<template>
  <aside class="tm-side">
    <div class="side-inner">
      <nav class="nav">
        <router-link
          v-for="g in groups"
          :key="g.path"
          :to="g.path"
          class="group"
          :class="{ active: isActive(g.path) }"
        >
          <span class="g-ic" v-html="g.icon"></span>
          <span class="g-lb">{{ g.label }}</span>
        </router-link>
      </nav>

      <div class="foot">
        <div class="ft-lbl">📡 数据 / 工具</div>
        <div v-for="s in services" :key="s.key" class="src">
          <span class="dot" :class="`s-${s.status}`"></span>
          <span class="name">{{ s.label }}</span>
          <span class="state">{{ s.statusText }}</span>
        </div>
        <div class="ft-ts">每 30s 心跳 · {{ lastCheck }}</div>
      </div>
    </div>
  </aside>
</template>

<script setup lang="ts">
import { onMounted, onUnmounted, ref } from 'vue';
import { useRoute } from 'vue-router';
import axios from 'axios';

const route = useRoute();

const icoPlaza = `<svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><rect x="3" y="3" width="7" height="7" rx="1"/><rect x="14" y="3" width="7" height="7" rx="1"/><rect x="3" y="14" width="7" height="7" rx="1"/><rect x="14" y="14" width="7" height="7" rx="1"/></svg>`;
const icoKb = `<svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><path d="M4 19.5v-15A2.5 2.5 0 0 1 6.5 2H20v20H6.5a2.5 2.5 0 0 1 0-5H20"/></svg>`;

/* 设置已挪到顶栏用户菜单 (UserMenu), 侧栏只保留业务导航 */
const groups = [
  { path: '/plaza',    label: '广场',   icon: icoPlaza },
  { path: '/kb-manage', label: '知识库', icon: icoKb },
];

interface ServiceHealth { key: string; label: string; status: 'ok' | 'warn' | 'off' | 'unknown'; statusText: string }
const services = ref<ServiceHealth[]>([
  { key: 'ragflow', label: 'RAGFlow', status: 'unknown', statusText: '...' },
  { key: 'dify',    label: 'Dify',    status: 'unknown', statusText: '...' },
]);
const lastCheck = ref('—');
let pollTimer: number | null = null;

function setSvc(key: string, st: 'ok' | 'warn' | 'off', txt?: string) {
  const i = services.value.findIndex((s) => s.key === key);
  if (i < 0) return;
  services.value[i].status = st;
  const map: Record<string, string> = { ok: '正常', warn: '部分', off: '未配置' };
  services.value[i].statusText = txt || map[st] || '未知';
}

async function poll() {
  try {
    const { data } = await axios.get('/api/v1/health/services');
    setSvc('ragflow', data.ragflow);
    setSvc('dify', data.dify);
  } catch {
    setSvc('ragflow', 'off');
    setSvc('dify', 'off');
  }
  const d = new Date();
  lastCheck.value = `${String(d.getHours()).padStart(2,'0')}:${String(d.getMinutes()).padStart(2,'0')}:${String(d.getSeconds()).padStart(2,'0')}`;
}

function isActive(path: string) {
  if (path === '/plaza') return route.path === '/plaza' || route.path.startsWith('/agents');
  return route.path === path || route.path.startsWith(path + '/');
}

onMounted(() => { poll(); pollTimer = window.setInterval(poll, 30_000); });
onUnmounted(() => { if (pollTimer) clearInterval(pollTimer); });
</script>

<style scoped>
/* 侧栏: 固定不动, 自己内部滚 (MainLayout 给了 100% 高) */
.tm-side {
  width: 220px;
  flex-shrink: 0;
  height: 100%;
  overflow: hidden;     /* 外层不滚, 内部 .side-inner 滚 */
  border-right: 1px solid var(--border);
}
.side-inner {
  height: 100%;
  overflow-y: auto;     /* 内容多时自己滚 */
  /* 顶部 12: 让"广场"按钮贴在 AppHeader 下方, 不跟主区 toolbar 对齐 (主区在 header 区显示标题了) */
  padding: 12px 12px 16px;
  display: flex;
  flex-direction: column;
  gap: 12px;
}

.nav { display: flex; flex-direction: column; gap: 2px; }
.group {
  display: flex; align-items: center; gap: 10px;
  padding: 9px 12px; border-radius: 9px;
  color: var(--ink-700); text-decoration: none;
  font-size: 13px; font-weight: 500;
  transition: background 0.15s ease, color 0.15s ease;
}
.group:hover { background: var(--surface-sunken); color: var(--ink-900); }
.group.active {
  /* 跟 KB 检索/对话 tab 风格统一: 浅底 + 渐变文字, 不再用深色渐变填底 */
  background: var(--primary-soft);
  font-weight: 600;
  box-shadow: 0 0 0 1px var(--primary-soft);
  /* 渐变文字: 标签用主色渐变, 图标保持纯色 (图标用 currentColor 不太方便, 直接给 .g-ic 单写) */
}
.group.active .g-lb {
  background: var(--primary-grad-text);
  -webkit-background-clip: text;
  background-clip: text;
  -webkit-text-fill-color: transparent;
  color: transparent;
}
.group.active .g-ic { color: var(--primary); }
.g-ic { display: inline-flex; align-items: center; }
.g-lb { flex: 1; }

.foot {
  margin-top: auto;
  padding: 12px;
  background: var(--surface-soft); backdrop-filter: blur(8px);
  border: 1px solid var(--border); border-radius: 10px;
  box-shadow: var(--shadow-sm);
  display: flex; flex-direction: column; gap: 6px;
  font-size: 11.5px;
}
.ft-lbl { font-size: 10.5px; color: var(--ink-500); font-weight: 600; text-transform: uppercase; letter-spacing: 0.05em; margin-bottom: 4px; }
.src { display: flex; align-items: center; gap: 7px; }
.dot { width: 7px; height: 7px; border-radius: 50%; flex-shrink: 0; }
.s-ok { background: var(--ok); box-shadow: 0 0 0 2px rgba(22, 163, 74, 0.18); }
.s-warn { background: var(--warn); box-shadow: 0 0 0 2px rgba(217, 119, 6, 0.18); }
.s-off { background: var(--err); box-shadow: 0 0 0 2px rgba(220, 38, 38, 0.18); }
.s-unknown { background: var(--ink-500); }
.name { flex: 1; color: var(--ink-700); }
.state { color: var(--ink-500); font-family: var(--font-mono); font-size: 10.5px; }
.ft-ts { margin-top: 4px; padding-top: 6px; border-top: 1px dashed var(--border); color: var(--ink-500); font-family: var(--font-mono); font-size: 10.5px; }
</style>
