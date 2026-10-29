<template>
  <aside class="tm-side">
    <div class="side-inner">
      <CapabilityNav />
      <ServiceStatus />
    </div>
  </aside>
</template>

<script setup lang="ts">
/**
 * 侧栏容器 —— 上半是能力导航器, 下半是服务状态.
 *
 * 2026-10-25: 原来这里是两个**页面级**导航项 (广场 / 知识库).
 * 知识库降级成能力墙上的一张卡之后, 侧栏不再是"功能分区", 而是"能力目录".
 */
import { onMounted } from 'vue';
import CapabilityNav from './CapabilityNav.vue';
import ServiceStatus from './ServiceStatus.vue';
import { useCapabilityStore } from '@/stores/capabilities';

const store = useCapabilityStore();

// 侧栏跟首页共用同一份能力数据 (store 里只拉一次)
onMounted(() => {
  store.load();
});
</script>

<style scoped>
/* 侧栏: 固定不动, 自己内部滚 (MainLayout 给了 100% 高) */
.tm-side {
  width: 220px;
  flex-shrink: 0;
  height: 100%;
  overflow: hidden;     /* 外层不滚, 内部 .side-inner 滚 */
  border-right: 1px solid var(--border);
}
.side-inner {
  height: 100%;
  overflow-y: auto;     /* 内容多时自己滚 */
  /* 顶部 12: 让导航贴在 AppHeader 下方, 不跟主区 toolbar 对齐 */
  padding: 12px 12px 16px;
  display: flex;
  flex-direction: column;
  gap: 12px;
}
/* ⚠️ **窄屏收窄侧栏** (2026-10-29 整改) ——
   侧栏原来 220px 是写死的, 窄屏下它一个人就吃掉大部分宽度:
   实测 375px 视口里侧栏占 220px, 主内容只剩 155px —— 基本没法用.

   ⚠️ 这里**只收窄**, 不做"图标条 / 抽屉态"那种大改 ——
      侧栏里的内容是文字导航 (能力名), 收成图标条要另做一套图标映射,
      反而更容易认错. 收窄后:
        1100px 以下 → 190px
        860px  以下 → 160px
      配合 MainLayout 里同步收掉的留白, 窄屏主内容能多出一半. */
@media (max-width: 1100px) {
  .tm-side { width: 190px; }
  .side-inner { padding: 12px 8px 14px; gap: 10px; }
}
@media (max-width: 860px) {
  .tm-side { width: 160px; }
  .side-inner { padding: 10px 6px 12px; }
}
</style>
