<template>
  <!-- 通用滚动通知栏: 顶部统一收纳所有轻量提示 (匿名访问 / 系统公告 / 实验性功能等).
       多个 notice 垂直堆叠, 每个独立可关, 关掉后写到 storage (localStorage / sessionStorage 均可, 走 dismissScope 配置).
       跟页面内容 (看板) 区分开, 不抢占状态徽章/筛选区的注意力. -->
  <div v-if="visibleNotices.length > 0" class="notice-bar" role="region" aria-label="通知栏">
    <div
      v-for="n in visibleNotices"
      :key="n.id"
      class="notice"
      :class="`notice-${n.type || 'info'}`"
      role="status"
    >
      <span class="n-icon">{{ iconFor(n.type) }}</span>
      <span class="n-text">
        <template v-for="(seg, i) in renderSegments(n)" :key="i">
          <a v-if="seg.kind === 'link'" :href="seg.href" class="n-link">{{ seg.text }}</a>
          <strong v-else-if="seg.kind === 'strong'">{{ seg.text }}</strong>
          <span v-else>{{ seg.text }}</span>
        </template>
      </span>
      <button
        v-if="n.dismissible !== false"
        class="n-close"
        type="button"
        :title="n.dismissTitle || '关闭 (本次会话不再显示)'"
        :aria-label="n.dismissTitle || '关闭通知'"
        @click="dismiss(n)"
      >✕</button>
    </div>
  </div>
</template>

<script setup lang="ts">
import { computed } from 'vue';

/** 单条通知 */
export interface NoticeItem {
  /** 唯一 id (同一 notice 跨次渲染要稳定, localStorage 用它做 dismiss key) */
  id: string;
  /** 类型 → 颜色 / 图标 */
  type?: 'info' | 'warn' | 'err' | 'ok';
  /** 文本片段: 字符串里匹配 {{text}} 会渲染为 <strong>, 链接用 [text](href) */
  text: string;
  /** 关闭后写 storage 的 key (传空 = 不记忆, 每次刷新都显示) */
  dismissKey?: string;
  /** 关闭后写哪个 storage:
   *  - 'local' (默认): 写入 localStorage, 关掉后长期不显示 (适合系统公告)
   *  - 'session':     写入 sessionStorage, 关掉后当前 tab 内不显示, 刷新/新标签页/明天会再出现 (适合持续性提示如匿名访问) */
  dismissScope?: 'local' | 'session';
  /** 是否可关闭 (默认 true) */
  dismissible?: boolean;
  /** 关闭按钮 title */
  dismissTitle?: string;
}

/** 渲染用的文本片段 */
type Segment = { kind: 'text'; text: string } | { kind: 'strong'; text: string } | { kind: 'link'; text: string; href: string };

const props = defineProps<{ notices: NoticeItem[] }>();

function readDismiss(key: string, scope: 'local' | 'session'): boolean {
  try {
    return (scope === 'session' ? sessionStorage : localStorage).getItem(key) === '1';
  } catch { return false; }
}
function writeDismiss(key: string, scope: 'local' | 'session') {
  try { (scope === 'session' ? sessionStorage : localStorage).setItem(key, '1'); }
  catch { /* 隐私模式 quota 满 → 静默 */ }
}

const visibleNotices = computed<NoticeItem[]>(() =>
  props.notices.filter(n => !n.dismissKey || !readDismiss(n.dismissKey, n.dismissScope || 'local'))
);

function iconFor(type?: NoticeItem['type']): string {
  switch (type) {
    case 'warn': return '⚠️';
    case 'err':  return '⛔';
    case 'ok':   return '✅';
    case 'info':
    default:     return '🔔';
  }
}

/** 解析文本: `{{xxx}}` → strong, `[xxx](href)` → link */
function renderSegments(n: NoticeItem): Segment[] {
  const segs: Segment[] = [];
  const re = /(\{\{[^}]+\}\}|\[[^\]]+\]\([^)]+\))/g;
  let last = 0;
  let m: RegExpExecArray | null;
  while ((m = re.exec(n.text)) !== null) {
    if (m.index > last) segs.push({ kind: 'text', text: n.text.slice(last, m.index) });
    const tok = m[0];
    if (tok.startsWith('{{')) {
      segs.push({ kind: 'strong', text: tok.slice(2, -2) });
    } else if (tok.startsWith('[')) {
      const lm = tok.match(/^\[([^\]]+)\]\(([^)]+)\)$/)!;
      segs.push({ kind: 'link', text: lm[1], href: lm[2] });
    }
    last = re.lastIndex;
  }
  if (last < n.text.length) segs.push({ kind: 'text', text: n.text.slice(last) });
  return segs;
}

function dismiss(n: NoticeItem) {
  if (n.dismissKey) writeDismiss(n.dismissKey, n.dismissScope || 'local');
  // 触发 computed 重算: 用 props.notices 的 mutation 不优雅 (父组件不知),
  // 这里走事件让父组件自己过滤, 保证数据流单向.
  emit('dismiss', n.id);
}

const emit = defineEmits<{
  (e: 'dismiss', id: string): void;
}>();
</script>

<style scoped>
/* 通知栏容器: 顶部独立区域, 不跟 .cr 的 card / banner 重叠. */
.notice-bar {
  display: flex;
  flex-direction: column;
  gap: 6px;
  margin-bottom: 14px;
}
/* 单条通知: 跟 .banner 同宽, 但更轻量 (无边框 hover 效果, 一行紧凑). */
.notice {
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 8px 14px;
  border-radius: var(--radius-card);
  font-size: 12.5px;
  line-height: 1.5;
  border: 1px solid;
}
/* info: 蓝调, 默认匿名/通用提示 */
.notice-info {
  background: color-mix(in srgb, var(--info, var(--primary)) 10%, var(--surface-soft));
  border-color: color-mix(in srgb, var(--info, var(--primary)) 40%, var(--border));
  color: color-mix(in srgb, var(--info, var(--primary)) 70%, var(--ink-900));
}
.notice-warn {
  background: color-mix(in srgb, var(--warn) 12%, var(--surface-soft));
  border-color: color-mix(in srgb, var(--warn) 45%, var(--border));
  color: color-mix(in srgb, var(--warn) 75%, var(--ink-900));
}
.notice-err {
  background: color-mix(in srgb, var(--err) 10%, var(--surface-soft));
  border-color: color-mix(in srgb, var(--err) 45%, var(--border));
  color: color-mix(in srgb, var(--err) 75%, var(--ink-900));
}
.notice-ok {
  background: color-mix(in srgb, var(--ok) 10%, var(--surface-soft));
  border-color: color-mix(in srgb, var(--ok) 40%, var(--border));
  color: color-mix(in srgb, var(--ok) 70%, var(--ink-900));
}
.n-icon { font-size: 14px; flex-shrink: 0; }
.notice-info .n-icon { color: var(--info, var(--primary)); }
.notice-warn .n-icon { color: var(--warn); }
.notice-err  .n-icon { color: var(--err); }
.notice-ok   .n-icon { color: var(--ok); }
.n-text { flex: 1; min-width: 0; }
.n-text strong { font-weight: 700; }
.n-link {
  color: inherit;
  text-decoration: none;
  font-weight: 600;
  border-bottom: 1px dashed currentColor;
}
.n-link:hover { border-bottom-style: solid; }
.n-close {
  border: none; background: transparent; color: inherit;
  font-size: 14px; line-height: 1; cursor: pointer; opacity: 0.55;
  padding: 4px 8px; border-radius: 4px; flex-shrink: 0;
  transition: opacity 0.15s, background 0.15s;
}
.n-close:hover { opacity: 1; background: color-mix(in srgb, currentColor 12%, transparent); }
</style>
