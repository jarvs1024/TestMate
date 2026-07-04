<template>
  <div class="set">
    <header class="page-head">
      <h1 class="title">设置</h1>
    </header>

    <section class="card sec">
      <div class="sec-h">外观</div>
      <div class="row">
        <div>
          <div class="row-t">主题</div>
          <div class="row-s">跟随系统或强制选择</div>
        </div>
        <div class="theme-chooser">
          <button
            v-for="m in modes"
            :key="m.value"
            class="tbtn"
            :class="{ active: themeStore.mode === m.value }"
            @click="themeStore.set(m.value)"
          >{{ m.label }}</button>
        </div>
      </div>
    </section>

    <section class="card sec">
      <div class="sec-h">账号</div>
      <div class="kv">
        <div class="k">用户名</div><div class="v">{{ userStore.user?.username || '-' }}</div>
        <div class="k">角色</div><div class="v">{{ roleText(userStore.user?.role) }}</div>
        <div class="k">用户 ID</div><div class="v mono">{{ userStore.user?.id || '-' }}</div>
      </div>
    </section>

    <section class="card sec">
      <div class="sec-h">后端服务</div>
      <div class="svc">
        <div class="svc-row">
          <span>TestMate Gateway</span>
          <span class="ok">● 健康</span>
        </div>
        <div class="svc-row">
          <span>RAGFlow</span>
          <span class="dim">○ 未配置</span>
        </div>
        <div class="svc-row">
          <span>Dify</span>
          <span class="dim">○ 未配置</span>
        </div>
      </div>
    </section>
  </div>
</template>

<script setup lang="ts">
import { useUserStore } from '@/stores/user';
import { useThemeStore } from '@/stores/theme';
const userStore = useUserStore();
const themeStore = useThemeStore();
const modes = [
  { value: 'auto'  as const, label: '自动' },
  { value: 'light' as const, label: '浅色' },
  { value: 'dark'  as const, label: '深色' },
];
function roleText(r?: string) {
  if (r === 'admin') return '管理员';
  if (r === 'tester') return '测试工程师';
  if (r === 'viewer') return '只读';
  return '-';
}
</script>

<style scoped>
.set { display: flex; flex-direction: column; gap: 12px; max-width: 720px; }
.title { font-size: 18px; font-weight: 600; margin: 0; color: var(--ink-900); }

.sec { padding: 16px 20px; }
.sec-h {
  font-size: 11.5px;
  text-transform: uppercase;
  letter-spacing: 0.6px;
  color: var(--ink-500);
  font-weight: 600;
  margin-bottom: 12px;
}

.row { display: flex; align-items: center; justify-content: space-between; gap: 12px; }
.row-t { font-size: 13px; color: var(--ink-900); font-weight: 500; }
.row-s { font-size: 12px; color: var(--ink-500); margin-top: 2px; }

.theme-chooser { display: inline-flex; border: 1px solid var(--border); border-radius: 4px; overflow: hidden; }
.tbtn {
  background: transparent; border: none; cursor: pointer;
  padding: 5px 12px; font-size: 12.5px;
  color: var(--ink-700); font-family: inherit;
  border-right: 1px solid var(--border);
}
.tbtn:last-child { border-right: none; }
.tbtn:hover { background: var(--bg-hover); }
.tbtn.active { background: var(--primary-soft); color: var(--primary); font-weight: 600; }

.kv { display: grid; grid-template-columns: 100px 1fr; row-gap: 8px; column-gap: 16px; font-size: 13px; }
.kv .k { color: var(--ink-500); }
.kv .v { color: var(--ink-900); }
.mono { font-family: var(--font-mono); font-size: 12.5px; }

.svc { display: flex; flex-direction: column; }
.svc-row {
  display: flex; justify-content: space-between; align-items: center;
  padding: 8px 0; font-size: 13px; color: var(--ink-900);
  border-bottom: 1px solid var(--border);
}
.svc-row:last-child { border-bottom: none; }
.ok { color: var(--ok); font-size: 12px; }
.dim { color: var(--ink-500); font-size: 12px; }
</style>
