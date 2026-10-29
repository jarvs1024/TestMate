<template>
  <div
    class="card cap-card"
    :class="[`kind-${capability.kind}`, { 'is-planned': planned }]"
    :role="planned ? 'img' : 'button'"
    :tabindex="planned ? -1 : 0"
    :aria-label="planned ? `${capability.name} · 规划中` : `${capability.name} · ${kindLabel(capability.kind)}`"
    @click="onClick"
    @keydown.enter.prevent="onClick"
    @keydown.space.prevent="onClick"
  >
    <div class="cc-hd">
      <div class="cc-icon">{{ capability.icon }}</div>
      <div class="cc-title">
        <div class="cc-name">{{ capability.name }}</div>
        <div class="cc-sub">
          <span class="cc-kind">{{ kind.icon }} {{ kind.label }}</span>
          <span class="cc-dot">·</span>
          <span class="cc-cat">{{ domainLabel }}</span>
        </div>
      </div>
      <div class="cc-badge" :class="`st-${capability.status}`">
        <span class="dot"></span>{{ statusText }}
      </div>
    </div>

    <p class="cc-summary">{{ capability.summary }}</p>

    <div class="cc-tags">
      <span v-for="t in capability.tags.slice(0, 4)" :key="t" class="tag">#{{ t }}</span>
    </div>

    <!-- 规划中的能力: 整张卡淡掉 + "规划中"水印, 不可点 -->
    <div v-if="planned" class="cc-overlay" aria-hidden="true">
      <span class="ov-dot"></span>
      <span class="ov-txt">规划中</span>
    </div>

    <div class="cc-foot">
      <div class="cc-meta">
        <span v-for="(m, i) in metaItems" :key="i" class="meta-item">
          <span class="mi-ic">{{ m.icon }}</span>{{ m.text }}
        </span>
        <span v-if="metaItems.length === 0" class="meta-item meta-empty">—</span>
      </div>
      <div v-if="!planned" class="cc-cta">
        {{ cta }}<span class="cta-arrow">›</span>
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
/**
 * 能力卡片 —— 首页能力墙里的一张卡.
 *
 * 关键设计 (2026-10-25):
 *   ① **角色徽标**(📦 资产 / 🛠 工具 / 📊 看板) 跟状态徽标分开:
 *      角色说"这张卡扮演什么", 状态说"它现在能不能用".
 *   ② **meta 行由父级传入** (`meta` prop) —— 卡片自己不取数.
 *      引擎/调用次数对看板和资产是假信息, 真实数字(资产数/数据集数/MR 数)
 *      要各自调自己的接口, 所以取数放在 Home, 卡片只负责渲染.
 *   ③ **CTA 必写**: 卡片不是都是智能体之后, 用户必须一眼看出点下去会发生什么.
 *      CTA 由**卡片自带** (后端 cta 字段) —— 资产组里"浏览资产"和"检索语料"动法不同.
 */
import { computed } from 'vue';
import type { Capability } from '@/api/capabilities';
import { categoryLabel, isPlanned, kindLabel, kindMeta, statusLabel } from '@/constants/capabilityKinds';
import { capabilityCta } from '@/utils/capabilities';

const props = defineProps<{
  capability: Capability;
  /** 角色相关的真实指标 (父级取好数传进来) */
  meta?: { icon: string; text: string }[];
}>();

const emit = defineEmits<{ (e: 'open', c: Capability): void }>();

const kind = computed(() => kindMeta(props.capability.kind));
// CTA 由卡片自带 (后端 cta 字段), 空则回落角色默认词
const cta = computed(() => capabilityCta(props.capability));
const planned = computed(() => isPlanned(props.capability.status));
const statusText = computed(() => statusLabel(props.capability.kind, props.capability.status));
const domainLabel = computed(() => categoryLabel(props.capability.category));
const metaItems = computed(() => props.meta || []);

function onClick() {
  if (planned.value) return; // 规划中的能力不可点
  emit('open', props.capability);
}
</script>

<style scoped>
.cap-card {
  cursor: pointer;
  transition: transform 0.15s ease, box-shadow 0.15s ease, border-color 0.15s ease;
  display: flex;
  flex-direction: column;
  gap: 10px;
  min-height: 190px;
}
.cap-card:hover {
  transform: translateY(-2px);
  border-color: var(--primary);
  box-shadow: 0 8px 24px rgba(59, 130, 246, 0.12), 0 0 0 3px var(--primary-soft);
}
.cap-card:focus-visible {
  outline: none;
  border-color: var(--primary);
  box-shadow: 0 0 0 3px var(--primary-soft);
}

.cc-hd { display: flex; align-items: flex-start; gap: 12px; }

.cc-icon {
  width: 42px; height: 42px;
  border-radius: 12px;
  background: linear-gradient(135deg, var(--primary), var(--primary-2));
  display: flex; align-items: center; justify-content: center;
  font-size: 21px;
  flex-shrink: 0;
  box-shadow: var(--primary-shadow);
}

.cc-title { flex: 1; min-width: 0; }
.cc-name { font-size: 16px; font-weight: 700; color: var(--ink-900); line-height: 1.2; }
.cc-sub {
  font-size: 11.5px; color: var(--ink-500); margin-top: 3px;
  font-family: var(--font-mono);
  display: flex; align-items: center; gap: 5px;
}
/* 角色徽标: 比域标签更重要 —— 它决定这张卡扮演什么 */
.cc-kind { color: var(--primary-2); font-weight: 600; }
.cc-dot { opacity: 0.5; }

.cc-badge {
  display: inline-flex; align-items: center; gap: 5px;
  padding: 3px 8px; border-radius: var(--radius-pill);
  font-size: 10.5px; font-weight: 600;
  background: var(--surface-sunken); color: var(--ink-700);
  flex-shrink: 0;
}
.cc-badge .dot { width: 6px; height: 6px; border-radius: 50%; background: currentColor; }
.st-stable { background: rgba(16, 185, 129, 0.12); color: var(--ok); }
.st-beta { background: rgba(245, 158, 11, 0.12); color: var(--warn); }
.st-alpha { background: rgba(245, 158, 11, 0.14); color: var(--warn); }
.st-draft { background: var(--surface-sunken); color: var(--ink-500); }
.st-deprecated { background: rgba(239, 68, 68, 0.10); color: var(--err); }

.cc-summary {
  margin: 0;
  font-size: 13.5px;
  color: var(--ink-700);
  line-height: 1.55;
  flex: 1;
}

.cc-tags { display: flex; flex-wrap: wrap; gap: 5px; }
.tag {
  font-size: 10.5px;
  color: var(--ink-500);
  background: var(--surface-sunken);
  padding: 2px 7px;
  border-radius: var(--radius-sm);
  font-family: var(--font-mono);
}

/* 规划中: 整张卡淡掉 + 水印, 不能点 */
.cap-card.is-planned { cursor: not-allowed; position: relative; overflow: hidden; opacity: 0.78; }
.cap-card.is-planned:hover {
  transform: none;
  border-color: var(--border);
  box-shadow: none;
}
.cap-card.is-planned .cc-icon { filter: grayscale(0.6); box-shadow: none; }
.cap-card.is-planned .cc-cta { display: none; }
.cc-overlay {
  position: absolute;
  top: 12px; right: 12px;
  display: inline-flex; align-items: center; gap: 6px;
  padding: 5px 12px;
  border-radius: var(--radius-pill);
  background: rgba(255, 255, 255, 0.85);
  backdrop-filter: blur(8px);
  -webkit-backdrop-filter: blur(8px);
  border: 1px solid var(--border);
  box-shadow: 0 2px 6px rgba(15, 23, 42, 0.06);
  font-size: 11px; font-weight: 600; color: var(--ink-700);
  pointer-events: none;
}
/* ⚠️ 暗色覆盖用 `html.dark` (class), 不是 `html[data-theme="dark"]` (属性) ——
   主题 store 在 auto 模式下写的是 data-theme="auto", 而 auto **是默认模式**
   (DEFAULT = 'auto'), 系统一暗色首屏就是这个状态 → 老选择器永远不命中,
   "规划中"药丸就保持白底 + 浅灰字 (对比度约 1.4:1, 几乎读不出来).
   store 的 applyTheme() 在**任何**模式下都会按实际解析结果给 html 加 .dark class,
   这个 class 才可靠. */
html.dark .cc-overlay { background: rgba(15, 22, 40, 0.85); color: var(--ink-300); }
.cc-overlay .ov-dot {
  width: 6px; height: 6px; border-radius: 50%;
  background: var(--ink-500);
  animation: ov-pulse 1.6s ease-in-out infinite;
}
@keyframes ov-pulse {
  0%, 100% { opacity: 0.4; transform: scale(0.85); }
  50%      { opacity: 1;   transform: scale(1); }
}

.cc-foot {
  display: flex; align-items: center; justify-content: space-between; gap: 10px;
  padding-top: 10px;
  border-top: 1px dashed var(--border);
}
.cc-meta { display: flex; gap: 10px; flex-wrap: wrap; min-width: 0; }
.meta-item {
  display: inline-flex; align-items: center; gap: 4px;
  font-size: 11px; color: var(--ink-500);
  font-family: var(--font-mono);
}
.meta-item .mi-ic { font-size: 11px; }
.meta-empty { opacity: 0.6; }

.cc-cta {
  font-size: 12px; font-weight: 600; color: var(--primary);
  white-space: nowrap; flex-shrink: 0;
  display: inline-flex; align-items: center; gap: 2px;
}
.cta-arrow { font-size: 14px; line-height: 1; }
.cap-card:hover .cc-cta { color: var(--primary-2); }
</style>
