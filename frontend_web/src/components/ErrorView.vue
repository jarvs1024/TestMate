<script setup lang="ts">
import { computed } from 'vue';
import { summarizeError } from '@/utils/format';

const props = defineProps<{
  /** 原始错误文本 (可能很长, 1KB+ 含完整 traceback) */
  raw: string | null | undefined;
  /** 短错误超过该长度才折叠 (短时不折叠), 默认 160 字 */
  inlineThresh?: number;
}>();

const sum = computed(() => summarizeError(props.raw));
// 单行 (inline) 模式下, 短于阈值直显; 长出 head 摘要 + root 因; traceback 进 <details>
const isLong = computed(() => !sum.value.short && (sum.value.head.length + (sum.value.root?.length || 0)) > (props.inlineThresh ?? 160));
const headShort = computed(() => {
  const h = sum.value.head;
  return h.length > 140 ? h.slice(0, 140) + '…' : h;
});
</script>

<template>
  <span v-if="!raw" class="ev-empty">—</span>
  <span v-else-if="sum.short || !isLong" class="ev-inline" :title="raw">{{ raw }}</span>
  <span v-else class="ev">
    <span class="ev-head" :title="sum.head">{{ headShort }}</span>
    <span v-if="sum.root" class="ev-root"> · 根因 {{ sum.root }}</span>
    <details v-if="sum.traceback" class="ev-tb">
      <summary>查看完整 traceback</summary>
      <pre class="ev-tb-pre">{{ sum.traceback }}</pre>
    </details>
  </span>
</template>

<style scoped>
.ev-inline {
  font-family: var(--font-mono); font-size: 11.5px; line-height: 1.5;
  color: color-mix(in srgb, var(--err) 85%, var(--ink-900));
  word-break: break-word; white-space: pre-wrap;
  max-width: 480px; display: inline-block;
}
.ev { display: inline-flex; flex-direction: column; align-items: flex-start; gap: 4px; max-width: 100%; }
.ev-head {
  font-family: var(--font-mono); font-size: 11.5px; line-height: 1.5;
  color: color-mix(in srgb, var(--err) 85%, var(--ink-900));
  word-break: break-word;
}
.ev-root {
  font-size: 11px;
  color: color-mix(in srgb, var(--err) 90%, var(--ink-700));
  background: color-mix(in srgb, var(--err) 10%, transparent);
  border: 1px solid color-mix(in srgb, var(--err) 25%, transparent);
  padding: 1px 8px; border-radius: 4px;
  font-family: var(--font-mono);
}
.ev-empty { color: var(--ink-500); }
.ev-tb summary {
  list-style: none; cursor: pointer; user-select: none;
  font-size: 11px; color: var(--ink-500);
  padding: 2px 8px; border-radius: 4px;
  background: var(--surface); border: 1px dashed var(--border);
}
.ev-tb summary::-webkit-details-marker { display: none; }
.ev-tb summary:hover { color: var(--primary); border-color: var(--primary); }
.ev-tb-pre {
  margin: 4px 0 0; padding: 8px 10px;
  background: color-mix(in srgb, var(--err) 6%, var(--surface-sunken));
  border: 1px solid color-mix(in srgb, var(--err) 20%, transparent);
  border-radius: 6px;
  font-family: var(--font-mono); font-size: 11px;
  color: color-mix(in srgb, var(--err) 80%, var(--ink-900)); line-height: 1.5;
  white-space: pre-wrap; word-break: break-word;
  max-height: 240px; overflow: auto;
}
</style>
