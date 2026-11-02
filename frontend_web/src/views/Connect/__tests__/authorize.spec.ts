import { afterAll, beforeEach, describe, expect, it, vi } from 'vitest';
import { flushPromises, mount, type VueWrapper } from '@vue/test-utils';
import { createMemoryHistory, createRouter } from 'vue-router';
import Authorize from '../Authorize.vue';

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

const OAUTH_QUERY = {
  client_id: 'client-123',
  redirect_uri: 'https://client.example/callback?existing=kept',
  response_type: 'code',
  scope: 'extensions:read extensions:write',
  code_challenge: 'challenge-abc',
  code_challenge_method: 'S256',
  state: 'state with spaces/&',
};

const PREVIEW = {
  client_id: 'client-123',
  client_name: 'CI Assistant',
  redirect_uri: 'https://client.example/callback?existing=kept',
  scopes: ['extensions:read', 'extensions:write'],
  response_type: 'code',
  code_challenge: 'challenge-abc',
  code_challenge_method: 'S256',
  state: 'state with spaces/&',
};

const NEW_QUERY = {
  ...OAUTH_QUERY,
  client_id: 'client-new',
  redirect_uri: 'https://new.example/callback',
  code_challenge: 'challenge-new',
  state: 'new-state',
};

const NEW_PREVIEW = {
  ...PREVIEW,
  client_id: 'client-new',
  client_name: 'New Assistant',
  redirect_uri: 'https://new.example/callback',
  scopes: ['extensions:read'],
  code_challenge: 'challenge-new',
  state: 'new-state',
};

const assignMock = vi.fn();
const originalLocation = window.location;

function button(w: VueWrapper, text: string) {
  const found = w.findAll('button').find((item) => item.text().trim() === text);
  if (!found) throw new Error(`找不到按钮: ${text}`);
  return found;
}

async function mountAuthorize() {
  const router = createRouter({
    history: createMemoryHistory(),
    routes: [{ path: '/connect/authorize', component: Authorize }],
  });
  await router.push({ path: '/connect/authorize', query: OAUTH_QUERY });
  await router.isReady();
  const wrapper = mount(Authorize, { global: { plugins: [router] } });
  await flushPromises();
  return { wrapper, router };
}

beforeEach(() => {
  api.previewMcpAuthorization.mockReset();
  api.authorizeMcp.mockReset();
  api.previewMcpAuthorization.mockResolvedValue(PREVIEW);
  api.authorizeMcp.mockResolvedValue({ callback_url: 'https://client.example/callback?code=one-time-code' });
  assignMock.mockReset();
  Object.defineProperty(window, 'location', {
    configurable: true,
    value: { assign: assignMock },
  });
});

afterAll(() => {
  Object.defineProperty(window, 'location', { configurable: true, value: originalLocation });
});

describe('MCP 授权同意页', () => {
  it('展示客户端身份和预览返回的读写权限，不按角色补权限', async () => {
    const { wrapper: w } = await mountAuthorize();

    expect(w.text()).toContain('CI Assistant');
    expect(w.text()).toContain('client-123');
    expect(w.text()).toContain('读取资产');
    expect(w.text()).toContain('管理资产');
    expect(w.findAll('input[type="checkbox"]')).toHaveLength(2);
    expect(api.previewMcpAuthorization).toHaveBeenCalledWith(OAUTH_QUERY);
    w.unmount();
  });

  it('同意时提交已验证字段和 narrowed scopes，并整页跳转 callback_url', async () => {
    const { wrapper: w } = await mountAuthorize();
    await w.get('input[type="checkbox"][value="extensions:write"]').setValue(false);
    await button(w, '同意授权').trigger('click');
    await flushPromises();

    expect(api.authorizeMcp).toHaveBeenCalledWith({
      client_id: 'client-123',
      redirect_uri: 'https://client.example/callback?existing=kept',
      scopes: ['extensions:read'],
      response_type: 'code',
      code_challenge: 'challenge-abc',
      code_challenge_method: 'S256',
      state: 'state with spaces/&',
    });
    expect(assignMock).toHaveBeenCalledWith('https://client.example/callback?code=one-time-code');
    w.unmount();
  });

  it('拒绝时保留 redirect_uri 原查询，返回 access_denied 和 state', async () => {
    const { wrapper: w } = await mountAuthorize();
    await button(w, '拒绝').trigger('click');

    expect(api.authorizeMcp).not.toHaveBeenCalled();
    expect(assignMock).toHaveBeenCalledTimes(1);
    const target = new URL(assignMock.mock.calls[0][0]);
    expect(target.origin + target.pathname).toBe('https://client.example/callback');
    expect(target.searchParams.get('existing')).toBe('kept');
    expect(target.searchParams.get('error')).toBe('access_denied');
    expect(target.searchParams.get('state')).toBe('state with spaces/&');
    w.unmount();
  });

  it('预览失败时禁用操作；重试成功后恢复授权', async () => {
    api.previewMcpAuthorization.mockRejectedValueOnce({
      response: { status: 400, data: { detail: { error: 'invalid_client', error_description: '未知客户端' } } },
    });
    const { wrapper: w } = await mountAuthorize();

    expect(w.text()).toContain('未知客户端');
    expect((button(w, '同意授权').element as HTMLButtonElement).disabled).toBe(true);
    expect((button(w, '拒绝').element as HTMLButtonElement).disabled).toBe(true);
    expect(api.authorizeMcp).not.toHaveBeenCalled();

    await button(w, '重试').trigger('click');
    await flushPromises();
    expect(w.text()).toContain('CI Assistant');
    expect((button(w, '同意授权').element as HTMLButtonElement).disabled).toBe(false);
    expect((button(w, '拒绝').element as HTMLButtonElement).disabled).toBe(false);
    expect(api.previewMcpAuthorization).toHaveBeenCalledTimes(2);
    w.unmount();
  });

  it('同路由 query 变化立即作废旧预览与操作，并加载新授权请求', async () => {
    let resolveNew: (value: typeof NEW_PREVIEW) => void = () => {};
    api.previewMcpAuthorization
      .mockResolvedValueOnce(PREVIEW)
      .mockImplementationOnce(() => new Promise((resolve) => { resolveNew = resolve; }));
    const { wrapper: w, router } = await mountAuthorize();
    expect(w.text()).toContain('CI Assistant');

    await router.push({ path: '/connect/authorize', query: NEW_QUERY });
    await w.vm.$nextTick();

    expect(w.text()).not.toContain('CI Assistant');
    expect(w.text()).toContain('正在验证授权请求');
    expect((button(w, '同意授权').element as HTMLButtonElement).disabled).toBe(true);
    expect((button(w, '拒绝').element as HTMLButtonElement).disabled).toBe(true);
    await button(w, '同意授权').trigger('click');
    await button(w, '拒绝').trigger('click');
    expect(api.authorizeMcp).not.toHaveBeenCalled();
    expect(assignMock).not.toHaveBeenCalled();
    expect(api.previewMcpAuthorization).toHaveBeenNthCalledWith(2, NEW_QUERY);

    resolveNew(NEW_PREVIEW);
    await flushPromises();
    expect(w.text()).toContain('New Assistant');
    expect(w.text()).toContain('client-new');
    expect(w.findAll('input[type="checkbox"]')).toHaveLength(1);
    w.unmount();
  });

  it('旧 preview 响应晚于新响应到达时不能覆盖新预览', async () => {
    let resolveOld: (value: typeof PREVIEW) => void = () => {};
    let resolveNew: (value: typeof NEW_PREVIEW) => void = () => {};
    api.previewMcpAuthorization
      .mockImplementationOnce(() => new Promise((resolve) => { resolveOld = resolve; }))
      .mockImplementationOnce(() => new Promise((resolve) => { resolveNew = resolve; }));
    const { wrapper: w, router } = await mountAuthorize();

    await router.push({ path: '/connect/authorize', query: NEW_QUERY });
    resolveNew(NEW_PREVIEW);
    await flushPromises();
    expect(w.text()).toContain('New Assistant');

    resolveOld(PREVIEW);
    await flushPromises();
    expect(w.text()).toContain('New Assistant');
    expect(w.text()).not.toContain('CI Assistant');
    expect(api.previewMcpAuthorization).toHaveBeenCalledTimes(2);
    w.unmount();
  });

  it('授权提交在途时切换 query，旧响应不能触发客户端跳转', async () => {
    let resolveAuthorize: (value: { callback_url: string }) => void = () => {};
    api.previewMcpAuthorization
      .mockResolvedValueOnce(PREVIEW)
      .mockResolvedValueOnce(NEW_PREVIEW);
    api.authorizeMcp.mockImplementationOnce(() => new Promise((resolve) => { resolveAuthorize = resolve; }));
    const { wrapper: w, router } = await mountAuthorize();
    await button(w, '同意授权').trigger('click');

    await router.push({ path: '/connect/authorize', query: NEW_QUERY });
    await flushPromises();
    resolveAuthorize({ callback_url: 'https://client.example/callback?code=stale-code' });
    await flushPromises();

    expect(w.text()).toContain('New Assistant');
    expect(assignMock).not.toHaveBeenCalled();
    w.unmount();
  });

  it('拒绝时保留存在但为空的 state', async () => {
    api.previewMcpAuthorization.mockResolvedValueOnce({ ...PREVIEW, state: '' });
    const { wrapper: w } = await mountAuthorize();
    await button(w, '拒绝').trigger('click');

    const target = new URL(assignMock.mock.calls[0][0]);
    expect(target.searchParams.has('state')).toBe(true);
    expect(target.searchParams.get('state')).toBe('');
    expect(target.searchParams.get('error')).toBe('access_denied');
    w.unmount();
  });
});
