<template>
  <span class="pill" :class="`is-${state}`" :title="title">
    <span class="d" :class="state"></span>
    <span>{{ stateText }}</span>
  </span>
</template>

<script setup lang="ts">
import { computed } from 'vue';
type State = 'ok' | 'warn' | 'off' | 'err';
const props = defineProps<{
  name: string;
  state: State;
}>();
const stateText = computed(() => {
  if (props.state === 'ok') return `${props.name} · 在线`;
  if (props.state === 'warn') return `${props.name} · 异常`;
  if (props.state === 'err') return `${props.name} · 错误`;
  return `${props.name} · 未配置`;
});
const title = computed(() => stateText.value);
</script>

<style scoped>
.pill {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  padding: 4px 10px;
  border-radius: var(--radius-pill);
  background: var(--surface-soft);
  border: 1px solid var(--border);
  font-size: 11.5px;
  color: var(--ink-700);
  backdrop-filter: blur(6px);
  -webkit-backdrop-filter: blur(6px);
  user-select: none;
}
.d {
  width: 6px; height: 6px; border-radius: 50%;
  background: var(--ink-500);
}
.d.ok   { background: var(--ok);   box-shadow: 0 0 0 3px rgba(22, 163, 74, 0.15); }
.d.warn { background: var(--warn); box-shadow: 0 0 0 3px rgba(217, 119, 6, 0.18); }
.d.err  { background: var(--err);  box-shadow: 0 0 0 3px rgba(220, 38, 38, 0.18); }
</style>
