<script setup lang="ts">
import { computed } from 'vue';
import { summarizeError, categorizeError } from '@/utils/format';

const props = defineProps<{
  /** 原始错误文本 (可能很长, 1KB+ 含完整 traceback) */
  raw: string | null | undefined;
  /** 短错误超过该长度才折叠 (短时不折叠), 默认 160 字 */
  inlineThresh?: number;
  /** 是否显示智能类别标签 (限流/鉴权/超时/...). 默认 true */
  showCategory?: boolean;
}>();

const sum = computed(() => summarizeError(props.raw));
const meta = computed(() => categorizeError(sum.value.head, sum.value.root));
// 单行 (inline) 模式下, 短于阈值直显; 长出 head 摘要 + root 因; traceback 进 <details>
// 旧版按 head+root 长度判定, 但 traceback 经常很长而 head 很短, 导致 raw 1KB+ 仍走 inline 全显.
// 改成按 raw 总长度: raw 超阈值就折叠, 不依赖 head 抽取是否"精简".
const isLong = computed(() => (props.raw?.length ?? 0) > (props.inlineThresh ?? 200));
/** 按词边界切, 不要硬切到半个词 (像 "litellm.Ra..." 这种残词)
 *  优先在标点 (: , ; . 空格) 处切, 找不到就硬切 */
const HEAD_SHORT_MAX = 140;
function smartTruncate(s: string, max: number): string {
  if (s.length <= max) return s;
  const slice = s.slice(0, max);
  // 优先级: ; > : > , > 空格 > 硬切
  for (const sep of ['; ', ': ', ', ', ' ']) {
    const i = slice.lastIndexOf(sep);
    if (i > max * 0.5) return slice.slice(0, i) + '…';
  }
  return slice + '…';
}
const headShort = computed(() => smartTruncate(sum.value.head, HEAD_SHORT_MAX));
const rootShort = computed(() => sum.value.root ? smartTruncate(sum.value.root, 240) : null);
</script>

<template>
  <span v-if="!raw" class="ev-empty">—</span>
  <span v-else-if="sum.short || !isLong" class="ev-inline" :title="raw">{{ raw }}</span>
  <span v-else class="ev">
    <span class="ev-head" :title="sum.head">{{ headShort }}</span>
    <!-- 智能类别: 限流/鉴权/超时/服务端/网络. showCategory=false 可关 -->
    <span v-if="(props.showCategory ?? true) && meta.category !== 'unknown'"
          class="ev-cat" :class="`ev-cat-${meta.category}`" :title="meta.rootType ? `类型: ${meta.rootType}${meta.httpStatus ? ` · HTTP ${meta.httpStatus}` : ''}` : meta.label">
      <span class="ev-cat-i">{{ meta.icon }}</span>{{ meta.label }}<span v-if="meta.httpStatus" class="ev-cat-n">{{ meta.httpStatus }}</span>
    </span>
    <span v-if="rootShort" class="ev-root" :title="sum.root ?? undefined"> · 根因 {{ rootShort }}</span>
    <details v-if="sum.traceback" class="ev-tb">
      <summary>查看完整 traceback</summary>
      <pre class="ev-tb-pre">{{ sum.traceback }}</pre>
    </details>
  </span>
</template>

<style>
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
/* 智能类别标签 — 不同类别不同色, 跟 ev-root 平级但更醒目 */
.ev-cat {
  display: inline-flex; align-items: center; gap: 3px;
  font-size: 10.5px; font-weight: 600;
  padding: 1px 7px; border-radius: 10px;
  border: 1px solid;
}
.ev-cat-i { font-size: 11px; line-height: 1; }
.ev-cat-n { font-family: var(--font-mono); font-weight: 700; margin-left: 1px; opacity: .85; }
.ev-cat-rate_limit { background: color-mix(in srgb, #f59e0b 14%, var(--surface)); color: #b45309; border-color: color-mix(in srgb, #f59e0b 35%, var(--border)); }
.ev-cat-auth       { background: color-mix(in srgb, #a855f7 14%, var(--surface)); color: #7e22ce; border-color: color-mix(in srgb, #a855f7 35%, var(--border)); }
.ev-cat-server     { background: color-mix(in srgb, var(--err) 14%, var(--surface)); color: var(--err); border-color: color-mix(in srgb, var(--err) 35%, var(--border)); }
.ev-cat-timeout    { background: color-mix(in srgb, #0ea5e9 14%, var(--surface)); color: #0369a1; border-color: color-mix(in srgb, #0ea5e9 35%, var(--border)); }
.ev-cat-network    { background: color-mix(in srgb, #64748b 14%, var(--surface)); color: #475569; border-color: color-mix(in srgb, #64748b 35%, var(--border)); }
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
