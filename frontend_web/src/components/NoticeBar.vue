<template>
  <!-- 顶部统一滚动通知栏: 贴在 AppHeader 下、页面主内容上, 一行高, 全宽.
       1 条 notice: 直接展示.
       多条: 自动轮播 (每 ~5s 切到下一条, 带平滑过渡), 也可手动 ◀ ▶.
       每条独立 ✕ (走 dismissKey, 关掉后从可见列表里移除, 其它继续轮播).
       文案片段: {{xxx}} → strong, [xxx](href) → link. -->
  <div
    v-if="visibleNotices.length > 0"
    class="notice-bar"
    :class="`notice-bar-${current.type || 'info'}`"
    role="region"
    aria-label="通知栏"
  >
    <div class="nb-icon" aria-hidden="true">{{ iconFor(current.type) }}</div>

    <transition name="nb-slide" mode="out-in">
      <div :key="current.id" class="nb-body" role="status">
        <template v-for="(seg, i) in renderSegments(current)" :key="i">
          <a v-if="seg.kind === 'link'" :href="seg.href" class="nb-link">{{ seg.text }}</a>
          <strong v-else-if="seg.kind === 'strong'">{{ seg.text }}</strong>
          <span v-else>{{ seg.text }}</span>
        </template>
      </div>
    </transition>

    <div v-if="visibleNotices.length > 1" class="nb-nav" aria-label="切换通知">
      <button class="nb-nav-btn" type="button" aria-label="上一条" @click="prev">‹</button>
      <span class="nb-count" aria-live="polite">{{ idx + 1 }} / {{ visibleNotices.length }}</span>
      <button class="nb-nav-btn" type="button" aria-label="下一条" @click="next">›</button>
    </div>

    <button
      class="nb-close"
      type="button"
      :title="current.dismissTitle || '关闭 (本次会话内不再显示)'"
      :aria-label="current.dismissTitle || '关闭通知'"
      @click="dismissCurrent"
    >✕</button>
  </div>
</template>

<script setup lang="ts">
import { computed, onBeforeUnmount, ref, watch } from 'vue';

/** 单条通知 */
export interface NoticeItem {
  id: string;
  type?: 'info' | 'warn' | 'err' | 'ok';
  text: string;
  dismissKey?: string;
  dismissScope?: 'local' | 'session';
  dismissible?: boolean;
  dismissTitle?: string;
}

type Segment = { kind: 'text'; text: string } | { kind: 'strong'; text: string } | { kind: 'link'; text: string; href: string };

const props = defineProps<{ notices: NoticeItem[] }>();
const emit = defineEmits<{ (e: 'dismiss', id: string): void }>();

const ROTATE_MS = 5000;

function readDismiss(key: string, scope: 'local' | 'session'): boolean {
  try {
    return (scope === 'session' ? sessionStorage : localStorage).getItem(key) === '1';
  } catch { return false; }
}
function writeDismiss(key: string, scope: 'local' | 'session') {
  try { (scope === 'session' ? sessionStorage : localStorage).setItem(key, '1'); }
  catch { /* 隐私模式 quota 满 → 静默 */ }
}

/** 可见列表 (去掉 dismiss 掉的). dismiss 后从 props.notices 里 filter 掉对应 id,
    这样轮播 idx 才不会跳到空位. */
const visibleNotices = computed<NoticeItem[]>(() => {
  const live = props.notices.filter(n => {
    if (!n.dismissKey) return true;
    return !readDismiss(n.dismissKey, n.dismissScope || 'local');
  });
  // 父组件也可以通过 dismiss 事件移除; 这里给个 set 记录组件实例内已 dismiss 的.
  return live.filter(n => !locallyDismissed.value.has(n.id));
});

const locallyDismissed = ref<Set<string>>(new Set());

/** 当前显示第几条 */
const idx = ref(0);
const current = computed(() => visibleNotices.value[Math.min(idx.value, visibleNotices.value.length - 1)] || visibleNotices.value[0]);

/** 轮播定时器: 多条才转, hover 暂停. */
let timer: number | undefined;
function startTimer() {
  stopTimer();
  if (visibleNotices.value.length <= 1) return;
  timer = window.setInterval(() => {
    idx.value = (idx.value + 1) % visibleNotices.value.length;
  }, ROTATE_MS);
}
function stopTimer() {
  if (timer !== undefined) { window.clearInterval(timer); timer = undefined; }
}
watch(visibleNotices, () => {
  // 列表变了 (dismiss / 登录状态变) → 复位 idx 并重启 timer
  idx.value = 0;
  startTimer();
}, { immediate: true });
onBeforeUnmount(stopTimer);

function prev() { idx.value = (idx.value - 1 + visibleNotices.value.length) % visibleNotices.value.length; }
function next() { idx.value = (idx.value + 1) % visibleNotices.value.length; }

function dismissCurrent() {
  const n = current.value;
  if (!n) return;
  if (n.dismissible === false) return;
  if (n.dismissKey) writeDismiss(n.dismissKey, n.dismissScope || 'local');
  locallyDismissed.value.add(n.id);
  locallyDismissed.value = new Set(locallyDismissed.value);
  emit('dismiss', n.id);
}

function iconFor(type?: NoticeItem['type']): string {
  switch (type) {
    case 'warn': return '⚠️';
    case 'err':  return '⛔';
    case 'ok':   return '✅';
    case 'info':
    default:     return '🔔';
  }
}

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
</script>

<style scoped>
/* 通知栏: 贴在 AppHeader 下, 全宽一行高, 不抢戏 (跟主题色, 背景柔和).
   多个 notice 时支持轮播 (切换有 nb-slide 过渡); hover 暂停由调用方控制 (这里没接,
   因为现在 notice 数量 ≤ 1 时不轮播, ≥ 2 时快速轮, 用户停留时间短). */
.notice-bar {
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 8px 14px;
  border-radius: var(--radius-card);
  border: 1px solid;
  font-size: 12.5px;
  line-height: 1.5;
  /* 顶部位置: margin-top 给 run-hd 之前的间距 */
  margin-bottom: 14px;
  min-height: 38px;
  overflow: hidden;
}
/* 4 种类型 → 不同色调 (跟设计 token 走, 浅深主题都清晰) */
.notice-bar-info {
  background: color-mix(in srgb, var(--info, var(--primary)) 10%, var(--surface-soft));
  border-color: color-mix(in srgb, var(--info, var(--primary)) 40%, var(--border));
  color: color-mix(in srgb, var(--info, var(--primary)) 70%, var(--ink-900));
}
.notice-bar-warn {
  background: color-mix(in srgb, var(--warn) 12%, var(--surface-soft));
  border-color: color-mix(in srgb, var(--warn) 45%, var(--border));
  color: color-mix(in srgb, var(--warn) 75%, var(--ink-900));
}
.notice-bar-err {
  background: color-mix(in srgb, var(--err) 10%, var(--surface-soft));
  border-color: color-mix(in srgb, var(--err) 45%, var(--border));
  color: color-mix(in srgb, var(--err) 75%, var(--ink-900));
}
.notice-bar-ok {
  background: color-mix(in srgb, var(--ok) 10%, var(--surface-soft));
  border-color: color-mix(in srgb, var(--ok) 40%, var(--border));
  color: color-mix(in srgb, var(--ok) 70%, var(--ink-900));
}
.nb-icon { font-size: 14px; flex-shrink: 0; }
.notice-bar-info .nb-icon { color: var(--info, var(--primary)); }
.notice-bar-warn .nb-icon { color: var(--warn); }
.notice-bar-err  .nb-icon { color: var(--err); }
.notice-bar-ok   .nb-icon { color: var(--ok); }
.nb-body { flex: 1; min-width: 0; }
.nb-body strong { font-weight: 700; }
.nb-link {
  color: inherit; text-decoration: none; font-weight: 600;
  border-bottom: 1px dashed currentColor;
}
.nb-link:hover { border-bottom-style: solid; }
/* 轮播 nav: 多条时才显示 */
.nb-nav { display: flex; align-items: center; gap: 4px; flex-shrink: 0; }
.nb-nav-btn {
  border: 1px solid currentColor; background: transparent; color: inherit;
  width: 22px; height: 22px; border-radius: 4px; cursor: pointer;
  font-size: 13px; line-height: 1; opacity: 0.55; padding: 0;
  display: inline-flex; align-items: center; justify-content: center;
}
.nb-nav-btn:hover { opacity: 1; background: color-mix(in srgb, currentColor 10%, transparent); }
.nb-count { font-size: 11px; opacity: 0.7; min-width: 36px; text-align: center; font-family: var(--font-mono); }
/* 关闭 */
.nb-close {
  border: none; background: transparent; color: inherit;
  font-size: 13px; line-height: 1; cursor: pointer; opacity: 0.55;
  padding: 4px 8px; border-radius: 4px; flex-shrink: 0;
  transition: opacity 0.15s, background 0.15s;
}
.nb-close:hover { opacity: 1; background: color-mix(in srgb, currentColor 12%, transparent); }
/* 轮播切换动画 */
.nb-slide-enter-active, .nb-slide-leave-active { transition: transform 0.35s ease, opacity 0.35s ease; }
.nb-slide-enter-from { transform: translateX(20px); opacity: 0; }
.nb-slide-leave-to   { transform: translateX(-20px); opacity: 0; }
</style>
