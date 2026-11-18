<template>
  <button
    type="button"
    class="tm-theme"
    :title="`当前: ${label} · 点击切换`"
    :aria-label="`切换主题 (当前: ${label})`"
    @click="themeStore.toggle()"
  >
    <!-- 跟随系统 = 电脑图标 (默认); 浅色 = 太阳; 深色 = 月亮 -->
    <svg v-if="themeStore.mode === 'auto'" width="17" height="17" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">
      <rect x="3" y="4" width="18" height="12" rx="2"/><path d="M8 20h8"/><path d="M12 16v4"/>
    </svg>
    <svg v-else-if="themeStore.mode === 'light'" width="17" height="17" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">
      <circle cx="12" cy="12" r="4"/><path d="M12 2v2"/><path d="M12 20v2"/><path d="m4.93 4.93 1.41 1.41"/><path d="m17.66 17.66 1.41 1.41"/><path d="M2 12h2"/><path d="M20 12h2"/><path d="m6.34 17.66-1.41 1.41"/><path d="m19.07 4.93-1.41 1.41"/>
    </svg>
    <svg v-else width="17" height="17" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">
      <path d="M21 12.79A9 9 0 1 1 11.21 3 7 7 0 0 0 21 12.79z"/>
    </svg>
  </button>
</template>

<script setup lang="ts">
import { computed } from 'vue';
import { useThemeStore } from '@/stores/theme';
const themeStore = useThemeStore();
// ⚠️ label 要**把 auto 说出来** —— 用户得知道现在是不是「跟随系统」.
const label = computed(() => {
  if (themeStore.mode === 'auto') return '跟随系统';
  return themeStore.mode === 'dark' ? '深色' : '浅色';
});
</script>

<style scoped>
.tm-theme {
  /* ⚠️ 2026-11-18: 跟消息铃铛 (.tm-bell) 同一尺寸/长相 —— 32px 方钮 + 17px 图标 */
  width: 32px; height: 32px;
  background: var(--surface-soft);
  border: 1px solid var(--border);
  color: var(--ink-700);
  border-radius: 8px;
  display: inline-grid; place-items: center;
  cursor: pointer;
  transition: border-color .15s ease, color .15s ease;
}
.tm-theme:hover { border-color: var(--primary); color: var(--ink-900); }
</style>
