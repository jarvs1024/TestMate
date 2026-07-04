<template>
  <header class="tm-header">
    <div class="logo">T</div>
    <div class="brand">
      <span class="t1">TestMate</span>
      <span class="t2">智能测试辅助平台 · v0.1</span>
    </div>

    <!-- 顶栏主导航 tab -->
    <nav class="topnav">
      <router-link to="/plaza" class="tn-item" :class="{ active: isPlaza }">
        广场
      </router-link>
      <router-link to="/kb-manage" class="tn-item" :class="{ active: isKb }">
        知识库
      </router-link>
      <router-link v-if="isAgent" to="/plaza" class="tn-item">
        <span class="tn-agent" v-if="currentAgent">{{ currentAgent.icon }} {{ currentAgent.name }}</span>
        <span v-else>智能体</span>
      </router-link>
    </nav>

    <div class="right">
      <ThemeSwitcher />
      <UserMenu />
    </div>
  </header>
</template>

<script setup lang="ts">
import { computed, onMounted, ref } from 'vue';
import { useRoute } from 'vue-router';
import { getAgent, type AgentSummary } from '@/api/agents';
import ThemeSwitcher from './ThemeSwitcher.vue';
import UserMenu from './UserMenu.vue';

const route = useRoute();

const isPlaza = computed(() => route.path === '/plaza');
const isKb = computed(() => route.path === '/kb-manage');
const isAgent = computed(() => route.path.startsWith('/agents/'));

const currentAgent = ref<AgentSummary | null>(null);

async function loadAgentIfNeeded() {
  if (!isAgent.value) {
    currentAgent.value = null;
    return;
  }
  const code = String(route.params.code || '');
  if (!code) return;
  try {
    currentAgent.value = await getAgent(code);
  } catch {
    currentAgent.value = null;
  }
}

onMounted(loadAgentIfNeeded);
</script>

<style scoped>
.tm-header {
  display: flex;
  align-items: center;
  gap: 12px;
  padding: 14px 24px 10px;
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
.brand { display: flex; flex-direction: column; min-width: 180px; }
.t1 { font-size: 17px; font-weight: 700; color: var(--ink-900); letter-spacing: -0.2px; line-height: 1.2; }
.t2 { font-size: 12.5px; color: var(--ink-500); margin-top: 1px; }

.topnav {
  margin-left: 16px;
  display: flex; align-items: center; gap: 2px;
  background: var(--surface-soft);
  backdrop-filter: blur(8px);
  border: 1px solid var(--border);
  border-radius: 10px;
  padding: 3px;
  box-shadow: var(--shadow-sm);
}
.tn-item {
  display: inline-flex; align-items: center; gap: 6px;
  padding: 6px 14px;
  border-radius: 7px;
  color: var(--ink-700); text-decoration: none;
  font-size: 13px; font-weight: 500;
  transition: background 0.15s ease, color 0.15s ease;
}
.tn-item:hover { background: var(--surface-sunken); color: var(--ink-900); }
.tn-item.active { background: var(--surface); color: var(--primary); font-weight: 600; box-shadow: var(--shadow-sm); }
.tn-ic { font-size: 14px; }
.tn-agent { font-family: var(--font-mono); font-size: 12px; }

.right { margin-left: auto; display: flex; align-items: center; gap: 8px; }
</style>
