<template>
  <section :id="'sec-users'" class="card grp">
    <h2>
      <span>👥 用户管理</span>
      <span class="grp-cnt">{{ users.length }} 个账号</span>
    </h2>

    <div class="hint">
      💡 账号必须<strong>管理员先建好</strong>才能登录 —— 登录页只认这里建出来的号,
      填谁的名字都进不来。<br />
      普通用户 = 公司邮箱前缀<span v-if="emailDomain">（{{ emailDomain }}）</span>,
      管理员 = 纯账号名 (不带 @), 一律要密码。<br />
      建号时<strong>密码留空</strong> = 免密登录 (只填用户名就能进);
      填了密码 = 登录必须输密码。
    </div>

    <!-- ===== 建号 ===== -->
    <div class="sub-grp">
      <h3>➕ 新建账号</h3>
      <div class="create-row">
        <div class="field">
          <label>用户名 <span class="req">*</span></label>
          <div class="input-wrap" :class="{ plain: !showDomain }">
            <input
              v-model="form.username"
              type="text"
              :placeholder="isAdminRole ? '账号名 (不带 @)' : 'zhangsan'"
              @keyup.enter="onCreate" />
            <span v-if="showDomain" class="suffix">{{ emailDomain }}</span>
          </div>
        </div>

        <div class="field">
          <label>角色</label>
          <select v-model="form.role">
            <option value="tester">测试者 · 能建能力/发资产</option>
            <option value="viewer">只读 · 只看</option>
            <option value="admin">管理员 · 能管配置和账号</option>
          </select>
        </div>

        <div class="field">
          <label>密码 <span class="opt">(可留空)</span></label>
          <input
            v-model="form.password"
            type="password"
            :placeholder="isAdminRole ? '管理员必须设置' : '留空 = 免密登录'"
            @keyup.enter="onCreate" />
        </div>

        <button class="primary create-btn" :disabled="busy || !form.username.trim()" @click="onCreate">
          {{ busy ? '创建中…' : '创建账号' }}
        </button>
      </div>
      <div v-if="formErr" class="err">{{ formErr }}</div>
    </div>

    <!-- ===== 账号列表 ===== -->
    <div class="sub-grp">
      <h3>
        👤 账号列表 <span class="sub-cnt">{{ users.length }}</span>
        <button class="mini-link" :disabled="busy" @click="emit('changed')">刷新</button>
      </h3>

      <!-- ⚠️ 取不到列表 ≠ 一个账号都没有 —— 失败要说清楚, 并给个重试入口 -->
      <div v-if="error" class="empty err">
        账号列表加载失败：{{ error }}
        <button class="ghost retry" :disabled="busy" @click="emit('changed')">重试</button>
      </div>

      <div v-else-if="!users.length" class="empty">还没有账号 —— 在上面建一个吧</div>

      <ul v-else class="user-list">
        <li v-for="u in users" :key="u.id" :class="{ off: !u.is_active }">
          <div class="u-main">
            <div class="u-name">
              <code>{{ u.username }}</code>
              <span class="badge" :class="u.role">{{ roleLabel(u.role) }}</span>
              <span class="badge" :class="u.password_required ? 'pwd' : 'nopwd'">
                {{ u.password_required ? '需密码' : '免密' }}
              </span>
              <span v-if="!u.is_active" class="badge off">已停用</span>
            </div>
            <div class="u-meta">创建于 {{ fmtTime(u.created_at) }}</div>
          </div>

          <div class="u-ops">
            <select
              class="role-sel"
              :value="u.role"
              :disabled="busy"
              @change="onRole(u, ($event.target as HTMLSelectElement).value)">
              <option value="tester">测试者</option>
              <option value="viewer">只读</option>
              <option value="admin">管理员</option>
            </select>
            <button class="ghost" :disabled="busy" @click="onResetPwd(u)">重置密码</button>
            <button class="ghost" :disabled="busy" @click="onToggleActive(u)">
              {{ u.is_active ? '停用' : '启用' }}
            </button>
          </div>
        </li>
      </ul>
    </div>
  </section>
</template>

<script setup lang="ts">
/**
 * 账号管理 (仅 admin) —— 2026-10-25 账号管理重构.
 *
 * 登录规则 (后端 app/api/auth.py):
 *   · 账号**必须管理员先建过**才能登录 —— 这里是唯一的建号入口;
 *   · 普通用户 = 公司邮箱 (后缀由后端的 AUTH_EMAIL_DOMAIN 决定, 这里运行时取), 建号时密码留空 → 免密, 填了 → 必须密码;
 *   · 管理员 = 不含 @ 的账号名, 一律要密码.
 *
 * ⚠️ 停用而不是删除: 账号名下的资产归属还在, 删号会把那些资产变成无主.
 */
import { computed, onMounted, reactive, ref } from 'vue';
import { ElMessage, ElMessageBox } from 'element-plus';
import { createUser, updateUser, getAuthConfig, type ManagedUser, type UserRole } from '@/api/users';

defineProps<{ users: ManagedUser[]; error?: string }>();
const emit = defineEmits<{ (e: 'changed'): void }>();

/**
 * 公司邮箱后缀 —— **运行时向后端取** (GET /api/v1/auth/config, 公开端点).
 *
 * ⚠️ 真源是后端的 AUTH_EMAIL_DOMAIN (可配) —— 前端写死的话, 后端换了域名,
 *    这里还显示旧后缀, 用户按旧后缀建号就登不进去.
 * ⚠️ 初始值先用兜底常量 (= 后端默认值): 配置接口挂了也不能让表单渲染不出来;
 *    真值取到后立刻覆盖 (后端默认就是它, 一般看不出跳变).
 */
const FALLBACK_EMAIL_DOMAIN = '@twsc.com.cn';
const emailDomain = ref(FALLBACK_EMAIL_DOMAIN);

onMounted(async () => {
  try {
    const cfg = await getAuthConfig();
    if (cfg?.email_domain) emailDomain.value = cfg.email_domain;
  } catch {
    /* 保留兜底常量 —— 表单照常能用 */
  }
});

const form = reactive<{ username: string; password: string; role: UserRole }>({
  username: '',
  password: '',
  role: 'tester',
});
const busy = ref(false);
const formErr = ref('');

/** 管理员账号名不带 @ —— 这时候不显示固定后缀 */
const isAdminRole = computed(() => form.role === 'admin');
const showDomain = computed(() => !isAdminRole.value && !form.username.includes('@'));

function roleLabel(role: UserRole): string {
  return role === 'admin' ? '管理员' : role === 'tester' ? '测试者' : '只读';
}

function fmtTime(iso: string | null): string {
  if (!iso) return '—';
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return iso;
  return d.toLocaleString('zh-CN', {
    hour12: false, year: 'numeric', month: '2-digit', day: '2-digit',
    hour: '2-digit', minute: '2-digit',
  });
}

/** 后端 422 的 detail 是字符串, 403/409 也是 —— 统一取出来给人看 */
function errText(e: any, fallback: string): string {
  const d = e?.response?.data?.detail;
  if (typeof d === 'string' && d) return d;
  if (d && typeof d === 'object' && d.message) return d.message;
  return fallback;
}

async function onCreate() {
  const username = form.username.trim();
  if (!username) return;
  busy.value = true;
  formErr.value = '';
  try {
    await createUser({
      username,
      password: form.password,
      role: form.role,
    });
    ElMessage.success(`账号已创建: ${username}`);
    form.username = '';
    form.password = '';
    emit('changed');
  } catch (e: any) {
    formErr.value = errText(e, '创建失败');
  } finally {
    busy.value = false;
  }
}

async function onToggleActive(u: ManagedUser) {
  busy.value = true;
  try {
    await updateUser(u.id, { is_active: !u.is_active });
    ElMessage.success(u.is_active ? `已停用 ${u.username}` : `已启用 ${u.username}`);
    emit('changed');
  } catch (e: any) {
    ElMessage.error(errText(e, '操作失败'));
  } finally {
    busy.value = false;
  }
}

async function onRole(u: ManagedUser, role: string) {
  if (role === u.role) return;
  busy.value = true;
  try {
    await updateUser(u.id, { role: role as UserRole });
    ElMessage.success(`${u.username} 的角色已改为「${roleLabel(role as UserRole)}」`);
    emit('changed');
  } catch (e: any) {
    ElMessage.error(errText(e, '改角色失败'));
    emit('changed');  // 失败时把 select 拉回原值
  } finally {
    busy.value = false;
  }
}

async function onResetPwd(u: ManagedUser) {
  let pwd = '';
  try {
    const r = await ElMessageBox.prompt(
      `给「${u.username}」设置新密码。\n`
      + `设完这个账号就是「必须密码」登录 (免密会同时失效)。`,
      '重置密码',
      {
        type: 'warning',
        confirmButtonText: '设置密码',
        cancelButtonText: '取消',
        inputPlaceholder: '新密码',
        inputValidator: (v: string) => (v || '').trim().length >= 6 || '密码至少 6 位',
      },
    );
    pwd = r.value || '';
  } catch {
    return;  // 用户取消
  }
  busy.value = true;
  try {
    await updateUser(u.id, { password: pwd });
    ElMessage.success(`${u.username} 的密码已重置`);
    emit('changed');
  } catch (e: any) {
    ElMessage.error(errText(e, '重置失败'));
  } finally {
    busy.value = false;
  }
}
</script>

<style scoped>
.grp h2 {
  font-size: 16px; font-weight: 700; margin: 0 0 14px; color: var(--ink-900);
  display: flex; align-items: center; gap: 8px;
}
.grp-cnt {
  font-size: 10.5px; padding: 2px 7px; background: var(--surface-sunken);
  color: var(--ink-500); border-radius: var(--radius-pill); font-weight: 500;
}
.sub-grp {
  padding: 16px 0 4px;
  border-top: 1px dashed var(--border);
  margin-top: 4px;
}
.sub-grp:first-of-type { border-top: none; padding-top: 8px; }
.sub-grp h3 {
  font-size: 13px; font-weight: 600; color: var(--ink-700);
  margin: 0 0 12px; display: flex; align-items: center; gap: 6px;
}
.sub-cnt {
  font-size: 10.5px; padding: 1px 6px; background: var(--surface-sunken);
  color: var(--ink-500); border-radius: var(--radius-pill); font-weight: 500;
}
.hint {
  margin-top: 10px; font-size: 12px; color: var(--ink-500); line-height: 1.6;
  background: var(--surface-sunken); border-radius: 8px; padding: 8px 12px;
}
.mini-link {
  margin-left: auto; background: transparent; border: 1px solid var(--border);
  padding: 2px 10px; border-radius: var(--radius-pill);
  font-size: 11px; color: var(--ink-700); cursor: pointer; font-family: inherit;
}
.mini-link:hover:not(:disabled) { border-color: var(--primary); color: var(--primary); }
.mini-link:disabled { opacity: 0.5; cursor: not-allowed; }

/* ===== 建号表单 ===== */
.create-row {
  display: flex; gap: 12px; align-items: flex-end; flex-wrap: wrap;
}
.field { display: flex; flex-direction: column; gap: 6px; flex: 1 1 180px; min-width: 0; }
.field label { font-size: 12.5px; color: var(--ink-700); font-weight: 500; }
.req { color: var(--err); }
.opt { color: var(--ink-500); font-weight: 400; }
.field input, .field select {
  width: 100%; padding: 8px 10px;
  border: 1px solid var(--border); border-radius: 7px;
  background: var(--surface); color: var(--ink-900);
  font-size: 13px; font-family: inherit;
  transition: border-color .15s ease, box-shadow .15s ease;
}
.field input:focus, .field select:focus {
  outline: none; border-color: var(--primary);
  box-shadow: 0 0 0 3px var(--primary-soft);
}
.create-btn { flex: 0 0 auto; height: 35px; padding: 0 18px; }

/* 用户名 + 固定后缀拼成一个输入框 */
.input-wrap { display: flex; align-items: stretch; }
.input-wrap input { flex: 1; min-width: 0; border-radius: 7px 0 0 7px; }
.input-wrap.plain input { border-radius: 7px; }
.input-wrap:focus-within input { border-color: var(--primary); box-shadow: 0 0 0 3px var(--primary-soft); }
.input-wrap:focus-within .suffix { border-color: var(--primary); }
.suffix {
  display: flex; align-items: center; padding: 0 11px;
  border: 1px solid var(--border); border-left: none;
  border-radius: 0 7px 7px 0; background: var(--surface-sunken);
  color: var(--ink-500); font-size: 12.5px; white-space: nowrap; user-select: none;
}

.err {
  margin-top: 10px; background: rgba(239, 68, 68, 0.06);
  border: 1px solid rgba(239, 68, 68, 0.25); border-radius: 8px;
  padding: 9px 12px; color: var(--err); font-size: 12.5px;
}

/* ===== 账号列表 ===== */
.empty { font-size: 12.5px; color: var(--ink-500); padding: 14px 0; }
/* 取数失败 —— 别跟"真的没有账号"长得一样 */
.empty.err {
  color: var(--err);
  display: flex; align-items: center; gap: 10px; flex-wrap: wrap;
}
.empty.err .retry { padding: 3px 12px; }
.user-list { list-style: none; margin: 0; padding: 0; display: flex; flex-direction: column; gap: 8px; }
.user-list li {
  display: flex; align-items: center; gap: 14px; flex-wrap: wrap;
  border: 1px solid var(--border); border-radius: var(--radius-sm);
  padding: 10px 12px; background: var(--surface-soft);
}
.user-list li.off { opacity: 0.6; }
.u-main { flex: 1; min-width: 200px; }
.u-name { display: flex; align-items: center; gap: 7px; flex-wrap: wrap; }
.u-name code {
  font-family: var(--font-mono); font-size: 12.5px; color: var(--ink-900);
  background: var(--surface-sunken); padding: 1px 7px; border-radius: 4px;
}
.u-meta { font-size: 11px; color: var(--ink-500); margin-top: 3px; }
.badge {
  font-size: 10.5px; font-weight: 600; padding: 1px 8px; border-radius: var(--radius-pill);
}
.badge.admin { background: rgba(239, 68, 68, 0.12); color: var(--err); }
.badge.tester { background: var(--primary-soft); color: var(--primary); }
.badge.viewer { background: rgba(100, 116, 139, 0.14); color: var(--ink-600); }
.badge.pwd { background: rgba(245, 158, 11, 0.14); color: var(--warn); }
.badge.nopwd { background: rgba(16, 185, 129, 0.13); color: var(--ok); }
.badge.off { background: rgba(100, 116, 139, 0.18); color: var(--ink-600); }

.u-ops { display: flex; align-items: center; gap: 8px; flex-wrap: wrap; }
.role-sel {
  padding: 5px 8px; border: 1px solid var(--border); border-radius: 7px;
  background: var(--surface); color: var(--ink-700); font-size: 12px; font-family: inherit;
}
.role-sel:disabled { opacity: 0.5; }

.primary {
  background: var(--primary-grad); color: #fff; border: 0;
  padding: 6px 14px; border-radius: 7px;
  font-size: 12.5px; font-weight: 600; font-family: inherit; cursor: pointer;
  transition: filter .15s ease, box-shadow .15s ease;
}
.primary:disabled { opacity: 0.5; cursor: not-allowed; }
.primary:not(:disabled):hover {
  filter: brightness(1.05);
  box-shadow: 0 3px 10px rgba(59, 130, 246, 0.25);
  transform: translateY(-1px);
}
.ghost {
  background: transparent; border: 1px solid var(--border);
  padding: 5px 12px; border-radius: 7px;
  color: var(--ink-700); font-size: 12px; cursor: pointer; font-family: inherit;
}
.ghost:hover:not(:disabled) { border-color: var(--primary); color: var(--primary); }
.ghost:disabled { opacity: 0.5; cursor: not-allowed; }
</style>
