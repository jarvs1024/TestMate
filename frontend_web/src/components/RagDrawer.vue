<template>
  <aside class="tm-rag">
    <div class="head">
      <span class="title">协议随身</span>
      <span class="hint">P1</span>
    </div>
    <div class="search">
      <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">
        <circle cx="11" cy="11" r="7"/><line x1="21" y1="21" x2="16.65" y2="16.65"/>
      </svg>
      <input v-model="q" type="text" placeholder="NVMe 2.0 random write…" disabled />
    </div>
    <div class="empty">
      <div class="em-title">RAGFlow 未接入</div>
      <div class="em-sub">P1 启动后,命中片段会列在这里</div>
    </div>
  </aside>
</template>

<script setup lang="ts">
import { ref } from 'vue';
const q = ref('');
</script>

<style scoped>
.tm-rag {
  width: 260px;
  background: var(--bg-sub);
  border-left: 1px solid var(--border);
  padding: 14px 14px;
  display: flex;
  flex-direction: column;
  gap: 10px;
  flex-shrink: 0;
}
.head { display: flex; align-items: center; justify-content: space-between; }
.title { font-size: 12px; font-weight: 600; color: var(--ink-900); letter-spacing: 0.2px; }
.hint { font-size: 10px; color: var(--ink-400); padding: 1px 6px; border: 1px solid var(--border); border-radius: 3px; }

.search {
  display: flex; align-items: center; gap: 6px;
  padding: 6px 8px;
  border: 1px solid var(--border);
  background: var(--bg);
  border-radius: 4px;
  color: var(--ink-500);
}
.search input {
  flex: 1; border: none; outline: none; background: transparent;
  font-size: 12.5px; color: var(--ink-900);
  font-family: inherit;
}
.search input::placeholder { color: var(--ink-400); }
.search input:disabled { cursor: not-allowed; }

.empty {
  flex: 1;
  display: flex; flex-direction: column; align-items: center; justify-content: center;
  gap: 4px;
  text-align: center;
  color: var(--ink-500);
}
.em-title { font-size: 12px; color: var(--ink-700); font-weight: 500; }
.em-sub { font-size: 11.5px; color: var(--ink-500); }
</style>
