<template>
  <aside class="tm-sidebar">
    <nav class="nav">
      <router-link
        v-for="item in items"
        :key="item.path"
        :to="item.path"
        class="nav-item"
        :class="{ 'is-active': isActive(item.path) }"
      >
        <span class="icon" :data-tag="item.tag">{{ item.icon }}</span>
        <span class="label">{{ item.label }}</span>
        <span v-if="item.tag" class="chip" :class="`chip-${item.tag}`">{{ tagText(item.tag) }}</span>
      </router-link>
    </nav>

    <div class="footer">
      <div class="divider"></div>
      <router-link
        to="/settings"
        class="nav-item is-quiet"
        :class="{ 'is-active': isActive('/settings') }"
      >
        <span class="icon">⚙</span>
        <span class="label">设置</span>
      </router-link>
    </div>
  </aside>
</template>

<script setup lang="ts">
import { useRoute } from 'vue-router';

const route = useRoute();

type Tag = 'live' | 'demo' | 'soon' | null;

const items = [
  { path: '/kb',         label: '知识库检索',  icon: '📚', tag: 'live' as Tag },
  { path: '/diagnosis',  label: '日志分析',    icon: '📋', tag: 'demo' as Tag },
  { path: '/cases',      label: '用例生成',    icon: '⚙️', tag: 'soon' as Tag },
  { path: '/ops',        label: '环境运维',    icon: '🖥',  tag: 'soon' as Tag },
  { path: '/plan',       label: '测试方案',    icon: '📑', tag: 'soon' as Tag },
];

function isActive(path: string) {
  return route.path === path || route.path.startsWith(path + '/');
}

function tagText(tag: Tag) {
  if (tag === 'live') return '已上线';
  if (tag === 'demo') return 'Demo';
  if (tag === 'soon') return '建设中';
  return '';
}
</script>

<style scoped>
.tm-sidebar {
  width: 220px;
  display: flex;
  flex-direction: column;
  background: var(--surface-soft);
  backdrop-filter: blur(6px);
  -webkit-backdrop-filter: blur(6px);
  border-right: 1px solid var(--border);
  padding: 14px 10px 10px;
  flex-shrink: 0;
}
.nav { flex: 1; display: flex; flex-direction: column; gap: 2px; }
.footer { display: flex; flex-direction: column; gap: 2px; }
.divider {
  height: 1px;
  background: var(--border);
  margin: 10px 6px;
}
.nav-item {
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 8px 10px;
  border-radius: var(--radius-md);
  color: var(--ink-700);
  text-decoration: none;
  font-size: 13.5px;
  font-weight: 500;
  transition: background .15s ease, color .15s ease;
  position: relative;
}
.nav-item .icon {
  width: 22px;
  text-align: center;
  font-size: 15px;
  filter: grayscale(0.2);
}
.nav-item .label { flex: 1; }
.nav-item.is-quiet { color: var(--ink-500); font-size: 13px; font-weight: 400; }
.nav-item:hover {
  background: var(--surface);
  color: var(--ink-900);
}
.nav-item.is-active {
  background: var(--primary-soft);
  color: var(--primary);
  font-weight: 600;
}
.nav-item.is-active .icon { filter: none; }

/* "建设中" 标记 */
.chip {
  font-size: 10px;
  padding: 1px 7px;
  border-radius: 999px;
  font-weight: 500;
  letter-spacing: 0.2px;
  border: 1px solid var(--border);
  background: var(--surface);
  color: var(--ink-500);
}
.chip-live {
  background: var(--status-ok-soft);
  color: var(--status-ok);
  border-color: transparent;
}
.chip-demo {
  background: var(--primary-soft);
  color: var(--primary);
  border-color: transparent;
}
.chip-soon {
  background: var(--surface-sunken);
  color: var(--ink-500);
}

/* "建设中" 整体灰一点 */
.nav-item:has(.chip-soon) {
  color: var(--ink-500);
}
.nav-item:has(.chip-soon):hover {
  color: var(--ink-700);
}
</style>
