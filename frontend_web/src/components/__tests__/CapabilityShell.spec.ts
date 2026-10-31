/**
 * 能力身份条 (CapabilityShell) —— **2026-10-31 第十五轮改版**.
 *
 * ⚠️ 这个组件**改了职责**:
 *   以前: 它自己渲染那一行「← 返回工作台 | 图标 | 名称 v版本 | 角色 · 分类 | 状态徽标」;
 *   现在: 身份条**并进页头** (AppHeader) —— 这个组件只负责**把数据交出去**,
 *         自己一个像素都不渲染.
 *
 * 为什么改 (用户原话):
 *   「优化返回工作台那行的内容可以放到最上面和上面的可复用的扩展资产这行内容融合,
 *     同时, 去掉返回工作台这个按钮」
 *   —— 原来页头已经有"插件·技能·连接"了, 下面那条又写一遍, 同一句话说两遍.
 *
 * 要盯住:
 *   ① 身份信息**完整**地交出去 (图标/名称/版本/角色/分类/状态);
 *   ② 组件**不再渲染**任何一行 (DOM 里只剩一个 0 尺寸锚点);
 *   ③ **没有「返回工作台」按钮**了 —— 侧边栏的「全部能力」就是回工作台的入口;
 *   ④ actions 插槽 (看板的时间窗/刷新) 也交给页头右侧;
 *   ⑤ 卸载时**清干净** —— 不然下次进别的页面还挂着上一个的身份.
 */
import { describe, expect, it, beforeEach } from 'vitest';
import { mount } from '@vue/test-utils';
import CapabilityShell from '../CapabilityShell.vue';
import { capActions, capIdentity, clearCapShell } from '@/stores/capShell';

beforeEach(() => {
  clearCapShell();
});

describe('能力身份条 (2026-10-31 第十五轮)', () => {
  it('把身份信息交给页头 (图标 / 名称 / 版本 / 角色 / 分类 / 状态)', () => {
    mount(CapabilityShell, {
      props: {
        name: '插件·技能·连接', icon: '🏪', kind: 'platform', status: 'beta',
        version: 'v0.1.0', category: 'ai-market',
      },
    });
    expect(capIdentity.value).toEqual({
      icon: '🏪', name: '插件·技能·连接', version: 'v0.1.0',
      kind: 'platform', category: 'ai-market', status: 'beta',
    });
  });

  it('组件**不再渲染**那一行 (DOM 里只剩一个 0 尺寸锚点)', () => {
    const w = mount(CapabilityShell, {
      props: { name: 'x', icon: '🛠', kind: 'tool', status: 'stable' },
    });
    // 身份名/角色/分类都不该再由这个组件渲染 (它们在页头里)
    expect(w.text()).not.toContain('x');
    expect(w.find('.sh-name').exists()).toBe(false);
    expect(w.find('.sh-kind').exists()).toBe(false);
    expect(w.find('.sh-badge').exists()).toBe(false);
  });

  it('⚠️ **没有「返回工作台」按钮**了 (用户要求去掉)', () => {
    const w = mount(CapabilityShell, {
      props: { name: 'x', icon: '🛠', kind: 'tool', status: 'stable' },
    });
    expect(w.find('.back').exists()).toBe(false);
    expect(w.text()).not.toContain('返回工作台');
  });

  it('actions 插槽 → 交给页头渲染', () => {
    mount(CapabilityShell, {
      props: { name: 'x', icon: '🛠', kind: 'board', status: 'stable' },
      slots: { actions: '<button class="my-act">刷新</button>' },
    });
    expect(capActions.value).toBeTruthy();
  });

  it('没有 actions 插槽 → 页头那边是空的', () => {
    mount(CapabilityShell, {
      props: { name: 'x', icon: '🛠', kind: 'board', status: 'stable' },
    });
    expect(capActions.value).toBeNull();
  });

  it('卸载时清干净 (不然下次进别的页面还挂着上一个的身份)', () => {
    const w = mount(CapabilityShell, {
      props: { name: 'x', icon: '🛠', kind: 'tool', status: 'stable' },
    });
    expect(capIdentity.value).toBeTruthy();
    w.unmount();
    expect(capIdentity.value).toBeNull();
    expect(capActions.value).toBeNull();
  });
});
