<template>
  <aside class="tm-rag">
    <div class="head">
      <div class="title">协议检索</div>
      <span class="badge">P1</span>
    </div>

    <div class="search card">
      <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">
        <circle cx="11" cy="11" r="7"/><line x1="21" y1="21" x2="16.65" y2="16.65"/>
      </svg>
      <input v-model="q" type="text" placeholder="搜索 NVMe / JEDEC 规范" disabled />
    </div>

    <div class="empty card">
      <div class="em-ic">
        <svg width="32" height="32" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round">
          <path d="M21 16V8a2 2 0 0 0-1-1.73l-7-4a2 2 0 0 0-2 0l-7 4A2 2 0 0 0 3 8v8a2 2 0 0 0 1 1.73l7 4a2 2 0 0 0 2 0l7-4A2 2 0 0 0 21 16z"/>
          <polyline points="3.27 6.96 12 12.01 20.73 6.96"/><line x1="12" y1="22.08" x2="12" y2="12"/>
        </svg>
      </div>
      <div class="em-title">RAGFlow 未接入</div>
      <div class="em-sub">P1 启动后,命中片段会列在这里,点击跳转主区</div>
    </div>
  </aside>
</template>

<script setup lang="ts">
import { ref } from 'vue';
const q = ref('');
</script>

<style scoped>
.tm-rag {
  width: 280px;
  padding: 20px 16px;
  display: flex;
  flex-direction: column;
  gap: 12px;
  flex-shrink: 0;
}
.head { display: flex; align-items: center; justify-content: space-between; padding: 0 4px; }
.title { font-size: 13px; font-weight: 600; color: var(--ink-900); letter-spacing: 0.2px; }
.badge {
  font-size: 10.5px; font-weight: 500;
  padding: 2px 8px; border-radius: var(--radius-pill);
  background: var(--primary-soft);
  color: var(--primary);
}

.search {
  display: flex; align-items: center; gap: 8px;
  padding: 10px 12px;
  color: var(--ink-500);
}
.search input {
  flex: 1; border: none; outline: none; background: transparent;
  font-size: 13px; color: var(--ink-900);
  font-family: inherit;
}
.search input::placeholder { color: var(--ink-400); }
.search input:disabled { cursor: not-allowed; }

.empty {
  flex: 1;
  display: flex; flex-direction: column; align-items: center; justify-content: center;
  text-align: center;
  gap: 8px;
  padding: 24px 16px;
  background: var(--surface);
  border-style: dashed;
}
.em-ic { color: var(--ink-400); margin-bottom: 4px; }
.em-title { font-size: 13px; color: var(--ink-700); font-weight: 600; }
.em-sub { font-size: 12px; color: var(--ink-500); line-height: 1.55; max-width: 200px; }
</style>
