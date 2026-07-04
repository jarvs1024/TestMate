<template>
  <div class="tm-theme-switch" role="tablist" aria-label="主题切换">
    <button
      type="button"
      role="tab"
      :aria-selected="themeStore.mode === 'auto'"
      :class="{ active: themeStore.mode === 'auto' }"
      title="跟随系统"
      aria-label="跟随系统"
      @click="themeStore.set('auto')"
    >
      <!-- 显示器图标 -->
      <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><rect x="3" y="4" width="18" height="14" rx="2"/><path d="M8 20h8"/><path d="M12 18v2"/></svg>
    </button>
    <button
      type="button"
      role="tab"
      :aria-selected="themeStore.mode === 'light'"
      :class="{ active: themeStore.mode === 'light' }"
      title="浅色"
      aria-label="浅色"
      @click="themeStore.set('light')"
    >
      <!-- 太阳图标 -->
      <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><circle cx="12" cy="12" r="4"/><path d="M12 2v2"/><path d="M12 20v2"/><path d="m4.93 4.93 1.41 1.41"/><path d="m17.66 17.66 1.41 1.41"/><path d="M2 12h2"/><path d="M20 12h2"/><path d="m6.34 17.66-1.41 1.41"/><path d="m19.07 4.93-1.41 1.41"/></svg>
    </button>
    <button
      type="button"
      role="tab"
      :aria-selected="themeStore.mode === 'dark'"
      :class="{ active: themeStore.mode === 'dark' }"
      title="深色"
      aria-label="深色"
      @click="themeStore.set('dark')"
    >
      <!-- 月亮图标 -->
      <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M21 12.79A9 9 0 1 1 11.21 3 7 7 0 0 0 21 12.79z"/></svg>
    </button>
  </div>
</template>

<script setup lang="ts">
import { useThemeStore } from '@/stores/theme';
const themeStore = useThemeStore();
</script>

<style scoped>
.tm-theme-switch {
  display: inline-flex;
  background: var(--surface-soft);
  border: 1px solid var(--border);
  border-radius: var(--radius-md);
  padding: 3px;
  gap: 2px;
  backdrop-filter: blur(6px);
  -webkit-backdrop-filter: blur(6px);
}
.tm-theme-switch button {
  width: 30px; height: 30px;
  border: none; background: transparent;
  color: var(--ink-500);
  border-radius: 8px;
  display: grid; place-items: center;
  cursor: pointer;
  transition: color .15s ease, background .15s ease;
}
.tm-theme-switch button:hover { color: var(--ink-900); }
.tm-theme-switch button.active {
  background: var(--surface);
  color: var(--primary);
  box-shadow: var(--shadow-sm);
}
</style>
