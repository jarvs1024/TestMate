<template>
  <div class="card agent-card" :class="`status-${agent.status}`" @click="$emit('open', agent)">
    <div class="ac-hd">
      <div class="ac-icon">{{ agent.icon }}</div>
      <div class="ac-title">
        <div class="ac-name">{{ agent.name }}</div>
        <div class="ac-ver">{{ agent.version }} · {{ categoryLabel }}</div>
      </div>
      <div class="ac-badge" :class="`st-${agent.status}`">
        <span class="dot"></span>{{ statusLabel }}
      </div>
    </div>
    <p class="ac-summary">{{ agent.summary }}</p>
    <div class="ac-tags">
      <span v-for="t in agent.tags.slice(0, 4)" :key="t" class="tag">#{{ t }}</span>
    </div>
    <div class="ac-meta">
      <span class="meta-item">🔧 {{ agent.engine }}</span>
      <span class="meta-item">📊 {{ agent.call_count }} 次</span>
      <span v-if="agent.last_called_at" class="meta-item">
        🕐 {{ relativeTime(agent.last_called_at) }}
      </span>
    </div>
  </div>
</template>

<script setup lang="ts">
import { computed } from 'vue';
import type { AgentSummary } from '@/api/agents';

const props = defineProps<{ agent: AgentSummary }>();
defineEmits<{ (e: 'open', a: AgentSummary): void }>();

const CATEGORY_LABELS: Record<string, string> = {
  'ssd-trace': 'Trace 诊断',
  'ssd-fw': 'FW 比对',
  'ssd-fio': 'FIO 性能',
  'ssd-burn': '老化任务',
  'ssd-spec': 'Spec 问答',
  'ssd-report': '测试报告',
  'ssd-ops': '机台运维',
};
const STATUS_LABELS: Record<string, string> = {
  draft: '草稿',
  alpha: '内测',
  beta: 'Beta',
  stable: '稳定',
  deprecated: '弃用',
};

const categoryLabel = computed(() => CATEGORY_LABELS[props.agent.category] || props.agent.category);
const statusLabel = computed(() => STATUS_LABELS[props.agent.status] || props.agent.status);

function relativeTime(iso: string): string {
  const diff = Date.now() - new Date(iso).getTime();
  const m = Math.floor(diff / 60000);
  if (m < 1) return '刚刚';
  if (m < 60) return `${m} 分钟前`;
  const h = Math.floor(m / 60);
  if (h < 24) return `${h} 小时前`;
  return `${Math.floor(h / 24)} 天前`;
}
</script>

<style scoped>
.agent-card {
  cursor: pointer;
  transition: transform 0.15s ease, box-shadow 0.15s ease, border-color 0.15s ease;
  display: flex;
  flex-direction: column;
  gap: 12px;
  min-height: 200px;
}
.agent-card:hover {
  transform: translateY(-2px);
  border-color: var(--primary);
  box-shadow: 0 8px 24px rgba(28, 100, 242, 0.12), 0 0 0 3px var(--primary-soft);
}
.agent-card.status-deprecated { opacity: 0.5; }

.ac-hd {
  display: flex;
  align-items: flex-start;
  gap: 12px;
}
.ac-icon {
  width: 44px; height: 44px;
  border-radius: 12px;
  background: linear-gradient(135deg, var(--primary), var(--primary-2));
  display: flex; align-items: center; justify-content: center;
  font-size: 22px;
  flex-shrink: 0;
  box-shadow: var(--primary-shadow);
}
.ac-title { flex: 1; min-width: 0; }
.ac-name { font-size: 16px; font-weight: 700; color: var(--ink-900); line-height: 1.2; }
.ac-ver { font-size: 11.5px; color: var(--ink-500); margin-top: 2px; font-family: var(--font-mono); }

.ac-badge {
  display: inline-flex; align-items: center; gap: 5px;
  padding: 3px 8px; border-radius: var(--radius-pill);
  font-size: 10.5px; font-weight: 600;
  background: var(--surface-sunken); color: var(--ink-700);
  flex-shrink: 0;
}
.ac-badge .dot { width: 6px; height: 6px; border-radius: 50%; background: currentColor; }
.st-stable { background: rgba(22, 163, 74, 0.1); color: var(--ok); }
.st-beta { background: rgba(217, 119, 6, 0.1); color: var(--warn); }
.st-alpha { background: rgba(245, 158, 11, 0.12); color: var(--warn); }
.st-draft { background: rgba(148, 163, 184, 0.15); color: var(--ink-500); }
.st-deprecated { background: rgba(220, 38, 38, 0.1); color: var(--err); }

.ac-summary {
  margin: 0;
  font-size: 13.5px;
  color: var(--ink-700);
  line-height: 1.55;
  flex: 1;
}

.ac-tags { display: flex; flex-wrap: wrap; gap: 5px; }
.tag {
  font-size: 10.5px;
  color: var(--ink-500);
  background: var(--surface-sunken);
  padding: 2px 7px;
  border-radius: var(--radius-sm);
  font-family: var(--font-mono);
}

.ac-meta {
  display: flex; gap: 10px; flex-wrap: wrap;
  padding-top: 10px;
  border-top: 1px dashed var(--border);
  font-size: 11px;
  color: var(--ink-500);
  font-family: var(--font-mono);
}
.meta-item { display: inline-flex; align-items: center; gap: 3px; }
</style>
