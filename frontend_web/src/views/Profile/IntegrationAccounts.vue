<template>
  <section class="card ext-accounts" aria-labelledby="ext-accounts-title">
    <header class="ext-head">
      <div>
        <h2 id="ext-accounts-title">平台认证</h2>
        <p class="intro">
          配置一次公司内部平台账号，TestMate 会代你登录并在过期前自动续期，内置 MCP 工具直接复用，不用每次输入密码。
          密码经 RSA 加密传输、AES-256-GCM 加密落库，页面不回显。
        </p>
      </div>
      <span class="secure-badge">传输与存储均加密</span>
    </header>

    <div v-if="loading" class="state" role="status">正在读取平台认证配置…</div>
    <div v-else-if="loadError" class="state error" role="alert">
      <strong>配置加载失败</strong>
      <p>{{ loadError }}</p>
      <button type="button" class="mini-btn" @click="load">重试</button>
    </div>

    <div v-else class="provider-grid">
      <article
        v-for="provider in providers"
        :key="provider.code"
        class="provider-card"
        :class="{ locked: !provider.enabled, bound: provider.bound }"
      >
        <header class="pc-head">
          <span class="pc-mark" :class="provider.code">{{ provider.name.slice(0, 2).toUpperCase() }}</span>
          <div class="pc-title">
            <h3>{{ provider.name }}</h3>
            <p>{{ hintOf(provider) }}</p>
          </div>
          <span class="pc-status" :class="statusOf(provider).tone">{{ statusOf(provider).label }}</span>
        </header>

        <dl v-if="provider.bound" class="pc-meta">
          <div><dt>账号</dt><dd>{{ provider.username }}</dd></div>
          <div><dt>最近登录</dt><dd>{{ formatTime(provider.last_login_at) }}</dd></div>
        </dl>
        <p v-if="provider.bound && provider.last_error" class="pc-warning" role="status">
          {{ provider.last_error }}
        </p>

        <p v-if="!provider.enabled" class="pc-offline">
          PLM 尚未接入。开放后沿用这里的账号/凭据与令牌框架，无需再配一套。
        </p>

        <form class="pc-form" @submit.prevent="save(provider)">
          <label class="field">
            <span>账号</span>
            <input
              v-model="formOf(provider).username"
              :aria-label="`${provider.name} 账号`"
              type="text"
              autocomplete="username"
              placeholder="登录账号"
              :disabled="!provider.enabled || isBusy(provider)"
            />
          </label>
          <label class="field">
            <span>密码</span>
            <input
              v-model="formOf(provider).password"
              :aria-label="`${provider.name} 密码`"
              type="password"
              autocomplete="new-password"
              placeholder="登录密码"
              :disabled="!provider.enabled || isBusy(provider)"
            />
          </label>

          <div class="pc-actions">
            <button
              type="submit"
              class="mini-btn primary"
              :aria-label="`${provider.name} 保存并验证`"
              :disabled="!provider.enabled || isBusy(provider)"
            >{{ busyLabel(provider, 'save', '保存并验证') }}</button>
            <button
              v-if="provider.bound"
              type="button"
              class="mini-btn"
              :disabled="!provider.enabled || isBusy(provider)"
              @click="test(provider)"
            >{{ busyLabel(provider, 'test', '测试连接') }}</button>
            <button
              v-if="provider.bound"
              type="button"
              class="mini-btn danger-ghost"
              :disabled="!provider.enabled || isBusy(provider)"
              @click="unbind(provider)"
            >{{ busyLabel(provider, 'remove', '解除绑定') }}</button>
          </div>

          <p v-if="notices[provider.code]" class="pc-notice" :class="notices[provider.code]?.tone" role="status">
            {{ notices[provider.code]?.text }}
          </p>
        </form>
      </article>
    </div>
  </section>
</template>

<script setup lang="ts">
import { onMounted, reactive, ref } from 'vue';
import { ElMessageBox } from 'element-plus';
import {
  deleteIntegrationCredentials,
  getIntegrationPublicKey,
  listIntegrationProviders,
  saveIntegrationCredentials,
  testIntegrationConnection,
  type IntegrationProvider,
} from '@/api/integrations';
import { encryptForTransport } from '@/utils/rsaTransport';
import { errorDetail, errorStatus, httpErrorText } from '@/utils/httpError';
import { parseApiTime } from '@/utils/format';

interface ProviderForm {
  username: string;
  password: string;
}

type Notice = { tone: 'ok' | 'error'; text: string };

const providers = ref<IntegrationProvider[]>([]);
const loading = ref(false);
const loadError = ref('');
const busy = ref<string | null>(null);
const notices = reactive<Record<string, Notice | undefined>>({});
const forms = reactive<Record<string, ProviderForm>>({});
let publicKeyPromise: Promise<string> | null = null;

function formOf(provider: IntegrationProvider): ProviderForm {
  if (!forms[provider.code]) {
    forms[provider.code] = { username: provider.username ?? '', password: '' };
  }
  return forms[provider.code];
}

function isBusy(provider: IntegrationProvider): boolean {
  return busy.value?.startsWith(`${provider.code}:`) ?? false;
}

function busyLabel(provider: IntegrationProvider, action: string, idle: string): string {
  if (busy.value === `${provider.code}:${action}`) {
    return action === 'save' ? '验证中…' : action === 'test' ? '测试中…' : '解除中…';
  }
  return idle;
}

function hintOf(provider: IntegrationProvider): string {
  if (!provider.enabled) return '统一凭据框架，接入后开放。';
  return provider.bound ? '已绑定账号，MCP 工具会复用登录态。' : '配置后即可在 MCP 中读写缺陷与需求。';
}

function statusOf(provider: IntegrationProvider): { label: string; tone: string } {
  if (!provider.enabled) return { label: '建设中', tone: 'off' };
  if (!provider.bound) return { label: '未配置', tone: 'idle' };
  if (provider.status === 'reauth_required') return { label: '需重新登录', tone: 'warn' };
  return { label: '已连接', tone: 'on' };
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

function errorText(error: unknown, fallback: string): string {
  return httpErrorText(errorStatus(error), errorDetail(error), fallback);
}

function replaceProvider(updated: IntegrationProvider) {
  const index = providers.value.findIndex((item) => item.code === updated.code);
  if (index >= 0) providers.value.splice(index, 1, updated);
}

async function load() {
  loading.value = true;
  loadError.value = '';
  try {
    const result = await listIntegrationProviders();
    providers.value = result.items;
    for (const provider of result.items) {
      const form = formOf(provider);
      form.username = provider.username ?? '';
      form.password = '';
    }
  } catch (error) {
    loadError.value = errorText(error, '平台认证配置加载失败');
  } finally {
    loading.value = false;
  }
}

async function transportKey(): Promise<string> {
  if (!publicKeyPromise) {
    publicKeyPromise = getIntegrationPublicKey()
      .then((result) => result.public_key)
      .catch((error) => {
        publicKeyPromise = null;
        throw error;
      });
  }
  return publicKeyPromise;
}

async function save(provider: IntegrationProvider) {
  if (!provider.enabled || isBusy(provider)) return;
  const form = formOf(provider);
  const username = form.username.trim();
  delete notices[provider.code];
  if (!username || !form.password) {
    notices[provider.code] = { tone: 'error', text: '账号和密码都要填。' };
    return;
  }
  busy.value = `${provider.code}:save`;
  try {
    const pem = await transportKey();
    const encrypted = await encryptForTransport(
      JSON.stringify({ username, password: form.password }),
      pem,
    );
    const updated = await saveIntegrationCredentials(provider.code, encrypted);
    form.password = '';
    form.username = updated.username ?? username;
    replaceProvider(updated);
    notices[provider.code] = { tone: 'ok', text: `已连接：${updated.username ?? username}` };
  } catch (error) {
    notices[provider.code] = { tone: 'error', text: errorText(error, '保存失败，请稍后重试') };
  } finally {
    busy.value = null;
  }
}

async function test(provider: IntegrationProvider) {
  if (!provider.enabled || isBusy(provider)) return;
  busy.value = `${provider.code}:test`;
  delete notices[provider.code];
  try {
    const result = await testIntegrationConnection(provider.code);
    notices[provider.code] = {
      tone: 'ok',
      text: `连接正常：${result.display_name}（${result.team_name}）`,
    };
  } catch (error) {
    notices[provider.code] = { tone: 'error', text: errorText(error, '连接测试失败') };
  } finally {
    busy.value = null;
  }
}

async function unbind(provider: IntegrationProvider) {
  if (!provider.enabled || isBusy(provider)) return;
  try {
    await ElMessageBox.confirm(
      `解除后，${provider.name} 的登录态会被清除，正在使用该账号的 MCP 工具将立即不可用。确认解除？`,
      '解除平台认证绑定',
      { type: 'warning', confirmButtonText: '确认解除', cancelButtonText: '取消' },
    );
  } catch {
    return;
  }
  busy.value = `${provider.code}:remove`;
  delete notices[provider.code];
  try {
    await deleteIntegrationCredentials(provider.code);
    await load();
  } catch (error) {
    notices[provider.code] = { tone: 'error', text: errorText(error, '解除绑定失败') };
  } finally {
    busy.value = null;
  }
}

onMounted(load);
</script>

<style scoped>
.ext-head { display: flex; align-items: flex-start; justify-content: space-between; gap: 16px; }
.ext-head h2 { margin: 0; color: var(--ink-900); font-size: 17px; }
.intro { max-width: 720px; margin: 9px 0 0; padding: 10px 12px; border-radius: 8px; background: var(--surface-sunken); color: var(--ink-500); font-size: 12px; line-height: 1.7; }
.secure-badge { flex: 0 0 auto; padding: 4px 10px; border: 1px solid rgba(16, 185, 129, .28); border-radius: var(--radius-pill); background: rgba(16, 185, 129, .08); color: var(--ok); font-size: 11px; }
.state { margin-top: 16px; padding: 24px 16px; border: 1px dashed var(--border); border-radius: 8px; background: var(--surface-sunken); color: var(--ink-500); text-align: center; font-size: 12px; }
.state.error { color: var(--err); border-color: rgba(239, 68, 68, .35); }
.state p { margin: 5px 0 12px; }
.provider-grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(320px, 1fr)); gap: 14px; margin-top: 16px; }
.provider-card { display: flex; flex-direction: column; gap: 12px; padding: 16px; border: 1px solid var(--border); border-radius: 10px; background: var(--surface-soft); }
.provider-card.bound { border-color: rgba(16, 185, 129, .28); }
.provider-card.locked { background: var(--surface-sunken); }
.pc-head { display: flex; align-items: flex-start; gap: 11px; }
.pc-mark { display: inline-flex; align-items: center; justify-content: center; width: 34px; height: 34px; flex: 0 0 34px; border-radius: 9px; background: var(--primary-soft); color: var(--primary-ink, var(--ink-900)); font-family: var(--font-mono); font-size: 12px; font-weight: 700; letter-spacing: .4px; }
.pc-mark.pingcode { background: rgba(59, 130, 246, .14); color: var(--primary); }
.pc-mark.plm { background: var(--surface-sunken); color: var(--ink-500); }
.pc-title { min-width: 0; flex: 1; }
.pc-title h3 { margin: 0; color: var(--ink-900); font-size: 14px; }
.pc-title p { margin: 3px 0 0; color: var(--ink-500); font-size: 11.5px; line-height: 1.6; }
.pc-status { flex: 0 0 auto; padding: 2px 8px; border-radius: var(--radius-pill); font-size: 10.5px; }
.pc-status.on { background: rgba(16, 185, 129, .12); color: var(--ok); }
.pc-status.warn { background: rgba(245, 158, 11, .14); color: var(--warn); }
.pc-status.idle { background: var(--surface-sunken); color: var(--ink-500); }
.pc-status.off { background: var(--surface-sunken); color: var(--ink-400, var(--ink-500)); }
.pc-meta { display: flex; gap: 18px; flex-wrap: wrap; margin: 0; padding: 9px 11px; border-radius: 8px; background: var(--surface); }
.pc-meta div { display: flex; gap: 5px; font-size: 11px; }
.pc-meta dt { color: var(--ink-500); }
.pc-meta dd { margin: 0; color: var(--ink-700); font-family: var(--font-mono); }
.pc-warning { margin: 0; padding: 8px 10px; border-radius: 7px; background: rgba(245, 158, 11, .1); color: var(--warn); font-size: 11.5px; line-height: 1.6; }
.pc-offline { margin: 0; padding: 10px 11px; border: 1px dashed var(--border); border-radius: 8px; color: var(--ink-500); font-size: 11.5px; line-height: 1.7; }
.pc-form { display: flex; flex-direction: column; gap: 11px; }
.field { display: flex; flex-direction: column; gap: 6px; color: var(--ink-700); font-size: 12px; }
.field input { width: 100%; min-height: 36px; padding: 7px 10px; border: 1px solid var(--border); border-radius: 7px; background: var(--surface); color: var(--ink-900); font: inherit; }
.field input:focus { outline: none; border-color: var(--primary); box-shadow: 0 0 0 3px var(--primary-soft); }
.field input:disabled { background: var(--surface-sunken); color: var(--ink-500); }
.pc-actions { display: flex; gap: 8px; flex-wrap: wrap; }
.pc-notice { margin: 0; padding: 8px 10px; border-radius: 7px; font-size: 11.5px; line-height: 1.6; }
.pc-notice.ok { background: rgba(16, 185, 129, .09); color: var(--ok); }
.pc-notice.error { background: rgba(239, 68, 68, .07); color: var(--err); border: 1px solid rgba(239, 68, 68, .2); }
@media (max-width: 640px) {
  .ext-head { flex-direction: column; }
  .provider-grid { grid-template-columns: 1fr; }
}
</style>
