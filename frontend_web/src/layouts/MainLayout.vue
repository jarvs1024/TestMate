<template>
  <div class="tm-shell">
    <AppHeader />
    <div class="tm-body">
      <AppSidebar />
      <main class="tm-main">
        <div class="container">
          <router-view v-slot="{ Component, route }">
            <transition name="tm-fade" mode="out-in">
              <component :is="Component" :key="route.fullPath" />
            </transition>
          </router-view>
        </div>
      </main>
    </div>
  </div>
</template>

<script setup lang="ts">
import AppHeader from '@/components/AppHeader.vue';
import AppSidebar from '@/components/AppSidebar.vue';
</script>

<style scoped>
/* 整页固定 viewport, 内部用独立 scroll 区分侧栏和主区 */
.tm-shell {
  display: flex;
  flex-direction: column;
  height: 100vh;          /* 不让 body 滚, 内部滚 */
  overflow: hidden;
}

.tm-body {
  flex: 1;
  display: flex;
  min-height: 0;          /* 关键: 让子元素 overflow: auto 生效 */
}

/* 侧栏: 固定不动, 自己内部滚 */
:deep(.tm-side) {
  height: 100%;
  overflow-y: auto;
  flex-shrink: 0;
  /* 防止弹性收缩把内容挤掉 */
  align-self: stretch;
}

/* 主区: 独立 scroll, 不带动侧栏 */
.tm-main {
  flex: 1;
  min-width: 0;
  overflow-y: auto;       /* 主区自己滚 */
  padding: 0 8px 32px;
}
.container {
  max-width: 1440px;
  margin: 0 auto;
  padding: 8px 32px 48px;
  width: 100%;
  box-sizing: border-box;
}
/* 大屏给 grid 更多空间, 让卡片列数自然变多 */
@media (min-width: 1600px) {
  .container { max-width: 1600px; padding: 8px 40px 48px; }
}

.tm-fade-enter-active, .tm-fade-leave-active { transition: opacity .15s ease, transform .15s ease; }
.tm-fade-enter-from { opacity: 0; transform: translateY(4px); }
.tm-fade-leave-to { opacity: 0; transform: translateY(-4px); }
</style>
