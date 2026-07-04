<template>
  <div class="set">
    <header class="head">
      <h1 class="title">设置</h1>
      <p class="sub">个人偏好 / 主题 / 账号 / 服务连接</p>
    </header>

    <section class="card sec">
      <div class="sec-h">外观</div>
      <div class="row">
        <div>
          <div class="row-t">主题</div>
          <div class="row-s">跟随系统或强制选择浅色/深色</div>
        </div>
        <div class="chooser">
          <button
            v-for="m in modes"
            :key="m.value"
            class="cbtn"
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
          <span class="ok"><span class="d"></span>健康</span>
        </div>
        <div class="svc-row">
          <span>RAGFlow</span>
          <span class="off"><span class="d"></span>未配置</span>
        </div>
        <div class="svc-row">
          <span>Dify</span>
          <span class="off"><span class="d"></span>未配置</span>
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
.set { display: flex; flex-direction: column; gap: 16px; max-width: 720px; }
.head { margin-bottom: 4px; }
.title { font-size: 28px; font-weight: 700; margin: 0; color: var(--ink-900); letter-spacing: -0.4px; }
.sub { font-size: 13.5px; color: var(--ink-500); margin: 4px 0 0; }
.sec { padding: 20px 24px; }
.sec-h { font-size: 12px; font-weight: 600; text-transform: uppercase; letter-spacing: 0.8px; color: var(--ink-500); margin-bottom: 14px; }
.row { display: flex; align-items: center; justify-content: space-between; gap: 12px; }
.row-t { font-size: 14px; color: var(--ink-900); font-weight: 500; }
.row-s { font-size: 12.5px; color: var(--ink-500); margin-top: 2px; }
.chooser { display: inline-flex; background: var(--surface-sunken); border-radius: var(--radius-md); padding: 3px; gap: 2px; }
.cbtn { background: transparent; border: none; cursor: pointer; padding: 5px 14px; font-size: 12.5px; color: var(--ink-700); font-family: inherit; border-radius: var(--radius-sm); }
.cbtn:hover { color: var(--ink-900); }
.cbtn.active { background: var(--surface); color: var(--primary); font-weight: 600; box-shadow: var(--shadow-sm); }

.kv { display: grid; grid-template-columns: 100px 1fr; row-gap: 10px; column-gap: 16px; font-size: 13.5px; }
.kv .k { color: var(--ink-500); }
.kv .v { color: var(--ink-900); }
.mono { font-family: var(--font-mono); font-size: 13px; }

.svc-row {
  display: flex; justify-content: space-between; align-items: center;
  padding: 10px 0; font-size: 13.5px; color: var(--ink-900);
  border-bottom: 1px solid var(--border);
}
.svc-row:last-child { border-bottom: none; }
.ok, .off { display: inline-flex; align-items: center; gap: 6px; font-size: 12.5px; }
.ok { color: var(--ok-text); }
.off { color: var(--ink-500); }
.ok .d, .off .d { width: 6px; height: 6px; border-radius: 50%; }
.ok .d { background: var(--ok); }
.off .d { background: var(--off); }
</style>
