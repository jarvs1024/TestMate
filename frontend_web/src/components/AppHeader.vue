<template>
  <header class="tm-header">
    <div class="logo">T</div>
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
  display: grid; place-items: center;
  background: linear-gradient(135deg, var(--primary), var(--primary-2));
  color: #fff; font-weight: 800; font-size: 18px;
  box-shadow: var(--primary-shadow);
  flex-shrink: 0;
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
