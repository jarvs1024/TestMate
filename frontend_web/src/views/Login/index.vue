<template>
  <div class="login">
    <form class="box" @submit.prevent="onSubmit">
      <div class="brand">
        <span class="logo">T</span>
        <span class="name">TestMate</span>
      </div>
      <p class="sub">智能测试辅助平台</p>

      <label class="lbl">用户名</label>
      <el-input v-model="form.username" placeholder="admin" size="large" />

      <label class="lbl mt">密码</label>
      <el-input v-model="form.password" type="password" placeholder="••••••••" size="large" show-password />

      <el-button
        type="primary"
        size="large"
        class="submit"
        :loading="loading"
        native-type="submit"
      >登录</el-button>

      <div v-if="error" class="err">{{ error }}</div>
    </form>
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
    error.value = e.response?.data?.detail || '登录失败';
  } finally {
    loading.value = false;
  }
}
</script>

<style scoped>
.login {
  min-height: 100vh;
  display: flex; align-items: center; justify-content: center;
  background: var(--bg);
  padding: 24px;
}
.box {
  width: 360px;
  background: var(--bg);
  border: 1px solid var(--border);
  border-radius: 6px;
  padding: 32px;
}
.brand { display: flex; align-items: center; gap: 8px; }
.logo {
  width: 22px; height: 22px;
  background: var(--primary);
  color: #fff;
  border-radius: 4px;
  display: grid; place-items: center;
  font-size: 12px; font-weight: 700;
}
.name { font-size: 15px; font-weight: 600; color: var(--ink-900); }
.sub { font-size: 12.5px; color: var(--ink-500); margin: 4px 0 22px; }

.lbl { display: block; font-size: 11.5px; color: var(--ink-500); font-weight: 500; margin-bottom: 6px; }
.lbl.mt { margin-top: 14px; }
.submit { width: 100%; margin-top: 18px; }
.err { margin-top: 12px; font-size: 12.5px; color: #DC2626; }
</style>
