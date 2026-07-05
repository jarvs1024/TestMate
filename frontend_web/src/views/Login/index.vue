<template>
  <div class="login">
    <div class="container">
      <div class="box">
        <div class="brand">
          <BrandLogo :size="44" />
          <div class="b-txt">
            <div class="t1">TestMate</div>
            <div class="t2">智能测试辅助平台</div>
          </div>
        </div>

        <h1 class="title">登录到工作台</h1>
        <p class="lede">使用你的内网账号继续,首次登录请联系管理员开通</p>

        <form @submit.prevent="onSubmit">
          <div class="field">
            <label>用户名 <span class="req">*</span></label>
            <input v-model="form.username" type="text" placeholder="admin" autocomplete="username" />
          </div>
          <div class="field">
            <label>密码 <span class="req">*</span></label>
            <input v-model="form.password" type="password" placeholder="••••••••" autocomplete="current-password" />
          </div>

          <button class="primary" :disabled="loading">
            <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round">
              <path d="M15 3h4a2 2 0 0 1 2 2v14a2 2 0 0 1-2 2h-4"/><polyline points="10 17 15 12 10 7"/><line x1="15" y1="12" x2="3" y2="12"/>
            </svg>
            <span>{{ loading ? '登录中…' : '登录' }}</span>
          </button>

          <div v-if="error" class="err">{{ error }}</div>
        </form>
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
import BrandLogo from '@/components/BrandLogo.vue';
import { reactive, ref } from 'vue';
import { useRouter, useRoute } from 'vue-router';
import { useUserStore } from '@/stores/user';

const router = useRouter();
const route = useRoute();
const userStore = useUserStore();

const form = reactive({ username: 'admin', password: 'Admin@2026' });
const loading = ref(false);
const error = ref('');

async function onSubmit() {
  loading.value = true;
  error.value = '';
  try {
    await userStore.login(form.username, form.password);
    const redirect = (route.query.redirect as string) || '/';
    router.push(redirect);
  } catch (e: any) {
    error.value = e.response?.data?.detail || '登录失败,请检查账号密码';
  } finally {
    loading.value = false;
  }
}
</script>

<style scoped>
.login { min-height: 100vh; display: flex; align-items: center; justify-content: center; padding: 24px; }
.container { max-width: 980px; width: 100%; display: flex; justify-content: center; }
.box {
  width: 100%; max-width: 420px;
  background: var(--surface-soft);
  backdrop-filter: blur(8px);
  -webkit-backdrop-filter: blur(8px);
  border: 1px solid var(--border);
  border-radius: var(--radius-card);
  box-shadow: var(--shadow-md);
  padding: 32px;
}
.brand { display: flex; align-items: center; gap: 12px; margin-bottom: 28px; }

.t1 { font-size: 17px; font-weight: 700; color: var(--ink-900); line-height: 1.2; letter-spacing: -0.2px; }
.t2 { font-size: 12.5px; color: var(--ink-500); margin-top: 2px; }

.title { font-size: 30px; font-weight: 800; color: var(--ink-900); margin: 0 0 8px; letter-spacing: -0.4px; line-height: 1.15; }
.lede { color: var(--ink-700); margin: 0 0 24px; font-size: 14.5px; }

.field { display: flex; flex-direction: column; gap: 6px; margin-bottom: 14px; }
.field label { font-size: 12.5px; color: var(--ink-700); font-weight: 500; }
.req { color: var(--err); }
.field input {
  width: 100%; padding: 9px 12px;
  border: 1px solid var(--border);
  border-radius: 8px;
  background: var(--surface);
  color: var(--ink-900);
  font-size: 13.5px;
  font-family: inherit;
  transition: border-color .15s ease, box-shadow .15s ease;
}
.field input:focus {
  outline: none;
  border-color: var(--primary);
  /* focus ring 用主渐变 (跟 logo 一致): 蓝→青绿 软光环 */
  box-shadow:
    0 0 0 3px var(--primary-soft),
    0 0 0 4px rgba(13, 148, 136, 0.10);
}

.primary {
  width: 100%;
  margin-top: 6px;
  padding: 9px 18px;
  background: var(--primary-grad);
  color: #fff;
  border: 0;
  border-radius: 9px;
  font-size: 13.5px;
  font-weight: 600;
  font-family: inherit;
  cursor: pointer;
  display: inline-flex; align-items: center; justify-content: center; gap: 6px;
  transition: transform .05s ease, box-shadow .15s ease, filter .15s ease;
}
.primary:hover:not(:disabled) {
  /* hover 时整体亮一档 (logo 渐变方向不变, 提亮即可) */
  filter: brightness(1.08) saturate(1.05);
  box-shadow: 0 8px 20px rgba(59, 130, 246, 0.30), 0 4px 10px rgba(13, 148, 136, 0.18);
}
.primary:active:not(:disabled) { transform: translateY(1px); }
.primary:disabled { opacity: 0.5; cursor: not-allowed; }

.err {
  margin-top: 12px;
  background: rgba(220, 38, 38, 0.06);
  border: 1px solid rgba(220, 38, 38, 0.25);
  border-radius: 8px;
  padding: 10px 12px;
  color: var(--err);
  font-size: 12.5px;
}
</style>
