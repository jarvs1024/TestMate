<template>
  <div class="login">
    <div class="container">
      <div class="box">
        <div class="brand">
          <BrandLogo :size="44" />
          <div class="b-txt">
            <div class="t1">TestMate</div>
            <div class="t2">SSD 测试伙伴</div>
          </div>
        </div>

        <h1 class="title">登录到工作台</h1>
        <p class="lede">
          账号需<strong>管理员提前开通</strong> —— 没开通的账号填了也进不来。<br />
          普通用户：填公司邮箱前缀<span v-if="emailDomain">（{{ emailDomain }}）</span>；
          管理员：填账号名，另输密码
        </p>

        <form @submit.prevent="onSubmit">
          <!-- 用户名 = 公司邮箱前缀 (后缀固定) -->
          <div class="field">
            <label>用户名 <span class="req">*</span></label>
            <div class="input-wrap" :class="{ plain: !showDomain }">
              <input
                ref="userInput"
                v-model="form.username"
                type="text"
                placeholder="zhangsan"
                autocomplete="username"
                @input="onUserInput" />
              <span v-if="showDomain" class="suffix">{{ emailDomain }}</span>
            </div>
          </div>

          <!-- 密码: 默认不占版面, 管理员才需要 (后端说 password_required 才展开) -->
          <div v-if="needPassword" class="field">
            <label>密码 <span class="req">*</span></label>
            <input
              ref="pwdInput"
              v-model="form.password"
              type="password"
              placeholder="••••••••"
              autocomplete="current-password" />
          </div>

          <button class="primary" :disabled="loading || !form.username.trim()">
            <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round">
              <path d="M15 3h4a2 2 0 0 1 2 2v4"/><polyline points="10 17 15 12 10 7"/><line x1="15" y1="12" x2="3" y2="12"/>
            </svg>
            <span>{{ loading ? '登录中…' : '登录' }}</span>
          </button>

          <div v-if="error" class="err">{{ error }}</div>
          <button v-else-if="!needPassword" type="button" class="link" @click="needPassword = true">
            用密码登录
          </button>
        </form>
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
/**
 * 登录页 —— 2026-10-25 账号管理重构.
 *
 * 新规则 (后端 app/api/auth.py):
 *   · 账号**必须管理员先建过**才能登录 —— 填了没开通的账号进不来;
 *   · **普通用户**: 输入公司邮箱前缀 (后缀固定 @twsc.com.cn) → 建号时没设密码
 *     就是免密登录, 设了密码就要输;
 *   · **管理员**: 账号名 (不含 @) → 必须密码.
 *
 * 所以这个表单默认**只有一个输入框**: 填完用户名回车就进去了 —— 真"一键".
 * 密码框默认不占版面, 两种情况才出现:
 *   ① 后端回 password_required (说明这个账号设了密码 / 是管理员);
 *   ② 用户自己点「用密码登录」(拿旧密码体系的同事也能用).
 *
 * ⚠️ 记住两个东西 (localStorage):
 *   · 上次用的用户名 → 下次自动填好, 回车即登录;
 *   · "这个账号要密码" → 下次直接把密码框摆出来, 管理员不用多点一次.
 */
import BrandLogo from '@/components/BrandLogo.vue';
import { computed, nextTick, onMounted, reactive, ref } from 'vue';
import { useRouter, useRoute } from 'vue-router';
import { useUserStore } from '@/stores/user';

/** 上次登录用的用户名 */
const LAST_USERNAME_KEY = 'testmate:last-username';
/** 需要密码的账号名 (值 = 用户名) */
const NEEDS_PASSWORD_KEY = 'testmate:needs-password';

const router = useRouter();
const route = useRoute();
const userStore = useUserStore();

const form = reactive({ username: '', password: '' });
const loading = ref(false);
const error = ref('');
const needPassword = ref(false);
const userInput = ref<HTMLInputElement | null>(null);
const pwdInput = ref<HTMLInputElement | null>(null);

/** 邮箱后缀 —— 从登录接口约定来的常量 (前端只做展示, 真正补后缀在后端) */
const emailDomain = '@twsc.com.cn';

/** 输入里已经有 @ 了就不用再显示固定后缀 */
const showDomain = computed(() => !form.username.includes('@'));

onMounted(() => {
  const last = localStorage.getItem(LAST_USERNAME_KEY) || '';
  if (last) {
    form.username = last;
    // 上次这个账号要过密码 → 直接把密码框摆出来
    needPassword.value = localStorage.getItem(NEEDS_PASSWORD_KEY) === last;
  }
});

/** 换了账号 → 密码框收起来 (新账号大概率是普通用户) */
function onUserInput() {
  error.value = '';
  if (needPassword.value && localStorage.getItem(NEEDS_PASSWORD_KEY) !== form.username) {
    needPassword.value = false;
    form.password = '';
  }
}

async function onSubmit() {
  const username = form.username.trim();
  if (!username) return;
  loading.value = true;
  error.value = '';
  try {
    await userStore.login(username, form.password);
    // 记住用户名 (下次自动填)
    localStorage.setItem(LAST_USERNAME_KEY, username);
    // ⚠️ "这个账号要密码"的标记要**按情况**处理:
    //    · 这次是带密码进来的 → 说明这个账号要密码 (管理员), 下次直接把密码框摆出来
    //    · 这次没输密码就进来了 → 说明这账号不需要密码 (普通用户), 标记撤掉
    if (form.password) {
      localStorage.setItem(NEEDS_PASSWORD_KEY, username);
    } else {
      localStorage.removeItem(NEEDS_PASSWORD_KEY);
    }
    const redirect = (route.query.redirect as string) || '/';
    router.push(redirect);
  } catch (e: any) {
    const detail = e?.response?.data?.detail;
    if (detail && typeof detail === 'object') {
      // 后端给的是结构化 detail: {code, message}
      if (detail.code === 'password_required') {
        // 这个账号要密码 → 展开密码框, 并记住 (下次直接摆出来)
        needPassword.value = true;
        error.value = detail.message || '该账号需要密码';
        localStorage.setItem(NEEDS_PASSWORD_KEY, username);
        await nextTick();
        pwdInput.value?.focus();
      } else {
        // account_not_found / account_disabled 等 —— 直接显示后端给的话
        error.value = detail.message || '登录失败, 请联系管理员';
      }
    } else {
      error.value = typeof detail === 'string' ? detail : '登录失败,请检查账号密码';
    }
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
  /* 清新版: 单层 focus ring */
  box-shadow: 0 0 0 3px var(--primary-soft);
}

/* 用户名 + 固定后缀: 两段拼成一个输入框 */
.input-wrap { display: flex; align-items: stretch; }
.input-wrap input { flex: 1; min-width: 0; border-radius: 8px 0 0 8px; }
.input-wrap.plain input { border-radius: 8px; }
.input-wrap:focus-within input { border-color: var(--primary); box-shadow: 0 0 0 3px var(--primary-soft); }
.input-wrap:focus-within .suffix { border-color: var(--primary); }
.suffix {
  display: flex; align-items: center;
  padding: 0 11px;
  border: 1px solid var(--border); border-left: none;
  border-radius: 0 8px 8px 0;
  background: var(--surface-sunken);
  color: var(--ink-500);
  font-size: 12.5px;
  white-space: nowrap;
  user-select: none;
}

.primary {
  width: 100%;
  margin-top: 6px;
  padding: 9px 18px;
  background: var(--primary-grad);
  color: #fff;
  border: 0;
  border-radius: 8px;
  font-size: 13.5px;
  font-weight: 600;
  font-family: inherit;
  cursor: pointer;
  display: inline-flex; align-items: center; justify-content: center; gap: 6px;
  transition: transform .08s ease, box-shadow .15s ease, filter .15s ease;
}
.primary:hover:not(:disabled) {
  filter: brightness(1.05);
  /* 单色柔和投影 */
  box-shadow: 0 4px 12px rgba(59, 130, 246, 0.28);
  transform: translateY(-1px);
}
.primary:active:not(:disabled) { transform: translateY(0); }
.primary:disabled { opacity: 0.5; cursor: not-allowed; }

/* 「用密码登录」—— 给习惯密码登录的人留的口子 */
.link {
  margin-top: 10px;
  background: none; border: 0; padding: 0;
  color: var(--ink-500); font-size: 12px; font-family: inherit;
  cursor: pointer; text-decoration: underline; text-underline-offset: 3px;
}
.link:hover { color: var(--primary); }

.err {
  margin-top: 12px;
  background: rgba(239, 68, 68, 0.06);
  border: 1px solid rgba(239, 68, 68, 0.25);
  border-radius: 8px;
  padding: 10px 12px;
  color: var(--err);
  font-size: 12.5px;
}
</style>
