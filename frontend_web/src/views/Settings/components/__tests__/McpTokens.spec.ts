import { afterAll, beforeEach, describe, expect, it, vi } from 'vitest';
import { flushPromises, mount, type VueWrapper } from '@vue/test-utils';
import { ElMessageBox, type MessageBoxData } from 'element-plus';
import McpTokens from '../McpTokens.vue';

const api = vi.hoisted(() => ({
  previewMcpAuthorization: vi.fn(),
  authorizeMcp: vi.fn(),
  listMcpGrants: vi.fn(),
  revokeMcpGrant: vi.fn(),
  listMcpTokens: vi.fn(),
  listMcpTokenScopes: vi.fn(),
  createMcpToken: vi.fn(),
  deleteMcpToken: vi.fn(),
}));

vi.mock('@/api/mcp', () => api);
vi.mock('element-plus', () => ({
  ElMessage: { success: vi.fn(), error: vi.fn(), warning: vi.fn() },
  ElMessageBox: { confirm: vi.fn() },
}));

const TOKEN = {
  id: 11,
  name: 'CI deploy',
  user_id: 2,
  username: 'publisher@example.com',
  scopes: ['extensions:read', 'extensions:write'],
  expires_at: '2099-01-02T03:04:00.000Z',
  revoked_at: null,
  last_used_at: null,
  created_at: '2026-10-31T10:00:00Z',
  token: 'tm_visible_token',
};

const writeTextMock = vi.fn();
const originalClipboard = navigator.clipboard;

function button(w: VueWrapper, text: string) {
  const found = w.findAll('button').find((item) => item.text().trim() === text);
  if (!found) throw new Error(`找不到按钮: ${text}`);
  return found;
}

async function mountTokens() {
  const wrapper = mount(McpTokens);
  await flushPromises();
  return wrapper;
}

beforeEach(() => {
  api.listMcpTokens.mockReset();
  api.listMcpTokenScopes.mockReset();
  api.createMcpToken.mockReset();
  api.deleteMcpToken.mockReset();
  api.listMcpTokens.mockResolvedValue({ items: [] });
  api.listMcpTokenScopes.mockResolvedValue({ scopes: ['extensions:read', 'extensions:write'] });
  api.createMcpToken.mockResolvedValue(TOKEN);
  api.deleteMcpToken.mockResolvedValue(undefined);
  vi.mocked(ElMessageBox.confirm).mockReset();
  vi.mocked(ElMessageBox.confirm).mockResolvedValue('confirm' as any);
  writeTextMock.mockReset();
  writeTextMock.mockResolvedValue(undefined);
  Object.defineProperty(navigator, 'clipboard', {
    configurable: true,
    value: { writeText: writeTextMock },
  });
});

afterAll(() => {
  Object.defineProperty(navigator, 'clipboard', { configurable: true, value: originalClipboard });
});

describe('个人中心 · 访问令牌', () => {
  it('以本人身份创建令牌，列表直接显示明文并可复制', async () => {
    api.listMcpTokens
      .mockResolvedValueOnce({ items: [] })
      .mockResolvedValueOnce({ items: [TOKEN] });
    const w = await mountTokens();

    await w.get('input[aria-label="令牌名称"]').setValue('CI deploy');
    await w.get('input[type="checkbox"][value="extensions:write"]').setValue(true);
    await w.get('input[aria-label="过期时间（可选）"]').setValue('2099-01-02T03:04');
    await button(w, '创建令牌').trigger('click');
    await flushPromises();

    expect(api.createMcpToken).toHaveBeenCalledWith({
      name: 'CI deploy',
      scopes: ['extensions:read', 'extensions:write'],
      expires_at: new Date('2099-01-02T03:04').toISOString(),
    });
    expect(api.listMcpTokens).toHaveBeenCalledTimes(2);
    expect(w.text()).toContain('tm_visible_token');

    await button(w, '复制').trigger('click');
    await flushPromises();
    expect(writeTextMock).toHaveBeenCalledWith('tm_visible_token');
    expect(button(w, '已复制').exists()).toBe(true);
    w.unmount();
  });

  it('只读账号不能勾选管理资产，也不会提交越权 scope', async () => {
    api.listMcpTokenScopes.mockResolvedValue({ scopes: ['extensions:read'] });
    const w = await mountTokens();

    const write = w.get('input[type="checkbox"][value="extensions:write"]').element as HTMLInputElement;
    expect(write.disabled).toBe(true);
    await w.get('input[aria-label="令牌名称"]').setValue('readonly');
    await button(w, '创建令牌').trigger('click');
    await flushPromises();

    expect(api.createMcpToken).toHaveBeenCalledWith({
      name: 'readonly',
      scopes: ['extensions:read'],
    });
    w.unmount();
  });

  it('确认删除后调用删除接口并刷新列表', async () => {
    api.listMcpTokens
      .mockResolvedValueOnce({ items: [TOKEN] })
      .mockResolvedValueOnce({ items: [] });
    const w = await mountTokens();

    await button(w, '删除').trigger('click');
    await flushPromises();

    expect(ElMessageBox.confirm).toHaveBeenCalled();
    expect(api.deleteMcpToken).toHaveBeenCalledWith(11);
    expect(api.listMcpTokens).toHaveBeenCalledTimes(2);
    expect(w.text()).not.toContain('tm_visible_token');
    w.unmount();
  });

  it('重复点击只打开一次确认并只删除一次', async () => {
    let resolveConfirm: (value: MessageBoxData) => void = () => {};
    let resolveDelete: () => void = () => {};
    vi.mocked(ElMessageBox.confirm).mockImplementation(() => new Promise((resolve) => {
      resolveConfirm = resolve;
    }));
    api.deleteMcpToken.mockImplementation(() => new Promise<void>((resolve) => {
      resolveDelete = resolve;
    }));
    api.listMcpTokens
      .mockResolvedValueOnce({ items: [TOKEN] })
      .mockResolvedValueOnce({ items: [] });
    const w = await mountTokens();
    const deleteButton = button(w, '删除');

    await deleteButton.trigger('click');
    await deleteButton.trigger('click');
    expect(ElMessageBox.confirm).toHaveBeenCalledTimes(1);

    resolveConfirm({} as MessageBoxData);
    await flushPromises();
    await deleteButton.trigger('click');
    expect(api.deleteMcpToken).toHaveBeenCalledTimes(1);

    resolveDelete();
    await flushPromises();
    expect(api.deleteMcpToken).toHaveBeenCalledWith(11);
    expect(api.listMcpTokens).toHaveBeenCalledTimes(2);
    w.unmount();
  });

  it('取消确认时不删除', async () => {
    vi.mocked(ElMessageBox.confirm).mockRejectedValue('cancel' as any);
    api.listMcpTokens.mockResolvedValue({ items: [TOKEN] });
    const w = await mountTokens();

    await button(w, '删除').trigger('click');
    await flushPromises();

    expect(api.deleteMcpToken).not.toHaveBeenCalled();
    expect(api.listMcpTokens).toHaveBeenCalledTimes(1);
    w.unmount();
  });

  it('列表加载失败可重试，历史令牌没有明文时给出说明', async () => {
    let rejectLoad: (reason: unknown) => void = () => {};
    api.listMcpTokens.mockImplementationOnce(() => new Promise((_resolve, reject) => {
      rejectLoad = reject;
    }));
    const w = await mountTokens();

    expect(w.text()).toContain('正在读取访问令牌');
    rejectLoad({ response: { status: 503, data: { detail: '令牌服务暂不可用' } } });
    await flushPromises();
    expect(w.text()).not.toContain('正在读取访问令牌');
    expect(w.text()).toContain('令牌服务暂不可用');

    api.listMcpTokens.mockResolvedValueOnce({ items: [{ ...TOKEN, token: null }] });
    await button(w, '重试').trigger('click');
    await flushPromises();
    expect(w.text()).toContain('该令牌创建于明文可见功能上线前');
    expect(w.findAll('button').some((item) => item.text().trim() === '复制')).toBe(false);
    w.unmount();
  });
});
