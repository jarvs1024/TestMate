<template>
  <button
    type="button"
    class="tm-theme"
    :title="`当前: ${label} · 点击切换`"
    :aria-label="label"
    @click="themeStore.toggle()"
  >
    <svg v-if="themeStore.resolved === 'light'" width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">
      <circle cx="12" cy="12" r="4"/><path d="M12 2v2"/><path d="M12 20v2"/><path d="m4.93 4.93 1.41 1.41"/><path d="m17.66 17.66 1.41 1.41"/><path d="M2 12h2"/><path d="M20 12h2"/><path d="m6.34 17.66-1.41 1.41"/><path d="m19.07 4.93-1.41 1.41"/>
    </svg>
    <svg v-else width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">
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
  width: 30px; height: 30px;
  background: var(--surface-soft);
  border: 1px solid var(--border);
  color: var(--ink-700);
  border-radius: 8px;
  display: grid; place-items: center;
  cursor: pointer;
  transition: border-color .15s ease, background .15s ease;
  backdrop-filter: blur(6px);
  -webkit-backdrop-filter: blur(6px);
}
.tm-theme:hover {
  border-color: var(--primary);
  background: var(--primary-soft);
  color: var(--primary);
}
</style>
