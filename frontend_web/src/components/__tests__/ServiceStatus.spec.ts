import { beforeEach, describe, expect, it, vi } from 'vitest';
import { flushPromises, mount } from '@vue/test-utils';
import axios from 'axios';
import ServiceStatus from '../ServiceStatus.vue';

const api = vi.hoisted(() => ({ listIntegrationProviders: vi.fn() }));

vi.mock('axios', () => ({ default: { get: vi.fn() } }));
vi.mock('@/api/integrations', () => ({
  listIntegrationProviders: api.listIntegrationProviders,
}));

function pingcodeRow(w: ReturnType<typeof mount>) {
  return w.findAll('.src').find((row) => row.find('.name').text() === 'PingCode');
}

async function mountPanel(provider: Record<string, unknown> | null) {
  api.listIntegrationProviders.mockResolvedValue({
    items: provider ? [provider] : [],
  });
  const wrapper = mount(ServiceStatus);
  await flushPromises();
  return wrapper;
}

beforeEach(() => {
  vi.mocked(axios.get).mockReset();
  vi.mocked(axios.get).mockResolvedValue({
    data: { ragflow: 'ok', review_agent: 'off' },
  } as never);
  api.listIntegrationProviders.mockReset();
});

describe('侧栏 · 数据 / 工具', () => {
  it('PingCode 已绑定且登录态正常时显示「正常」', async () => {
    const w = await mountPanel({ code: 'pingcode', bound: true, status: 'ok' });

    const row = pingcodeRow(w);
    expect(row).toBeTruthy();
    expect(row?.text()).toContain('正常');
    w.unmount();
  });

  it('PingCode 需重新登录时给出告警文案', async () => {
    const w = await mountPanel({
      code: 'pingcode',
      bound: true,
      status: 'reauth_required',
    });

    const row = pingcodeRow(w);
    expect(row).toBeTruthy();
    expect(row?.find('.dot').classes()).toContain('s-warn');
    expect(row?.text()).toContain('需重登');
    w.unmount();
  });

  it('未绑定 PingCode 时整行隐藏', async () => {
    const w = await mountPanel({ code: 'pingcode', bound: false, status: 'unbound' });

    expect(pingcodeRow(w)).toBeUndefined();
    expect(w.text()).not.toContain('PingCode');
    w.unmount();
  });
});
