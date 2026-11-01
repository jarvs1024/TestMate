/**
 * 路由表 (2026-10-25 能力墙重构后).
 *
 * 盯住的是**契约**, 不是实现:
 *   ① 首页 = 能力墙, 匿名可读 (publicRead);
 *   ② 旧地址 (/plaza、/agents/:code) 要跳转, 不能 404 —— 同事的浏览器书签还在;
 *   ③ 除首页和代码检视外, 其余页面都要登录;
 *   ④ 四个能力详情页各就各位.
 *
 * ⚠️ 跳转类断言必须**真导航** (`router.push`) —— `router.resolve()` 只做匹配,
 *    不会跟着 redirect 走, 拿它断言会误判成"没跳转".
 */
import { describe, expect, it, beforeAll } from 'vitest';
import { createRouter, createMemoryHistory } from 'vue-router';
import { createPinia, setActivePinia } from 'pinia';
import { useUserStore } from '@/stores/user';
import appRouter, { routes } from '../index';

const router = createRouter({ history: createMemoryHistory(), routes });

const OAUTH_AUTHORIZE_PATH = '/connect/authorize?client_id=client%2Fci&redirect_uri=https%3A%2F%2Fclient.example%2Fcb%3Fa%3D1%26b%3Dtwo&response_type=code&scope=market%3Aread%20market%3Awrite&code_challenge=a-%2B%2F%3D&code_challenge_method=S256&state=x%20%26%3D%2B%2F%25';
const LOGIN_REDIRECT_PATH = '/login?redirect=/connect/authorize?client_id=client%252Fci%26redirect_uri=https%253A%252F%252Fclient.example%252Fcb%253Fa%253D1%2526b%253Dtwo%26response_type=code%26scope=market%253Aread%2520market%253Awrite%26code_challenge=a-%252B%252F%253D%26code_challenge_method=S256%26state=x%2520%2526%253D%252B%252F%2525';

beforeAll(() => {
  // 登录态 —— 否则守卫会把受保护页面踢去 /login, 断言就测不到跳转本身
  const pinia = createPinia();
  setActivePinia(pinia);
  useUserStore(pinia).token = 'test-token';
});

function metaOf(path: string) {
  return router.resolve(path).meta;
}

describe('路由表', () => {
  it('首页是能力墙, 匿名可读', () => {
    const r = router.resolve('/');
    expect(r.name).toBe('home');
    expect(r.meta.publicRead).toBe(true);
    expect(r.meta.title).toBe('工作台');
  });

  it('旧地址 /plaza 跳回首页 (旧书签不 404)', async () => {
    await router.push('/plaza');
    expect(router.currentRoute.value.name).toBe('home');
    expect(router.currentRoute.value.path).toBe('/');
  });

  it('旧地址 /agents/:code 跳到工具型运行页', async () => {
    await router.push('/agents/log-analysis');
    expect(router.currentRoute.value.path).toBe('/c/log-analysis');
    expect(router.currentRoute.value.name).toBe('tool-runner');
  });

  it('代码检视是看板, 保持匿名可读', () => {
    const r = router.resolve('/code-review');
    expect(r.name).toBe('code-review');
    expect(r.meta.publicRead).toBe(true);
    expect(r.meta.title).toBe('代码检视');
  });

  it('目录型 / 知识型 各就各位', () => {
    expect(router.resolve('/market').name).toBe('market');
    expect(router.resolve('/kb-manage').name).toBe('kb-manage');
    expect(router.resolve('/kb-manage').meta.title).toBe('知识库');
  });

  it('软件库是独立页面 (不塞进 /market 的 Tab)', () => {
    const r = router.resolve('/software');
    expect(r.name).toBe('software');
    expect(r.meta.title).toBe('软件库');
    // 要登录才能看 —— 软件包是内网资产
    expect(r.meta.publicRead).toBeFalsy();
  });

  it('除首页和代码检视外, 其余都要登录', () => {
    for (const p of ['/market', '/kb-manage', '/software', '/settings', '/c/log-analysis', '/connect/authorize', '/connect/grants', '/profile']) {
      expect(metaOf(p).publicRead).toBeFalsy();
      expect(metaOf(p).requiresAuth).toBe(true);
    }
  });

  it('MCP 同意页与授权管理位于 MainLayout 的 /connect 下', () => {
    for (const p of ['/connect/authorize', '/connect/grants']) {
      const resolved = router.resolve(p);
      expect(resolved.matched).toHaveLength(2);
      expect(resolved.matched[0].path).toBe('/');
      expect(resolved.meta.requiresAuth).toBe(true);
    }
  });

  it('个人中心位于 MainLayout 下并承载授权与令牌', () => {
    const resolved = router.resolve('/profile');
    expect(resolved.name).toBe('profile');
    expect(resolved.meta.title).toBe('个人中心');
    expect(resolved.meta.lede).toBe('管理授权与访问令牌');
    expect(resolved.matched[0].path).toBe('/');
    expect(resolved.meta.requiresAuth).toBe(true);
  });

  it('未登录真实导航保留完整 OAuth query，登录后按 redirect 返回原地址', async () => {
    const userStore = useUserStore();
    userStore.token = '';
    try {
      await appRouter.push(OAUTH_AUTHORIZE_PATH);

      expect(appRouter.currentRoute.value.name).toBe('login');
      expect(appRouter.currentRoute.value.fullPath).toBe(LOGIN_REDIRECT_PATH);
      expect(appRouter.currentRoute.value.query.redirect).toBe(OAUTH_AUTHORIZE_PATH);

      userStore.token = 'test-token';
      await appRouter.push(appRouter.currentRoute.value.query.redirect as string);
      expect(appRouter.currentRoute.value.name).toBe('mcp-authorize');
      expect(appRouter.currentRoute.value.fullPath).toBe(OAUTH_AUTHORIZE_PATH);
    } finally {
      userStore.token = 'test-token';
    }
  });

  it('用户侧文案不再出现「智能体广场」', () => {
    expect(JSON.stringify(routes)).not.toContain('智能体广场');
  });

  // ⚠️ 2026-10-28: 设置页整个 **adminOnly** ——
  //    设置项里全是平台级配置 (存储路径 / 仓库地址 / 审核白名单 / 账号管理),
  //    非管理员既改不了, 又是一屏机密. 路由守卫拦一道 (手敲地址 / 旧书签都进不去).
  it('设置页是 adminOnly', () => {
    expect(router.resolve('/settings').meta.adminOnly).toBe(true);
  });

  it('别的页面不该被误标成 adminOnly', () => {
    for (const p of ['/market', '/kb-manage', '/software', '/']) {
      expect(metaOf(p).adminOnly).toBeFalsy();
    }
  });
});
