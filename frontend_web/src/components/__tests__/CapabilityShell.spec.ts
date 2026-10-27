/**
 * 能力详情统一外壳 (CapabilityShell).
 *
 * 这个外壳是四个详情页的公共头部 —— 重构前它们各写各的, 长得都不一样.
 * 要盯住:
 *   ① 角色徽标 + 状态徽标都在 (角色说"扮演什么", 状态说"能不能用");
 *   ② 状态词按角色换 (看板说"正常", 不说"稳定");
 *   ③ 「← 返回工作台」回到首页, 不是回旧的"广场";
 *   ④ actions 插槽给页面放自己的操作区 (看板的时间窗 / 刷新);
 *   ⑤ **外壳里没有描述行** (2026-10-25 第四轮): 页头已经有 lede,
 *      外壳再写一遍就是同一句话说两遍 —— 描述归位到正文.
 */
import { describe, expect, it, vi, beforeEach } from 'vitest';
import { mount } from '@vue/test-utils';
import router from '@/router';
import CapabilityShell from '../CapabilityShell.vue';

beforeEach(async () => {
  await router.replace('/');
});

describe('能力详情外壳', () => {
  it('渲染名称 / 图标 / 角色 / 状态', () => {
    const w = mount(CapabilityShell, {
      props: {
        name: '代码检视', icon: '🧬', kind: 'board', status: 'stable',
        version: 'v0.2.0', category: 'auto-code',
      },
      global: { plugins: [router] },
    });
    expect(w.find('.sh-icon').text()).toBe('🧬');
    expect(w.find('.sh-name').text()).toContain('代码检视');
    expect(w.find('.sh-ver').text()).toContain('v0.2.0');
    expect(w.find('.sh-kind').text()).toContain('看板');
    expect(w.find('.sh-cat').text()).toContain('自动化代码');
    expect(w.find('.sh-badge').text()).toContain('正常');
    w.unmount();
  });

  /**
   * 外壳不再有描述行 —— 页头 (AppHeader) 的 lede 已经承担了这句描述.
   * 留着就是同一句话说两遍 (用户反馈"描述重复了").
   */
  it('外壳里没有描述行 (描述归位到正文, 不跟页头重复)', () => {
    const w = mount(CapabilityShell, {
      props: {
        name: '代码检视', icon: '🧬', kind: 'board', status: 'stable',
        version: 'v0.2.0', category: 'auto-code',
      },
      global: { plugins: [router] },
    });
    expect(w.find('.sh-summary').exists()).toBe(false);
    // 身份信息压在一行上 —— 没有第二个行块
    expect(w.find('.sh-title').exists()).toBe(false);
    w.unmount();
  });

  it('工具型的状态词是「规划中」, 不是看板的「未接入」', () => {
    const tool = mount(CapabilityShell, {
      props: { name: '日志分析', icon: '📜', kind: 'tool', status: 'draft' },
      global: { plugins: [router] },
    });
    expect(tool.find('.sh-badge').text()).toContain('规划中');
    tool.unmount();

    const lib = mount(CapabilityShell, {
      props: { name: '知识库', icon: '📚', kind: 'platform', status: 'draft' },
      global: { plugins: [router] },
    });
    expect(lib.find('.sh-kind').text()).toContain('资产');
    expect(lib.find('.sh-badge').text()).toContain('未接入');
    lib.unmount();
  });

  it('「← 返回工作台」回到首页', async () => {
    const push = vi.spyOn(router, 'push').mockResolvedValue(undefined as any);
    const w = mount(CapabilityShell, {
      props: { name: 'x', icon: '🛠', kind: 'tool', status: 'stable' },
      global: { plugins: [router] },
    });
    expect(w.find('.back').text()).toContain('返回工作台');
    await w.find('.back').trigger('click');
    expect(push).toHaveBeenCalledWith({ name: 'home' });
    push.mockRestore();
    w.unmount();
  });

  it('actions 插槽能塞页面自己的操作区', () => {
    const w = mount(CapabilityShell, {
      props: { name: 'x', icon: '🛠', kind: 'tool', status: 'stable' },
      slots: { actions: '<button class="my-act">刷新</button>' },
      global: { plugins: [router] },
    });
    expect(w.find('.sh-actions .my-act').exists()).toBe(true);
    w.unmount();
  });
});
