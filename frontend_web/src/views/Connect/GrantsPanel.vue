<template>
  <section class="card grants-card" aria-labelledby="grants-title">
    <header class="page-header">
      <div>
        <p class="eyebrow">MCP CONNECTIONS</p>
        <h1 id="grants-title">授权管理</h1>
        <p>查看客户端获得的权限。撤销后，该客户端的新请求会立即失去授权。</p>
      </div>
      <button type="button" class="mini-btn" :disabled="loading" @click="loadGrants">刷新</button>
    </header>

    <div v-if="loading" class="state" role="status">正在读取授权…</div>
    <div v-else-if="loadError" class="state error" role="alert">
      <strong>授权列表加载失败</strong>
      <p>{{ loadError }}</p>
      <button type="button" class="mini-btn" @click="loadGrants">重试</button>
    </div>
    <div v-else-if="!grants.length" class="state empty">
      <strong>还没有 MCP 授权</strong>
      <p>当你同意客户端的连接请求后，授权会显示在这里。</p>
    </div>

    <ul v-else class="grant-list">
      <li v-for="grant in grants" :key="grant.id" :class="{ revoked: grant.revoked_at }">
        <div class="grant-heading">
          <div class="client-identity">
            <strong>{{ grant.client_name }}</strong>
            <code>{{ grant.client_id }}</code>
          </div>
          <span class="status" :class="grant.revoked_at ? 'off' : 'on'">
            {{ grant.revoked_at ? '已撤销' : '生效中' }}
          </span>
        </div>

        <div class="grant-scopes" aria-label="已授权权限">
          <span v-for="scope in grant.scopes" :key="scope" class="scope-chip">
            {{ scopeText(scope) }} <code>{{ scope }}</code>
          </span>
        </div>

        <dl class="grant-meta">
          <div><dt>创建时间</dt><dd>{{ formatTime(grant.created_at) }}</dd></div>
          <div><dt>最近变更</dt><dd>{{ formatTime(grant.updated_at) }}</dd></div>
          <div><dt>授权版本</dt><dd class="mono">v{{ grant.version }}</dd></div>
          <div v-if="grant.revoked_at"><dt>撤销时间</dt><dd>{{ formatTime(grant.revoked_at) }}</dd></div>
        </dl>

        <div v-if="!grant.revoked_at" class="grant-actions">
          <button
            type="button"
            class="mini-btn danger"
            :disabled="busyId !== null"
            @click="revoke(grant)"
          >{{ busyId === grant.id ? '正在撤销…' : '撤销授权' }}</button>
        </div>
      </li>
    </ul>
    <p v-if="actionError" class="action-error" role="alert">{{ actionError }}</p>
  </section>
</template>

<script setup lang="ts">
import { onMounted, ref } from 'vue';
import { ElMessage, ElMessageBox } from 'element-plus';
import { listMcpGrants, revokeMcpGrant, type McpGrant, type McpScope } from '@/api/mcp';
import { errorDetail, errorStatus, httpErrorText } from '@/utils/httpError';
import { parseApiTime } from '@/utils/format';

const grants = ref<McpGrant[]>([]);
const loading = ref(false);
const loadError = ref('');
const actionError = ref('');
const busyId = ref<number | null>(null);

function errorText(error: unknown, fallback: string): string {
  return httpErrorText(errorStatus(error), errorDetail(error), fallback);
}

function scopeText(scope: McpScope): string {
  return scope === 'market:write' ? '管理资产' : '读取资产';
}

function formatTime(value: string | null): string {
  if (!value) return '—';
  const date = parseApiTime(value);
  if (!date) return value;
  return date.toLocaleString('zh-CN', {
    hour12: false,
    year: 'numeric',
    month: '2-digit',
    day: '2-digit',
    hour: '2-digit',
    minute: '2-digit',
  });
}

async function loadGrants() {
  loading.value = true;
  loadError.value = '';
  try {
    const result = await listMcpGrants();
    grants.value = result.items;
  } catch (error) {
    loadError.value = errorText(error, '授权列表加载失败');
  } finally {
    loading.value = false;
  }
}

async function revoke(grant: McpGrant) {
  if (busyId.value !== null || grant.revoked_at) return;
  busyId.value = grant.id;
  actionError.value = '';
  try {
    try {
      await ElMessageBox.confirm(
        `撤销后，「${grant.client_name}」将不能继续以你的身份访问 TestMate。确认撤销？`,
        '撤销 MCP 授权',
        {
          type: 'warning',
          confirmButtonText: '确认撤销',
          cancelButtonText: '取消',
        },
      );
    } catch {
      return;
    }
    if (busyId.value !== grant.id || grant.revoked_at) return;

    await revokeMcpGrant(grant.id);
    ElMessage.success(`已撤销 ${grant.client_name} 的授权`);
    await loadGrants();
  } catch (error) {
    actionError.value = errorText(error, '撤销失败，请重试');
  } finally {
    busyId.value = null;
  }
}

onMounted(loadGrants);
</script>

<style scoped>
.grants-card { padding: clamp(18px, 3vw, 28px); }
.page-header { display: flex; align-items: flex-start; justify-content: space-between; gap: 18px; margin-bottom: 20px; }
.eyebrow { margin: 0 0 4px; color: var(--primary); font-family: var(--font-mono); font-size: 11px; font-weight: 700; letter-spacing: .07em; }
h1 { margin: 0; color: var(--ink-900); font-size: 25px; }
.page-header p:last-child { margin: 7px 0 0; color: var(--ink-500); font-size: 12.5px; }
.state { padding: 34px 20px; border: 1px dashed var(--border); border-radius: var(--radius-sm); background: var(--surface-sunken); color: var(--ink-500); text-align: center; }
.state p { margin: 6px 0 0; font-size: 12px; }
.state.error { color: var(--err); border-color: rgba(239, 68, 68, .35); }
.state.error .mini-btn { margin-top: 14px; }
.state.empty strong { color: var(--ink-700); }
.grant-list { display: flex; flex-direction: column; gap: 12px; margin: 0; padding: 0; list-style: none; }
.grant-list > li { padding: 16px; border: 1px solid var(--border); border-left: 3px solid var(--ok); border-radius: var(--radius-sm); background: var(--surface-soft); }
.grant-list > li.revoked { border-left-color: var(--border-strong); opacity: .72; }
.grant-heading { display: flex; align-items: flex-start; justify-content: space-between; gap: 12px; }
.client-identity { display: flex; min-width: 0; flex-direction: column; gap: 2px; }
.client-identity strong { color: var(--ink-900); font-size: 15px; }
.client-identity code, .mono { font-family: var(--font-mono); }
.client-identity code { overflow-wrap: anywhere; color: var(--ink-500); font-size: 11px; }
.status { flex: 0 0 auto; padding: 2px 9px; border-radius: var(--radius-pill); font-size: 11px; font-weight: 600; }
.status.on { background: rgba(16, 185, 129, .12); color: var(--ok); }
.status.off { background: var(--surface-sunken); color: var(--ink-500); }
.grant-scopes { display: flex; gap: 7px; flex-wrap: wrap; margin-top: 13px; }
.scope-chip { padding: 4px 9px; border-radius: 7px; background: var(--primary-soft); color: var(--ink-700); font-size: 11.5px; }
.scope-chip code { margin-left: 4px; color: var(--primary); font-family: var(--font-mono); font-size: 10.5px; }
.grant-meta { display: grid; grid-template-columns: repeat(3, minmax(0, 1fr)); gap: 10px; margin: 15px 0 0; }
.grant-meta div { min-width: 0; }
.grant-meta dt { color: var(--ink-500); font-size: 10.5px; }
.grant-meta dd { margin: 2px 0 0; color: var(--ink-700); font-size: 11.5px; }
.grant-actions { display: flex; justify-content: flex-end; margin-top: 14px; padding-top: 12px; border-top: 1px dashed var(--border); }
.mini-btn.danger { color: var(--err); border-color: rgba(239, 68, 68, .35); }
.mini-btn.danger:hover:not(:disabled) { border-color: var(--err); background: rgba(239, 68, 68, .08); color: var(--err); }
.action-error { margin: 12px 0 0; color: var(--err); font-size: 12px; }
@media (max-width: 640px) {
  .page-header { align-items: stretch; flex-direction: column; }
  .page-header > .mini-btn { align-self: flex-start; }
  .grant-meta { grid-template-columns: 1fr; }
  .grant-actions .mini-btn { width: 100%; justify-content: center; }
}
</style>
