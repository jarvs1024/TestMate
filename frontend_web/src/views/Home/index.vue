<template>
  <div class="home">
    <!-- ===== 待办带: 首页真正的职责是"告诉我今天该看什么" ===== -->
    <div v-if="todos.length" class="todo-strip">
      <span class="ts-label">待办</span>
      <button v-for="t in todos" :key="t.key" type="button" class="ts-item" :class="`tone-${t.tone}`" @click="go(t.to)">
        <span class="ts-ic">{{ t.icon }}</span>
        <span class="ts-text">{{ t.text }}</span>
        <span class="ts-go">→</span>
      </button>
    </div>
    <div v-else-if="!loggedIn" class="todo-strip anon">
      <span class="ts-ic">🔒</span>
      <span class="ts-text">登录后可见你的待办 (资产审核 / 同步失败 / 知识库状态)</span>
    </div>

    <!-- ===== 工具条: 角色筛选 + 状态 + 搜索 ===== -->
    <div class="home-toolbar">
      <div class="filters">
        <button v-for="f in kindFilters" :key="f.value"
          class="filter" :class="{ active: kindFilter === f.value }"
          @click="kindFilter = f.value">
          <span class="lbl">{{ f.label }}</span><span class="count">{{ countBy(f.value) }}</span>
        </button>
      </div>
      <div class="right">
        <select v-model="statusFilter" class="status-sel" title="按可用状态筛选">
          <option value="">全部状态</option>
          <option value="ready">可用</option>
          <option value="planned">规划中</option>
        </select>
        <div class="search">
          <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><circle cx="11" cy="11" r="8"/><path d="m21 21-4.3-4.3"/></svg>
          <input v-model="keyword" placeholder="搜能力 / 标签 / 说明..." />
        </div>
      </div>
    </div>

    <!-- ===== 能力网格 ===== -->
    <div v-if="loading" class="state">加载中…</div>
    <!-- ⚠️ 加载失败 ≠ 没有能力 —— 以前这里只看 filtered.length, /agents 挂了就渲染成
         「没有匹配的能力」(假空态), 而侧栏 CapabilityNav 同时显示「能力列表加载失败」,
         两边自相矛盾. 现在把 store 的 error 摆出来, 并给个重试入口. -->
    <div v-else-if="store.error" class="state err">
      <div class="st-ic">⚠️</div>
      <div>能力列表加载失败</div>
      <div class="st-sub">{{ store.error }}</div>
      <button class="retry-btn" @click="retryLoad">重试</button>
    </div>
    <div v-else-if="filtered.length === 0" class="state">
      <div class="st-ic">🧭</div>
      <div>没有匹配的能力</div>
      <div class="st-sub">换个关键词, 或者把筛选切回「全部」</div>
    </div>
    <div v-else class="grid">
      <CapabilityCard v-for="c in filtered" :key="c.code" :capability="c" :meta="metaOf(c)" @open="onOpen" />
    </div>
  </div>
</template>

<script setup lang="ts">
/**
 * 首页 —— 能力墙.
 *
 * 2026-10-25 重构: 原来的「智能体广场」假设每张卡都是智能体 (统一显示引擎 /
 * 调用次数 / 最近调用). 实际上卡片有三种**角色** (工具干活 / 看板看数 / 底座供料),
 * 那些字段对非工具卡是假信息. 现在:
 *   ① 卡片按角色渲染徽标 + 对应的 meta (真实数字);
 *   ② 顶部多一条**待办带** —— 首页先回答"今天该看什么", 再回答"有什么";
 *   ③ 规划中的能力沉底, 不占首屏黄金位.
 */
import { computed, onMounted, ref } from 'vue';
import { useRouter } from 'vue-router';
import CapabilityCard from './CapabilityCard.vue';
import { useCapabilityStore } from '@/stores/capabilities';
import { useUserStore } from '@/stores/user';
import { CAPABILITY_KINDS, isPlanned, type CapabilityKind } from '@/constants/capabilityKinds';
import {
  PLATFORM_META_SOURCE,
  capabilityRouteName,
  engineLabel,
  matchesKeyword,
  relativeTime,
  sortCapabilities,
} from '@/utils/capabilities';
import type { Capability } from '@/api/capabilities';
import { getOverview } from '@/api/reviewagent';
import { getSyncStatus, listAssets } from '@/api/assets';
import { kbHealth, listDatasets } from '@/api/kb';

interface Todo {
  key: string;
  icon: string;
  text: string;
  tone: 'warn' | 'err' | 'info';
  to: { name: string };
}

interface MetaItem { icon: string; text: string }

const router = useRouter();
const store = useCapabilityStore();
const userStore = useUserStore();

const kindFilter = ref<'all' | CapabilityKind>('all');
const statusFilter = ref<'' | 'ready' | 'planned'>('');
const keyword = ref('');

const loading = computed(() => store.loading && !store.loaded);
const loggedIn = computed(() => userStore.isLoggedIn);

/** 角色筛选条 —— 顺序跟 CAPABILITY_KINDS 一致 */
const kindFilters = computed(() => [
  { value: 'all' as const, label: '全部' },
  ...CAPABILITY_KINDS.map((k) => ({ value: k.value, label: `${k.icon} ${k.label}` })),
]);


/** 能力列表 (过滤 + 排序) */
const filtered = computed(() => {
  let list = store.all;
  if (kindFilter.value !== 'all') list = list.filter((c) => c.kind === kindFilter.value);
  if (statusFilter.value === 'ready') list = list.filter((c) => !isPlanned(c.status));
  else if (statusFilter.value === 'planned') list = list.filter((c) => isPlanned(c.status));
  const kw = keyword.value.trim();
  if (kw) list = list.filter((c) => matchesKeyword(c, kw));
  return sortCapabilities(list);
});

function countBy(kind: string): number {
  return store.countByKind[kind] ?? 0;
}

/**
 * 能力列表加载失败 → 重试.
 *
 * ⚠️ force=true: store 拉失败时 loaded 还是 false, 但显式 force 更保险
 *    (万一上次是"拉到了但被清空", 也能真的重新拉一次).
 */
async function retryLoad() {
  await store.load(true);
}

// ===== 卡片 meta: 按角色取真实数据 =====
// 取数失败一律降级 (不阻塞卡片渲染), 免得一个接口挂了就白屏.
const boardMeta = ref<MetaItem[]>([]);
const catalogMeta = ref<MetaItem[]>([]);
const libraryMeta = ref<MetaItem[]>([]);

function metaOf(c: Capability): MetaItem[] {
  if (c.kind === 'board') {
    return boardMeta.value.length ? boardMeta.value : [{ icon: '📡', text: '评审数据' }];
  }
  if (c.kind === 'platform') {
    // 底座: 同属一类, 但取数来源不同 (数资产 / 数语料) —— 按卡片自己的来源分派
    switch (PLATFORM_META_SOURCE[c.code]) {
      case 'assets':
        return catalogMeta.value.length ? catalogMeta.value : [{ icon: '🧩', text: '技能沉淀' }];
      case 'kb':
        return libraryMeta.value.length ? libraryMeta.value : [{ icon: '📚', text: 'RAG 语料' }];
      default:
        return [{ icon: '🧱', text: '平台底座' }];
    }
  }
  // 工具: 引擎 + 最近使用 —— 这两个字段只有能跑的卡才有意义
  const items: MetaItem[] = [{ icon: '🔧', text: engineLabel(c.engine) }];
  items.push({ icon: '🕐', text: relativeTime(c.last_called_at) });
  return items;
}

// ===== 待办带 =====
const todos = ref<Todo[]>([]);

/**
 * 知识库通不通 —— **探一次**, 后面两处共用.
 *
 * ⚠️ 为什么要探 (2026-10-25):
 *    RAGFlow 没配时 `/kb/datasets` 会返 502. 首页把它当"降级"处理 (卡片显示兜底文案),
 *    但**请求照样发出去了** —— 浏览器控制台每次都留一条 502, e2e 的"全程无失败请求"
 *    也会被它顶掉. 探明没配就别去拉数据 —— 省一次请求, 也少一条噪音.
 */
const kbState = ref<{ status?: string; message?: string } | null>(null);
let kbProbe: Promise<boolean> | null = null;
async function probeKb(): Promise<boolean> {
  if (kbProbe) return kbProbe;
  kbProbe = (async () => {
    try {
      // ⚠️ silent: 首页把这些接口的失败都当"降级"处理, 不该弹全局错误
      const kb = await kbHealth({ silent: true });
      kbState.value = kb || {};
      return !!(kb?.status && kb.status === 'ok');
    } catch {
      kbState.value = {};
      return false;   // 探不到 → 当作没通, 别再去拉数据
    }
  })();
  return kbProbe;
}

async function loadTodos() {
  const list: Todo[] = [];
  // 知识库状态: 这个接口不要求登录, 匿名也能探到 RAGFlow 通不通
  // ⚠️ silent: 首页把这几个接口的失败都当"降级"处理 (卡片显示兜底文案),
  //    不该弹全局错误 —— 否则 RAGFlow 没配时首页一进来就弹红条.
  await probeKb();
  const kb = kbState.value;
  if (kb?.status && kb.status !== 'ok') {
    list.push({
      key: 'kb-off',
      icon: '📚',
      text: kb.status === 'off' ? '知识库未接入 (RAGFlow 未配置)' : `知识库状态异常: ${kb.message || kb.status}`,
      tone: 'warn',
      to: { name: 'kb-manage' },
    });
  }
  // 资产市场的待办需要登录态 (接口要鉴权)
  if (loggedIn.value) {
    try {
      // ⚠️ silent: 首页把这几个接口的失败都当"降级"处理 (卡片显示兜底文案),
      //    不该弹全局错误 —— 否则 RAGFlow 没配时首页一进来就弹红条.
      const s = await getSyncStatus({ silent: true });
      if (s.my_review_count > 0) {
        list.push({
          key: 'asset-review',
          icon: '📋',
          text: `${s.my_review_count} 个资产等你处理 (待审核 / 被驳回)`,
          tone: 'warn',
          to: { name: 'market' },
        });
      }
      if (s.failed_count > 0) {
        list.push({
          key: 'asset-failed',
          icon: '❌',
          text: `${s.failed_count} 个资产同步失败`,
          tone: 'err',
          to: { name: 'market' },
        });
      }
      if (s.unpublish_pending_count > 0) {
        list.push({
          key: 'asset-unpublish',
          icon: '🗑',
          text: `${s.unpublish_pending_count} 个下架申请等确认`,
          tone: 'info',
          to: { name: 'market' },
        });
      }
    } catch (e: any) {
      // ⚠️ 取不到资产状态 ≠ 没有待办 —— 以前这里 catch 是空的, 整段待办静默消失,
      //    用户以为"今天没待办". 现在留一条可见的错误提示, 这一段不消失.
      list.push({
        key: 'asset-status-failed',
        icon: '⚠️',
        text: `资产状态读取失败: ${errText(e, '未知错误')}`,
        tone: 'err',
        to: { name: 'market' },
      });
    }
  }
  todos.value = list;
}

/** 后端的 detail 可能是字符串也可能是对象 —— 取不到就退化到 message */
function errText(e: any, fallback: string): string {
  const d = e?.response?.data?.detail;
  if (typeof d === 'string' && d) return d;
  if (d && typeof d === 'object' && d.message) return String(d.message);
  return e?.message || fallback;
}

// ===== 角色 meta 取数 =====
async function loadMetas() {
  // 看板: 评审概览 (匿名可读, 后端走 get_optional_user)
  try {
    // ⚠️ silent: ReviewAgent 没配 / 宕机时这个接口**本来就会失败**,
    //    卡片已经按降级文案渲染好了 —— 按 request.ts 顶部的约定,
    //    "调用方自己会兜底降级的请求不该弹全局错误", 否则首页一进来就飘红条.
    const ov = await getOverview(undefined, { silent: true });
    if (ov?.mrs) {
      boardMeta.value = [
        { icon: '📈', text: `${ov.mrs.total} 个 MR` },
        { icon: '💡', text: `${ov.suggestions?.total ?? 0} 条建议` },
      ];
    }
  } catch {
    /* ReviewAgent 没配 / 挂了 → 保持降级文案 */
  }
  if (!loggedIn.value) return;
  // 底座 · 资产市场: 资产数 (接口要鉴权)
  try {
    const assets = await listAssets({ limit: 200 }, { silent: true });
    catalogMeta.value = [{ icon: '🗂', text: `${assets.total ?? assets.items?.length ?? 0} 个资产` }];
  } catch {
    /* 同上 */
  }
  // 知识: 数据集 / 文档 / 分段
  // ⚠️ 知识库没配 (RAGFlow 未配置) 时**别去拉** —— 那个接口必然 502,
  //    白白留一条失败请求 (页面卡片本来就有兜底文案).
  if (!(await probeKb())) return;
  try {
    const ds = await listDatasets({ silent: true });
    const items = ds.items || [];
    const docs = items.reduce((s, d) => s + (d.document_count || 0), 0);
    const chunks = items.reduce((s, d) => s + (d.chunk_count || 0), 0);
    libraryMeta.value = [
      { icon: '📚', text: `${items.length} 数据集` },
      { icon: '📄', text: `${docs} 文档` },
      { icon: '🧩', text: `${chunks} 分段` },
    ];
  } catch {
    /* 同上 */
  }
}

// ===== 交互 =====
function go(target: { name: string }) {
  router.push(target);
}

/**
 * 点卡片.
 *
 * 匿名用户: 只有**公开只读**的能力能直接进 (目前是代码检视看板),
 * 其余一律引导去登录 —— 首页能看, 进详情要登录.
 */
function onOpen(c: Capability) {
  const name = capabilityRouteName(c);
  const target = router.getRoutes().find((r) => r.name === name);
  const isPublic = !!(target?.meta?.publicRead);
  if (!loggedIn.value && !isPublic) {
    router.push({ name: 'login', query: { redirect: router.currentRoute.value.fullPath } });
    return;
  }
  if (name === 'tool-runner') {
    router.push({ name, params: { code: c.code } });
    return;
  }
  router.push({ name });
}

onMounted(async () => {
  await store.load();
  // 待办 / meta 都不阻塞卡片渲染 —— 卡片先出来, 数字后到
  await Promise.allSettled([loadTodos(), loadMetas()]);
});
</script>

<style scoped>
.home { display: flex; flex-direction: column; gap: 16px; }

/* ===== 待办带 ===== */
.todo-strip {
  display: flex; align-items: center; gap: 10px; flex-wrap: wrap;
  background: var(--surface-soft); backdrop-filter: blur(8px);
  border: 1px solid var(--border); border-radius: var(--radius-card);
  padding: 10px 14px; box-shadow: var(--shadow-sm);
  position: sticky; top: 0; z-index: 4;
}
.todo-strip.anon { color: var(--ink-500); font-size: 12.5px; }
.ts-label {
  font-size: 10.5px; font-weight: 700; letter-spacing: 0.06em;
  color: var(--ink-500); text-transform: uppercase;
}
.ts-item {
  display: inline-flex; align-items: center; gap: 6px;
  padding: 5px 11px; border-radius: var(--radius-pill);
  border: 1px solid var(--border);
  background: var(--surface);
  font-size: 12.5px; font-family: inherit; cursor: pointer;
  color: var(--ink-700);
  transition: all .15s ease;
}
.ts-item:hover { border-color: var(--primary); color: var(--ink-900); }
.ts-item .ts-ic { font-size: 12px; }
.ts-item .ts-go { opacity: 0.6; font-size: 13px; }
.tone-warn { color: var(--warn); }
.tone-err { color: var(--err); }
.tone-info { color: var(--ink-700); }

/* ===== 工具条 ===== */
.home-toolbar {
  display: flex; justify-content: space-between; align-items: center; gap: 16px;
  background: var(--surface-soft); backdrop-filter: blur(8px);
  border: 1px solid var(--border); border-radius: var(--radius-card);
  padding: 12px 16px; box-shadow: var(--shadow-sm);
  position: sticky; top: 52px; z-index: 3;
}
.filters { display: flex; gap: 6px; flex-wrap: wrap; }
.filter {
  background: transparent; border: 1px solid transparent;
  padding: 7px 14px; border-radius: var(--radius-pill);
  font-size: 13px; color: var(--ink-700); cursor: pointer;
  font-family: inherit; transition: all 0.15s ease;
  display: inline-flex; align-items: center; gap: 5px;
}
.filter:hover { background: var(--surface-sunken); color: var(--ink-900); }
.filter.active {
  background: var(--primary-grad-soft);
  border-color: transparent;
  font-weight: 600;
  box-shadow: inset 0 0 0 1px var(--border);
}
.filter.active .lbl {
  display: inline-block;
  background: var(--primary-grad-text);
  -webkit-background-clip: text;
  background-clip: text;
  -webkit-text-fill-color: transparent;
  color: transparent;
}
.filter .count {
  font-size: 11.5px; background: var(--surface); padding: 1px 7px; border-radius: var(--radius-pill);
  font-family: var(--font-mono); font-weight: 600;
}
.filter.active .count { background: var(--primary-grad); color: #fff; }

.right { display: flex; align-items: center; gap: 10px; }
.status-sel {
  font-size: 12.5px; font-family: inherit;
  padding: 6px 9px; border-radius: 8px;
  border: 1px solid var(--border); background: var(--surface);
  color: var(--ink-700); cursor: pointer;
}
.search {
  display: flex; align-items: center; gap: 6px;
  background: var(--surface); border: 1px solid var(--border);
  padding: 6px 10px; border-radius: 8px;
  color: var(--ink-500);
}
.search input {
  border: 0; outline: none; background: transparent;
  font-size: 13px; color: var(--ink-900); font-family: inherit; width: 190px;
}

/* ===== 网格 ===== */
.grid {
  display: grid;
  grid-template-columns: repeat(3, minmax(0, 1fr));
  gap: 16px;
}
@media (max-width: 1100px) { .grid { grid-template-columns: repeat(2, minmax(0, 1fr)); } }
@media (max-width: 760px)  { .grid { grid-template-columns: 1fr; } }

.state {
  background: var(--surface-soft); backdrop-filter: blur(8px);
  border: 1px solid var(--border); border-radius: var(--radius-card);
  padding: 60px 20px; text-align: center; color: var(--ink-500);
  font-size: 13.5px; display: flex; flex-direction: column; gap: 8px; align-items: center;
}
.st-ic { font-size: 32px; opacity: 0.4; }
.st-sub { font-size: 12px; opacity: 0.8; }
/* 加载失败 —— 跟"真的没有能力"必须区分开 */
.state.err { color: var(--err); border-color: rgba(239, 68, 68, 0.3); }
.retry-btn {
  background: transparent; border: 1px solid var(--err); color: var(--err);
  padding: 5px 16px; border-radius: var(--radius-pill);
  font-size: 12.5px; cursor: pointer; font-family: inherit;
}
.retry-btn:hover { background: var(--err); color: #fff; }
</style>
