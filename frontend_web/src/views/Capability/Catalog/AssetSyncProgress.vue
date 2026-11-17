<template>
  <div class="sp" :class="`sp-${phase}`">
    <div class="sp-head">
      <span class="sp-dot" aria-hidden="true"></span>
      <div class="sp-headtxt">
        <div class="sp-title" aria-live="polite">{{ title }}</div>
        <div v-if="sub" class="sp-sub">{{ sub }}</div>
      </div>
      <span class="sp-pct">{{ percent }}%</span>
    </div>

    <div class="sp-track" :class="{ 'is-bad': phase === 'failed' }"
         role="progressbar" aria-valuemin="0" aria-valuemax="100"
         :aria-valuenow="percent" :aria-label="title">
      <div class="sp-rail"><div class="sp-fill" :style="{ width: percent + '%' }"></div></div>

      <div class="sp-actor" :style="{ left: percent + '%' }">
        <span v-if="running" class="sp-dust" aria-hidden="true"><i></i><i></i><i></i></span>
        <span v-if="phase === 'auto-retry'" class="sp-bubble sweat" aria-hidden="true">💦</span>
        <span v-else-if="phase === 'failed'" class="sp-bubble dots" aria-hidden="true">…</span>

        <svg class="sp-turtle" :class="turtleClass" viewBox="0 0 64 46" aria-hidden="true">
          <!-- 尾巴 -->
          <path class="tail" d="M12 27 L3.4 23.2 Q2.2 22.8 3.2 21.9 L12 21.2 Z"
                fill="#4f9e67" />
          <!-- 腿 (前两条是远侧, 深一点; 近侧两条压在壳前, 亮一点) -->
          <rect class="leg leg-a" x="15.5" y="30" width="9" height="12" rx="4.5" fill="#4a9660" />
          <rect class="leg leg-c" x="33.5" y="30" width="9" height="12" rx="4.5" fill="#4a9660" />
          <!-- 龟壳: 深色边 + 壳面 + 六边形纹 -->
          <ellipse cx="30" cy="25" rx="19" ry="12.6" fill="#26663f" />
          <ellipse cx="30" cy="23.6" rx="17.4" ry="11" fill="#3f9b63" />
          <path d="M30 15.4 L37.4 19.6 L37.4 27.8 L30 32 L22.6 27.8 L22.6 19.6 Z"
                fill="none" stroke="#9adcae" stroke-width="1.3" opacity="0.75" />
          <path d="M23.2 17.6 Q22.4 22.4 23.4 28.4 M36.8 17.6 Q37.6 22.4 36.6 28.4"
                fill="none" stroke="#9adcae" stroke-width="1.1" opacity="0.5" />
          <rect class="leg leg-b" x="12.5" y="31.5" width="9" height="11" rx="4.5" fill="#6fbf78" />
          <rect class="leg leg-d" x="37" y="31.5" width="9" height="11" rx="4.5" fill="#6fbf78" />
          <!-- 头 + 脖子 -->
          <path d="M45 20.6 Q49 18.8 52.4 20.4 L52.4 25.6 Q48.6 27.2 45 25.8 Z" fill="#5aa968" />
          <ellipse cx="52.6" cy="21" rx="7.4" ry="6.3" fill="#6fbf78" />
          <ellipse cx="54.8" cy="24" rx="4.2" ry="2.4" fill="#a8d8ae" opacity="0.7" />
          <!-- 失败: 双眼变叉; 完成: 张嘴笑 -->
          <template v-if="phase === 'failed'">
            <path d="M53.2 18.8 L56.2 21.6 M56.2 18.8 L53.2 21.6"
                  fill="none" stroke="#23312a" stroke-width="1.2" stroke-linecap="round" />
          </template>
          <circle v-else class="eye" cx="54.8" cy="20.2" r="1.5" fill="#23312a" />
          <path v-if="phase === 'done'" class="smile"
                d="M52 24.2 Q54.6 27.4 57.6 23.9" fill="none"
                stroke="#23312a" stroke-width="1.4" stroke-linecap="round" />
          <path v-else d="M53.4 25 Q54.8 26.2 56.4 25" fill="none"
                stroke="#23312a" stroke-width="1.1" stroke-linecap="round" opacity="0.7" />
        </svg>
      </div>

      <div v-if="phase === 'done'" class="sp-confetti" aria-hidden="true">
        <i v-for="n in 10" :key="n" :style="confettiStyle(n)"></i>
      </div>
    </div>

    <div v-if="stampText" class="sp-stamp" :class="{ 'is-bad': phase === 'failed' }" lang="en">{{ stampText }}</div>

    <div v-if="phase === 'failed'" class="sp-fail">
      <div class="sp-fail-h">⚠ {{ reason }}</div>
      <div v-if="hint" class="sp-fail-hint">建议：{{ hint }}</div>
      <div v-if="savedOnServer" class="sp-fail-safe">资产已保存在服务端工作区，不会丢。</div>
      <details v-if="detail" class="sp-detail">
        <summary>技术详情</summary>
        <pre>{{ detail }}</pre>
      </details>
    </div>
  </div>
</template>

<script setup lang="ts">
import { computed } from 'vue';

export type SyncPhase = 'uploading' | 'saving' | 'syncing' | 'auto-retry' | 'done' | 'failed';

const props = withDefaults(defineProps<{
  phase: SyncPhase;
  percent: number;
  title: string;
  sub?: string;
  stamp?: string;
  reason?: string;
  hint?: string;
  detail?: string;
  /** 失败时内容是否已落盘 (只在真存过时才说"资产不会丢") */
  savedOnServer?: boolean;
}>(), {
  sub: '', stamp: '', reason: '', hint: '', detail: '', savedOnServer: false,
});

const running = computed(() =>
  props.phase === 'uploading' || props.phase === 'saving' || props.phase === 'syncing');

const turtleClass = computed(() => ({
  run: running.value,
  cheer: props.phase === 'done',
  sit: props.phase === 'failed',
  tired: props.phase === 'auto-retry',
}));

// 印章只认两种终态: 成功 SUCCESS (待审时是调用方给的 SUBMITTED), 失败 FAILED
const stampText = computed(() => {
  if (props.phase === 'failed') return 'FAILED';
  return props.phase === 'done' ? props.stamp : '';
});

const CONF_COLORS = ['#f59e0b', '#10b981', '#3b82f6', '#ef4444', '#a855f7'];

function confettiStyle(n: number) {
  const i = n - 1;
  return {
    left: `${10 + i * 8}%`,
    background: CONF_COLORS[i % CONF_COLORS.length],
    animationDelay: `${(i % 4) * 0.05}s`,
    transform: `rotate(${i * 37}deg)`,
  };
}
</script>

<style scoped>
.sp { padding: 6px 2px 2px; }
.sp-head { display: flex; align-items: center; gap: 10px; }
.sp-dot {
  width: 9px; height: 9px; border-radius: 50%; flex: none;
  background: var(--primary); animation: sp-pulse 1.1s ease-in-out infinite;
}
.sp-failed .sp-dot { background: var(--err); animation: none; }
.sp-done .sp-dot { background: var(--ok); animation: none; }
.sp-auto-retry .sp-dot { background: var(--warn); }
.sp-headtxt { flex: 1; min-width: 0; }
.sp-title { font-size: 14px; font-weight: 700; color: var(--ink-900); }
.sp-sub { margin-top: 2px; font-size: 11.5px; color: var(--ink-500); }
.sp-pct {
  font-size: 20px; font-weight: 800; color: var(--primary);
  font-variant-numeric: tabular-nums;
}
.sp-failed .sp-pct { color: var(--err); }
.sp-auto-retry .sp-pct { color: var(--warn); }

/* ===== 轨道 ===== */
.sp-track { position: relative; margin: 52px 6px 0; height: 14px; }
.sp-rail {
  position: absolute; inset: 0; border-radius: 999px; overflow: hidden;
  background: var(--surface-sunken); border: 1px solid var(--border);
}
.sp-fill {
  height: 100%; border-radius: 999px; transition: width 0.6s ease;
  background: linear-gradient(90deg, var(--primary), #7c9cff 55%, #a78bfa);
  background-size: 160% 100%; animation: sp-flow 2.2s linear infinite;
}
.sp-track.is-bad .sp-rail { border-style: dashed; border-color: rgba(239, 68, 68, 0.5); }
.sp-track.is-bad .sp-fill {
  background: linear-gradient(90deg, #ef4444, #f87171); animation: none;
}
.sp-done .sp-fill { background: linear-gradient(90deg, #10b981, #34d399); animation: none; }

/* ===== 乌龟 ===== */
.sp-actor {
  position: absolute; top: 0; width: 0; height: 0;
  transition: left 0.6s ease, transform 0.3s ease; z-index: 2;
}
.sp-turtle {
  position: absolute; left: -26px; bottom: 0; width: 60px; height: 44px;
  overflow: visible; filter: drop-shadow(0 2px 2px rgba(0, 0, 0, 0.18));
}
/* 龟速前进: 慢节奏左右摇摆, 四条短腿小幅度划水 */
.sp-turtle.run { animation: sp-waddle 0.62s ease-in-out infinite alternate; }
.sp-turtle.run .leg-a,
.sp-turtle.run .leg-d {
  transform-box: fill-box; transform-origin: 50% 0;
  animation: sp-paddle 0.48s ease-in-out infinite alternate;
}
.sp-turtle.run .leg-b,
.sp-turtle.run .leg-c {
  transform-box: fill-box; transform-origin: 50% 0;
  animation: sp-paddle 0.48s ease-in-out infinite alternate-reverse;
}
.sp-turtle.run .tail {
  transform-box: fill-box; transform-origin: 100% 50%;
  animation: sp-tail-sway 0.8s ease-in-out infinite alternate;
}
.sp-turtle.cheer { animation: sp-hop 0.6s ease 1; }
/* 冲线时乌龟头会伸出轨道右端 —— 整只往回挪, 别顶出面板 */
.sp-done .sp-actor { transform: translateX(-26px); }
.sp-turtle.sit {
  transform: translate(1px, 7px) rotate(-5deg);
  filter: grayscale(0.4) drop-shadow(0 2px 2px rgba(0, 0, 0, 0.15));
}
.sp-turtle.tired { animation: sp-pant 1.3s ease-in-out infinite; }

/* ===== 尘土 / 气泡 / 礼花 ===== */
.sp-dust { position: absolute; left: -30px; bottom: -4px; }
.sp-dust i {
  position: absolute; bottom: 0; width: 7px; height: 7px; border-radius: 50%;
  background: rgba(148, 163, 184, 0.55);
  animation: sp-dust 0.55s linear infinite;
}
.sp-dust i:nth-child(2) { width: 5px; height: 5px; animation-delay: 0.18s; }
.sp-dust i:nth-child(3) { width: 9px; height: 9px; animation-delay: 0.34s; }

.sp-bubble {
  position: absolute; left: 20px; top: -50px; font-size: 13px; line-height: 1;
}
.sp-bubble.sweat { animation: sp-sweat 1s ease-in-out infinite; }
.sp-bubble.dots { color: var(--ink-400); letter-spacing: 1px; }

.sp-confetti { position: absolute; inset: 0; pointer-events: none; }
.sp-confetti i {
  position: absolute; top: -6px; width: 6px; height: 10px; border-radius: 2px;
  animation: sp-confetti 1.1s ease-out both;
}
.sp-confetti i:nth-child(2n) { width: 5px; height: 5px; border-radius: 50%; }
.sp-confetti i:nth-child(3n) { width: 8px; height: 4px; }

/* ===== 印章: 成功 SUCCESS / 失败 FAILED —— 橡胶章, 双线外框, 狠狠盖下去 ===== */
.sp-stamp {
  margin: 18px auto 2px; width: fit-content; padding: 5px 20px 6px;
  border: 2.5px solid var(--ok); border-radius: 9px;
  outline: 1.5px solid var(--ok); outline-offset: 3px;
  background: rgba(16, 185, 129, 0.06);
  color: var(--ok);
  font-size: 22px; font-weight: 900; line-height: 1.15;
  letter-spacing: 0.18em; text-indent: 0.18em; text-transform: uppercase;
  transform: rotate(-5deg);
  animation: sp-stamp 0.5s cubic-bezier(0.2, 1.5, 0.4, 1) both;
}
.sp-stamp.is-bad {
  border-color: var(--err); outline-color: var(--err);
  background: rgba(239, 68, 68, 0.06);
  color: var(--err);
  transform: rotate(4deg);
  animation-name: sp-stamp-bad;
}

/* ===== 失败卡片 ===== */
.sp-fail {
  margin-top: 18px; padding: 12px 14px; border-radius: var(--radius-sm);
  background: rgba(239, 68, 68, 0.06); border: 1px solid rgba(239, 68, 68, 0.28);
}
.sp-fail-h { font-size: 13px; font-weight: 700; color: var(--err); }
.sp-fail-hint { margin-top: 5px; font-size: 11.5px; color: var(--ink-700); }
.sp-fail-safe { margin-top: 7px; font-size: 11.5px; color: var(--ink-500); }
.sp-detail { margin-top: 9px; font-size: 11px; color: var(--ink-500); }
.sp-detail summary { cursor: pointer; user-select: none; }
.sp-detail pre {
  margin: 6px 0 0; padding: 8px 10px; max-height: 160px; overflow: auto;
  background: var(--surface-sunken); border-radius: 6px;
  font-family: var(--font-mono); font-size: 10.5px; line-height: 1.55;
  color: var(--ink-700); white-space: pre-wrap; word-break: break-all;
}

@keyframes sp-pulse { 0%, 100% { opacity: 1; } 50% { opacity: 0.35; } }
@keyframes sp-flow { from { background-position: 0 0; } to { background-position: 160% 0; } }
@keyframes sp-waddle {
  from { transform: translateY(0) rotate(-2.5deg); }
  to { transform: translateY(-2.5px) rotate(2deg); }
}
@keyframes sp-paddle { from { transform: rotate(12deg); } to { transform: rotate(-12deg); } }
@keyframes sp-tail-sway { from { transform: rotate(-9deg); } to { transform: rotate(11deg); } }
@keyframes sp-hop {
  0% { transform: translateY(0) rotate(0); }
  40% { transform: translateY(-9px) rotate(-6deg); }
  70% { transform: translateY(-3px) rotate(3deg); }
  100% { transform: translateY(0) rotate(0); }
}
@keyframes sp-pant { 0%, 100% { transform: translateY(0) scale(1); } 50% { transform: translateY(1px) scale(1.03); } }
@keyframes sp-dust {
  0% { opacity: 0.8; transform: translate(0, 0) scale(0.6); }
  100% { opacity: 0; transform: translate(-16px, -4px) scale(1.2); }
}
@keyframes sp-sweat {
  0%, 100% { transform: translateY(0); opacity: 1; }
  50% { transform: translateY(4px); opacity: 0.55; }
}
@keyframes sp-confetti {
  0% { opacity: 1; transform: translateY(0) rotate(0); }
  100% { opacity: 0; transform: translateY(34px) rotate(240deg); }
}
@keyframes sp-stamp {
  0% { opacity: 0; transform: rotate(-5deg) scale(2.2); }
  60% { opacity: 1; transform: rotate(-5deg) scale(0.95); }
  100% { opacity: 1; transform: rotate(-5deg) scale(1); }
}
@keyframes sp-stamp-bad {
  0% { opacity: 0; transform: rotate(4deg) scale(2.2); }
  60% { opacity: 1; transform: rotate(4deg) scale(0.95); }
  100% { opacity: 1; transform: rotate(4deg) scale(1); }
}

@media (prefers-reduced-motion: reduce) {
  .sp-turtle, .sp-turtle .leg, .sp-turtle .tail, .sp-dot,
  .sp-fill, .sp-dust i, .sp-bubble, .sp-confetti i, .sp-stamp {
    animation: none !important;
  }
  .sp-confetti { display: none; }
  .sp-fill, .sp-actor { transition: none; }
}
</style>
