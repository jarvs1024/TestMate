<template>
  <header class="tm-header">
    <div class="brand">
      <span class="logo">T</span>
      <span class="name">TestMate</span>
      <span class="sep">/</span>
      <span class="wb">{{ workbenchName }}</span>
    </div>
    <div class="right">
      <StatusDot name="RAGFlow" :state="ragState" />
      <StatusDot name="Dify" :state="difyState" />
      <ThemeSwitcher />
      <UserMenu />
    </div>
  </header>
</template>

<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref } from 'vue';
import { useRoute } from 'vue-router';
import request from '@/utils/request';
import StatusDot from './StatusDot.vue';
import ThemeSwitcher from './ThemeSwitcher.vue';
import UserMenu from './UserMenu.vue';

const route = useRoute();
const workbenchName = computed(() => (route.meta.title as string) || 'TestMate');

const ragState = ref<'ok' | 'off'>('off');
const difyState = ref<'ok' | 'off'>('off');
let pollTimer: number | null = null;

async function fetchStatus() {
  try {
    const data = (await request.get('/health/services')) as { ragflow?: 'ok' | 'off'; dify?: 'ok' | 'off' };
    ragState.value = data.ragflow === 'ok' ? 'ok' : 'off';
    difyState.value = data.dify === 'ok' ? 'ok' : 'off';
  } catch {
    ragState.value = 'off';
    difyState.value = 'off';
  }
}

onMounted(() => {
  fetchStatus();
  pollTimer = window.setInterval(fetchStatus, 30_000);
});
onBeforeUnmount(() => {
  if (pollTimer) window.clearInterval(pollTimer);
});
</script>

<style scoped>
.tm-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  height: 48px;
  padding: 0 20px;
  background: var(--bg);
  border-bottom: 1px solid var(--border);
  flex-shrink: 0;
}
.brand { display: flex; align-items: center; gap: 8px; }
.logo {
  width: 22px; height: 22px;
  background: var(--primary);
  color: #fff;
  border-radius: 4px;
  display: grid; place-items: center;
  font-size: 12px; font-weight: 700;
}
.name {
  font-size: 13px; font-weight: 600; color: var(--ink-900);
  letter-spacing: 0.1px;
}
.sep { color: var(--ink-400); font-size: 13px; }
.wb { font-size: 13px; color: var(--ink-500); }

.right { display: flex; align-items: center; gap: 14px; }
</style>
