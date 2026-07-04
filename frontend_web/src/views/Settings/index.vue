<template>
  <div class="settings-page">
    <div class="page-head">
      <div>
        <h1 class="page-title">系统设置</h1>
        <p class="page-lede">个人偏好 / 主题 / API token / 服务连接</p>
      </div>
    </div>

    <div class="settings-grid">
      <PreviewWindow title="appearance" subtitle="外观">
        <div class="card-body">
          <div class="row">
            <div>
              <div class="row-title">主题</div>
              <div class="row-sub">跟随系统,或强制浅色 / 深色</div>
            </div>
            <ThemeSwitcher />
          </div>
        </div>
      </PreviewWindow>

      <PreviewWindow title="account" subtitle="账号信息">
        <div class="card-body">
          <div class="kv">
            <div class="k">用户名</div><div class="v tm-mono">{{ userStore.user?.username || '-' }}</div>
            <div class="k">角色</div><div class="v">{{ roleText(userStore.user?.role) }}</div>
            <div class="k">用户 ID</div><div class="v tm-mono">{{ userStore.user?.id || '-' }}</div>
          </div>
        </div>
      </PreviewWindow>

      <PreviewWindow title="api-token" subtitle="个人 API token">
        <div class="card-body">
          <p class="hint">供本地 Python 脚本调用 TestMate API 使用,P1 启用,目前接口未实装</p>
          <div class="token-box tm-mono">tmt_xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx</div>
        </div>
      </PreviewWindow>

      <PreviewWindow title="services" subtitle="后端服务">
        <div class="card-body">
          <div class="svc-row">
            <span>TestMate Gateway</span>
            <span class="chip chip-ok">● 健康</span>
          </div>
          <div class="svc-row">
            <span>RAGFlow</span>
            <span class="chip chip-off">○ 未配置</span>
          </div>
          <div class="svc-row">
            <span>Dify</span>
            <span class="chip chip-off">○ 未配置</span>
          </div>
        </div>
      </PreviewWindow>
    </div>
  </div>
</template>

<script setup lang="ts">
import { useUserStore } from '@/stores/user';
import PreviewWindow from '@/components/PreviewWindow.vue';
import ThemeSwitcher from '@/components/ThemeSwitcher.vue';

const userStore = useUserStore();

function roleText(r?: string) {
  if (r === 'admin') return '管理员';
  if (r === 'tester') return '测试工程师';
  if (r === 'viewer') return '只读';
  return '-';
}
</script>

<style scoped>
.settings-page { display: flex; flex-direction: column; gap: 16px; }
.page-head { display: flex; align-items: flex-end; justify-content: space-between; gap: 16px; }
.page-title { font-size: 24px; font-weight: 700; margin: 0; color: var(--ink-900); }
.page-lede { font-size: 13.5px; color: var(--ink-500); margin: 4px 0 0; }

.settings-grid {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 16px;
}

.card-body { padding: 18px 22px; }

.row {
  display: flex; align-items: center; justify-content: space-between;
  gap: 12px;
}
.row-title { font-size: 14px; font-weight: 600; color: var(--ink-900); }
.row-sub { font-size: 12.5px; color: var(--ink-500); margin-top: 2px; }

.kv {
  display: grid; grid-template-columns: 100px 1fr;
  row-gap: 10px; column-gap: 16px;
  font-size: 13.5px;
}
.kv .k { color: var(--ink-500); }
.kv .v { color: var(--ink-900); }

.hint { font-size: 12.5px; color: var(--ink-500); margin: 0 0 12px; }
.token-box {
  font-size: 12.5px;
  padding: 8px 12px;
  background: var(--surface-sunken);
  border-radius: var(--radius-md);
  color: var(--ink-500);
  letter-spacing: 0.5px;
}

.svc-row {
  display: flex; align-items: center; justify-content: space-between;
  padding: 8px 0;
  font-size: 13.5px;
  color: var(--ink-900);
  border-bottom: 1px solid var(--border);
}
.svc-row:last-child { border-bottom: none; }
.chip {
  font-size: 11px; padding: 2px 9px; border-radius: 999px;
  font-weight: 500;
  border: 1px solid transparent;
}
.chip-ok  { background: var(--status-ok-soft); color: var(--status-ok); }
.chip-off { background: var(--surface-sunken); color: var(--ink-500); border-color: var(--border); }
</style>
