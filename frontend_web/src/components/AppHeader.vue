<template>
  <header class="tm-header">
    <div class="logo">T</div>
    <div class="brand">
      <span class="t1">TestMate</span>
      <span class="t2">智能测试辅助平台 · v0.1</span>
    </div>

    <div class="wb">
      <span class="wb-lbl">当前</span>
      <span class="wb-name">{{ workbenchName }}</span>
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

const ragState = ref<'ok' | 'warn' | 'off' | 'err'>('off');
const difyState = ref<'ok' | 'warn' | 'off' | 'err'>('off');
let pollTimer: number | null = null;

async function fetchStatus() {
  try {
    const data = (await request.get('/health/services')) as { ragflow?: string; dify?: string };
    ragState.value = (data.ragflow as any) || 'off';
    difyState.value = (data.dify as any) || 'off';
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
  gap: 12px;
  padding: 16px 24px;
  background: transparent;
  flex-shrink: 0;
}
.logo {
  width: 38px; height: 38px;
  border-radius: 10px;
  display: grid; place-items: center;
  background: linear-gradient(135deg, var(--primary), var(--primary-2));
  color: #fff; font-weight: 800; font-size: 18px;
  box-shadow: var(--primary-shadow);
  flex-shrink: 0;
}
.brand { display: flex; flex-direction: column; min-width: 200px; }
.t1 { font-size: 17px; font-weight: 700; color: var(--ink-900); letter-spacing: -0.2px; line-height: 1.2; }
.t2 { font-size: 12.5px; color: var(--ink-500); margin-top: 1px; }

.wb {
  margin-left: 16px;
  display: inline-flex;
  align-items: center;
  gap: 8px;
  padding: 5px 14px;
  background: var(--surface-soft);
  border: 1px solid var(--border);
  border-radius: var(--radius-pill);
  backdrop-filter: blur(8px);
  -webkit-backdrop-filter: blur(8px);
}
.wb-lbl { font-size: 11.5px; color: var(--ink-500); }
.wb-name { font-size: 13px; font-weight: 600; color: var(--ink-900); }

.right { margin-left: auto; display: flex; align-items: center; gap: 10px; }
</style>
