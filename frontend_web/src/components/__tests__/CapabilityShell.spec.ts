/**
 * 能力详情统一外壳 (CapabilityShell).
 *
 * 这个外壳是四个详情页的公共头部 —— 重构前它们各写各的, 长得都不一样.
 * 要盯住:
 *   ① 形态徽标 + 状态徽标都在 (形态说"怎么用", 状态说"能不能用");
 *   ② 状态词按形态换 (看板说"正常", 不说"稳定");
 *   ③ 「← 返回工作台」回到首页, 不是回旧的"广场";
 *   ④ actions 插槽给页面放自己的操作区 (看板的时间窗 / 刷新).
 */
import { describe, expect, it, vi, beforeEach } from 'vitest';
import { mount } from '@vue/test-utils';
import router from '@/router';
import CapabilityShell from '../CapabilityShell.vue';

beforeEach(async () => {
  await router.replace('/');
});

describe('能力详情外壳', () => {
  it('渲染名称 / 图标 / 形态 / 状态 / 摘要', () => {
    const w = mount(CapabilityShell, {
      props: {
        name: '代码检视', icon: '🧬', kind: 'board', status: 'stable',
        summary: 'MR 生命周期 / 建议采纳率', version: 'v0.2.0', category: 'auto-code',
      },
      global: { plugins: [router] },
    });
    expect(w.find('.sh-icon').text()).toBe('🧬');
    expect(w.find('.sh-name').text()).toContain('代码检视');
    expect(w.find('.sh-name').text()).toContain('v0.2.0');
    expect(w.find('.sh-kind').text()).toContain('看板');
    expect(w.find('.sh-cat').text()).toContain('自动化代码');
    expect(w.find('.sh-badge').text()).toContain('正常');
    expect(w.find('.sh-summary').text()).toContain('MR 生命周期');
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
      props: { name: '知识库存', icon: '📚', kind: 'library', status: 'draft' },
      global: { plugins: [router] },
    });
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

  it('没传摘要时不渲染摘要行', () => {
    const w = mount(CapabilityShell, {
      props: { name: 'x', icon: '🛠', kind: 'tool', status: 'stable' },
      global: { plugins: [router] },
    });
    expect(w.find('.sh-summary').exists()).toBe(false);
    w.unmount();
  });
});
