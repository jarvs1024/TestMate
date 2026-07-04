<template>
  <div class="plaza">
    <div class="plaza-hd">
      <h1 class="title">智能体广场</h1>
      <p class="lede">SSD 测试域专用 AI 智能体 · 点击卡片进入运行页</p>
    </div>

    <div class="plaza-toolbar">
      <div class="filters">
        <button v-for="f in FILTERS" :key="f.value"
          class="filter" :class="{ active: filter === f.value }"
          @click="filter = f.value">
          {{ f.label }} <span class="count">{{ countBy(f.value) }}</span>
        </button>
      </div>
      <div class="search">
        <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><circle cx="11" cy="11" r="8"/><path d="m21 21-4.3-4.3"/></svg>
        <input v-model="keyword" placeholder="搜智能体 / 标签..." />
      </div>
    </div>

    <div v-if="loading" class="loading">加载中...</div>
    <div v-else-if="filtered.length === 0" class="empty">
      <div style="font-size: 32px; opacity: 0.4">🩺</div>
      <div>暂无匹配的智能体</div>
    </div>
    <div v-else class="grid">
      <AgentCard v-for="a in filtered" :key="a.code" :agent="a" @open="onOpen" />
    </div>
  </div>
</template>

<script setup lang="ts">
import { computed, onMounted, ref } from 'vue';
import { useRouter } from 'vue-router';
import AgentCard from './AgentCard.vue';
import { listAgents, type AgentSummary } from '@/api/agents';

const router = useRouter();
const agents = ref<AgentSummary[]>([]);
const loading = ref(true);
const filter = ref<'all' | 'stable' | 'beta' | 'featured'>('all');
const keyword = ref('');

const FILTERS = [
  { value: 'all' as const, label: '全部' },
  { value: 'featured' as const, label: '⭐ 精选' },
  { value: 'stable' as const, label: '稳定' },
  { value: 'beta' as const, label: 'Beta' },
];

const filtered = computed(() => {
  let list = agents.value;
  if (filter.value === 'featured') list = list.filter((a) => a.is_featured);
  else if (filter.value === 'stable') list = list.filter((a) => a.status === 'stable');
  else if (filter.value === 'beta') list = list.filter((a) => a.status === 'beta');
  if (keyword.value.trim()) {
    const k = keyword.value.toLowerCase();
    list = list.filter(
      (a) =>
        a.name.toLowerCase().includes(k) ||
        a.summary.toLowerCase().includes(k) ||
        a.tags.some((t) => t.toLowerCase().includes(k)),
    );
  }
  return list;
});

function countBy(f: string): number {
  if (f === 'all') return agents.value.length;
  if (f === 'featured') return agents.value.filter((a) => a.is_featured).length;
  if (f === 'stable') return agents.value.filter((a) => a.status === 'stable').length;
  if (f === 'beta') return agents.value.filter((a) => a.status === 'beta').length;
  return 0;
}

function onOpen(a: AgentSummary) {
  router.push({ name: 'agent-runner', params: { code: a.code } });
}

onMounted(async () => {
  try {
    const data = await listAgents();
    agents.value = data.items;
  } finally {
    loading.value = false;
  }
});
</script>

<style scoped>
.plaza { display: flex; flex-direction: column; gap: 18px; }
.plaza-hd { margin-bottom: 4px; }
.title { font-size: 30px; font-weight: 800; margin: 0 0 8px; letter-spacing: -0.4px; color: var(--ink-900); }
.lede { color: var(--ink-700); margin: 0; font-size: 14.5px; }

.plaza-toolbar {
  display: flex; justify-content: space-between; align-items: center; gap: 16px;
  background: var(--surface-soft); backdrop-filter: blur(8px);
  border: 1px solid var(--border); border-radius: var(--radius-card);
  padding: 12px 16px; box-shadow: var(--shadow-sm);
}
.filters { display: flex; gap: 6px; }
.filter {
  background: transparent; border: 1px solid transparent;
  padding: 6px 12px; border-radius: var(--radius-pill);
  font-size: 12.5px; color: var(--ink-700); cursor: pointer;
  font-family: inherit; transition: all 0.15s ease;
  display: inline-flex; align-items: center; gap: 5px;
}
.filter:hover { background: var(--surface-sunken); color: var(--ink-900); }
.filter.active { background: var(--primary-soft); color: var(--primary); border-color: var(--primary); font-weight: 600; }
.filter .count {
  font-size: 10.5px; background: var(--surface); padding: 1px 6px; border-radius: var(--radius-pill);
  font-family: var(--font-mono);
}
.filter.active .count { background: var(--primary); color: #fff; }

.search {
  display: flex; align-items: center; gap: 6px;
  background: var(--surface); border: 1px solid var(--border);
  padding: 6px 10px; border-radius: 8px;
  color: var(--ink-500);
}
.search input {
  border: 0; outline: none; background: transparent;
  font-size: 13px; color: var(--ink-900); font-family: inherit; width: 180px;
}

.grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(300px, 1fr));
  gap: 16px;
}

.loading, .empty {
  background: var(--surface-soft); backdrop-filter: blur(8px);
  border: 1px solid var(--border); border-radius: var(--radius-card);
  padding: 60px 20px; text-align: center; color: var(--ink-500);
  font-size: 13.5px; display: flex; flex-direction: column; gap: 8px; align-items: center;
}
</style>
