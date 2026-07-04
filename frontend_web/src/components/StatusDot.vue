<template>
  <span class="tm-dot" :class="`is-${state}`" :title="title">
    <span class="d"></span>
    <span class="lbl">{{ label }}</span>
  </span>
</template>

<script setup lang="ts">
import { computed } from 'vue';

type State = 'ok' | 'off';
const props = defineProps<{
  name: string;
  state: State;
  hint?: string;
}>();

const label = computed(() =>
  props.state === 'ok' ? `${props.name}` : props.name,
);
const title = computed(() => `${props.name} · ${props.state === 'ok' ? '在线' : '未配置'}${props.hint ? ' · ' + props.hint : ''}`);
</script>

<style scoped>
.tm-dot {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  font-size: 12px;
  color: var(--ink-700);
  user-select: none;
}
.d {
  width: 7px;
  height: 7px;
  border-radius: 50%;
  background: var(--ok);
  box-shadow: 0 0 0 2px var(--ok-soft);
}
.is-off .d {
  background: var(--off);
  box-shadow: none;
}
.is-off .lbl { color: var(--ink-500); }
</style>
