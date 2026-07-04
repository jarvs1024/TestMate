<template>
  <aside class="tm-rag">
    <div class="head">
      <div class="title">📖 协议随身</div>
      <div class="sub">NVMe · JEDEC · 企业 spec</div>
    </div>

    <div class="search">
      <span class="icon">🔍</span>
      <input
        v-model="query"
        type="text"
        placeholder="搜索 NVMe 2.0 random write latency…"
        :disabled="true"
      />
    </div>

    <div class="empty">
      <div class="empty-mark">📡</div>
      <div class="empty-title">RAGFlow 待接入</div>
      <div class="empty-hint">P1 启动后,这里会展示命中片段,点跳转主区阅读原文</div>
    </div>

    <div class="foot">
      <div class="kbd">⌘K</div>
      <span>快捷搜索</span>
    </div>
  </aside>
</template>

<script setup lang="ts">
import { ref } from 'vue';
const query = ref('');
</script>

<style scoped>
.tm-rag {
  width: 300px;
  display: flex;
  flex-direction: column;
  background: var(--surface-soft);
  backdrop-filter: blur(6px);
  -webkit-backdrop-filter: blur(6px);
  border-left: 1px solid var(--border);
  padding: 16px 14px;
  flex-shrink: 0;
  gap: 12px;
}
.head .title { font-size: 14px; font-weight: 600; color: var(--ink-900); }
.head .sub { font-size: 11.5px; color: var(--ink-500); margin-top: 2px; }

.search {
  display: flex;
  align-items: center;
  gap: 8px;
  background: var(--surface);
  border: 1px solid var(--border);
  border-radius: var(--radius-md);
  padding: 7px 10px;
  transition: border-color .15s ease, box-shadow .15s ease;
}
.search:focus-within {
  border-color: var(--primary);
  box-shadow: 0 0 0 3px var(--primary-soft);
}
.search .icon { color: var(--ink-400); font-size: 13px; }
.search input {
  flex: 1; border: none; outline: none;
  background: transparent;
  font-size: 13px;
  color: var(--ink-900);
  font-family: inherit;
}
.search input::placeholder { color: var(--ink-400); }
.search input:disabled { cursor: not-allowed; }

.empty {
  flex: 1;
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  text-align: center;
  padding: 24px 12px;
  border-radius: var(--radius-md);
  background: var(--surface);
  border: 1px dashed var(--border);
  gap: 6px;
}
.empty-mark { font-size: 28px; opacity: .7; }
.empty-title { font-size: 13px; font-weight: 600; color: var(--ink-700); }
.empty-hint { font-size: 11.5px; color: var(--ink-500); line-height: 1.55; }

.foot {
  display: flex; align-items: center; gap: 8px;
  font-size: 11.5px; color: var(--ink-500);
}
.kbd {
  font-family: var(--font-mono);
  font-size: 10.5px;
  padding: 2px 6px;
  border-radius: 4px;
  background: var(--surface);
  border: 1px solid var(--border);
  color: var(--ink-700);
}
</style>
