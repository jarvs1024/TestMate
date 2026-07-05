<template>
  <header class="tm-header">
    <div class="logo">
      <svg viewBox="0 0 38 38" width="38" height="38" fill="none" xmlns="http://www.w3.org/2000/svg" aria-hidden="true">
        <defs>
          <linearGradient id="lg-bg" x1="0" y1="0" x2="1" y2="1">
            <stop offset="0%" stop-color="#6366F1"/>
            <stop offset="100%" stop-color="#3B82F6"/>
          </linearGradient>
          <linearGradient id="lg-m" x1="0" y1="0" x2="0" y2="1">
            <stop offset="0%" stop-color="#ffffff"/>
            <stop offset="100%" stop-color="#e0f2fe"/>
          </linearGradient>
        </defs>
        <!-- 背景圆角方块: 蓝紫渐变 -->
        <rect x="0" y="0" width="38" height="38" rx="10" fill="url(#lg-bg)"/>
        <!-- 后置 M (深绿, 轻微错位制造立体) -->
        <path d="M9.5 28 L9.5 10 L14 10 L19 19.5 L24 10 L28.5 10 L28.5 28 L24 28 L24 17 L20 24.5 L18 24.5 L14 17 L14 28 Z" fill="#0d9488" transform="translate(1,1)"/>
        <!-- 前置 M (白蓝渐变, 主) -->
        <path d="M9.5 28 L9.5 10 L14 10 L19 19.5 L24 10 L28.5 10 L28.5 28 L24 28 L24 17 L20 24.5 L18 24.5 L14 17 L14 28 Z" fill="url(#lg-m)"/>
      </svg>
    </div>
    <div class="brand">
      <span class="t1">TestMate</span>
      <span class="t2">智能测试辅助平台 · v0.1</span>
    </div>
    <!-- 当前页面标题 (居中显示, 跟左侧 brand 视觉对称) -->
    <div v-if="pageTitle" class="page-title">
      <div class="pt-name">{{ pageTitle }}</div>
      <div v-if="pageLede" class="pt-lede">{{ pageLede }}</div>
    </div>
    <div class="right">
      <ThemeSwitcher />
      <UserMenu />
    </div>
  </header>
</template>

<script setup lang="ts">
import { computed } from 'vue';
import { useRoute } from 'vue-router';
import ThemeSwitcher from './ThemeSwitcher.vue';
import UserMenu from './UserMenu.vue';

const route = useRoute();
const pageTitle = computed(() => (route.meta?.title as string) || '');
const pageLede = computed(() => (route.meta?.lede as string) || '');
</script>

<style scoped>
.tm-header {
  display: flex;
  align-items: center;
  gap: 12px;
  padding: 16px 24px;
  background: transparent;
  flex-shrink: 0;
}
.logo {
  width: 38px; height: 38px;
  border-radius: 10px;
  flex-shrink: 0;
  display: grid; place-items: center;
  box-shadow: var(--primary-shadow);
  overflow: hidden;            /* svg 圆角内裁切 */
}
.brand { display: flex; flex-direction: column; min-width: 180px; }
.t1 { font-size: 17px; font-weight: 700; color: var(--ink-900); letter-spacing: -0.2px; line-height: 1.2; }
.t2 { font-size: 12.5px; color: var(--ink-500); margin-top: 1px; }

.right { margin-left: auto; display: flex; align-items: center; gap: 8px; }

/* 当前页面标题: 在 brand 之后, 用户菜单之前 */
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
</style>
