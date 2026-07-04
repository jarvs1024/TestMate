<template>
  <div class="min-h-screen flex items-center justify-center bg-slate-50">
    <div class="w-96 p-8 bg-white rounded-2xl shadow-floating">
      <div class="flex items-center gap-3 mb-6">
        <div class="w-10 h-10 rounded-xl bg-primary-600 flex items-center justify-center text-white font-bold text-lg">
          T
        </div>
        <h1 class="text-xl font-semibold m-0">TestMate</h1>
      </div>
      <p class="text-sm text-slate-500 mb-6">智能测试辅助平台</p>

      <el-form :model="form" @submit.prevent="onSubmit">
        <el-form-item>
          <el-input v-model="form.username" placeholder="用户名" size="large" />
        </el-form-item>
        <el-form-item>
          <el-input v-model="form.password" type="password" placeholder="密码" size="large" show-password />
        </el-form-item>
        <el-button type="primary" size="large" class="w-full" :loading="loading" @click="onSubmit">
          登录
        </el-button>
      </el-form>

      <div v-if="error" class="mt-3 text-sm text-rose-600">{{ error }}</div>
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

const form = reactive({ username: 'admin', password: 'admin123' });
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
