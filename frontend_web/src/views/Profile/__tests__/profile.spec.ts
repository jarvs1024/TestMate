import { describe, expect, it, vi } from 'vitest';
import { mount, type VueWrapper } from '@vue/test-utils';
import Profile from '../index.vue';

const store = vi.hoisted(() => ({
  user: { id: 2, username: 'tester@example.com', role: 'tester' },
}));

vi.mock('@/stores/user', () => ({
  useUserStore: () => store,
}));

function tab(w: VueWrapper, text: string) {
  const found = w.findAll('button').find((item) => item.text().trim() === text);
  if (!found) throw new Error(`找不到标签: ${text}`);
  return found;
}

describe('个人中心', () => {
  it('默认展示授权管理，可切换到访问令牌', async () => {
    const w = mount(Profile, {
      global: {
        stubs: {
          GrantsPanel: { template: '<div data-test="grants-panel" />' },
          McpTokens: { template: '<div data-test="tokens-panel" />' },
        },
      },
    });

    expect(w.find('[data-test="grants-panel"]').exists()).toBe(true);
    expect(w.find('[data-test="tokens-panel"]').exists()).toBe(false);

    await tab(w, '访问令牌').trigger('click');
    expect(w.find('[data-test="grants-panel"]').exists()).toBe(false);
    expect(w.find('[data-test="tokens-panel"]').exists()).toBe(true);
    w.unmount();
  });

  it('页内不再重复标题; 账号挂在动作条右侧', () => {
    const w = mount(Profile, {
      global: {
        stubs: {
          GrantsPanel: { template: '<div data-test="grants-panel" />' },
          McpTokens: { template: '<div data-test="tokens-panel" />' },
        },
      },
    });

    // 标题和 lede 归顶栏 (AppHeader) —— 页内再写一遍就是两个标题
    expect(w.find('h1').exists()).toBe(false);
    expect(w.text()).not.toContain('PERSONAL CENTER');
    // 顶部跟扩展库/软件库共用同一个动作条
    const actions = w.find('.mk-actions');
    expect(actions.exists()).toBe(true);
    expect(actions.find('.kind-tabs').exists()).toBe(true);
    expect(actions.text()).toContain('授权管理');
    expect(actions.text()).toContain('访问令牌');
    expect(actions.text()).toContain('tester@example.com');
    w.unmount();
  });
});
