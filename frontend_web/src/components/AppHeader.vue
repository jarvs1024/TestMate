<template>
  <header class="tm-header">
    <div class="left">
      <div class="logo">T</div>
      <div class="brand">
        <div class="name">TestMate</div>
        <div class="sub">智能测试辅助平台</div>
      </div>
    </div>

    <div class="center">
      <div class="wb">
        <span class="wb-label">当前工作台</span>
        <span class="wb-name">{{ workbenchName }}</span>
      </div>
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

onMounted(() => { fetchStatus(); pollTimer = window.setInterval(fetchStatus, 30_000); });
onBeforeUnmount(() => { if (pollTimer) window.clearInterval(pollTimer); });
</script>

<style scoped>
.tm-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  height: 64px;
  padding: 0 24px;
  background: transparent;
  position: sticky;
  top: 0;
  z-index: 50;
}
.left { display: flex; align-items: center; gap: 12px; min-width: 260px; }
.logo {
  width: 38px; height: 38px;
  border-radius: var(--radius-md);
  background: var(--primary-grad);
  color: #fff;
  display: grid; place-items: center;
  font-size: 18px; font-weight: 700;
  box-shadow: var(--primary-shadow);
}
.brand { display: flex; flex-direction: column; gap: 1px; }
.name { font-size: 15px; font-weight: 700; color: var(--ink-900); letter-spacing: 0.2px; line-height: 1.2; }
.sub { font-size: 11.5px; color: var(--ink-500); line-height: 1; }

.center { flex: 1; display: flex; justify-content: center; }
.wb {
  display: inline-flex;
  align-items: center;
  gap: 10px;
  padding: 6px 16px;
  background: var(--surface);
  border: 1px solid var(--border);
  border-radius: var(--radius-pill);
  box-shadow: var(--shadow-sm);
}
.wb-label { font-size: 11.5px; color: var(--ink-500); }
.wb-name { font-size: 13.5px; font-weight: 600; color: var(--ink-900); }

.right { display: flex; align-items: center; gap: 10px; min-width: 260px; justify-content: flex-end; }
</style>
