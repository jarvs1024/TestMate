<template>
  <header class="tm-header">
    <div class="logo">T</div>
    <div class="brand">
      <span class="t1">TestMate</span>
      <span class="t2">智能测试辅助平台 · v0.1</span>
    </div>
    <div class="right">
      <ThemeSwitcher />
      <UserMenu />
    </div>
  </header>
</template>

<script setup lang="ts">
import ThemeSwitcher from './ThemeSwitcher.vue';
import UserMenu from './UserMenu.vue';
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
</style>
