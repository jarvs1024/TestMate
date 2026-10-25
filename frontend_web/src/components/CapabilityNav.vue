<template>
  <div class="cap-nav">
    <!-- 全部能力 (= 首页) -->
    <router-link to="/" class="all-link" :class="{ active: isHome }">
      <span class="ic">
        <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><rect x="3" y="3" width="7" height="7" rx="1"/><rect x="14" y="3" width="7" height="7" rx="1"/><rect x="3" y="14" width="7" height="7" rx="1"/><rect x="14" y="14" width="7" height="7" rx="1"/></svg>
      </span>
      <span class="lb">全部能力</span>
    </router-link>

    <div class="sep"></div>

    <!-- 按角色分组 —— 侧栏 = 能力导航器, 首页 = 能力总览, 同一份数据 -->
    <div v-for="g in store.grouped" :key="g.meta.value" class="group">
      <div class="g-hd">
        <span class="g-ic">{{ g.meta.icon }}</span>
        <span class="g-lb">{{ g.meta.label }}</span>
        <span class="g-count">{{ g.items.length }}</span>
      </div>
      <router-link
        v-for="c in g.items"
        :key="c.code"
        :to="targetOf(c)"
        class="item"
        :class="{ active: isActive(c), planned: isPlanned(c.status) }"
        :title="c.summary"
      >
        <span class="i-ic">{{ c.icon }}</span>
        <span class="i-lb">{{ c.name }}</span>
        <span v-if="isPlanned(c.status)" class="i-tag">规划中</span>
      </router-link>
    </div>

    <div v-if="!store.loaded && store.loading" class="nav-loading">加载中…</div>
    <div v-else-if="store.error" class="nav-error">能力列表加载失败</div>
  </div>
</template>

<script setup lang="ts">
/**
 * 能力导航器 —— 侧栏上半部分.
 *
 * 为什么侧栏不再列"页面"而是列"能力" (2026-10-25):
 *   以前侧栏是「广场 / 知识库」两个**平级分区**, 用户得先判断
 *   "我要去广场还是去知识库"; 知识库跟广场其实是两类不同性质的东西,
 *   平级摆在一起会让它显得像另一个功能区.
 *   现在侧栏跟首页共用同一份能力数据: 首页是能力总览, 侧栏是能力目录,
 *   不会出现"侧栏有、首页没有"的情况.
 *
 * 分组按**角色** (工具 / 看板 / 底座), 不是按实现形态 —— 角色才回答"这卡干嘛"。
 */
import { computed } from 'vue';
import { useRoute, useRouter } from 'vue-router';
import { useCapabilityStore } from '@/stores/capabilities';
import { isPlanned } from '@/constants/capabilityKinds';
import { capabilityRouteName } from '@/utils/capabilities';
import type { Capability } from '@/api/capabilities';

const store = useCapabilityStore();
const route = useRoute();
const router = useRouter();

const isHome = computed(() => route.path === '/' || route.path === '/plaza');

/** 能力 → 路由 (工具型要带 code 参数) */
function targetOf(c: Capability) {
  const name = capabilityRouteName(c);
  if (name === 'tool-runner') return { name, params: { code: c.code } };
  return { name };
}

/** 当前所在的能力 —— 跟路径比对 */
function isActive(c: Capability): boolean {
  const name = capabilityRouteName(c);
  if (name === 'tool-runner') return route.path === `/c/${c.code}` || route.path === `/agents/${c.code}`;
  try {
    const resolved = router.resolve({ name }).path;
    return resolved === route.path;
  } catch {
    return false;
  }
}
</script>

<style scoped>
.cap-nav { display: flex; flex-direction: column; gap: 2px; }

.all-link {
  display: flex; align-items: center; gap: 10px;
  padding: 9px 12px; border-radius: 9px;
  color: var(--ink-700); text-decoration: none;
  font-size: 13px; font-weight: 500;
  transition: background .15s ease, color .15s ease;
}
.all-link:hover { background: var(--surface-sunken); color: var(--ink-900); }
.all-link.active {
  background: var(--primary-grad-soft);
  font-weight: 600;
  box-shadow: inset 0 0 0 1px var(--border);
}
.all-link.active .lb {
  background: var(--primary-grad-text);
  -webkit-background-clip: text;
  background-clip: text;
  -webkit-text-fill-color: transparent;
  color: transparent;
}
.all-link .ic { display: inline-flex; align-items: center; color: var(--primary); }

.sep { height: 1px; background: var(--border); margin: 8px 4px 6px; }

.group { display: flex; flex-direction: column; gap: 1px; margin-bottom: 6px; }
.g-hd {
  display: flex; align-items: center; gap: 6px;
  padding: 6px 12px 4px;
  font-size: 10.5px; font-weight: 700; letter-spacing: .04em;
  color: var(--ink-500); text-transform: uppercase;
}
.g-ic { font-size: 11px; }
.g-lb { flex: 1; }
.g-count {
  font-family: var(--font-mono); font-size: 10px;
  background: var(--surface-sunken); padding: 0 6px; border-radius: var(--radius-pill);
}

.item {
  display: flex; align-items: center; gap: 9px;
  padding: 7px 12px; border-radius: 8px;
  color: var(--ink-700); text-decoration: none;
  font-size: 12.5px;
  transition: background .15s ease, color .15s ease;
}
.item:hover { background: var(--surface-sunken); color: var(--ink-900); }
.item.active {
  background: var(--surface-sunken);
  color: var(--ink-900);
  font-weight: 600;
  box-shadow: inset 0 0 0 1px var(--border);
}
.item.planned { opacity: .6; }
.i-ic { font-size: 13px; flex-shrink: 0; }
.i-lb { flex: 1; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.i-tag {
  font-size: 9.5px; color: var(--ink-500);
  background: var(--surface-sunken); padding: 1px 5px; border-radius: var(--radius-sm);
}

.nav-loading, .nav-error {
  padding: 8px 12px; font-size: 11.5px; color: var(--ink-500);
}
.nav-error { color: var(--err); }
</style>
