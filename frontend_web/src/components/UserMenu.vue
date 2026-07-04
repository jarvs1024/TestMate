<template>
  <el-dropdown trigger="click" @command="onCommand">
    <button class="tm-user" type="button">
      <span class="avatar">{{ initial }}</span>
      <span class="name">{{ userStore.user?.username || '未登录' }}</span>
      <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">
        <path d="m6 9 6 6 6-6"/>
      </svg>
    </button>
    <template #dropdown>
      <el-dropdown-menu>
        <el-dropdown-item disabled>
          <div class="dd-head">
            <div class="dd-name">{{ userStore.user?.username || '未登录' }}</div>
            <div class="dd-role">{{ roleText(userStore.user?.role) }}</div>
          </div>
        </el-dropdown-item>
        <el-dropdown-item divided command="settings">
          <span class="ic">
            <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><circle cx="12" cy="12" r="3"/><path d="M19.4 15a1.65 1.65 0 0 0 .33 1.82l.06.06a2 2 0 1 1-2.83 2.83l-.06-.06a1.65 1.65 0 0 0-1.82-.33 1.65 1.65 0 0 0-1 1.51V21a2 2 0 0 1-4 0v-.09A1.65 1.65 0 0 0 9 19.4a1.65 1.65 0 0 0-1.82.33l-.06.06a2 2 0 1 1-2.83-2.83l.06-.06a1.65 1.65 0 0 0 .33-1.82 1.65 1.65 0 0 0-1.51-1H3a2 2 0 0 1 0-4h.09A1.65 1.65 0 0 0 4.6 9a1.65 1.65 0 0 0-.33-1.82l-.06-.06a2 2 0 1 1 2.83-2.83l.06.06a1.65 1.65 0 0 0 1.82.33H9a1.65 1.65 0 0 0 1-1.51V3a2 2 0 0 1 4 0v.09a1.65 1.65 0 0 0 1 1.51 1.65 1.65 0 0 0 1.82-.33l.06-.06a2 2 0 1 1 2.83 2.83l-.06.06a1.65 1.65 0 0 0-.33 1.82V9a1.65 1.65 0 0 0 1.51 1H21a2 2 0 0 1 0 4h-.09a1.65 1.65 0 0 0-1.51 1z"/></svg>
          </span>
          设置
        </el-dropdown-item>
        <el-dropdown-item command="logout">
          <span class="ic">
            <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><path d="M9 21H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h4"/><polyline points="16 17 21 12 16 7"/><line x1="21" y1="12" x2="9" y2="12"/></svg>
          </span>
          退出登录
        </el-dropdown-item>
      </el-dropdown-menu>
    </template>
  </el-dropdown>
</template>

<script setup lang="ts">
import { computed } from 'vue';
import { useRouter } from 'vue-router';
import { ElMessage } from 'element-plus';
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
    ElMessage.success('已退出登录');
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
  gap: 8px;
  height: 36px;
  padding: 0 10px 0 4px;
  background: var(--surface);
  border: 1px solid var(--border);
  color: var(--ink-900);
  border-radius: var(--radius-md);
  cursor: pointer;
  font-family: inherit;
  font-size: 13.5px;
  font-weight: 500;
  transition: border-color .15s ease, background .15s ease;
}
.tm-user:hover {
  border-color: var(--primary);
  background: var(--primary-soft);
}
.avatar {
  width: 26px; height: 26px;
  border-radius: var(--radius-sm);
  background: var(--primary-grad);
  color: #fff;
  font-size: 12px; font-weight: 600;
  display: grid; place-items: center;
}
.name { line-height: 1; }
.dd-head { padding: 4px 0; display: flex; flex-direction: column; gap: 2px; }
.dd-name { font-size: 13px; font-weight: 600; color: var(--ink-900); }
.dd-role { font-size: 11.5px; color: var(--ink-500); }
.ic { display: inline-flex; vertical-align: -2px; margin-right: 6px; color: var(--ink-500); }
</style>
