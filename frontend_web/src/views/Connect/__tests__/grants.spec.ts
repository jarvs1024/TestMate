import { beforeEach, describe, expect, it, vi } from 'vitest';
import { flushPromises, mount, type VueWrapper } from '@vue/test-utils';
import { ElMessageBox, type MessageBoxData } from 'element-plus';
import Grants from '../Grants.vue';

const api = vi.hoisted(() => ({
  previewMcpAuthorization: vi.fn(),
  authorizeMcp: vi.fn(),
  listMcpGrants: vi.fn(),
  revokeMcpGrant: vi.fn(),
  listMcpTokens: vi.fn(),
  createMcpToken: vi.fn(),
  revokeMcpToken: vi.fn(),
}));

vi.mock('@/api/mcp', () => api);
vi.mock('element-plus', () => ({
  ElMessage: { success: vi.fn(), error: vi.fn(), warning: vi.fn() },
  ElMessageBox: { confirm: vi.fn() },
}));

const ACTIVE_GRANT = {
  id: 7,
  client_id: 'client-123',
  client_name: 'CI Assistant',
  scopes: ['market:read', 'market:write'],
  version: 2,
  revoked_at: null,
  created_at: '2026-10-30T08:00:00Z',
  updated_at: '2026-10-31T09:00:00Z',
};

function button(w: VueWrapper, text: string) {
  const found = w.findAll('button').find((item) => item.text().trim() === text);
  if (!found) throw new Error(`找不到按钮: ${text}`);
  return found;
}

async function mountGrants() {
  const wrapper = mount(Grants);
  await flushPromises();
  return wrapper;
}

beforeEach(() => {
  api.listMcpGrants.mockReset();
  api.revokeMcpGrant.mockReset();
  api.listMcpGrants.mockResolvedValue({ items: [ACTIVE_GRANT] });
  api.revokeMcpGrant.mockResolvedValue(undefined);
  vi.mocked(ElMessageBox.confirm).mockReset();
  vi.mocked(ElMessageBox.confirm).mockResolvedValue('confirm' as any);
});

describe('MCP 授权管理', () => {
  it('确认撤销后调用 DELETE，并重新拉取列表', async () => {
    api.listMcpGrants
      .mockResolvedValueOnce({ items: [ACTIVE_GRANT] })
      .mockResolvedValueOnce({ items: [{ ...ACTIVE_GRANT, revoked_at: '2026-10-31T10:00:00Z' }] });
    const w = await mountGrants();

    expect(w.text()).toContain('CI Assistant');
    expect(w.text()).toContain('读取资产');
    await button(w, '撤销授权').trigger('click');
    await flushPromises();

    expect(ElMessageBox.confirm).toHaveBeenCalled();
    expect(api.revokeMcpGrant).toHaveBeenCalledWith(7);
    expect(api.listMcpGrants).toHaveBeenCalledTimes(2);
    expect(w.text()).toContain('已撤销');
    w.unmount();
  });

  it('重复点击只打开一次确认并只撤销和刷新一次', async () => {
    let resolveConfirm: (value: MessageBoxData) => void = () => {};
    let resolveRevoke: () => void = () => {};
    vi.mocked(ElMessageBox.confirm).mockImplementation(() => new Promise((resolve) => {
      resolveConfirm = resolve;
    }));
    api.revokeMcpGrant.mockImplementation(() => new Promise<void>((resolve) => {
      resolveRevoke = resolve;
    }));
    api.listMcpGrants
      .mockResolvedValueOnce({ items: [ACTIVE_GRANT] })
      .mockResolvedValueOnce({ items: [{ ...ACTIVE_GRANT, revoked_at: '2026-10-31T10:00:00Z' }] });
    const w = await mountGrants();
    const revokeButton = button(w, '撤销授权');

    await revokeButton.trigger('click');
    await revokeButton.trigger('click');
    expect(ElMessageBox.confirm).toHaveBeenCalledTimes(1);

    resolveConfirm({} as MessageBoxData);
    await flushPromises();
    await revokeButton.trigger('click');
    await revokeButton.trigger('click');
    expect(api.revokeMcpGrant).toHaveBeenCalledTimes(1);

    resolveRevoke();
    await flushPromises();
    expect(api.revokeMcpGrant).toHaveBeenCalledWith(7);
    expect(api.listMcpGrants).toHaveBeenCalledTimes(2);
    w.unmount();
  });

  it('取消确认时不撤销', async () => {
    vi.mocked(ElMessageBox.confirm).mockRejectedValue('cancel' as any);
    const w = await mountGrants();
    await button(w, '撤销授权').trigger('click');
    await flushPromises();

    expect(api.revokeMcpGrant).not.toHaveBeenCalled();
    expect(api.listMcpGrants).toHaveBeenCalledTimes(1);
    w.unmount();
  });

  it('加载和失败状态清楚分离，错误可重试到空列表', async () => {
    let rejectLoad: (reason: unknown) => void = () => {};
    api.listMcpGrants.mockImplementationOnce(() => new Promise((_resolve, reject) => {
      rejectLoad = reject;
    }));
    const w = mount(Grants);
    await w.vm.$nextTick();
    expect(w.text()).toContain('正在读取授权');

    rejectLoad({ response: { status: 500, data: { detail: '数据库暂不可用' } } });
    await flushPromises();
    expect(w.text()).toContain('数据库暂不可用');
    expect(w.text()).not.toContain('正在读取授权');

    api.listMcpGrants.mockResolvedValueOnce({ items: [] });
    await button(w, '重试').trigger('click');
    await flushPromises();
    expect(w.text()).toContain('还没有 MCP 授权');
    expect(api.listMcpGrants).toHaveBeenCalledTimes(2);
    w.unmount();
  });
});
