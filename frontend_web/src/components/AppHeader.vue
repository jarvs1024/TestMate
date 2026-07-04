<template>
  <header class="tm-header">
    <div class="left">
      <div class="brand-mark">T</div>
      <div class="brand-name">
        <span class="name">TestMate</span>
        <span class="suffix">/ 智能测试辅助平台</span>
      </div>
      <span class="version">v0.1</span>
    </div>

    <div class="center">
      <div class="workbench-name">{{ workbenchName }}</div>
    </div>

    <div class="right">
      <ServiceStatusPill name="RAGFlow" :state="ragState" hint="协议检索后端" />
      <ServiceStatusPill name="Dify" :state="difyState" hint="Agent 编排后端" />
      <ThemeSwitcher />
      <UserMenu />
    </div>
  </header>
</template>

<script setup lang="ts">
import { computed, onMounted, onBeforeUnmount, ref } from 'vue';
import { useRoute } from 'vue-router';
import request from '@/utils/request';
import ServiceStatusPill from './ServiceStatusPill.vue';
import ThemeSwitcher from './ThemeSwitcher.vue';
import UserMenu from './UserMenu.vue';

const route = useRoute();
const workbenchName = computed(() => (route.meta.title as string) || 'TestMate');

// 服务状态(后端 /api/v1/health/services 聚合)
const ragState = ref<'ok' | 'warn' | 'off'>('off');
const difyState = ref<'ok' | 'warn' | 'off'>('off');

let pollTimer: number | null = null;

async function fetchStatus() {
  try {
    const data = (await request.get('/health/services')) as { ragflow?: 'ok' | 'warn' | 'off'; dify?: 'ok' | 'warn' | 'off' };
    ragState.value = data.ragflow || 'off';
    difyState.value = data.dify || 'off';
  } catch {
    // 后端没起来/没接口, 都按未配置处理
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
  height: 56px;
  padding: 0 20px;
  background: var(--surface-soft);
  backdrop-filter: blur(8px);
  -webkit-backdrop-filter: blur(8px);
  border-bottom: 1px solid var(--border);
  position: sticky;
  top: 0;
  z-index: 50;
}

.left { display: flex; align-items: center; gap: 10px; min-width: 280px; }
.brand-mark {
  width: 32px; height: 32px;
  border-radius: 8px;
  background: var(--primary-grad);
  box-shadow: var(--primary-shadow);
  display: grid; place-items: center;
  color: #fff; font-size: 16px; font-weight: 700;
  letter-spacing: 0.5px;
}
.brand-name { display: flex; align-items: baseline; gap: 6px; }
.brand-name .name { font-size: 15px; font-weight: 600; color: var(--ink-900); }
.brand-name .suffix { font-size: 12.5px; color: var(--ink-500); }
.version {
  margin-left: 6px;
  font-size: 11px; color: var(--ink-400);
  padding: 1px 6px; border-radius: 999px;
  background: var(--surface-sunken);
  border: 1px solid var(--border);
}

.center {
  flex: 1;
  display: flex;
  align-items: center;
  justify-content: center;
}
.workbench-name {
  font-size: 13px;
  color: var(--ink-500);
  letter-spacing: 0.3px;
}

.right { display: flex; align-items: center; gap: 10px; }
</style>
