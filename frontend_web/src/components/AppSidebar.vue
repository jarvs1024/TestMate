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
</style>
