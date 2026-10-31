/**
 * 页头 (AppHeader) —— **能力身份条并进标题行** (2026-10-31 第十五轮).
 *
 * ⚠️ 改版原因 (用户原话):
 *   「优化返回工作台那行的内容可以放到最上面和上面的可复用的扩展资产这行内容融合,
 *     同时, 去掉返回工作台这个按钮」
 *   —— 原来页头写一遍"插件·技能·连接", 下面那条身份条又写一遍, 重复且占行.
 *
 * 要盯住:
 *   ① 身份信息 (图标/版本/角色·分类/状态徽标) 渲染在**标题行**里;
 *   ② lede 仍在第二行 (页面级说明);
 *   ③ 没有身份时 (首页等) → 只显示普通标题, 不多占位;
 *   ④ 页面自己的操作区渲染在右侧 (主题/用户之前).
 */
import { describe, expect, it, beforeEach } from 'vitest';
import { mount } from '@vue/test-utils';
import { createRouter, createMemoryHistory } from 'vue-router';
import { createPinia, setActivePinia } from 'pinia';
import { defineComponent, h } from 'vue';
import AppHeader from '../AppHeader.vue';
import { capActions, clearCapShell, setCapIdentity } from '@/stores/capShell';

const Stub = { template: '<div />' };

function makeRouter() {
  return createRouter({
    history: createMemoryHistory(),
    routes: [
      { path: '/', name: 'home', component: Stub, meta: { title: '工作台', lede: '测试伙伴能干的活都在这儿' } },
      { path: '/market', name: 'market', component: Stub, meta: { title: '插件·技能·连接', lede: '可复用的扩展资产' } },
    ],
  });
}

async function mountHeader(path = '/market') {
  // ⚠️ 页头里有 userStore (pinia) —— 不装 pinia 会直接抛错
  const pinia = createPinia();
  setActivePinia(pinia);
  const router = makeRouter();
  await router.replace(path);
  await router.isReady();
  const w = mount(AppHeader, {
    global: {
      plugins: [router, pinia],
      stubs: {
        BrandLogo: Stub, ThemeSwitcher: Stub, UserMenu: Stub, NoticeBar: Stub,
      },
    },
  });
  await router.isReady();
  return { w, router };
}

beforeEach(() => {
  clearCapShell();
});

describe('页头 · 能力身份条', () => {
  it('身份信息渲染在**标题行**里 (图标 + 版本 + 角色·分类 + 状态)', async () => {
    setCapIdentity({
      icon: '🏪', name: '插件·技能·连接', version: 'v0.1.0',
      kind: 'platform', category: 'ai-market', status: 'beta',
    });
    const { w } = await mountHeader('/market');
    const name = w.find('.pt-name');
    expect(name.exists()).toBe(true);
    expect(name.text()).toContain('插件·技能·连接');
    expect(name.text()).toContain('v0.1.0');
    // 角色 + 分类 + 状态徽标
    expect(w.find('.pt-kind').exists()).toBe(true);
    expect(w.find('.pt-cat').exists()).toBe(true);
    expect(w.find('.pt-badge').text()).toContain('正常');
    // 图标
    expect(w.find('.pt-icon').text()).toBe('🏪');
    w.unmount();
  });

  it('lede 仍在第二行 (页面级说明没丢)', async () => {
    setCapIdentity({
      icon: '🏪', name: '插件·技能·连接', kind: 'platform', status: 'beta',
    });
    const { w } = await mountHeader('/market');
    expect(w.find('.pt-lede').text()).toContain('可复用的扩展资产');
    w.unmount();
  });

  it('没有身份时 (首页) → 只显示普通标题, 不多占位', async () => {
    const { w } = await mountHeader('/');
    expect(w.find('.pt-icon').exists()).toBe(false);
    expect(w.find('.pt-badge').exists()).toBe(false);
    expect(w.find('.pt-name').text()).toContain('工作台');
    w.unmount();
  });

  it('页面自己的操作区渲染在右侧', async () => {
    setCapIdentity({ icon: '🧬', name: '代码检视', kind: 'board', status: 'stable' });
    // ⚠️ 用 render 函数而不是 template —— 测试环境不一定带运行时编译器
    capActions.value = defineComponent({
      render: () => h('button', { class: 'my-act' }, '刷新'),
    });
    const { w } = await mountHeader('/market');
    // ⚠️ `class="cap-actions"` 挂在 <component> 上 → 落到**它自己渲染出的根元素**,
    //    所以是同一个元素带两个类, 不是父子关系
    const act = w.find('.my-act');
    expect(act.exists()).toBe(true);
    expect(act.classes()).toContain('cap-actions');
    w.unmount();
  });
});
