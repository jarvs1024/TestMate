<template>
  <header class="tm-header">
    <BrandLogo :size="38" />
    <div class="brand">
      <span class="t1">TestMate</span>
      <span class="t2">智能测试辅助平台 · v0.1</span>
    </div>
    <!-- 当前页面标题 (居中显示, 跟左侧 brand 视觉对称) -->
    <div v-if="pageTitle" class="page-title">
      <div class="pt-name">{{ pageTitle }}</div>
      <div v-if="pageLede" class="pt-lede">{{ pageLede }}</div>
    </div>
    <!-- 通用滚动通知栏 (匿名访问 / 系统公告等, 跨页面共享).
         NoticeBar 自己管 dismiss 持久化 (sessionStorage/localStorage, 走 dismissScope),
         这里只需要提供 notices 列表即可, 不必监听 dismiss 事件. -->
    <NoticeBar :notices="notices" class="tm-notice" />
    <div class="right">
      <ThemeSwitcher />
      <UserMenu />
    </div>
  </header>
</template>

<script setup lang="ts">
import { computed } from 'vue';
import { useRoute } from 'vue-router';
import BrandLogo from './BrandLogo.vue';
import ThemeSwitcher from './ThemeSwitcher.vue';
import UserMenu from './UserMenu.vue';
import NoticeBar, { type NoticeItem } from './NoticeBar.vue';
import { useUserStore } from '@/stores/user';

const route = useRoute();
const pageTitle = computed(() => (route.meta?.title as string) || '');
const pageLede = computed(() => (route.meta?.lede as string) || '');

// 通知数据源 (AppHeader 全局管理, 跨页面共享).
// 当前: 匿名访问提示. 后续要加系统公告 / 实验功能提示, push 到 list 即可.
// dismiss 行为 (sessionStorage 持久 / 关掉后从可见列表移除) 由 NoticeBar 自己管, 不必回调.
const userStore = useUserStore();
const notices = computed<NoticeItem[]>(() => {
  const list: NoticeItem[] = [];
  if (!userStore.token) {
    list.push({
      id: 'cr-anon-readonly',
      type: 'info',
      text: '您正在匿名访问,部分交互功能需 [登录](/login?redirect=/code-review) 后使用',
      marquee: true,
      dismissKey: 'cr:anon-notice-dismissed',
      dismissScope: 'session',
      dismissTitle: '本次会话内不再提示 (刷新会重新出现)',
    });
  }
  return list;
});
</script>

<style scoped>
.tm-header {
  display: flex;
  align-items: center;
  gap: 12px;
  padding: 14px 24px;
  background: var(--surface-soft);
  backdrop-filter: blur(10px);
  -webkit-backdrop-filter: blur(10px);
  border-bottom: 1px solid var(--border);
  flex-shrink: 0;
}

.brand { display: flex; flex-direction: column; min-width: 180px; }
.t1 { font-size: 17px; font-weight: 700; color: var(--ink-900); letter-spacing: -0.2px; line-height: 1.2; }
.t2 { font-size: 12.5px; color: var(--ink-500); margin-top: 1px; }

.right { margin-left: auto; display: flex; align-items: center; gap: 8px; }

/* 当前页面标题: 在 brand 之后, 通知栏之前 */
.page-title {
  margin-left: 32px;          /* 跟 brand 留点空 */
  padding-left: 24px;
  border-left: 1px solid var(--border);
  display: flex;
  flex-direction: column;
  justify-content: center;
  min-width: 0;
}
.pt-name {
  font-size: 18px;
  font-weight: 700;
  color: var(--ink-900);
  line-height: 1.2;
  letter-spacing: -0.2px;
}
.pt-lede {
  font-size: 12px;
  color: var(--ink-500);
  margin-top: 1px;
  line-height: 1.2;
  max-width: 600px;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

/* 通知栏 (header 内嵌版): 视觉上跟标题块/主题按钮同处一行, 但权重更轻 ——
   不抢标题戏, 用微染色背景 + 细边框, 文字色走 ink-700 而不是 info 主色,
   让它看起来像 AppHeader 的一部分, 而不是塞进去的卡片.
   padding / height 跟 lede 一行高度对齐. */
.tm-notice {
  margin-left: 18px;
  margin-bottom: 0;
  flex: 1;
  min-width: 0;
  padding: 4px 8px 4px 12px;
  min-height: 28px;
  font-size: 12px;
  border-radius: 14px;
  /* 覆盖 NoticeBar 默认的卡片样式: 微染色 + 细边 + ink-700 文字,
     跟 AppHeader 的中性色更搭 */
  background: color-mix(in srgb, var(--info, var(--primary)) 7%, transparent);
  border: 1px solid color-mix(in srgb, var(--info, var(--primary)) 20%, transparent);
  color: color-mix(in srgb, var(--ink-700) 90%, var(--info, var(--primary)) 10%);
}
/* 通知内部元素轻量化: icon 小一号, ✕ 更隐形, link 不下划线虚线那么突出. */
.tm-notice :deep(.nb-icon) { font-size: 13px; opacity: 0.85; }
.tm-notice :deep(.nb-body) { font-weight: 500; }
.tm-notice :deep(.nb-link) { border-bottom: 1px solid color-mix(in srgb, currentColor 35%, transparent); }
.tm-notice :deep(.nb-link:hover) { border-bottom-color: currentColor; }
.tm-notice :deep(.nb-nav-btn) { width: 20px; height: 20px; font-size: 12px; }
.tm-notice :deep(.nb-count) { min-width: 30px; }
.tm-notice :deep(.nb-close) { padding: 2px 6px; font-size: 12px; opacity: 0.45; }
.tm-notice :deep(.nb-close:hover) { opacity: 0.9; }
</style>
