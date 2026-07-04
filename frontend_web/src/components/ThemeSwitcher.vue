<template>
  <button
    type="button"
    class="tm-theme"
    :title="`当前: ${label} (点击切换)`"
    :aria-label="label"
    @click="themeStore.toggle()"
  >
    <!-- 太阳: resolved=light 时显示; 月亮: resolved=dark 时显示 -->
    <svg v-if="themeStore.resolved === 'light'" width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">
      <circle cx="12" cy="12" r="4"/><path d="M12 2v2"/><path d="M12 20v2"/><path d="m4.93 4.93 1.41 1.41"/><path d="m17.66 17.66 1.41 1.41"/><path d="M2 12h2"/><path d="M20 12h2"/><path d="m6.34 17.66-1.41 1.41"/><path d="m19.07 4.93-1.41 1.41"/>
    </svg>
    <svg v-else width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">
      <path d="M21 12.79A9 9 0 1 1 11.21 3 7 7 0 0 0 21 12.79z"/>
    </svg>
  </button>
</template>

<script setup lang="ts">
import { computed } from 'vue';
import { useThemeStore } from '@/stores/theme';
const themeStore = useThemeStore();
const label = computed(() => themeStore.resolved === 'dark' ? '深色' : '浅色');
</script>

<style scoped>
.tm-theme {
  width: 28px; height: 28px;
  border: 1px solid var(--border);
  background: transparent;
  color: var(--ink-500);
  border-radius: 4px;
  display: grid; place-items: center;
  cursor: pointer;
  transition: color .12s ease, border-color .12s ease, background .12s ease;
}
.tm-theme:hover {
  color: var(--ink-900);
  border-color: var(--border-strong);
  background: var(--bg-hover);
}
</style>
