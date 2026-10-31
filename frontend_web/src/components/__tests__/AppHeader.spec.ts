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
import { mount, flushPromises } from '@vue/test-utils';
import { createRouter, createMemoryHistory } from 'vue-router';
import { createPinia, setActivePinia } from 'pinia';
import { defineComponent, h } from 'vue';
import AppHeader from '../AppHeader.vue';
import { capActions, clearCapShell, setCapIdentity } from '@/stores/capShell';
import { platformName, platformTagline, platformVersion } from '@/stores/platform';

const Stub = { template: '<div />' };

// ⚠️ 2026-10-31 (第十八轮): 页头要显示**平台信息** (名称/副标题/版本号) ——
//    数据在 `@/stores/platform` 这个共享模块里 (启动时加载一次).
//    这里直接设值, 别让单测真发网络请求.
function setPlatformInfo(v: { name?: string; version?: string; tagline?: string }) {
  platformName.value = v.name ?? 'TestMate';
  platformVersion.value = v.version ?? '1.0.0';
  platformTagline.value = v.tagline ?? '智能测试辅助平台';
}

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
  setPlatformInfo({});
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

/**
 * 平台名称 / 副标题 / 版本号 (2026-10-31 第十八轮).
 *
 * ⚠️ 这三样以前是**写死**的:
 *   · 副标题写死 "SSD 测试伙伴" —— 但平台早就不只是 SSD 相关了;
 *   · 版本号取后端 APP_VERSION (config.py 里写死), 改一次要发版.
 * 现在都从**设置项**里取 (`general.platform_*`), 管理员改完立刻生效.
 */
describe('页头 · 平台名称/副标题/版本号走设置项', () => {
  it('副标题 + 版本号显示设置项里的值', async () => {
    setPlatformInfo({ version: '2.3.4', tagline: '资产协作平台' });
    const { w } = await mountHeader('/market');
    await flushPromises();
    expect(w.find('.t2').text()).toContain('资产协作平台');
    expect(w.find('.t2').text()).toContain('v2.3.4');
    w.unmount();
  });

  it('平台显示名也走设置项', async () => {
    setPlatformInfo({ name: '质量助手' });
    const { w } = await mountHeader('/market');
    await flushPromises();
    expect(w.find('.t1').text()).toBe('质量助手');
    w.unmount();
  });

  it('⚠️ 接口挂了 → 用兜底默认值, 不能显示空白 (更不能是"SSD 测试伙伴"那种旧文案)', async () => {
    // ⚠️ 兜底默认值 = 共享模块的初始值 (接口没回来时的样子)
    const { w } = await mountHeader('/market');
    await flushPromises();
    const t2 = w.find('.t2').text();
    expect(t2).toContain('智能测试辅助平台');
    expect(t2).toContain('v1.0.0');
    expect(t2).not.toContain('SSD');
    w.unmount();
  });
});

/**
 * 页头状态徽标的**颜色** (2026-10-31 第十九轮).
 *
 * ⚠️ 用户投诉「顶部页头也是」: 徽标 class 以前按**原始 status** 生成,
 *    资产的 beta (st-beta 橙) 跟看板的 stable (st-stable 绿) **文案都是「正常」** ——
 *    同一句话两个颜色. 现在按**语义色调**生成.
 */
describe('页头 · 状态徽标按语义色调上色', () => {
  it('资产的 beta 文案是「正常」→ class 是 st-ok (不是 st-beta)', async () => {
    setCapIdentity({
      icon: '🏪', name: '插件·技能·连接', kind: 'platform', category: 'ai-market', status: 'beta',
    });
    const { w } = await mountHeader('/market');
    const badge = w.find('.pt-badge');
    expect(badge.text()).toContain('正常');
    expect(badge.classes()).toContain('st-ok');
    expect(badge.classes()).not.toContain('st-beta');
    expect(badge.classes()).not.toContain('st-stable');
    w.unmount();
  });

  it('看板的 stable 也是绿色 st-ok —— 跟资产的 beta 同一个色调', async () => {
    setCapIdentity({ icon: '🧬', name: '代码检视', kind: 'board', status: 'stable' });
    const { w } = await mountHeader('/market');
    const badge = w.find('.pt-badge');
    expect(badge.text()).toContain('正常');
    expect(badge.classes()).toContain('st-ok');
    w.unmount();
  });

  it('工具的 beta 是公测 → 橙色 st-warn', async () => {
    setCapIdentity({ icon: '🛠', name: '日志分析', kind: 'tool', status: 'beta' });
    const { w } = await mountHeader('/market');
    const badge = w.find('.pt-badge');
    expect(badge.text()).toContain('公测');
    expect(badge.classes()).toContain('st-warn');
    w.unmount();
  });
});
