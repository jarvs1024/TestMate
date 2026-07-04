<template>
  <div class="login">
    <div class="box">
      <div class="brand">
        <div class="logo">T</div>
        <div>
          <div class="name">TestMate</div>
          <div class="sub">智能测试辅助平台</div>
        </div>
      </div>

      <h1 class="title">登录到工作台</h1>
      <p class="lede">使用你的内网账号继续,首次登录请联系管理员开通</p>

      <form @submit.prevent="onSubmit" class="form">
        <div class="field">
          <label class="lbl">用户名 <span class="req">*</span></label>
          <el-input v-model="form.username" placeholder="admin" size="large" />
        </div>
        <div class="field">
          <label class="lbl">密码 <span class="req">*</span></label>
          <el-input v-model="form.password" type="password" placeholder="••••••••" size="large" show-password />
        </div>

        <button type="submit" class="primary" :disabled="loading">
          <svg v-if="!loading" width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">
            <path d="M15 3h4a2 2 0 0 1 2 2v14a2 2 0 0 1-2 2h-4"/><polyline points="10 17 15 12 10 7"/><line x1="15" y1="12" x2="3" y2="12"/>
          </svg>
          <span v-if="loading">登录中…</span>
          <span v-else>登录</span>
        </button>

        <div v-if="error" class="err">
          <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><circle cx="12" cy="12" r="10"/><line x1="12" y1="8" x2="12" y2="12"/><line x1="12" y1="16" x2="12.01" y2="16"/></svg>
          {{ error }}
        </div>
      </form>
    </div>
  </div>
</template>

<script setup lang="ts">
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
.login {
  min-height: 100vh;
  display: flex; align-items: center; justify-content: center;
  padding: 24px;
}
.box {
  width: 420px;
  background: var(--surface);
  border: 1px solid var(--border);
  border-radius: var(--radius-xl);
  box-shadow: var(--shadow-lg);
  padding: 36px 36px 32px;
}
.brand { display: flex; align-items: center; gap: 12px; margin-bottom: 28px; }
.logo {
  width: 44px; height: 44px;
  border-radius: var(--radius-md);
  background: var(--primary-grad);
  color: #fff;
  display: grid; place-items: center;
  font-size: 20px; font-weight: 700;
  box-shadow: var(--primary-shadow);
}
.name { font-size: 15px; font-weight: 700; color: var(--ink-900); line-height: 1.2; }
.sub { font-size: 11.5px; color: var(--ink-500); margin-top: 2px; }

.title { font-size: 24px; font-weight: 700; color: var(--ink-900); margin: 0 0 6px; letter-spacing: -0.2px; }
.lede { font-size: 13px; color: var(--ink-500); margin: 0 0 24px; }

.form { display: flex; flex-direction: column; gap: 4px; }
.field { display: flex; flex-direction: column; }
.lbl { font-size: 12.5px; color: var(--ink-700); font-weight: 500; margin-bottom: 6px; }
.req { color: var(--primary); }

.primary {
  margin-top: 18px;
  height: 44px;
  display: inline-flex; align-items: center; justify-content: center; gap: 8px;
  background: var(--primary-grad);
  color: #fff;
  border: none;
  border-radius: var(--radius-md);
  font-size: 14px; font-weight: 600;
  cursor: pointer;
  box-shadow: var(--primary-shadow);
  transition: filter .15s ease, transform .05s ease;
  font-family: inherit;
}
.primary:hover { filter: brightness(1.05); }
.primary:active { transform: scale(0.99); }
.primary:disabled { opacity: 0.6; cursor: not-allowed; }

.err {
  margin-top: 12px;
  padding: 8px 12px;
  display: flex; align-items: center; gap: 6px;
  background: #FEF2F2;
  color: #DC2626;
  border: 1px solid #FECACA;
  border-radius: var(--radius-md);
  font-size: 12.5px;
}
</style>
