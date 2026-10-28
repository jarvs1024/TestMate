/**
 * 用户菜单 (UserMenu) —— 顶栏右上角的账号下拉.
 *
 * 为什么盯这个 (2026-10-25):
 *   下拉里原来有两条**死路** —— 点了只弹一句话, 什么都不发生:
 *     · 「能力注册 (admin)」→ 只弹 "能力注册 · P1 实现"
 *     · 「主题 · ☀ / 🌙 / 自动」→ 只弹 "点顶栏 ☀/🌙 切换主题"
 *       (顶栏那颗太阳就在旁边, 这条是纯废话)
 *   死路菜单项比没有更糟 —— 用户以为有功能, 点一下才发现是空头支票.
 *
 * 所以下拉现在只留三件事: 身份 → 设置 → 退出登录.
 *
 * ⚠️ 同一天的第二个坑: **未登录时不该显示「退出登录」**.
 *   你本来就没登录, "退出"谁去? 点了还会弹一句假的 "已退出登录".
 *   「设置」同理 —— 设置页所有接口都要登录, 未登录点进去必然被踢回登录页.
 *   跟删死路一个道理: 未登录时这一格只留「登录」, 登录完自然变成 设置 + 退出登录.
 */
import { describe, expect, it, vi, beforeEach } from 'vitest';
import { mount } from '@vue/test-utils';
import { createPinia, setActivePinia } from 'pinia';
import { readFileSync } from 'node:fs';
import { resolve } from 'node:path';

const { pushMock } = vi.hoisted(() => ({ pushMock: vi.fn() }));

// 只 mock 用得到的两个 —— 真路由会把 /login 的 .vue 懒加载进来 (连带一堆 API 模块),
// 测试里没桩全会在 import 阶段炸, 导航被中止, 断言看起来像"功能没实现".
vi.mock('vue-router', () => ({
  useRouter: () => ({
    push: pushMock,
    currentRoute: { value: { path: '/code-review', fullPath: '/code-review' } },
  }),
}));

vi.mock('element-plus', () => ({
  ElMessage: { success: vi.fn(), error: vi.fn(), warning: vi.fn() },
}));

const SRC = readFileSync(resolve(process.cwd(), 'src/components/UserMenu.vue'), 'utf8');
/** 只看 <template> —— 注释里可以写"以前有过这两条", 不该被当成还留着 */
const TPL = SRC.slice(SRC.indexOf('<template>'), SRC.indexOf('</template>'));

/**
 * element-plus 的下拉是 teleport 到 body 的, 直接 mount 看不到菜单项.
 * 换成"就地渲染"的桩 —— 菜单项照样能查, 但不用去 body 里捞.
 */
const stubs = {
  'el-dropdown': {
    name: 'ElDropdown',
    props: ['trigger'],
    emits: ['command'],
    template: '<div class="dd-stub"><slot /><slot name="dropdown" /></div>',
  },
  'el-dropdown-menu': { template: '<div class="dd-menu-stub"><slot /></div>' },
  'el-dropdown-item': {
    name: 'ElDropdownItem',
    props: ['command', 'disabled', 'divided'],
    template: '<div class="dd-item-stub" :data-command="command"><slot /></div>',
  },
};

async function mountMenu(opts: { loggedIn?: boolean; role?: 'admin' | 'tester' | 'viewer' } = {}) {
  const pinia = createPinia();
  setActivePinia(pinia);
  const { useUserStore } = await import('@/stores/user');
  const userStore = useUserStore(pinia);
  if (opts.loggedIn) {
    userStore.token = 'test-token';
    const role = opts.role || 'tester';
    userStore.user = { id: 1, username: role === 'admin' ? 'admin' : 'tester', role } as any;
  }
  const UserMenu = (await import('../UserMenu.vue')).default;
  const w = mount(UserMenu, { global: { plugins: [pinia], stubs } });
  return { w, userStore };
}

/** 当前渲染出来的菜单项 command 列表 (顺序 = 渲染顺序) */
function commands(w: any): string[] {
  return w.findAll('[data-command]').map((el: any) => el.attributes('data-command'));
}

/** 模拟点某个菜单项 —— 直接触发 el-dropdown 的 command 事件 */
async function clickItem(w: any, cmd: string) {
  w.findComponent({ name: 'ElDropdown' }).vm.$emit('command', cmd);
  await w.vm.$nextTick();
}

beforeEach(() => {
  pushMock.mockReset();
});

describe('用户菜单', () => {
  it('下拉里没有「能力注册」和「主题」两条死路', () => {
    expect(TPL).not.toContain('能力注册');
    expect(TPL).not.toContain('command="theme"');
    expect(TPL).not.toContain('command="agents"');
  });

  it('对应的占位提示也一并没了 (不是换个地方继续弹)', () => {
    expect(SRC).not.toContain('P1 实现');
    expect(SRC).not.toContain('点顶栏');
  });

  it('模板里三条命令都还在 (状态决定显示哪几条)', () => {
    expect(TPL).toContain('command="settings"');
    expect(TPL).toContain('command="logout"');
    expect(TPL).toContain('command="login"');
    expect(TPL).toContain('dd-head');       // 身份头 (用户名 + 角色)
  });

  it('主题切换走顶栏的 ThemeSwitcher (下拉里不再重复一份)', () => {
    const header = readFileSync(resolve(process.cwd(), 'src/components/AppHeader.vue'), 'utf8');
    expect(header).toContain('<ThemeSwitcher');
  });
});

describe('用户菜单 · 登录态', () => {
  it('已登录: 退出登录, 没有「登录」', async () => {
    const { w } = await mountMenu({ loggedIn: true });
    // ⚠️ 普通账号看不到「设置」 (设置页 adminOnly, 2026-10-28)
    expect(commands(w)).toEqual(['logout']);
    expect(w.text()).toContain('tester');
    expect(w.text()).toContain('测试工程师');
    w.unmount();
  });

  it('已登录: 点「退出登录」→ 清会话并回登录页', async () => {
    const { w, userStore } = await mountMenu({ loggedIn: true });
    await clickItem(w, 'logout');
    expect(userStore.token).toBe('');
    expect(userStore.user).toBeNull();
    expect(pushMock).toHaveBeenCalledWith('/login');
    w.unmount();
  });

  it('已登录 (admin): 点「设置」→ 跳设置页', async () => {
    const { w } = await mountMenu({ loggedIn: true, role: 'admin' });
    await clickItem(w, 'settings');
    expect(pushMock).toHaveBeenCalledWith('/settings');
    w.unmount();
  });

  // ⚠️ 2026-10-28: 设置页整个只给管理员 —— 非管理员的菜单里**不该有「设置」**.
  //    (以前是"能进但改不了", 现在根本进不去 —— 路由守卫也会拦一道)
  it('已登录 (非 admin): 菜单里**没有**「设置」', async () => {
    const { w } = await mountMenu({ loggedIn: true, role: 'tester' });
    expect(commands(w)).toEqual(['logout']);
    expect(w.text()).not.toContain('设置');
    w.unmount();
  });

  it('已登录 (只读角色): 菜单里**没有**「设置」', async () => {
    const { w } = await mountMenu({ loggedIn: true, role: 'viewer' });
    expect(commands(w)).toEqual(['logout']);
    w.unmount();
  });
});

describe('用户菜单 · 未登录', () => {
  it('未登录: 只剩「登录」, 不显示「退出登录」和「设置」', async () => {
    const { w } = await mountMenu();
    expect(commands(w)).toEqual(['login']);
    expect(w.text()).not.toContain('退出登录');
    expect(w.text()).not.toContain('设置');
    w.unmount();
  });

  it('未登录: 顶栏显示「未登录」', async () => {
    const { w } = await mountMenu();
    expect(w.text()).toContain('未登录');
    w.unmount();
  });

  it('未登录: 点「登录」→ 跳登录页, 带 redirect 回跳', async () => {
    const { w } = await mountMenu();
    await clickItem(w, 'login');
    expect(pushMock).toHaveBeenCalledWith({
      path: '/login',
      query: { redirect: '/code-review' },
    });
    w.unmount();
  });

  it('登录成功后菜单自动变成 退出登录 (普通账号)', async () => {
    const { w, userStore } = await mountMenu();
    expect(commands(w)).toEqual(['login']);
    userStore.token = 'test-token';
    userStore.user = { id: 1, username: 'tester', role: 'tester' } as any;
    await w.vm.$nextTick();
    // ⚠️ 普通账号看不到「设置」 (设置页 adminOnly)
    expect(commands(w)).toEqual(['logout']);
    w.unmount();
  });

  it('登录成功 (admin) 后菜单是 设置 + 退出登录', async () => {
    const { w, userStore } = await mountMenu();
    userStore.token = 'test-token';
    userStore.user = { id: 1, username: 'admin', role: 'admin' } as any;
    await w.vm.$nextTick();
    expect(commands(w)).toEqual(['settings', 'logout']);
    w.unmount();
  });
});
