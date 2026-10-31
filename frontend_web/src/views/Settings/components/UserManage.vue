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
              :class="{ invalid: !!fieldErr.username }"
              :placeholder="isAdminRole ? '账号名 (不带 @)' : 'zhangsan'"
              @keyup.enter="onCreate" />
            <span v-if="showDomain" class="suffix">{{ emailDomain }}</span>
          </div>
          <!-- ⚠️ 字段级错误: 贴在出问题的字段下面 (以前所有错误都甩到整行下方) -->
          <div v-if="fieldErr.username" class="field-err">{{ fieldErr.username }}</div>
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
            :class="{ invalid: !!(fieldErr.password || pwdErr) }"
            :placeholder="isAdminRole ? '管理员必须设置' : '留空 = 免密登录'"
            @keyup.enter="onCreate" />
          <!-- ⚠️ 字段级错误: 管理员账号没设密码时, 错误要**贴着密码框**,
               而不是冒在三个字段下面那条红框里 (以前根本看不出是哪个字段错了).
               pwdErr 是**实时**的 —— 「创建账号」按钮已经禁用了, 用户必须一眼
               看得出为什么点不动. -->
          <div v-if="fieldErr.password || pwdErr" class="field-err">{{ fieldErr.password || pwdErr }}</div>
        </div>

        <button class="primary create-btn"
                :disabled="busy || !form.username.trim() || !!pwdErr"
                @click="onCreate">
          {{ busy ? '创建中…' : '创建账号' }}
        </button>
      </div>
      <!-- ⚠️ 只放**通用**错误 (后端返回的、说不清是哪个字段的那些) -->
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
            <!-- ⚠️ 删除 = **不可逆**: 账号没了, 名下资产的作者名会留着, 但再也没法以这个账号身份操作.
               所以按钮单独用 .ghost.danger (红字红框) 跟中性的停用/启用区分开.
               ⚠️ **管理员账号一律不许删** (2026-10-31 用户明确要求) ——
                  管理员是"谁在管这个系统"的凭据, 删掉等于永久放弃一个管理入口.
                  要下线一个管理员 → 走「停用」(可逆) 或把角色改成「测试者」.
               「当前登录的这个账号」也直接禁用 —— 后端也会拦 (400), 但让人白点一次没意义. -->
            <button class="ghost danger"
                    :disabled="busy || isSelf(u) || u.role === 'admin'"
                    :title="deleteTitle(u)"
                    @click="onDelete(u)">删除</button>
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
 * ⚠️ 停用 vs 删除 (2026-10-31 加上删除):
 *   · 停用 = **可逆** —— 临时封一个号, 随时「启用」回来, 名下资产一点没动;
 *   · 删除 = **不可逆** —— 账号没了, 名下资产/软件/知识库文档的**作者名会留着**
 *     (还看得出是谁交的), 但以后没法再以这个账号身份操作 (改不了、发不了新版本).
 *     所以删除必须走**加强的二次确认** —— 不只是弹个框点「确定」,
 *     而是要把**账号名原样敲出来**才放行 (跟知识库「删数据集」一个口径).
 *   · ⚠️ **管理员账号一律不许删** —— 管理员是"谁在管这个系统"的凭据,
 *     删掉等于永久放弃一个管理入口. 要下线一个管理员 → 「停用」或改成「测试者」。
 */
import { computed, onMounted, reactive, ref } from 'vue';
import { ElMessage, ElMessageBox } from 'element-plus';
import { createUser, updateUser, deleteUser, getAuthConfig, type ManagedUser, type UserRole } from '@/api/users';
import { parseApiTime } from '@/utils/format';
import { isAuthor } from '@/utils/author';
import { useUserStore } from '@/stores/user';

defineProps<{ users: ManagedUser[]; error?: string }>();
const emit = defineEmits<{ (e: 'changed'): void }>();

/**
 * 拿 user store —— 拿不到就 null.
 *
 * ⚠️ 为什么包 try/catch 而不是直接 useUserStore():
 *    没有 pinia 上下文时 (有些单测直接 mount 这个组件, 没装 pinia 插件)
 *    useUserStore() 会抛 "no active Pinia", 整个组件渲染不出来 ——
 *    这里宁可当成"不知道当前是谁", 剩下的交给后端护栏 (不能删自己) 兜底.
 * ⚠️ 也没用 getActivePinia() 判断: 它内部 inject pinia 时没给默认值,
 *    组件里调它 Vue 会刷一条 "injection Symbol(pinia) not found" 的警告 —— 那种噪音更烦人.
 */
function safeUserStore(): ReturnType<typeof useUserStore> | null {
  try {
    return useUserStore();
  } catch {
    return null;
  }
}

const userStore = safeUserStore();

/** 当前登录账号 (null = 不知道, 比如没登录/没 pinia) */
const currentUser = computed(() => userStore?.user ?? null);

/**
 * 这个账号是不是**当前登录的自己**?
 *
 * ⚠️ 两种口径都认 (跟后端 identity.name_matches 一致):
 *   · id 对得上 → 同一个人;
 *   · 用户名对得上 —— 短名 ('admin') 和全邮箱 ('zhangsan@twsc.com.cn') 互认.
 *     只认一种的话会出现"后端放行、前端不敢给按钮"的拧巴状态 (见 utils/author.ts).
 */
function isSelf(u: ManagedUser): boolean {
  const me = currentUser.value;
  if (!me) return false;
  if (typeof me.id === 'number' && me.id > 0 && u.id === me.id) return true;
  return isAuthor(u.username, me.username);
}

/**
 * 「删除」按钮的 tooltip —— 把**为什么不能删**说清楚 (别只写个灰按钮让人猜).
 *
 * ⚠️ 三种不能删的情况:
 *   ① **管理员账号** —— 一律不许删 (2026-10-31 用户明确要求「禁止删管理员」).
 *      管理员是"谁在管这个系统"的凭据, 删掉等于永久放弃一个管理入口。
 *      要下线一个管理员 → 「停用」(可逆) 或把角色改成「测试者」;
 *   ② 当前登录的账号 —— 后端也拦, 别让人白点;
 *   ③ 其余情况 (普通账号) —— 可以删, 但不可逆。
 */
function deleteTitle(u: ManagedUser): string {
  if (u.role === 'admin') {
    return '管理员账号不能删除 —— 请改用「停用」或把角色改成「测试者」';
  }
  if (isSelf(u)) return '不能删除当前登录的账号';
  return '删除账号 (不可恢复)';
}

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
/**
 * 表单级错误 —— 只装**通用**错误 (说不清是哪个字段的那些).
 *
 * ⚠️ 以前所有错误 (包括"管理员账号必须设置密码") 都塞在这一个变量里,
 *    冒在三个字段下面 —— 密码框旁边一点提示都没有.
 *    现在按字段定位 (见 fieldErr), 这里只兜底.
 */
const formErr = ref('');
/**
 * 字段级错误 —— username / password 各一条.
 *
 * ⚠️ 有了它, 用户一眼能看出**是哪个字段**错了, 不用猜.
 */
const fieldErr = reactive<{ username: string; password: string }>({
  username: '',
  password: '',
});

/** 管理员账号名不带 @ —— 这时候不显示固定后缀 */
const isAdminRole = computed(() => form.role === 'admin');
const showDomain = computed(() => !isAdminRole.value && !form.username.includes('@'));

/**
 * 管理员账号必须设密码 —— 前端**提前拦一道**.
 *
 * ⚠️ 后端 (auth.py) 本来就会拒 (422 管理员账号必须设置密码), 但以前前端不拦,
 *    点了「创建账号」整个表单往返一次, 才在三个字段下面冒出一条红框,
 *    密码框旁边什么都没有 —— placeholder 写着「管理员必须设置」, 却没有必填标记.
 *    ⚠️ 这里只是**提前告诉用户**, 后端仍是最终校验, 安全性不变.
 */
const pwdErr = computed(() => {
  if (isAdminRole.value && !form.password.trim()) return '管理员账号必须设置密码';
  return '';
});

function roleLabel(role: UserRole): string {
  return role === 'admin' ? '管理员' : role === 'tester' ? '测试者' : '只读';
}

function fmtTime(iso: string | null): string {
  if (!iso) return '—';
  // ⚠️ 后端给的是 **UTC** —— 走 parseApiTime, 否则本地时区解析会差 8 小时
  const d = parseApiTime(iso);
  if (!d) return iso;
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
  // ⚠️ 每次提交先把上一轮的错清干净 (否则旧错误还挂着)
  fieldErr.username = '';
  fieldErr.password = '';
  formErr.value = '';
  // ⚠️ 管理员账号没设密码 → 提前拦下, 并把错贴在密码字段下面
  if (pwdErr.value) {
    fieldErr.password = pwdErr.value;
    return;
  }
  busy.value = true;
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
    // ⚠️ 按字段定位 —— 后端的话里说的是哪个字段, 错就贴到哪个字段下面.
    //    (后端 detail 是纯字符串, 只能按关键词分; 分不出来就落表单底部)
    const msg = errText(e, '创建失败');
    if (msg.includes('密码')) fieldErr.password = msg;
    else if (msg.includes('用户名') || msg.includes('账号') || msg.includes('邮箱')) fieldErr.username = msg;
    else formErr.value = msg;
  } finally {
    busy.value = false;
  }
}

async function onToggleActive(u: ManagedUser) {
  // ⚠️ 停用是**立刻生效**的破坏性操作 (2026-10-30) ——
  //    以前点一下就直接发请求: 对方手上的 token 当场作废, 下一次请求就被踢,
  //    当场登录不了, 而按钮文案只有两个字「停用」, 没说任何后果.
  //    同一文件里「重置密码」**有**确认框 —— 两个危险操作标准不一致, 这里补齐.
  if (u.is_active) {
    try {
      await ElMessageBox.confirm(
        `停用后「${u.username}」将立刻无法登录（其名下资产会保留，可随时「启用」恢复）。确认停用？`,
        '停用账号',
        {
          type: 'warning',
          confirmButtonText: '确认停用',
          cancelButtonText: '取消',
        },
      );
    } catch {
      return;  // 用户取消 —— 不发请求
    }
  }
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

/**
 * 删除账号 —— **不可逆**, 要**手打账号名**才能删.
 *
 * ⚠️ 为什么光点一下「确定」不够:
 *    账号列表里一行就一个「删除」按钮, 挨着「停用」「改角色」——
 *    点错的概率不低 (以前只弹一个确认框, 一路点「确定」就删了).
 *    删号**没有回收站**: 账号没了就是没了, 名下的资产/软件/文档虽然留着,
 *    但那个身份再也回不来 (也没法再以它发新版本/改说明).
 *    所以沿用知识库「删数据集」那一套 —— **把账号名原样敲出来**才放行.
 *    (本项目刚出过误删 5 篇协议 PDF 的事故, 见交接文档 §㉕⑧)
 *
 * ⚠️ 为什么前端也要拦「删自己」: 后端会返回 400 ("不能删除当前登录的账号"),
 *    但那时用户已经点完确认框、白等了一趟 —— 按钮直接禁用 + title 说明更省事.
 * ⚠️ 删**别的管理员**账号前端不拦: 用户要的就是"管理员也能删",
 *    "至少留一个可用管理员"这条护栏由后端兜底, 前端不越权猜.
 * ⚠️ ElMessageBox 是**纯文本**, 不渲染 Markdown —— 别写 `**强调**`.
 */
async function onDelete(u: ManagedUser) {
  if (busy.value) return;
  if (u.role === 'admin') {
    ElMessage.warning('管理员账号不能删除 —— 请改用「停用」或把角色改成「测试者」');
    return;
  }
  if (isSelf(u)) {
    ElMessage.warning('不能删除当前登录的账号');
    return;
  }
  try {
    await ElMessageBox.prompt(
      `即将删除账号「${u.username}」—— 删除后**无法恢复**，这个账号将立刻无法登录。\n`
      + `它名下的资产、软件、知识库文档会保留（作者名还在），`
      + `但以后没法再以这个账号身份操作。\n`
      + `请输入账号名「${u.username}」以确认：`,
      '删除账号',
      {
        type: 'warning',
        confirmButtonText: '永久删除',
        cancelButtonText: '取消',
        inputPlaceholder: u.username,
        inputValidator: (v: string) =>
          (v || '').trim() === u.username ? true : '账号名对不上 —— 请原样输入上面的账号名',
      },
    );
  } catch {
    return;  // 用户取消 —— 不是错误
  }
  busy.value = true;
  try {
    await deleteUser(u.id);
    ElMessage.success(`已删除账号 ${u.username}`);
    emit('changed');
  } catch (e: any) {
    ElMessage.error(errText(e, '删除失败'));
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
/* ⚠️ 出错的字段标红 (2026-10-30) —— 以前错误统一甩在整行下方,
   密码框红不红根本看不出来, 用户不知道是哪个字段没填 */
.field input.invalid { border-color: var(--err); }
.field input.invalid:focus { box-shadow: 0 0 0 3px rgba(239, 68, 68, 0.15); }
/* 字段级错误: 贴着出问题的那个字段 */
.field-err { font-size: 11.5px; color: var(--err); line-height: 1.4; }
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
/* ⚠️ 删除按钮 = 红字红框, 跟旁边中性的 ghost 按钮区分开 (不可逆的操作不能长得跟"改角色"一样).
   ⚠️ hover 必须**再写一条** .ghost.danger:hover:not(:disabled) ——
   通用规则 .ghost:hover:not(:disabled) 权重更高, 会把红按钮一碰就变成主色蓝. */
.ghost.danger { color: var(--err); border-color: rgba(239, 68, 68, 0.35); }
.ghost.danger:hover:not(:disabled) {
  border-color: var(--err);
  background: rgba(239, 68, 68, 0.08);
  color: var(--err);
}
</style>
