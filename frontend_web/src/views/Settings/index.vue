<template>
  <div class="set">
    <h1 class="title">设置</h1>
    <p class="lede">个人偏好 / 主题 / 账号 / 服务连接</p>

    <div class="card">
      <h2><span>外观</span></h2>
      <div class="row">
        <div>
          <div class="lbl">主题</div>
          <div class="hint">跟随系统或强制选择浅色/深色</div>
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
    </div>

    <div class="card">
      <h2><span>账号</span></h2>
      <div class="kv">
        <div class="k">用户名</div><div class="v">{{ userStore.user?.username || '-' }}</div>
        <div class="k">角色</div><div class="v">{{ roleText(userStore.user?.role) }}</div>
        <div class="k">用户 ID</div><div class="v mono">{{ userStore.user?.id || '-' }}</div>
      </div>
    </div>

    <div class="card">
      <h2><span>后端服务</span></h2>
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
    </div>
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
.set { display: flex; flex-direction: column; gap: 18px; }
.title { font-size: 30px; font-weight: 800; margin: 0 0 10px; letter-spacing: -0.4px; color: var(--ink-900); }
.lede { color: var(--ink-700); margin: 0 0 24px; font-size: 14.5px; }
h2 { font-size: 15px; font-weight: 700; margin: 0 0 14px; display: flex; align-items: center; gap: 8px; }
.row { display: flex; align-items: center; justify-content: space-between; gap: 12px; }
.lbl { font-size: 13.5px; color: var(--ink-900); font-weight: 500; }
.hint { font-size: 12.5px; color: var(--ink-500); margin-top: 2px; }
.chooser { display: inline-flex; background: var(--surface-sunken); border-radius: 9px; padding: 3px; gap: 2px; }
.cbtn { background: transparent; border: none; cursor: pointer; padding: 5px 14px; font-size: 12.5px; color: var(--ink-700); font-family: inherit; border-radius: 6px; }
.cbtn:hover { color: var(--ink-900); }
.cbtn.active { background: var(--surface); color: var(--primary); font-weight: 600; box-shadow: var(--shadow-sm); }

.kv { display: grid; grid-template-columns: 100px 1fr; row-gap: 10px; column-gap: 16px; font-size: 13.5px; }
.kv .k { color: var(--ink-500); }
.kv .v { color: var(--ink-900); }
.mono { font-family: var(--font-mono); }

.svc-row {
  display: flex; justify-content: space-between; align-items: center;
  padding: 10px 0; font-size: 13.5px; color: var(--ink-900);
  border-bottom: 1px solid var(--border);
}
.svc-row:last-child { border-bottom: none; }
.ok, .off { display: inline-flex; align-items: center; gap: 6px; font-size: 12.5px; }
.ok { color: var(--ok); }
.off { color: var(--ink-500); }
.ok .d, .off .d { width: 6px; height: 6px; border-radius: 50%; }
.ok .d { background: var(--ok); box-shadow: 0 0 0 3px rgba(22, 163, 74, 0.15); }
.off .d { background: var(--off); }
</style>
