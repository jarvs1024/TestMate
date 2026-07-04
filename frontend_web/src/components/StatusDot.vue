<template>
  <span class="tm-pill" :class="`is-${state}`" :title="title">
    <span class="d"></span>
    <span>{{ stateText }}</span>
  </span>
</template>

<script setup lang="ts">
import { computed } from 'vue';
const props = defineProps<{
  name: string;
  state: 'ok' | 'off';
}>();
const stateText = computed(() => props.state === 'ok' ? '在线' : '未配置');
const title = computed(() => `${props.name} · ${stateText.value}`);
</script>

<style scoped>
.tm-pill {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  font-size: 12.5px;
  font-weight: 500;
  padding: 4px 10px;
  border-radius: var(--radius-pill);
  border: 1px solid transparent;
  user-select: none;
}
.tm-pill .d {
  width: 6px; height: 6px; border-radius: 50%;
  background: var(--ok);
}
.tm-pill.is-ok {
  background: var(--ok-soft);
  color: var(--ok-text);
  border-color: rgba(16, 185, 129, 0.2);
}
.tm-pill.is-off {
  background: var(--off-soft);
  color: var(--off-text);
  border-color: var(--border);
}
.tm-pill.is-off .d { background: var(--off); }
</style>
