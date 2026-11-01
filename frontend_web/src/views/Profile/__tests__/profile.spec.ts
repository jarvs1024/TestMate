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

    expect(w.text()).toContain('个人中心');
    expect(w.text()).toContain('tester@example.com');
    expect(w.find('[data-test="grants-panel"]').exists()).toBe(true);
    expect(w.find('[data-test="tokens-panel"]').exists()).toBe(false);

    await tab(w, '访问令牌').trigger('click');
    expect(w.find('[data-test="grants-panel"]').exists()).toBe(false);
    expect(w.find('[data-test="tokens-panel"]').exists()).toBe(true);
    w.unmount();
  });
});
