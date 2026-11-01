<template>
  <div class="profile-page">
    <header class="profile-header">
      <p class="eyebrow">PERSONAL CENTER</p>
      <h1>个人中心</h1>
      <p>{{ username }} · 管理授权与访问令牌</p>
    </header>

    <div class="kind-tabs" role="tablist" aria-label="个人中心分区">
      <button
        type="button"
        class="kind-tab"
        role="tab"
        :aria-selected="tab === 'grants'"
        :class="{ active: tab === 'grants' }"
        @click="tab = 'grants'"
      >授权管理</button>
      <button
        type="button"
        class="kind-tab"
        role="tab"
        :aria-selected="tab === 'tokens'"
        :class="{ active: tab === 'tokens' }"
        @click="tab = 'tokens'"
      >访问令牌</button>
    </div>

    <GrantsPanel v-if="tab === 'grants'" />
    <McpTokens v-else />
  </div>
</template>

<script setup lang="ts">
import { computed, ref } from 'vue';
import { useUserStore } from '@/stores/user';
import GrantsPanel from '@/views/Connect/GrantsPanel.vue';
import McpTokens from '@/views/Settings/components/McpTokens.vue';

const userStore = useUserStore();
const tab = ref<'grants' | 'tokens'>('grants');
const username = computed(() => userStore.user?.username || '未登录');
</script>

<style scoped>
.profile-page { display: flex; width: min(980px, 100%); flex-direction: column; gap: 16px; margin: 0 auto; padding: 12px 4px 40px; }
.eyebrow { margin: 0 0 4px; color: var(--primary); font-family: var(--font-mono); font-size: 11px; font-weight: 700; letter-spacing: .07em; }
h1 { margin: 0; color: var(--ink-900); font-size: 25px; }
.profile-header p:last-child { margin: 7px 0 0; color: var(--ink-500); font-size: 12.5px; }
.kind-tabs { margin: 0; }
</style>
