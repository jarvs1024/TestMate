<template>
  <aside class="tm-rag">
    <div class="h">
      <span class="t">协议检索</span>
      <span class="b">P1</span>
    </div>
    <div class="search">
      <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">
        <circle cx="11" cy="11" r="7"/><line x1="21" y1="21" x2="16.65" y2="16.65"/>
      </svg>
      <input v-model="q" type="text" placeholder="搜索 NVMe / JEDEC 规范" disabled />
    </div>
    <div class="empty">
      <svg width="28" height="28" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">
        <path d="M21 16V8a2 2 0 0 0-1-1.73l-7-4a2 2 0 0 0-2 0l-7 4A2 2 0 0 0 3 8v8a2 2 0 0 0 1 1.73l7 4a2 2 0 0 0 2 0l7-4A2 2 0 0 0 21 16z"/><polyline points="3.27 6.96 12 12.01 20.73 6.96"/><line x1="12" y1="22.08" x2="12" y2="12"/>
      </svg>
      <div class="e-t">RAGFlow 未接入</div>
      <div class="e-s">P1 启动后,命中片段列在这里</div>
    </div>
  </aside>
</template>

<script setup lang="ts">
import { ref } from 'vue';
const q = ref('');
</script>

<style scoped>
.tm-rag {
  width: 240px;
  padding: 16px 12px;
  display: flex;
  flex-direction: column;
  gap: 10px;
  flex-shrink: 0;
}
.h { display: flex; align-items: center; justify-content: space-between; padding: 0 4px; }
.t { font-size: 12.5px; font-weight: 600; color: var(--ink-900); }
.b { font-size: 10px; font-weight: 600; padding: 2px 7px; border-radius: var(--radius-pill); background: var(--primary-soft); color: var(--primary); }

.search {
  display: flex; align-items: center; gap: 6px;
  padding: 8px 10px;
  background: var(--surface-soft);
  border: 1px solid var(--border);
  border-radius: 8px;
  color: var(--ink-500);
  backdrop-filter: blur(6px);
  -webkit-backdrop-filter: blur(6px);
}
.search input {
  flex: 1; border: none; outline: none; background: transparent;
  font-size: 12.5px; color: var(--ink-900);
  font-family: inherit;
}
.search input::placeholder { color: var(--ink-500); }
.search input:disabled { cursor: not-allowed; }

.empty {
  flex: 1;
  display: flex; flex-direction: column; align-items: center; justify-content: center;
  text-align: center; gap: 6px;
  padding: 24px 12px;
  background: var(--surface-soft);
  border: 1px dashed var(--border);
  border-radius: 12px;
  color: var(--ink-500);
  backdrop-filter: blur(6px);
  -webkit-backdrop-filter: blur(6px);
}
.empty svg { opacity: 0.5; }
.e-t { font-size: 12.5px; color: var(--ink-700); font-weight: 500; }
.e-s { font-size: 11.5px; color: var(--ink-500); }
</style>
