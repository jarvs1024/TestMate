<template>
  <div class="profile-page">
    <!-- 标题 / lede 归顶栏 (AppHeader) —— 页面里再写一遍就是两个标题.
         顶部动作条跟扩展库 / 软件库共用 .mk-actions, tab 共用 .kind-tabs. -->
    <div class="mk-actions">
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
      <div class="ma-right">
        <span class="account-meta">当前账号 · <b>{{ username }}</b></span>
      </div>
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
.profile-page { display: flex; flex-direction: column; gap: 16px; padding: 12px 4px 40px; }
.account-meta { color: var(--ink-500); font-family: var(--font-mono); font-size: 12px; }
.account-meta b { color: var(--ink-900); font-weight: 600; }
</style>
