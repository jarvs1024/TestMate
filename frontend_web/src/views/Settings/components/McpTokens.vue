<template>
  <section id="sec-mcp-tokens" class="card grp" aria-labelledby="mcp-tokens-title">
    <h2 id="mcp-tokens-title">访问令牌</h2>
    <p class="intro">
      令牌以你当前账号的身份访问 TestMate 的集成服务（如内置 MCP），权限不会超过账号现有能力。
      权限按系统区分：TestMate 平台能力、PingCode、PLM；勾上哪些权限，令牌就只能做哪些事。
      令牌可在下方随时查看、复制或删除。
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
          <legend>
            <span>权限 <b>*</b></span>
            <!-- 全选: 只勾当前账号可用的权限, 无权项仍置灰 -->
            <label v-if="allowedScopes.length > 1" class="scope-all">
              <input
                type="checkbox"
                data-test="scope-all"
                :checked="allScopesSelected"
                :indeterminate.prop="partiallySelected"
                @change="toggleAll"
              /> 全选
            </label>
          </legend>
          <div v-for="system in SCOPE_SYSTEMS" :key="system.code" class="scope-group">
            <div class="scope-system-head">
              <b>{{ system.label }}</b>
              <span>{{ system.hint }}</span>
            </div>
            <div v-if="scopesOfSystem(system.code).length" class="scope-options">
              <label v-for="scope in scopesOfSystem(system.code)" :key="scope">
                <input
                  v-model="form.scopes"
                  type="checkbox"
                  :value="scope"
                  :disabled="!allowedScopes.includes(scope)"
                /> {{ scopeLabel(scope) }}
              </label>
            </div>
            <p v-else class="scope-empty">接入后开放，当前令牌暂不包含该系统的权限。</p>
          </div>
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
              <div class="token-field">
                <code class="token-value">{{ visibleToken(token) }}</code>
                <button
                  type="button"
                  class="eye"
                  :aria-label="isRevealed(token.id) ? '隐藏令牌' : '显示完整令牌'"
                  :title="isRevealed(token.id) ? '隐藏令牌' : '显示完整令牌'"
                  @click="toggleReveal(token.id)"
                >{{ isRevealed(token.id) ? '🙈' : '👁' }}</button>
              </div>
              <button type="button" class="mini-btn" @click="copyToken(token)">
                {{ copiedId === token.id ? '已复制' : '复制' }}
              </button>
            </div>
            <p v-else class="legacy-note">该令牌创建于明文可见功能上线前，无法再次查看。</p>
            <div
              v-for="group in groupScopes(token.scopes)"
              :key="group.system.code"
              class="token-scopes"
            >
              <span class="scope-system">{{ group.system.label }}</span>
              <span v-for="scope in group.scopes" :key="scope">{{ scopeLabel(scope) }}</span>
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
import {
  SCOPE_SYSTEMS,
  groupScopes,
  scopeMeta,
  scopesOfSystem,
} from '@/utils/mcpScopes';

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
const revealedIds = ref<number[]>([]);
let copiedTimer: number | undefined;

const form = reactive<{ name: string; scopes: McpScope[]; expiresAt: string }>({
  name: '',
  scopes: ['extensions:read'],
  expiresAt: '',
});

const allScopesSelected = computed(() => (
  allowedScopes.value.length > 0
  && allowedScopes.value.every((scope) => form.scopes.includes(scope))
));

const partiallySelected = computed(() => (
  !allScopesSelected.value
  && form.scopes.some((scope) => allowedScopes.value.includes(scope))
));

function toggleAll() {
  form.scopes = allScopesSelected.value
    ? form.scopes.filter((scope) => !allowedScopes.value.includes(scope))
    : Array.from(new Set([...form.scopes, ...allowedScopes.value]));
}

const canCreate = computed(() => (
  !creating.value
  && !!form.name.trim()
  && form.scopes.length > 0
  && form.scopes.every((scope) => allowedScopes.value.includes(scope))
));

function errorText(error: unknown, fallback: string): string {
  return httpErrorText(errorStatus(error), errorDetail(error), fallback);
}

function scopeLabel(scope: McpScope): string {
  return scopeMeta(scope).label;
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

// 与设置页 secret 的 _mask 规则一致: 前 4 位 + 圆点 + 后 4 位
function maskToken(value: string): string {
  if (value.length <= 8) return '••••';
  return value.slice(0, 4) + '•'.repeat(Math.max(4, value.length - 8)) + value.slice(-4);
}

function isRevealed(id: number): boolean {
  return revealedIds.value.includes(id);
}

function toggleReveal(id: number) {
  revealedIds.value = isRevealed(id)
    ? revealedIds.value.filter((item) => item !== id)
    : [...revealedIds.value, id];
}

function visibleToken(token: McpToken): string {
  const value = token.token ?? '';
  return isRevealed(token.id) ? value : maskToken(value);
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
.scope-field { display: flex; flex-direction: column; grid-column: 1 / -1; gap: 10px; margin: 0; padding: 0; border: 0; color: var(--ink-700); font-size: 12px; }
.scope-field legend { display: flex; align-items: center; gap: 10px; width: 100%; margin-bottom: 6px; }
.scope-all { margin-left: auto; display: inline-flex; align-items: center; gap: 5px; color: var(--ink-500); font-size: 11.5px; cursor: pointer; }
.scope-all input { accent-color: var(--primary); }
.scope-group { display: flex; flex-direction: column; gap: 6px; padding: 9px 11px; border: 1px solid var(--border); border-radius: 8px; background: var(--surface-soft); }
.scope-system-head { display: flex; align-items: baseline; gap: 8px; }
.scope-system-head b { color: var(--ink-900); font-size: 12px; }
.scope-system-head span { color: var(--ink-500); font-size: 10.5px; }
.scope-options { display: flex; gap: 18px; flex-wrap: wrap; }
.scope-options label { display: inline-flex; align-items: center; gap: 6px; cursor: pointer; }
.scope-options label:has(input:disabled) { cursor: not-allowed; color: var(--ink-500); }
.scope-options input { accent-color: var(--primary); }
.scope-empty { margin: 0; color: var(--ink-500); font-size: 11px; }
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
.token-field { position: relative; min-width: 0; flex: 1; }
.token-value { display: block; padding: 7px 36px 7px 9px; border: 1px solid var(--border); border-radius: 6px; background: var(--surface); color: var(--ink-900); font-family: var(--font-mono); font-size: 11px; white-space: pre-wrap; word-break: break-all; user-select: all; }
.eye {
  position: absolute; right: 4px; top: 50%; transform: translateY(-50%);
  padding: 2px 6px; border: 0; background: transparent; color: var(--ink-500);
  font-size: 13px; line-height: 1; cursor: pointer;
}
.eye:hover { color: var(--ink-900); }
.legacy-note { margin: 9px 0 0; color: var(--ink-500); font-size: 11.5px; }
.token-scopes { display: flex; align-items: center; gap: 6px; flex-wrap: wrap; margin-top: 8px; }
.token-scopes span { padding: 2px 7px; border-radius: 5px; background: var(--primary-soft); color: var(--ink-700); font-size: 10.5px; }
.token-scopes .scope-system { background: var(--surface-sunken); color: var(--ink-500); font-family: var(--font-mono); }
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
