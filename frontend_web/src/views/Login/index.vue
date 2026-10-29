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
          填公司邮箱前缀<span v-if="emailDomain">（{{ emailDomain }}）</span>，或管理员账号名。<br />
          账号需<strong>管理员提前开通</strong>；未设密码的账号<strong>免密登录</strong>，回车即可。
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
            <div v-if="hintText" class="hint" :class="hintKind">{{ hintText }}</div>
          </div>

          <!-- 密码: **只有这个账号真的要密码时才摆出来** (后端探测的结果) -->
          <div v-if="needPassword" class="field">
            <label>密码 <span class="req">*</span></label>
            <input
              ref="pwdInput"
              v-model="form.password"
              type="password"
              placeholder="请输入密码"
              autocomplete="current-password" />
          </div>

          <button class="primary" :disabled="loading || !form.username.trim()">
            <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round">
              <path d="M15 3h4a2 2 0 0 1 2 2v4"/><polyline points="10 17 15 12 10 7"/><line x1="15" y1="12" x2="3" y2="12"/>
            </svg>
            <span>{{ buttonText }}</span>
          </button>

          <div v-if="error" class="err" :class="{ warn: errorIsWarn }">{{ error }}</div>

          <!-- 探测失败时的**兜底口子** (正常情况下不需要它 —— 要密码的账号密码框自动出现) -->
          <button
            v-else-if="hintState === 'failed' && !needPassword"
            type="button"
            class="link"
            @click="showPasswordBox">
            该账号有密码？点这里输入
          </button>
        </form>
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
/**
 * 登录页 —— 免密优先.
 *
 * 账号口径 (后端 app/api/auth.py):
 *   · 账号**必须管理员先建过**才能登录 —— 填了没开通的账号进不来;
 *   · **普通用户**: 输入公司邮箱前缀 (后缀由后端的 AUTH_EMAIL_DOMAIN 决定)
 *     → 建号时没设密码 = **免密登录**, 设了密码就要输;
 *   · **管理员**: 账号名 (不含 @) → 一律要密码.
 *
 * 所以表单默认**只有一个输入框**: 填完用户名回车就进去了 —— 真"一键".
 *
 * 密码框**只在"这个账号真的要密码"时才出现**, 判据是后端的账号提示
 * (GET /api/v1/auth/account-hint):
 *   ① 探测到 needs_password → 摆出密码框, 并说清"这个号已设密码";
 *   ② 探测到免密账号         → 不摆密码框, 按钮写成「免密登录」;
 *   ③ 探测失败 (后端不可达)  → 退回老路: 先提交, 后端回 password_required
 *      再展开密码框 (这一步失败会被登录限流计数, 所以只是兜底);
 *   ④ 上次登录过且带密码的账号 → localStorage 记着, 下次直接摆出密码框.
 *
 * ⚠️ 记住三个东西 (localStorage):
 *   · 上次用的用户名 → 下次自动填好, 回车即登录;
 *   · "这个账号要密码" → 下次直接把密码框摆出来, 不用多点一次.
 */
import BrandLogo from '@/components/BrandLogo.vue';
import { computed, nextTick, onBeforeUnmount, onMounted, reactive, ref } from 'vue';
import { useRouter, useRoute } from 'vue-router';
import { useUserStore } from '@/stores/user';
import { getAccountHint, getAuthConfig, type AccountHint } from '@/api/users';
import { errorDetail, errorStatus, httpErrorText } from '@/utils/httpError';

/** 上次登录用的用户名 */
const LAST_USERNAME_KEY = 'testmate:last-username';
/** 需要密码的账号名 (值 = 用户名) */
const NEEDS_PASSWORD_KEY = 'testmate:needs-password';

/** 探测的防抖间隔 (毫秒) —— 别一个字一个字地打一次接口 */
const HINT_DEBOUNCE_MS = 300;

const router = useRouter();
const route = useRoute();
const userStore = useUserStore();

const form = reactive({ username: '', password: '' });
const loading = ref(false);
const error = ref('');
/** 这条提示是"提醒"还是"错误"? (要密码 → 提醒, 黄色; 登录失败 → 错误, 红色) */
const errorIsWarn = ref(false);
const needPassword = ref(false);
const userInput = ref<HTMLInputElement | null>(null);
const pwdInput = ref<HTMLInputElement | null>(null);

/** 账号提示的状态机: idle → checking → ready / failed */
const hintState = ref<'idle' | 'checking' | 'ready' | 'failed'>('idle');
const hint = ref<AccountHint | null>(null);
/** 当前这份提示是**给哪个账号名**的 —— 换了账号, 旧结论立刻作废 */
const hintFor = ref('');

/** 探测序号 —— 后发先至时只认最后一次 (慢请求回来不能覆盖新账号的结论) */
let hintSeq = 0;
let hintTimer: ReturnType<typeof setTimeout> | null = null;

/**
 * 公司邮箱后缀 —— **运行时向后端取** (GET /api/v1/auth/config, 公开端点).
 *
 * ⚠️ 真源是后端的 AUTH_EMAIL_DOMAIN (可配) —— 前端写死的话, 后端换了域名,
 *    这里还显示旧后缀, 用户按旧后缀填账号就登不进去.
 * ⚠️ 初始值先用兜底常量 (= 后端默认值): 配置接口挂了也不能让登录表单渲染不出来;
 *    真值取到后立刻覆盖 —— 后端默认就是它, 一般看不出跳变.
 *    (兜底只在"取不到"时用, 不是"永远用".)
 */
const FALLBACK_EMAIL_DOMAIN = '@twsc.com.cn';
const emailDomain = ref(FALLBACK_EMAIL_DOMAIN);

/** 输入里已经有 @ 了就不用再显示固定后缀 */
const showDomain = computed(() => {
  if (form.username.includes('@')) return false;
  // ⚠️ 管理员账号是**账号名** (admin), 不是邮箱 —— 探测出来是管理员就别再挂
  //    "@twsc.com.cn" 后缀, 否则提示本身就是错的.
  if (hint.value?.account === 'ok' && hint.value.role === 'admin') return false;
  return true;
});

/** 账号状态提示 (一行, 跟着输入走) */
const hintText = computed(() => {
  const u = form.username.trim();
  if (!u) return '';
  if (hintState.value === 'checking') return '正在核对账号…';
  // ⚠️ 探测失败的**唯一来源**是 getAccountHint 返回 null, 而 api/users.ts 把
  //    所有异常 (网络失败 / 502 / 429 限流) 都吞成了 null ——
  //    所以这里**不能**说成"账号需管理员提前开通" (那是 h.account === 'missing' 的结论).
  //    以前两句话一模一样, 用户以为自己账号没开通, 去找管理员, 实际是平台挂了.
  if (hintState.value === 'failed') return '账号状态暂时查不到（服务未就绪或查询过频），可直接尝试登录';
  const h = hint.value;
  if (!h) return '';
  if (h.account === 'ok') {
    const who = h.role === 'admin' ? '管理员账号' : '账号已开通';
    return h.needs_password
      ? `${who} · 已设置密码，请输入密码登录`
      : `${who} · 免密登录，直接回车即可`;
  }
  if (h.account === 'missing') return '该账号尚未开通，请联系管理员';
  if (h.account === 'disabled') return '该账号已停用，请联系管理员';
  return '';
});

/** 提示的语气 (ok / bad / busy / need-pw / warn) */
const hintKind = computed(() => {
  if (hintState.value === 'checking') return 'busy';
  // ⚠️ failed 以前落回 'plain' (灰字) —— 灰字跟"一切正常"长得一样,
  //    用户看不出这是**异常**. 探测失败是"服务没就绪/被限流", 用 warn (黄) 才看得出.
  if (hintState.value === 'failed') return 'warn';
  const h = hint.value;
  if (h?.account === 'ok') return h.needs_password ? 'need-pw' : 'ok';
  if (h?.account === 'missing' || h?.account === 'disabled') return 'bad';
  return 'plain';
});

/** 按钮文案 —— 免密账号就说清楚是免密 */
const buttonText = computed(() => {
  if (loading.value) return '登录中…';
  if (hint.value?.account === 'ok' && !hint.value.needs_password) return '免密登录';
  return '登录';
});

onMounted(async () => {
  const last = localStorage.getItem(LAST_USERNAME_KEY) || '';
  if (last) {
    form.username = last;
    // 上次这个账号要过密码 → 直接把密码框摆出来 (不用等探测)
    needPassword.value = localStorage.getItem(NEEDS_PASSWORD_KEY) === last;
    // 后缀取真值 (取不到就用兜底常量, 见上面的说明)
    void checkAccountHint(last);
  }
  try {
    const cfg = await getAuthConfig();
    if (cfg?.email_domain) emailDomain.value = cfg.email_domain;
  } catch {
    /* 保留兜底常量 —— 表单照常能用 */
  }
});

onBeforeUnmount(() => {
  if (hintTimer) clearTimeout(hintTimer);
  // 让在途的探测回来时自动作废 (别再往已卸载的组件上写状态)
  hintSeq += 1;
});

/** 换了账号 → 旧结论作废, 重新排一次探测 */
function onUserInput() {
  error.value = '';
  errorIsWarn.value = false;
  const u = form.username.trim();

  if (hintFor.value && u !== hintFor.value) {
    hint.value = null;
    hintState.value = 'idle';
    hintFor.value = '';
  }
  // 记住的"这个号要密码"只对**那一个账号名**成立 —— 换个号就收起来
  if (localStorage.getItem(NEEDS_PASSWORD_KEY) !== u) {
    needPassword.value = false;
    form.password = '';
  }
  scheduleHintCheck(u);
}

/** 防抖后去问后端: 这个账号要不要密码 */
function scheduleHintCheck(username: string) {
  if (hintTimer) clearTimeout(hintTimer);
  if (username.length < 2) {
    hint.value = null;
    hintState.value = 'idle';
    hintFor.value = '';
    return;
  }
  hintTimer = setTimeout(() => {
    hintTimer = null;
    void checkAccountHint(username);
  }, HINT_DEBOUNCE_MS);
}

/**
 * 问后端账号提示.
 *
 * ⚠️ 失败**不报错** —— 探测是"锦上添花": 探不到就退回老路 (提交时后端说
 *    password_required 再展开密码框), 登录照样能用. 用户不该看到"探测失败"。
 */
async function checkAccountHint(username: string) {
  const seq = ++hintSeq;
  hintState.value = 'checking';
  const res = await getAccountHint(username);
  // 有更新的探测了 → 这份结果作废 (慢请求不能盖掉新账号的结论)
  if (seq !== hintSeq) return;
  if (!res) {
    hintState.value = 'failed';
    return;
  }
  hint.value = res;
  hintFor.value = username;
  hintState.value = 'ready';
  if (res.account === 'ok') {
    needPassword.value = res.needs_password;
    if (res.needs_password) {
      localStorage.setItem(NEEDS_PASSWORD_KEY, username);
    } else if (localStorage.getItem(NEEDS_PASSWORD_KEY) === username) {
      // 这个号刚被改成免密了 → 撤掉"要密码"的标记
      localStorage.removeItem(NEEDS_PASSWORD_KEY);
    }
  } else {
    needPassword.value = false;
  }
}

/** 探测失败时的兜底: 手动把密码框叫出来 */
function showPasswordBox() {
  needPassword.value = true;
  error.value = '';
  errorIsWarn.value = false;
  void nextTick(() => pwdInput.value?.focus());
}

async function onSubmit() {
  const username = form.username.trim();
  if (!username) return;
  loading.value = true;
  error.value = '';
  errorIsWarn.value = false;
  try {
    await userStore.login(username, needPassword.value ? form.password : '');
    // 记住用户名 (下次自动填)
    localStorage.setItem(LAST_USERNAME_KEY, username);
    // ⚠️ "这个账号要密码"的标记要**按情况**处理:
    //    · 这次是带密码进来的 → 说明这个账号要密码 (管理员), 下次直接把密码框摆出来
    //    · 这次没输密码就进来了 → 说明这账号不需要密码 (普通用户), 标记撤掉
    if (needPassword.value && form.password) {
      localStorage.setItem(NEEDS_PASSWORD_KEY, username);
    } else {
      localStorage.removeItem(NEEDS_PASSWORD_KEY);
    }
    const redirect = (route.query.redirect as string) || '/';
    router.push(redirect);
  } catch (e: any) {
    const detail = errorDetail(e);
    const code = (detail as { code?: string } | null)?.code;
    if (code === 'password_required') {
      // 这个账号要密码 → 展开密码框 (这不是"错误", 是流程的下一步), 并记住
      needPassword.value = true;
      localStorage.setItem(NEEDS_PASSWORD_KEY, username);
      error.value = (detail as { message?: string }).message || '该账号需要密码';
      errorIsWarn.value = true;
      await nextTick();
      pwdInput.value?.focus();
    } else {
      // account_not_found / account_disabled 等 —— 显示后端给的人话
      error.value = httpErrorText(errorStatus(e), detail, '登录失败，请稍后再试');
      errorIsWarn.value = false;
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
.lede { color: var(--ink-700); margin: 0 0 24px; font-size: 14.5px; line-height: 1.6; }
.lede strong { color: var(--ink-900); font-weight: 700; }

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

/* 账号状态提示 (一行, 跟着输入走) */
.hint {
  font-size: 12.5px;
  line-height: 1.5;
  color: var(--ink-500);
  display: flex; align-items: center; gap: 5px;
}
.hint.ok { color: var(--ok); }
.hint.need-pw { color: var(--ink-700); }
.hint.bad { color: var(--err); }
.hint.busy { color: var(--ink-500); }
/* ⚠️ warn = 探测失败 (服务没就绪 / 查询过频) —— 黄色, 跟"一切正常"的灰字区分开 */
.hint.warn { color: var(--warn); }

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

/* 兜底口子: 探测失败时才出现, 平时不占版面 */
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
  line-height: 1.5;
}
/* ⚠️ warn = "这不是失败, 是流程的下一步" (要密码 / 探测不到) —— 黄色, 别吓唬人 */
.err.warn {
  background: rgba(245, 158, 11, 0.08);
  border-color: rgba(245, 158, 11, 0.3);
  color: #b45309;
}
</style>
