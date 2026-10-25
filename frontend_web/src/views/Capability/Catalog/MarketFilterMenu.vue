/**
 * 市场页的「项目 + 排序」合并筛选菜单 (2026-10-25).
 *
 * 为什么合并 (用户反馈: "现在和非类在一排显示方式有点拥挤"):
 *   原来筛选行是三段 —— 分类 chip (9 个) + 项目 chip (6 个) + 排序下拉 ——
 *   分类 chip 撑满第一行, 项目 chip 被挤到第二行, 排序下拉孤零零挂最右.
 *   现在合成**一个**下拉: 按钮上显示当前选择 (如「6100 · 最新」),
 *   面板里分「项目」「排序」两组, 点一下就生效.
 *
 * ⚠️ 点击外部关闭必须注册在**捕获阶段**:
 *    element-plus 的抽屉内容层带 `@click.stop` —— 冒泡阶段的事件到不了
 *    document, 用默认的冒泡监听的话, 抽屉里点外面**永远收不到**
 *    (AssetUploadDialog 的图标面板已经踩过这个坑, 见 commit 7716e85).
 */
<template>
  <div ref="wrap" class="filter-menu">
    <button type="button" class="filter-trigger" :title="triggerTitle"
            :aria-expanded="open" @click="open = !open">
      <span class="ft-text">{{ triggerText }}</span>
      <span class="ft-caret">▾</span>
    </button>

    <div v-if="open" class="filter-panel" role="menu">
      <!-- ===== 项目 ===== -->
      <div class="fp-group">
        <div class="fp-title">项目</div>
        <button v-for="p in projectItems" :key="p.value" type="button"
                class="fp-item" :class="{ on: project === p.value }"
                :title="p.hint" @click="pickProject(p.value)">
          <span class="fpi-radio" />
          <span class="fpi-label">{{ p.label }}</span>
          <span v-if="p.count" class="fpi-count">{{ p.count }}</span>
        </button>
      </div>

      <!-- ===== 排序 ===== -->
      <div class="fp-group">
        <div class="fp-title">排序</div>
        <button v-for="s in MARKET_SORT_OPTIONS" :key="s.value" type="button"
                class="fp-item" :class="{ on: sort === s.value }"
                @click="pickSort(s.value)">
          <span class="fpi-radio" />
          <span class="fpi-label">{{ s.label }}</span>
        </button>
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
import { computed, onMounted, onUnmounted, ref } from 'vue';
import { MARKET_SORT_OPTIONS, type MarketProjectItem, type MarketSort } from './marketCatalog';

const props = defineProps<{
  /** 当前项目筛选: '' = 全部, 'general' = 只看通用, 其他 = 该项目特有 + 通用 */
  project: string;
  /** 当前排序 */
  sort: MarketSort;
  /** 项目列表 (含「通用」) */
  projects: MarketProjectItem[];
}>();
const emit = defineEmits<{
  (e: 'update:project', v: string): void;
  (e: 'update:sort', v: MarketSort): void;
}>();

const open = ref(false);
const wrap = ref<HTMLElement | null>(null);

/** 下拉里的项目选项 —— 「全部」放在最前, 其余按后端给的顺序 */
const projectItems = computed(() => [
  {
    value: '',
    label: '全部项目',
    count: 0,
    hint: '不按项目过滤 —— 所有项目的资产都列出来',
  },
  ...props.projects.map((p) => ({
    value: p.code,
    label: p.code === 'general' ? '通用' : p.name,
    count: p.total || 0,
    // ⚠️ 语义跟后端一致 (marketplace.py 的 project 参数):
    //    选某个项目 = 该项目特有 **+ 通用** (通用资产在该项目同样适用);
    //    选「通用」= 只看通用的.
    hint: p.code === 'general'
      ? '只看通用资产 (所有项目都能用的)'
      : `只看 ${p.name} 项目特有 + 通用资产`,
  })),
]);

/** 按钮上显示的当前选择 —— 例: 「6100 · 最新」 */
const triggerText = computed(() => {
  const proj = props.project === ''
    ? '全部项目'
    : (props.project === 'general'
      ? '通用'
      : props.project);
  const srt = MARKET_SORT_OPTIONS.find((x) => x.value === props.sort)?.label || props.sort;
  return `${proj} · ${srt}`;
});

/** 按钮的 title —— 说清当前筛选到底筛了什么 */
const triggerTitle = computed(() => {
  const p = projectItems.value.find((x) => x.value === props.project);
  const srt = MARKET_SORT_OPTIONS.find((x) => x.value === props.sort)?.label || props.sort;
  return `${p?.hint || '不按项目过滤'} · 排序: ${srt}`;
});

function pickProject(v: string) {
  emit('update:project', v);
  open.value = false;
}
function pickSort(v: MarketSort) {
  emit('update:sort', v);
  open.value = false;
}

/** 点外面 → 收起 */
function onDocClick(e: MouseEvent) {
  if (!open.value) return;
  if (wrap.value && wrap.value.contains(e.target as Node)) return;
  open.value = false;
}
/** Esc → 收起 */
function onKey(e: KeyboardEvent) {
  if (e.key === 'Escape') open.value = false;
}

onMounted(() => {
  // ⚠️ 捕获阶段 (第三个参数 true) —— 见文件头注释
  document.addEventListener('click', onDocClick, true);
  document.addEventListener('keydown', onKey);
});
onUnmounted(() => {
  document.removeEventListener('click', onDocClick, true);
  document.removeEventListener('keydown', onKey);
});
</script>

<style scoped>
.filter-menu { position: relative; flex-shrink: 0; }
.filter-trigger {
  display: inline-flex; align-items: center; gap: 6px;
  background: var(--surface); border: 1px solid var(--border);
  padding: 6px 11px; border-radius: 8px;
  font-size: 12.5px; color: var(--ink-700); cursor: pointer;
  font-family: inherit; transition: all 0.15s ease;
}
.filter-trigger:hover { border-color: var(--primary); color: var(--ink-900); }
.ft-caret { font-size: 10px; opacity: 0.75; }

.filter-panel {
  position: absolute; right: 0; top: calc(100% + 8px); z-index: 40;
  min-width: 220px; padding: 10px;
  /* ⚠️ 不透明 —— 半透明底会透出后面的卡片文字, 读不清 */
  background: linear-gradient(var(--surface), var(--surface)), var(--bg-base);
  border: 1px solid var(--border);
  border-radius: 12px; box-shadow: var(--shadow-lg);
}
.fp-group + .fp-group { margin-top: 8px; padding-top: 8px; border-top: 1px dashed var(--border); }
.fp-title { font-size: 11.5px; color: var(--ink-500); padding: 2px 6px 6px; }
.fp-item {
  display: flex; align-items: center; gap: 8px; width: 100%;
  padding: 6px 8px; margin-bottom: 2px; text-align: left;
  background: transparent; border: 1px solid transparent; border-radius: 8px;
  cursor: pointer; font-family: inherit; font-size: 12.5px; color: var(--ink-700);
}
.fp-item:hover { background: var(--surface-soft); color: var(--ink-900); }
.fp-item.on { background: rgba(59, 130, 246, 0.10); color: var(--ink-900); font-weight: 600; }
.fpi-radio {
  width: 12px; height: 12px; border-radius: 50%; flex-shrink: 0;
  border: 1.5px solid var(--border);
}
.fp-item.on .fpi-radio { border-color: var(--primary); background: var(--primary); box-shadow: inset 0 0 0 2px var(--surface); }
.fpi-label { flex: 1; }
.fpi-count {
  font-size: 10.5px; color: var(--ink-500);
  font-family: var(--font-mono); font-weight: 600;
}
.fp-item.on .fpi-count { color: var(--primary); }
</style>
