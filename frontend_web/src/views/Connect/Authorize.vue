<template>
  <div class="connect-page">
    <section class="card consent-card" aria-labelledby="consent-title">
      <header class="consent-header">
        <p class="eyebrow">MCP 连接授权</p>
        <h1 id="consent-title">确认客户端访问权限</h1>
        <p class="lede">核对客户端与权限边界。只有你勾选的能力会授予这次连接。</p>
      </header>

      <div v-if="loading" class="state" role="status">正在验证授权请求…</div>
      <div v-else-if="loadError" class="state error" role="alert">
        <strong>授权请求验证失败</strong>
        <p>{{ loadError }}</p>
        <button type="button" class="mini-btn" @click="loadPreview">重试</button>
      </div>

      <template v-else-if="preview">
        <div class="boundary" aria-label="客户端与权限边界">
          <div class="client-block">
            <span class="boundary-label">请求访问的客户端</span>
            <strong class="client-name">{{ preview.client_name }}</strong>
            <code>{{ preview.client_id }}</code>
            <span class="redirect">回调至 {{ preview.redirect_uri }}</span>
          </div>
          <div class="boundary-arrow" aria-hidden="true">→</div>
          <div class="permission-intro">
            <span class="boundary-label">将获得你选择的权限</span>
            <strong>以你的 TestMate 身份访问</strong>
            <span>可随时在「个人中心 · 授权管理」中撤销</span>
          </div>
        </div>

        <fieldset class="scope-list" :disabled="submitting">
          <legend>选择授予的权限</legend>
          <label v-for="scope in preview.scopes" :key="scope" class="scope-item">
            <input v-model="selectedScopes" type="checkbox" :value="scope" />
            <span class="scope-copy">
              <span class="scope-title">
                <strong>{{ scopeText(scope).title }}</strong>
                <code>{{ scope }}</code>
              </span>
              <span class="scope-description">{{ scopeText(scope).description }}</span>
            </span>
          </label>
        </fieldset>

        <p v-if="preview && !selectedScopes.length" class="selection-hint">至少选择一项权限才能同意授权。</p>
        <p v-if="actionError" class="action-error" role="alert">{{ actionError }}</p>
      </template>

      <div class="actions">
        <button
          type="button"
          class="mini-btn"
          :disabled="!preview || loading || submitting"
          @click="deny"
        >拒绝</button>
        <button
          type="button"
          class="mini-btn primary"
          :disabled="!preview || loading || submitting || !selectedScopes.length"
          @click="approve"
        >{{ submitting ? '正在授权…' : '同意授权' }}</button>
      </div>
    </section>
  </div>
</template>

<script setup lang="ts">
import { ref, watch } from 'vue';
import { useRoute } from 'vue-router';
import {
  authorizeMcp,
  previewMcpAuthorization,
  type McpAuthorizationPreview,
  type McpAuthorizationQuery,
  type McpScope,
} from '@/api/mcp';
import { errorDetail, errorStatus, httpErrorText } from '@/utils/httpError';

const route = useRoute();
const preview = ref<McpAuthorizationPreview | null>(null);
const selectedScopes = ref<McpScope[]>([]);
const loading = ref(false);
const submitting = ref(false);
const loadError = ref('');
const actionError = ref('');
let previewRequestSequence = 0;

function queryText(value: unknown): string {
  return typeof value === 'string' ? value : '';
}

function authorizationQuery(): McpAuthorizationQuery {
  const query: McpAuthorizationQuery = {
    client_id: queryText(route.query.client_id),
    redirect_uri: queryText(route.query.redirect_uri),
    response_type: queryText(route.query.response_type),
    scope: queryText(route.query.scope),
    code_challenge: queryText(route.query.code_challenge),
    code_challenge_method: queryText(route.query.code_challenge_method),
  };
  if (typeof route.query.state === 'string') query.state = route.query.state;
  return query;
}

function errorText(error: unknown, fallback: string): string {
  const detail = errorDetail(error);
  if (detail && typeof detail === 'object') {
    const description = (detail as { error_description?: unknown }).error_description;
    if (typeof description === 'string' && description) return description;
  }
  return httpErrorText(errorStatus(error), detail, fallback);
}

function scopeText(scope: McpScope): { title: string; description: string } {
  if (scope === 'market:write') {
    return {
      title: '管理资产',
      description: '以你的名义新建、修改、发布或下架你有权操作的插件、技能和连接器。',
    };
  }
  return {
    title: '读取资产',
    description: '查看插件、技能、连接器及其版本信息，并读取你本可访问的内容。',
  };
}

async function loadPreview() {
  const requestSequence = ++previewRequestSequence;
  const query = authorizationQuery();
  loading.value = true;
  submitting.value = false;
  loadError.value = '';
  actionError.value = '';
  preview.value = null;
  selectedScopes.value = [];
  try {
    const result = await previewMcpAuthorization(query);
    if (requestSequence !== previewRequestSequence) return;
    preview.value = result;
    selectedScopes.value = [...result.scopes];
  } catch (error) {
    if (requestSequence !== previewRequestSequence) return;
    loadError.value = errorText(error, '无法验证授权请求');
  } finally {
    if (requestSequence === previewRequestSequence) loading.value = false;
  }
}

async function approve() {
  const current = preview.value;
  if (!current || submitting.value || !selectedScopes.value.length) return;
  const requestSequence = previewRequestSequence;
  submitting.value = true;
  actionError.value = '';
  try {
    const result = await authorizeMcp({
      client_id: current.client_id,
      redirect_uri: current.redirect_uri,
      scopes: [...selectedScopes.value],
      response_type: current.response_type,
      code_challenge: current.code_challenge,
      code_challenge_method: current.code_challenge_method,
      state: current.state,
    });
    if (requestSequence !== previewRequestSequence) return;
    // callback_url 是客户端地址，不能用 Axios 请求，也不能走站内路由。
    window.location.assign(result.callback_url);
  } catch (error) {
    if (requestSequence !== previewRequestSequence) return;
    actionError.value = errorText(error, '授权失败，请重试');
  } finally {
    if (requestSequence === previewRequestSequence) submitting.value = false;
  }
}

function deny() {
  const current = preview.value;
  if (!current || submitting.value) return;
  const target = new URL(current.redirect_uri);
  target.searchParams.set('error', 'access_denied');
  if (current.state !== null && current.state !== undefined) {
    target.searchParams.set('state', current.state);
  }
  window.location.assign(target.toString());
}

watch(() => route.query, () => {
  void loadPreview();
}, { immediate: true });
</script>

<style scoped>
.connect-page {
  width: min(880px, 100%);
  margin: 0 auto;
  padding: 12px 4px 40px;
}
.consent-card { padding: clamp(20px, 4vw, 34px); }
.consent-header { margin-bottom: 24px; }
.eyebrow {
  margin: 0 0 5px;
  color: var(--primary);
  font-family: var(--font-mono);
  font-size: 11px;
  font-weight: 700;
  letter-spacing: .08em;
  text-transform: uppercase;
}
h1 { margin: 0; color: var(--ink-900); font-size: clamp(22px, 4vw, 28px); line-height: 1.25; }
.lede { margin: 8px 0 0; color: var(--ink-500); font-size: 13px; }
.state {
  padding: 24px;
  border: 1px dashed var(--border);
  border-radius: var(--radius-sm);
  background: var(--surface-sunken);
  color: var(--ink-500);
  text-align: center;
}
.state.error { color: var(--err); border-color: rgba(239, 68, 68, .35); }
.state.error p { margin: 6px 0 14px; }
.boundary {
  display: grid;
  grid-template-columns: minmax(0, 1fr) auto minmax(0, 1fr);
  gap: 18px;
  align-items: stretch;
  margin-bottom: 22px;
}
.client-block, .permission-intro {
  display: flex;
  min-width: 0;
  flex-direction: column;
  gap: 5px;
  padding: 16px;
  border: 1px solid var(--border);
  border-radius: var(--radius-sm);
  background: var(--surface-soft);
}
.permission-intro { background: var(--primary-grad-soft); }
.boundary-label { color: var(--ink-500); font-size: 11px; }
.client-name, .permission-intro strong { color: var(--ink-900); font-size: 16px; }
.client-block code, .scope-title code { font-family: var(--font-mono); font-size: 11px; color: var(--primary); }
.redirect, .permission-intro span:last-child {
  overflow-wrap: anywhere;
  color: var(--ink-500);
  font-size: 11px;
}
.boundary-arrow { align-self: center; color: var(--primary); font-size: 22px; }
.scope-list { display: flex; flex-direction: column; gap: 9px; margin: 0; padding: 0; border: 0; }
.scope-list legend { margin-bottom: 10px; color: var(--ink-900); font-size: 14px; font-weight: 700; }
.scope-item {
  display: flex;
  align-items: flex-start;
  gap: 12px;
  padding: 13px 14px;
  border: 1px solid var(--border);
  border-radius: var(--radius-sm);
  background: var(--surface-soft);
  cursor: pointer;
}
.scope-item:focus-within { border-color: var(--primary); box-shadow: 0 0 0 3px var(--primary-soft); }
.scope-item input { width: 17px; height: 17px; margin: 2px 0 0; accent-color: var(--primary); flex: 0 0 auto; }
.scope-copy { display: flex; min-width: 0; flex-direction: column; gap: 4px; }
.scope-title { display: flex; align-items: center; gap: 9px; flex-wrap: wrap; color: var(--ink-900); }
.scope-description { color: var(--ink-500); font-size: 12px; line-height: 1.6; }
.selection-hint, .action-error { margin: 10px 0 0; font-size: 12px; }
.selection-hint { color: var(--warn); }
.action-error { color: var(--err); }
.actions { display: flex; justify-content: flex-end; gap: 10px; margin-top: 24px; padding-top: 18px; border-top: 1px solid var(--border); }
.actions .mini-btn { min-width: 92px; justify-content: center; padding: 9px 18px; }
@media (max-width: 640px) {
  .boundary { grid-template-columns: 1fr; gap: 8px; }
  .boundary-arrow { justify-self: center; transform: rotate(90deg); }
  .actions { flex-direction: column-reverse; }
  .actions .mini-btn { width: 100%; }
}
</style>
