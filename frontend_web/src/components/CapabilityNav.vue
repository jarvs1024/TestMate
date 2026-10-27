<template>
  <div class="cap-nav">
    <!-- ===== ① 区块标题: 先说清楚"这一块是什么" ===== -->
    <div class="nav-cap">
      <span class="nc-lb">能力</span>
      <span class="nc-rule"></span>
    </div>

    <!-- ===== ② 总览入口: 卡片化, 权重高于下面的分组 ===== -->
    <router-link to="/" class="all-link" :class="{ active: isHome }">
      <span class="ic">
        <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><rect x="3" y="3" width="7" height="7" rx="1"/><rect x="14" y="3" width="7" height="7" rx="1"/><rect x="3" y="14" width="7" height="7" rx="1"/><rect x="14" y="14" width="7" height="7" rx="1"/></svg>
      </span>
      <span class="lb">全部能力</span>
      <span class="count">{{ store.items.length }}</span>
    </router-link>

    <!-- ===== ③ 角色分组: 组标题 + 细分隔线 + 条目 ===== -->
    <div v-for="g in store.grouped" :key="g.meta.value" class="group">
      <div class="g-hd">
        <span class="g-ic">{{ g.meta.icon }}</span>
        <span class="g-lb">{{ g.meta.label }}</span>
        <span class="g-count">{{ g.items.length }}</span>
      </div>
      <div class="g-rule"></div>
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
 * 分组按**角色** (资产 / 工具 / 看板), 不是按实现形态 —— 角色才回答"这卡干嘛"。
 *
 * ⚠️ 排版为什么要四层 (2026-10-25 第三轮, 用户反馈"无层次感"):
 *   改之前的侧栏是**平铺**的: 「全部能力」/ 组标题 / 条目三者视觉权重一样,
 *   组标题还是 10.5px 灰色 uppercase (中文 uppercase 没意义, 几乎看不见),
 *   条目跟组标题左边界相同 (看不出父子关系), 三组之间只有 6px 间距 (糊成一坨).
 *   用户看不出"全部能力"是**总览入口**而不是又一个分类.
 *
 *   现在的四层:
 *     ① 区块标题「能力」+ 右侧细线 —— 界定这是哪一块
 *     ② 「全部能力」卡片 —— 总览, 权重高于单个分组 (带边框/底色/总数)
 *     ③ 角色组标题 (13px 加粗深色) + 组下细分隔线 —— 组标题与它的条目成一个单元
 *     ④ 条目缩进到组标题之下 —— 明确的父子关系; 当前项用左侧竖条指示
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

// ⚠️ '/plaza' 现在只是路由表里的 redirect (旧「智能体广场」地址), URL 不会停留在那儿 ——
//    留着它等于一个永远命中不了的判断.
const isHome = computed(() => route.path === '/');

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
.cap-nav { display: flex; flex-direction: column; }

/* ===== ① 区块标题 ===== */
.nav-cap { display: flex; align-items: center; gap: 8px; padding: 2px 3px 8px; }
.nc-lb {
  font-size: 10.5px; font-weight: 700; letter-spacing: .08em;
  color: var(--ink-500);
}
.nc-rule { flex: 1; height: 1px; background: var(--border); }

/* ===== ② 总览入口 (卡片) ===== */
.all-link {
  display: flex; align-items: center; gap: 10px;
  padding: 9px 11px; border-radius: 10px;
  background: var(--surface-soft);
  border: 1px solid var(--border);
  color: var(--ink-700); text-decoration: none;
  font-size: 13px; font-weight: 600;
  transition: background .15s ease, color .15s ease, border-color .15s ease;
}
.all-link:hover { background: var(--surface-sunken); color: var(--ink-900); }
.all-link.active {
  background: var(--primary-grad-soft);
  border-color: var(--primary);
  color: var(--ink-900);
  box-shadow: var(--shadow-sm);
}
.all-link.active .lb {
  background: var(--primary-grad-text);
  -webkit-background-clip: text;
  background-clip: text;
  -webkit-text-fill-color: transparent;
  color: transparent;
}
.all-link .ic { display: inline-flex; align-items: center; color: var(--primary); }
.all-link .lb { flex: 1; }
.all-link .count {
  font-family: var(--font-mono); font-size: 11px;
  color: var(--ink-500); font-weight: 500;
}
.all-link.active .count { color: var(--ink-700); }

/* ===== ③ 角色分组 ===== */
.group { display: flex; flex-direction: column; margin-top: 15px; }
.g-hd {
  display: flex; align-items: center; gap: 6px;
  padding: 0 2px;
  font-size: 12.5px; font-weight: 700; letter-spacing: .01em;
  color: var(--ink-900);
}
.g-ic { font-size: 12px; }
.g-lb { flex: 1; }
.g-count {
  font-family: var(--font-mono); font-size: 10.5px; font-weight: 500;
  color: var(--ink-500);
}
/* 组标题下的细线 —— 把"标题 + 它的条目"圈成一个单元, 三组之间自然分开 */
.g-rule { height: 1px; background: var(--border); margin: 6px 0 4px; }

/* ===== ④ 能力条目 (缩进在组标题之下) ===== */
.item {
  display: flex; align-items: center; gap: 9px;
  padding: 6px 10px 6px 24px; border-radius: 8px;
  color: var(--ink-700); text-decoration: none;
  font-size: 12.5px;
  transition: background .15s ease, color .15s ease;
}
.item:hover { background: var(--surface-sunken); color: var(--ink-900); }
.item.active {
  background: var(--primary-soft);
  color: var(--ink-900);
  font-weight: 600;
  box-shadow: inset 2px 0 0 var(--primary);   /* 左侧竖条 = 当前位置 */
}
.item.planned { opacity: .55; }
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
