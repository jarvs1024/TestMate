<template>
  <aside class="tm-side">
    <nav class="nav">
      <router-link
        v-for="item in items"
        :key="item.path"
        :to="item.path"
        class="item"
        :class="{ active: isActive(item.path) }"
      >
        <span class="ic" v-html="item.icon"></span>
        <span class="lb">{{ item.label }}</span>
        <span v-if="item.soon" class="badge">P1</span>
      </router-link>
    </nav>
    <div class="foot">
      <router-link to="/settings" class="item" :class="{ active: isActive('/settings') }">
        <span class="ic" v-html="icoSettings"></span>
        <span class="lb">设置</span>
      </router-link>
    </div>
  </aside>
</template>

<script setup lang="ts">
import { useRoute } from 'vue-router';
const route = useRoute();

const icoBook = `<svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><path d="M4 19.5v-15A2.5 2.5 0 0 1 6.5 2H20v20H6.5a2.5 2.5 0 0 1 0-5H20"/></svg>`;
const icoLog  = `<svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z"/><path d="M14 2v6h6"/><path d="M9 13h6"/><path d="M9 17h4"/></svg>`;
const icoCase = `<svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><rect x="3" y="3" width="7" height="7" rx="1"/><rect x="14" y="3" width="7" height="7" rx="1"/><rect x="3" y="14" width="7" height="7" rx="1"/><rect x="14" y="14" width="7" height="7" rx="1"/></svg>`;
const icoOps  = `<svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><polyline points="4 17 10 11 4 5"/><line x1="12" y1="19" x2="20" y2="19"/></svg>`;
const icoPlan = `<svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><line x1="8" y1="6" x2="21" y2="6"/><line x1="8" y1="12" x2="21" y2="12"/><line x1="8" y1="18" x2="21" y2="18"/><line x1="3" y1="6" x2="3.01" y2="6"/><line x1="3" y1="12" x2="3.01" y2="12"/><line x1="3" y1="18" x2="3.01" y2="18"/></svg>`;
const icoSettings = `<svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><circle cx="12" cy="12" r="3"/><path d="M19.4 15a1.65 1.65 0 0 0 .33 1.82l.06.06a2 2 0 1 1-2.83 2.83l-.06-.06a1.65 1.65 0 0 0-1.82-.33 1.65 1.65 0 0 0-1 1.51V21a2 2 0 0 1-4 0v-.09A1.65 1.65 0 0 0 9 19.4a1.65 1.65 0 0 0-1.82.33l-.06.06a2 2 0 1 1-2.83-2.83l.06-.06a1.65 1.65 0 0 0 .33-1.82 1.65 1.65 0 0 0-1.51-1H3a2 2 0 0 1 0-4h.09A1.65 1.65 0 0 0 4.6 9a1.65 1.65 0 0 0-.33-1.82l-.06-.06a2 2 0 1 1 2.83-2.83l.06.06a1.65 1.65 0 0 0 1.82.33H9a1.65 1.65 0 0 0 1-1.51V3a2 2 0 0 1 4 0v.09a1.65 1.65 0 0 0 1 1.51 1.65 1.65 0 0 0 1.82-.33l.06-.06a2 2 0 1 1 2.83 2.83l-.06.06a1.65 1.65 0 0 0-.33 1.82V9a1.65 1.65 0 0 0 1.51 1H21a2 2 0 0 1 0 4h-.09a1.65 1.65 0 0 0-1.51 1z"/></svg>`;

const items = [
  { path: '/kb',        label: '知识库检索', icon: icoBook, soon: false },
  { path: '/diagnosis', label: '日志分析',   icon: icoLog,  soon: false },
  { path: '/cases',     label: '用例生成',   icon: icoCase, soon: true  },
  { path: '/ops',       label: '环境运维',   icon: icoOps,  soon: true  },
  { path: '/plan',      label: '测试方案',   icon: icoPlan, soon: true  },
];

function isActive(path: string) {
  return route.path === path || route.path.startsWith(path + '/');
}
</script>

<style scoped>
.tm-side {
  width: 220px;
  padding: 16px 12px;
  display: flex;
  flex-direction: column;
  gap: 6px;
  flex-shrink: 0;
}
.nav, .foot { display: flex; flex-direction: column; gap: 2px; }
.foot { margin-top: auto; padding-top: 12px; border-top: 1px solid var(--border); }
.item {
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 9px 12px;
  border-radius: 9px;
  color: var(--ink-700);
  text-decoration: none;
  font-size: 13.5px;
  font-weight: 500;
  transition: background .12s ease, color .12s ease;
}
.item .ic { display: inline-flex; color: var(--ink-500); }
.item:hover { background: var(--surface-soft); color: var(--ink-900); }
.item:hover .ic { color: var(--ink-700); }
.item.active {
  background: var(--primary-soft);
  color: var(--primary);
  font-weight: 600;
}
.item.active .ic { color: var(--primary); }

.item:has(.badge) { color: var(--ink-500); }
.item:has(.badge) .ic { color: var(--ink-500); }
.badge {
  margin-left: auto;
  font-size: 10px; font-weight: 600;
  padding: 2px 8px; border-radius: var(--radius-pill);
  background: var(--primary-soft); color: var(--primary);
}
</style>
