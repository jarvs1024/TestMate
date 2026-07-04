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
.tm-shell { display: flex; flex-direction: column; min-height: 100vh; }
.tm-body { flex: 1; display: flex; min-height: 0; }
.tm-main { flex: 1; min-width: 0; padding: 0 8px 32px; overflow: auto; }
.container { max-width: 1080px; margin: 0 auto; padding: 8px 16px 48px; }

.tm-fade-enter-active, .tm-fade-leave-active { transition: opacity .15s ease, transform .15s ease; }
.tm-fade-enter-from { opacity: 0; transform: translateY(4px); }
.tm-fade-leave-to { opacity: 0; transform: translateY(-4px); }
</style>
