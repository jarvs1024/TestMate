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
        <el-dropdown-item divided command="agents">智能体注册 (admin)</el-dropdown-item>
        <el-dropdown-item command="theme">主题 · {{ themeLabel }}</el-dropdown-item>
        <el-dropdown-item command="logout">退出登录</el-dropdown-item>
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
const themeLabel = '☀ / 🌙 / 自动';

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
  } else if (cmd === 'agents') {
    ElMessage.info('智能体注册 · P1 实现');
  } else if (cmd === 'theme') {
    ElMessage.info('点顶栏 ☀/🌙 切换主题');
  }
}
</script>

<style scoped>
.tm-user {
  display: inline-flex;
  align-items: center;
  gap: 8px;
  height: 32px;
  padding: 0 10px 0 3px;
  background: var(--surface-soft);
  border: 1px solid var(--border);
  color: var(--ink-900);
  border-radius: 8px;
  cursor: pointer;
  font-family: inherit;
  font-size: 13.5px;
  font-weight: 500;
  backdrop-filter: blur(6px);
  -webkit-backdrop-filter: blur(6px);
  transition: border-color .15s ease;
}
.tm-user:hover { border-color: var(--primary); }
.avatar {
  width: 24px; height: 24px;
  border-radius: 6px;
  background: linear-gradient(135deg, var(--primary), var(--primary-2));
  color: #fff;
  font-size: 11px; font-weight: 700;
  display: grid; place-items: center;
}
.name { line-height: 1; }
.dd-head { padding: 4px 0; }
.dd-name { font-size: 13px; font-weight: 600; color: var(--ink-900); }
.dd-role { font-size: 11.5px; color: var(--ink-500); margin-top: 1px; }
</style>
