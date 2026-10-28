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
import { routes } from '../index';

const router = createRouter({ history: createMemoryHistory(), routes });

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
    for (const p of ['/market', '/kb-manage', '/software', '/settings', '/c/log-analysis']) {
      expect(metaOf(p).publicRead).toBeFalsy();
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
