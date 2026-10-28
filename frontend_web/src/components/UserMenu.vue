<template>
  <el-dropdown trigger="click" @command="onCommand">
    <button class="tm-user" type="button">
      <span class="avatar">{{ initial }}</span>
      <span class="name">{{ userStore.user?.username || '未登录' }}</span>
      <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">
        <path d="m6 9 6 6 6-6"/>
      </svg>
    </button>
    <template #dropdown>
      <el-dropdown-menu>
        <el-dropdown-item disabled>
          <div class="dd-head">
            <div class="dd-name">{{ userStore.user?.username || '未登录' }}</div>
            <div class="dd-role">{{ roleText(userStore.user?.role) }}</div>
          </div>
        </el-dropdown-item>
        <!-- ⚠️ 未登录时这两条都不能留 ——
             · 「退出登录」: 你本来就没登录, "退出"谁去? 点了还会弹一句
               "已退出登录" (假的), 纯属误导.
             · 「设置」: 设置页所有接口都要登录, 未登录点进去必然被踢回登录页.
             跟 2026-10-25 那次删死路一个道理 —— 点了没用的菜单项比没有更糟.
             所以未登录时这一格只留「登录」, 登录完菜单自然变成 设置 + 退出登录. -->
        <!-- ⚠️ 「设置」只给 admin (2026-10-28) —— 设置页整个是 adminOnly.
             非管理员进来既改不了, 又是一堆只读项, 纯干扰. 路由守卫也会拦一道
             (手敲地址 / 旧书签都进不去) —— 这里是把**入口**藏掉. -->
        <el-dropdown-item v-if="loggedIn && isAdmin" divided command="settings">设置</el-dropdown-item>
        <el-dropdown-item v-if="loggedIn" command="logout">退出登录</el-dropdown-item>
        <el-dropdown-item v-else divided command="login">登录</el-dropdown-item>
      </el-dropdown-menu>
    </template>
  </el-dropdown>
</template>

<script setup lang="ts">
import { computed } from 'vue';
import { useRouter } from 'vue-router';
import { ElMessage } from 'element-plus';
import { useUserStore } from '@/stores/user';

const router = useRouter();
const userStore = useUserStore();
const initial = computed(() => (userStore.user?.username || '?')[0]?.toUpperCase() || '?');

/**
 * 是否已登录 —— 顶栏下拉靠它切菜单.
 *
 * 取 store 的 getter (!!token), 不看 user 对象:
 *   登录动作是"先拿 token 再拉 /me", 半登录态下 token 有、user 可能还没落,
 *   反过来 clearSession 只清两者, 不会出现"有 user 没 token"的假登录态.
 *   跟 views/Home/index.vue 的 loggedIn 同一口径.
 */
const loggedIn = computed(() => userStore.isLoggedIn);
/** 是不是管理员 —— 决定「设置」入口出不出现 (2026-10-28) */
const isAdmin = computed(() => userStore.isAdmin);

function roleText(r?: string) {
  if (r === 'admin') return '管理员';
  if (r === 'tester') return '测试工程师';
  if (r === 'viewer') return '只读';
  return '-';
}

/**
 * 下拉里只留"身份 + 设置 + 退出登录"三件事 (2026-10-25).
 *
 * 删掉的两个都是**死路**, 点了只会弹一句话:
 *   · 「能力注册 (admin)」→ 只弹一句"这个功能以后才有", 什么都没发生
 *   · 「主题 · ☀ / 🌙 / 自动」→ 只让用户自己去按那个主题按钮, 而它就在旁边
 *   死路菜单项比没有更糟 —— 用户以为有功能, 点一下才发现是空头支票.
 *   主题切换走 AppHeader 的 ThemeSwitcher, 那里一颗按钮就够了.
 *
 * 未登录时菜单只剩「登录」一条 (2026-10-25 补) —— 详见模板里的注释.
 */
function onCommand(cmd: string) {
  if (cmd === 'logout') {
    userStore.logout();
    ElMessage.success('已退出登录');
    router.push('/login');
  } else if (cmd === 'settings') {
    router.push('/settings');
  } else if (cmd === 'login') {
    // ⚠️ 带 redirect —— 用户可能是在某个页面发现没登录才点菜单进来的,
    //    登录完应该回原来那一页, 而不是被丢回首页.
    //    已经在登录页时不重复跳 (会白白把 query 里的 redirect 冲掉).
    if (router.currentRoute.value.path !== '/login') {
      router.push({ path: '/login', query: { redirect: router.currentRoute.value.fullPath } });
    }
  }
}
</script>

<style scoped>
.tm-user {
  display: inline-flex;
  align-items: center;
  gap: 8px;
  height: 32px;
  padding: 0 10px 0 3px;
  background: var(--surface-soft);
  border: 1px solid var(--border);
  color: var(--ink-900);
  border-radius: 8px;
  cursor: pointer;
  font-family: inherit;
  font-size: 13.5px;
  font-weight: 500;
  backdrop-filter: blur(6px);
  -webkit-backdrop-filter: blur(6px);
  transition: border-color .15s ease;
}
.tm-user:hover { border-color: var(--primary); }
.avatar {
  width: 24px; height: 24px;
  border-radius: 6px;
  background: linear-gradient(135deg, var(--primary), var(--primary-2));
  color: #fff;
  font-size: 11px; font-weight: 700;
  display: grid; place-items: center;
}
.name { line-height: 1; }
.dd-head { padding: 4px 0; }
.dd-name { font-size: 13px; font-weight: 600; color: var(--ink-900); }
.dd-role { font-size: 11.5px; color: var(--ink-500); margin-top: 1px; }
</style>
