<template>
  <el-dropdown trigger="click" @command="onCommand">
    <button class="tm-user" type="button">
      <span class="avatar">{{ initial }}</span>
      <span class="name">{{ userStore.user?.username || '未登录' }}</span>
      <svg width="10" height="10" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">
        <path d="m6 9 6 6 6-6"/>
      </svg>
    </button>
    <template #dropdown>
      <el-dropdown-menu>
        <el-dropdown-item disabled>
          <div style="display:flex; flex-direction:column; gap:2px; padding: 4px 0;">
            <span style="font-size:13px; font-weight:600;">{{ userStore.user?.username }}</span>
            <span style="font-size:11px; color: var(--ink-500);">角色 · {{ roleText(userStore.user?.role) }}</span>
          </div>
        </el-dropdown-item>
        <el-dropdown-item divided command="settings">设置</el-dropdown-item>
        <el-dropdown-item command="logout">退出登录</el-dropdown-item>
      </el-dropdown-menu>
    </template>
  </el-dropdown>
</template>

<script setup lang="ts">
import { computed } from 'vue';
import { useRouter } from 'vue-router';
import { useUserStore } from '@/stores/user';

const router = useRouter();
const userStore = useUserStore();

const initial = computed(() => (userStore.user?.username || '?')[0]?.toUpperCase() || '?');

function roleText(r?: string) {
  if (r === 'admin') return '管理员';
  if (r === 'tester') return '测试工程师';
  if (r === 'viewer') return '只读';
  return '-';
}

function onCommand(cmd: string) {
  if (cmd === 'logout') {
    userStore.logout();
    router.push('/login');
  } else if (cmd === 'settings') {
    router.push('/settings');
  }
}
</script>

<style scoped>
.tm-user {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  padding: 3px 8px 3px 3px;
  border: 1px solid transparent;
  background: transparent;
  border-radius: 4px;
  cursor: pointer;
  color: var(--ink-700);
  font-size: 12.5px;
  font-family: inherit;
  transition: background .12s ease, border-color .12s ease;
}
.tm-user:hover {
  background: var(--bg-hover);
  border-color: var(--border);
}
.avatar {
  width: 22px; height: 22px;
  border-radius: 4px;
  background: var(--primary-soft);
  color: var(--primary);
  font-size: 11px; font-weight: 600;
  display: grid; place-items: center;
}
.name { font-weight: 500; }
</style>
