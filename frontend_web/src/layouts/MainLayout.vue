<template>
  <div class="tm-shell">
    <AppHeader />
    <div class="tm-body">
      <AppSidebar />
      <main class="tm-main">
        <router-view v-slot="{ Component, route }">
          <transition name="tm-fade" mode="out-in">
            <component :is="Component" :key="route.fullPath" />
          </transition>
        </router-view>
      </main>
      <RagDrawer />
    </div>
  </div>
</template>

<script setup lang="ts">
import AppHeader from '@/components/AppHeader.vue';
import AppSidebar from '@/components/AppSidebar.vue';
import RagDrawer from '@/components/RagDrawer.vue';
</script>

<style scoped>
.tm-shell { display: flex; flex-direction: column; height: 100vh; overflow: hidden; }
.tm-body { flex: 1; display: flex; min-height: 0; }
.tm-main { flex: 1; min-width: 0; overflow: auto; padding: 20px 24px; background: var(--bg); }

.tm-fade-enter-active, .tm-fade-leave-active { transition: opacity .15s ease; }
.tm-fade-enter-from, .tm-fade-leave-to { opacity: 0; }
</style>
