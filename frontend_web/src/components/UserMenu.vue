<template>
  <el-dropdown trigger="click" @command="onCommand">
    <div class="tm-user-menu">
      <div class="avatar">{{ initial }}</div>
      <span class="name">{{ userStore.user?.username || '未登录' }}</span>
      <span class="caret">▾</span>
    </div>
    <template #dropdown>
      <el-dropdown-menu>
        <el-dropdown-item disabled>
          <div style="display:flex; flex-direction:column; gap:2px; padding: 4px 0;">
            <span style="font-size:13px; font-weight:600;">{{ userStore.user?.username }}</span>
            <span style="font-size:11px; color: var(--ink-500);">角色:{{ userStore.user?.role || '-' }}</span>
          </div>
        </el-dropdown-item>
        <el-dropdown-item divided command="settings">⚙ 设置</el-dropdown-item>
        <el-dropdown-item command="logout">↩ 退出登录</el-dropdown-item>
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

const initial = computed(() => {
  const name = userStore.user?.username || '?';
  return name[0]?.toUpperCase() || '?';
});

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
.tm-user-menu {
  display: inline-flex;
  align-items: center;
  gap: 8px;
  padding: 4px 10px 4px 4px;
  border-radius: var(--radius-pill);
  border: 1px solid var(--border);
  background: var(--surface-soft);
  cursor: pointer;
  user-select: none;
  transition: background .15s ease, border-color .15s ease;
}
.tm-user-menu:hover {
  background: var(--surface);
  border-color: var(--border-strong);
}
.avatar {
  width: 26px; height: 26px;
  border-radius: 50%;
  background: var(--primary-grad);
  color: #fff;
  font-size: 12px; font-weight: 600;
  display: grid; place-items: center;
}
.name { font-size: 13px; color: var(--ink-900); font-weight: 500; }
.caret { font-size: 10px; color: var(--ink-500); }
</style>
