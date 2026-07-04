<template>
  <div class="tm-uc">
    <div class="badge-row">
      <span class="chip chip-soon">P1 计划中</span>
      <span class="chip chip-eta">预计 3 周内</span>
    </div>

    <h2 class="title">
      {{ title }}
      <span class="tm-serif suffix">— 在路上</span>
    </h2>
    <p class="lede">{{ lede }}</p>

    <div class="timeline">
      <div class="step done">
        <div class="dot"></div>
        <div class="lbl">P0 脚手架</div>
      </div>
      <div class="line done"></div>
      <div class="step current">
        <div class="dot"></div>
        <div class="lbl">P1 核心场景</div>
      </div>
      <div class="line"></div>
      <div class="step">
        <div class="dot"></div>
        <div class="lbl">P2 增强</div>
      </div>
    </div>

    <ul class="plan">
      <li v-for="(p, i) in plan" :key="i">
        <span class="bullet">›</span>
        <span>{{ p }}</span>
      </li>
    </ul>

    <div class="hint">
      想优先这个? 在
      <a class="link" href="javascript:void(0)" @click="$emit('feedback')">反馈墙</a>
      留言
    </div>
  </div>
</template>

<script setup lang="ts">
defineProps<{
  title: string;
  lede: string;
  plan: string[];
}>();
defineEmits<{ (e: 'feedback'): void }>();
</script>

<style scoped>
.tm-uc {
  max-width: 720px;
  margin: 0 auto;
  padding: 48px 36px;
  background: var(--surface);
  border: 1px solid var(--border);
  border-radius: var(--radius-lg);
  box-shadow: var(--shadow-md);
}

.badge-row { display: flex; gap: 8px; margin-bottom: 14px; }
.chip {
  font-size: 11px; padding: 3px 10px; border-radius: 999px;
  border: 1px solid transparent;
  font-weight: 500;
  letter-spacing: 0.2px;
}
.chip-soon {
  background: var(--primary-soft);
  color: var(--primary);
}
.chip-eta {
  background: var(--surface-sunken);
  color: var(--ink-500);
  border-color: var(--border);
}

.title {
  font-size: 26px;
  font-weight: 700;
  color: var(--ink-900);
  margin: 0 0 8px;
  line-height: 1.3;
}
.title .suffix {
  color: var(--ink-500);
  font-size: 22px;
  margin-left: 4px;
}

.lede {
  font-size: 14.5px;
  color: var(--ink-700);
  line-height: 1.65;
  margin: 0 0 28px;
}

.timeline {
  display: flex;
  align-items: center;
  gap: 0;
  margin-bottom: 28px;
}
.step { display: flex; flex-direction: column; align-items: center; gap: 6px; }
.step .dot {
  width: 14px; height: 14px; border-radius: 50%;
  background: var(--surface-sunken);
  border: 2px solid var(--border-strong);
}
.step .lbl {
  font-size: 11.5px; color: var(--ink-500);
  white-space: nowrap;
}
.step.done .dot {
  background: var(--status-ok);
  border-color: var(--status-ok);
  box-shadow: 0 0 0 3px var(--status-ok-soft);
}
.step.done .lbl { color: var(--ink-700); }
.step.current .dot {
  background: var(--primary-grad);
  border-color: transparent;
  box-shadow: 0 0 0 3px var(--primary-soft);
}
.step.current .lbl {
  color: var(--primary);
  font-weight: 600;
}
.line {
  flex: 1;
  height: 2px;
  background: var(--border);
  margin: 0 -2px 16px;
}
.line.done { background: var(--status-ok); }

.plan {
  list-style: none;
  padding: 0;
  margin: 0 0 24px;
  display: flex;
  flex-direction: column;
  gap: 10px;
}
.plan li {
  display: flex;
  align-items: baseline;
  gap: 10px;
  font-size: 13.5px;
  color: var(--ink-700);
  line-height: 1.55;
}
.plan .bullet {
  color: var(--primary);
  font-family: var(--font-mono);
  font-size: 16px;
  font-weight: 700;
  line-height: 1;
}

.hint {
  font-size: 12.5px;
  color: var(--ink-500);
  padding-top: 16px;
  border-top: 1px solid var(--border);
}
.link {
  color: var(--primary);
  text-decoration: none;
  border-bottom: 1px dashed var(--primary);
}
.link:hover { color: var(--primary-deep); }
</style>
