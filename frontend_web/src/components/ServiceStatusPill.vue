<template>
  <div :class="['tm-status-pill', `is-${state}`, { offline: state !== 'ok' }]" :title="title">
    <span class="dot"></span>
    <span class="label">{{ label }}</span>
    <span class="hint">{{ stateText }}</span>
  </div>
</template>

<script setup lang="ts">
import { computed } from 'vue';

type State = 'ok' | 'warn' | 'off';
const props = defineProps<{
  name: string;          // 'RAGFlow' / 'Dify'
  state: State;          // ok=在线, warn=异常, off=未配置/离线
  hint?: string;         // 鼠标悬停说明
}>();

const stateText = computed(() =>
  props.state === 'ok' ? '在线' : props.state === 'warn' ? '异常' : '未配置',
);

const label = computed(() => props.name);
const title = computed(() => `${props.name} · ${stateText.value}${props.hint ? ' · ' + props.hint : ''}`);
</script>

<style scoped>
.tm-status-pill {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  font-size: 12px;
  color: var(--ink-700);
  background: var(--surface-soft);
  border: 1px solid var(--border);
  padding: 5px 10px;
  border-radius: var(--radius-pill);
  backdrop-filter: blur(6px);
  -webkit-backdrop-filter: blur(6px);
  user-select: none;
}
.tm-status-pill .dot {
  width: 7px; height: 7px; border-radius: 50%;
  background: var(--status-ok);
  box-shadow: 0 0 0 3px var(--status-ok-soft);
}
.tm-status-pill .label { font-weight: 600; letter-spacing: .2px; }
.tm-status-pill .hint { color: var(--ink-500); }

.tm-status-pill.is-warn .dot {
  background: var(--status-warn);
  box-shadow: 0 0 0 3px var(--status-warn-soft);
  animation: tm-pulse 1.6s ease-in-out infinite;
}
.tm-status-pill.is-off .dot {
  background: var(--status-off);
  box-shadow: 0 0 0 3px rgba(148, 163, 184, 0.18);
}

@keyframes tm-pulse { 0%, 100% { opacity: 1 } 50% { opacity: .4 } }
</style>
