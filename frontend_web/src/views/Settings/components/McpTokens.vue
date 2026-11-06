<template>
  <section id="sec-mcp-tokens" class="card grp" aria-labelledby="mcp-tokens-title">
    <h2 id="mcp-tokens-title">访问令牌</h2>
    <p class="intro">
      令牌以你当前账号的身份访问 TestMate 的集成服务（如 MCP），权限不会超过账号现有能力。令牌可在下方随时查看、复制或删除。
    </p>

    <div class="sub-grp">
      <h3>创建令牌</h3>
      <div class="token-form">
        <label class="field">
          <span>令牌名称 <b>*</b></span>
          <input
            v-model="form.name"
            aria-label="令牌名称"
            type="text"
            maxlength="128"
            placeholder="例如：CI 发布流水线"
            :disabled="creating"
          />
        </label>
        <label class="field">
          <span>过期时间（可选）</span>
          <input v-model="form.expiresAt" aria-label="过期时间（可选）" type="datetime-local" :disabled="creating" />
        </label>
        <fieldset class="scope-field" :disabled="creating">
          <legend>权限 <b>*</b></legend>
          <label><input v-model="form.scopes" type="checkbox" value="extensions:read" :disabled="!canRead" /> 读取资产</label>
          <label><input v-model="form.scopes" type="checkbox" value="extensions:write" :disabled="!canWrite" /> 管理资产</label>
          <label><input v-model="form.scopes" type="checkbox" value="kb:read" :disabled="!canKbRead" /> 读取知识库</label>
          <label><input v-model="form.scopes" type="checkbox" value="kb:write" :disabled="!canKbWrite" /> 写入知识库</label>
        </fieldset>
        <button type="button" class="mini-btn primary create-btn" :disabled="!canCreate" @click="create">
          {{ creating ? '创建中…' : '创建令牌' }}
        </button>
      </div>
      <p v-if="scopesError" class="form-hint" role="alert">{{ scopesError }}</p>
      <p v-if="createError" class="inline-error" role="alert">{{ createError }}</p>
    </div>

    <div class="sub-grp">
      <div class="list-heading">
        <h3>我的令牌 <span>{{ tokens.length }}</span></h3>
        <button type="button" class="mini-btn" :disabled="loading" @click="loadTokens">刷新</button>
      </div>

      <div v-if="loading" class="state" role="status">正在读取访问令牌…</div>
      <div v-else-if="loadError" class="state error" role="alert">
        <strong>令牌列表加载失败</strong>
        <p>{{ loadError }}</p>
        <button type="button" class="mini-btn" @click="loadTokens">重试</button>
      </div>
      <div v-else-if="!tokens.length" class="state">还没有访问令牌</div>
      <ul v-else class="token-list">
        <li v-for="token in tokens" :key="token.id">
          <div class="token-main">
            <div class="token-name">
              <strong>{{ token.name }}</strong>
              <span class="status" :class="statusOf(token).tone">{{ statusOf(token).label }}</span>
            </div>
            <div v-if="token.token" class="token-value-row">
              <code class="token-value">{{ token.token }}</code>
              <button type="button" class="mini-btn" @click="copyToken(token)">
                {{ copiedId === token.id ? '已复制' : '复制' }}
              </button>
            </div>
            <p v-else class="legacy-note">该令牌创建于明文可见功能上线前，无法再次查看。</p>
            <div class="token-scopes">
              <span v-for="scope in token.scopes" :key="scope">{{ scopeText(scope) }}</span>
            </div>
            <dl>
              <div><dt>创建</dt><dd>{{ formatTime(token.created_at) }}</dd></div>
              <div><dt>过期</dt><dd>{{ token.expires_at ? formatTime(token.expires_at) : '永不过期' }}</dd></div>
              <div><dt>最近使用</dt><dd>{{ formatTime(token.last_used_at) }}</dd></div>
            </dl>
          </div>
          <div class="token-actions">
            <button
              type="button"
              class="mini-btn danger"
              :disabled="busyId !== null"
              @click="remove(token)"
            >{{ busyId === token.id ? '删除中…' : '删除' }}</button>
          </div>
        </li>
      </ul>
      <p v-if="actionError" class="inline-error" role="alert">{{ actionError }}</p>
    </div>
  </section>
</template>

<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, reactive, ref } from 'vue';
import { ElMessage, ElMessageBox } from 'element-plus';
import {
  createMcpToken,
  deleteMcpToken,
  listMcpTokenScopes,
  listMcpTokens,
  type CreateMcpTokenPayload,
  type McpScope,
  type McpToken,
} from '@/api/mcp';
import { errorDetail, errorStatus, httpErrorText } from '@/utils/httpError';
import { parseApiTime } from '@/utils/format';
import { copyToClipboard } from '@/utils/clipboard';

const tokens = ref<McpToken[]>([]);
const allowedScopes = ref<McpScope[]>(['extensions:read', 'kb:read']);
const loading = ref(false);
const loadError = ref('');
const scopesError = ref('');
const createError = ref('');
const actionError = ref('');
const creating = ref(false);
const busyId = ref<number | null>(null);
const copiedId = ref<number | null>(null);
let copiedTimer: number | undefined;

const form = reactive<{ name: string; scopes: McpScope[]; expiresAt: string }>({
  name: '',
  scopes: ['extensions:read'],
  expiresAt: '',
});

const canRead = computed(() => allowedScopes.value.includes('extensions:read'));
const canWrite = computed(() => allowedScopes.value.includes('extensions:write'));
const canKbRead = computed(() => allowedScopes.value.includes('kb:read'));
const canKbWrite = computed(() => allowedScopes.value.includes('kb:write'));
const canCreate = computed(() => (
  !creating.value
  && !!form.name.trim()
  && form.scopes.length > 0
  && form.scopes.every((scope) => allowedScopes.value.includes(scope))
));

function errorText(error: unknown, fallback: string): string {
  return httpErrorText(errorStatus(error), errorDetail(error), fallback);
}

const SCOPE_TEXT: Record<McpScope, string> = {
  'extensions:read': '读取资产',
  'extensions:write': '管理资产',
  'kb:read': '读取知识库',
  'kb:write': '写入知识库',
};

function scopeText(scope: McpScope): string {
  return SCOPE_TEXT[scope] ?? scope;
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

function statusOf(token: McpToken): { label: string; tone: string } {
  if (token.revoked_at) return { label: '已撤销', tone: 'off' };
  const expiry = token.expires_at ? parseApiTime(token.expires_at) : null;
  if (expiry && expiry.getTime() <= Date.now()) return { label: '已过期', tone: 'off' };
  return { label: '生效中', tone: 'on' };
}

async function loadScopes() {
  scopesError.value = '';
  try {
    const result = await listMcpTokenScopes();
    allowedScopes.value = result.scopes;
  } catch {
    allowedScopes.value = ['extensions:read', 'kb:read'];
    scopesError.value = '未能读取当前可用权限，暂时只能创建只读令牌。';
  }
  form.scopes = form.scopes.filter((scope) => allowedScopes.value.includes(scope));
  if (!form.scopes.length && allowedScopes.value.length) form.scopes = [allowedScopes.value[0]];
}

async function loadTokens() {
  loading.value = true;
  loadError.value = '';
  try {
    const result = await listMcpTokens();
    tokens.value = result.items;
  } catch (error) {
    loadError.value = errorText(error, '令牌列表加载失败');
  } finally {
    loading.value = false;
  }
}

async function create() {
  if (!canCreate.value) return;
  creating.value = true;
  createError.value = '';
  actionError.value = '';
  try {
    const payload: CreateMcpTokenPayload = {
      name: form.name.trim(),
      scopes: form.scopes,
    };
    if (form.expiresAt) payload.expires_at = new Date(form.expiresAt).toISOString();
    const created = await createMcpToken(payload);
    form.name = '';
    form.expiresAt = '';
    form.scopes = allowedScopes.value.length ? [allowedScopes.value[0]] : [];
    ElMessage.success(`已创建 ${created.name}`);
    await loadTokens();
  } catch (error) {
    createError.value = errorText(error, '创建令牌失败');
  } finally {
    creating.value = false;
  }
}

async function copyToken(token: McpToken) {
  if (!token.token) return;
  // ⚠️ 2026-11-04 (第二十四轮): 用全局 copyToClipboard —— 内网 IP + HTTP
  //    不是安全上下文, navigator.clipboard 是 undefined → 一律失败.
  const ok = await copyToClipboard(token.token);
  if (!ok) {
    ElMessage.error('复制失败，请手动选择令牌文本');
    return;
  }
  copiedId.value = token.id;
  ElMessage.success('令牌已复制');
  window.clearTimeout(copiedTimer);
  copiedTimer = window.setTimeout(() => { copiedId.value = null; }, 2000);
}

async function remove(token: McpToken) {
  if (busyId.value !== null) return;
  busyId.value = token.id;
  actionError.value = '';
  try {
    try {
      await ElMessageBox.confirm(
        `删除后不可恢复，使用「${token.name}」的客户端会立即失去访问权限。确认删除？`,
        '删除访问令牌',
        {
          type: 'warning',
          confirmButtonText: '确认删除',
          cancelButtonText: '取消',
        },
      );
    } catch {
      return;
    }
    if (busyId.value !== token.id) return;

    await deleteMcpToken(token.id);
    ElMessage.success(`已删除 ${token.name}`);
    await loadTokens();
  } catch (error) {
    actionError.value = errorText(error, '删除令牌失败');
  } finally {
    busyId.value = null;
  }
}

onMounted(() => {
  void loadScopes();
  void loadTokens();
});

onBeforeUnmount(() => window.clearTimeout(copiedTimer));
</script>

<style scoped>
.grp h2 { margin: 0; color: var(--ink-900); font-size: 17px; }
.intro { margin: 9px 0 0; padding: 10px 12px; border-radius: 8px; background: var(--surface-sunken); color: var(--ink-500); font-size: 12px; line-height: 1.7; }
.sub-grp { margin-top: 18px; padding-top: 16px; border-top: 1px dashed var(--border); }
.sub-grp h3 { margin: 0 0 12px; color: var(--ink-700); font-size: 13px; }
.token-form { display: grid; grid-template-columns: minmax(180px, 1.2fr) minmax(170px, 1fr); gap: 13px; align-items: end; }
.field { display: flex; min-width: 0; flex-direction: column; gap: 6px; color: var(--ink-700); font-size: 12px; }
.field b, .scope-field b { color: var(--err); font-weight: 500; }
.field input { width: 100%; min-height: 36px; padding: 7px 10px; border: 1px solid var(--border); border-radius: 7px; background: var(--surface); color: var(--ink-900); font: inherit; }
.field input:focus { outline: none; border-color: var(--primary); box-shadow: 0 0 0 3px var(--primary-soft); }
.scope-field { display: flex; grid-column: 1 / -1; gap: 16px; margin: 0; padding: 0; border: 0; color: var(--ink-700); font-size: 12px; }
.scope-field legend { margin-bottom: 6px; }
.scope-field label { display: inline-flex; align-items: center; gap: 6px; cursor: pointer; }
.scope-field label:has(input:disabled) { cursor: not-allowed; color: var(--ink-500); }
.scope-field input { accent-color: var(--primary); }
.create-btn { grid-column: 1 / -1; justify-self: end; justify-content: center; min-height: 36px; }
.form-hint { margin: 9px 0 0; color: var(--warn); font-size: 11.5px; }
.inline-error { display: flex; align-items: center; gap: 10px; flex-wrap: wrap; margin: 10px 0; padding: 9px 11px; border: 1px solid rgba(239, 68, 68, .25); border-radius: 8px; background: rgba(239, 68, 68, .06); color: var(--err); font-size: 12px; }
.list-heading { display: flex; align-items: center; justify-content: space-between; gap: 12px; }
.list-heading h3 { display: flex; align-items: center; gap: 7px; }
.list-heading h3 span { padding: 1px 7px; border-radius: var(--radius-pill); background: var(--surface-sunken); color: var(--ink-500); font-size: 10.5px; }
.state { padding: 24px 16px; border: 1px dashed var(--border); border-radius: 8px; background: var(--surface-sunken); color: var(--ink-500); text-align: center; font-size: 12px; }
.state.error { color: var(--err); border-color: rgba(239, 68, 68, .35); }
.state p { margin: 5px 0 12px; }
.token-list { display: flex; flex-direction: column; gap: 9px; margin: 0; padding: 0; list-style: none; }
.token-list > li { display: flex; align-items: flex-start; gap: 14px; padding: 13px; border: 1px solid var(--border); border-radius: 8px; background: var(--surface-soft); }
.token-main { min-width: 0; flex: 1; }
.token-name { display: flex; align-items: center; gap: 8px; flex-wrap: wrap; }
.token-name strong { color: var(--ink-900); }
.status { padding: 1px 8px; border-radius: var(--radius-pill); font-size: 10.5px; }
.status.on { background: rgba(16, 185, 129, .12); color: var(--ok); }
.status.off { background: var(--surface-sunken); color: var(--ink-500); }
.token-value-row { display: flex; align-items: center; gap: 8px; margin-top: 9px; }
.token-value { min-width: 0; flex: 1; padding: 7px 9px; border: 1px solid var(--border); border-radius: 6px; background: var(--surface); color: var(--ink-900); font-family: var(--font-mono); font-size: 11px; white-space: pre-wrap; word-break: break-all; user-select: all; }
.legacy-note { margin: 9px 0 0; color: var(--ink-500); font-size: 11.5px; }
.token-scopes { display: flex; gap: 6px; margin-top: 8px; }
.token-scopes span { padding: 2px 7px; border-radius: 5px; background: var(--primary-soft); color: var(--ink-700); font-size: 10.5px; }
.token-main dl { display: flex; gap: 18px; flex-wrap: wrap; margin: 10px 0 0; }
.token-main dl div { display: flex; gap: 5px; font-size: 10.5px; }
.token-main dt { color: var(--ink-500); }
.token-main dd { margin: 0; color: var(--ink-700); }
.token-actions { flex: 0 0 auto; }
.mini-btn.danger { color: var(--err); border-color: rgba(239, 68, 68, .35); }
.mini-btn.danger:hover:not(:disabled) { border-color: var(--err); background: rgba(239, 68, 68, .08); color: var(--err); }
@media (max-width: 820px) {
  .token-form { grid-template-columns: 1fr; }
  .scope-field { grid-column: auto; }
  .create-btn { justify-self: stretch; }
}
@media (max-width: 520px) {
  .token-list > li { flex-direction: column; }
  .token-actions, .token-actions .mini-btn { width: 100%; }
  .token-actions .mini-btn { justify-content: center; }
  .token-value-row { align-items: stretch; flex-direction: column; }
}
</style>
