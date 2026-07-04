<template>
  <div class="h-screen flex flex-col bg-slate-50">
    <!-- 顶栏 -->
    <header class="h-14 flex items-center justify-between px-6 bg-white border-b border-slate-200 shrink-0">
      <div class="flex items-center gap-3">
        <div class="w-8 h-8 rounded-lg bg-primary-600 flex items-center justify-center text-white font-bold">
          T
        </div>
        <h1 class="text-base font-semibold m-0">TestMate 智能测试辅助平台</h1>
      </div>
      <div class="flex items-center gap-4 text-sm">
        <div class="flex items-center gap-2 text-slate-500">
          <span class="w-2 h-2 rounded-full bg-emerald-500"></span>
          <span>服务正常</span>
        </div>
        <el-dropdown @command="onCommand">
          <span class="cursor-pointer text-slate-700">
            {{ userStore.user?.username || '未登录' }} ⌄
          </span>
          <template #dropdown>
            <el-dropdown-menu>
              <el-dropdown-item command="settings">⚙ 设置</el-dropdown-item>
              <el-dropdown-item command="logout">退出登录</el-dropdown-item>
            </el-dropdown-menu>
          </template>
        </el-dropdown>
      </div>
    </header>

    <!-- 三轴主体 -->
    <div class="flex-1 flex overflow-hidden">
      <!-- 左轴:导航 -->
      <aside class="w-56 bg-white border-r border-slate-200 flex flex-col shrink-0">
        <nav class="flex-1 p-3 space-y-1">
          <router-link
            v-for="item in navItems"
            :key="item.path"
            :to="item.path"
            class="flex items-center gap-3 px-3 py-2 rounded-lg text-sm text-slate-700 hover:bg-slate-100"
            active-class="bg-primary-50 text-primary-700 font-medium"
          >
            <span class="text-lg">{{ item.icon }}</span>
            <span>{{ item.label }}</span>
          </router-link>
        </nav>
        <!-- 机台状态占位(P1 实装) -->
        <div class="p-3 border-t border-slate-200 text-xs">
          <div class="text-slate-500 mb-2">机台状态</div>
          <div class="text-slate-400 italic">P1 实装</div>
        </div>
      </aside>

      <!-- 中轴:工作区 -->
      <main class="flex-1 overflow-auto p-8">
        <router-view />
      </main>

      <!-- 右轴:RAG 协议随身 -->
      <aside class="w-80 bg-white border-l border-slate-200 shrink-0 p-4">
        <div class="text-sm font-medium text-slate-700 mb-3">📖 协议随身</div>
        <el-input placeholder="搜索 NVMe / JEDEC 规范" size="default" disabled>
          <template #prefix>🔍</template>
        </el-input>
        <div class="mt-4 text-xs text-slate-400 italic">
          P1 接入 RAGFlow,P0 占位
        </div>
      </aside>
    </div>
  </div>
</template>

<script setup lang="ts">
import { useRouter } from 'vue-router';
import { useUserStore } from '@/stores/user';

const router = useRouter();
const userStore = useUserStore();

const navItems = [
  { path: '/diagnosis', icon: '📊', label: 'log 诊断' },
  { path: '/kb', icon: '📚', label: '协议检索' },
  { path: '/settings', icon: '⚙️', label: '设置' },
];

function onCommand(cmd: string) {
  if (cmd === 'logout') {
    userStore.logout();
    router.push('/login');
  } else if (cmd === 'settings') {
    router.push('/settings');
  }
}
</script>
