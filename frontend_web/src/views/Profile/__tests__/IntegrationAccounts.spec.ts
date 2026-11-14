import { beforeEach, describe, expect, it, vi } from 'vitest';
import { flushPromises, mount, type VueWrapper } from '@vue/test-utils';
import { ElMessageBox } from 'element-plus';
import type { IntegrationProvider } from '@/api/integrations';
import IntegrationAccounts from '../IntegrationAccounts.vue';

const api = vi.hoisted(() => ({
  listIntegrationProviders: vi.fn(),
  getIntegrationPublicKey: vi.fn(),
  saveIntegrationCredentials: vi.fn(),
  testIntegrationConnection: vi.fn(),
  deleteIntegrationCredentials: vi.fn(),
}));

vi.mock('@/api/integrations', () => api);
vi.mock('@/utils/rsaTransport', () => ({
  encryptForTransport: vi.fn(async () => 'encrypted-payload'),
}));
vi.mock('element-plus', () => ({
  ElMessage: { success: vi.fn(), error: vi.fn(), warning: vi.fn() },
  ElMessageBox: { confirm: vi.fn() },
}));

const UNBOUND: IntegrationProvider = {
  id: null,
  code: 'pingcode',
  name: 'PingCode',
  enabled: true,
  bound: false,
  username: null,
  status: 'unbound',
  last_login_at: null,
  last_error: null,
};

const BOUND: IntegrationProvider = {
  ...UNBOUND,
  id: 8,
  bound: true,
  username: 'demo-user',
  status: 'ok',
  last_login_at: '2026-11-12T09:00:00Z',
};

const PLM: IntegrationProvider = {
  id: null,
  code: 'plm',
  name: 'PLM',
  enabled: false,
  bound: false,
  username: null,
  status: 'unbound',
  last_login_at: null,
  last_error: null,
};

function button(w: VueWrapper, text: string) {
  const found = w.findAll('button').find((item) => item.text().trim() === text);
  if (!found) throw new Error(`找不到按钮: ${text}`);
  return found;
}

async function mountAccounts(providers = [UNBOUND, PLM]) {
  api.listIntegrationProviders.mockResolvedValueOnce({ items: providers });
  const wrapper = mount(IntegrationAccounts);
  await flushPromises();
  return wrapper;
}

beforeEach(() => {
  Object.values(api).forEach((mock) => mock.mockReset());
  viaDefaults();
  vi.mocked(ElMessageBox.confirm).mockReset();
  vi.mocked(ElMessageBox.confirm).mockResolvedValue('confirm' as never);
});

function viaDefaults() {
  api.listIntegrationProviders.mockResolvedValue({ items: [UNBOUND, PLM] });
  api.getIntegrationPublicKey.mockResolvedValue({
    algorithm: 'RSA-PKCS1v15',
    public_key: '-----BEGIN PUBLIC KEY-----pem',
  });
  api.saveIntegrationCredentials.mockResolvedValue(BOUND);
  api.testIntegrationConnection.mockResolvedValue({
    display_name: '张三',
    team_name: '测试团队',
    login_at: '2026-11-12T09:00:00Z',
  });
  api.deleteIntegrationCredentials.mockResolvedValue(undefined);
}

describe('个人中心 · 平台认证', () => {
  it('PingCode 卡片可直接录入账号密码，PLM 卡片显示建设中且不可配置', async () => {
    const w = await mountAccounts();

    expect(w.text()).toContain('PingCode');
    expect(w.text()).toContain('PLM');
    expect(w.text()).toContain('建设中');

    const password = w.get('input[aria-label="PingCode 密码"]');
    expect(password.attributes('type')).toBe('password');
    expect(password.attributes('autocomplete')).toBe('new-password');
    expect(w.findAll('button').some((item) => item.text().trim() === '显示')).toBe(false);

    const plmSave = w.get('button[aria-label="PLM 保存并验证"]');
    expect(plmSave.attributes('disabled')).toBeDefined();
  });

  it('保存时用公钥加密账号密码，明文密码不回显', async () => {
    const w = await mountAccounts();
    await w.get('input[aria-label="PingCode 账号"]').setValue('demo-user');
    await w.get('input[aria-label="PingCode 密码"]').setValue('demo-pass');

    await w.get('form').trigger('submit');
    await flushPromises();

    expect(api.getIntegrationPublicKey).toHaveBeenCalled();
    expect(api.saveIntegrationCredentials).toHaveBeenCalledWith(
      'pingcode',
      'encrypted-payload',
    );
    const { encryptForTransport } = await import('@/utils/rsaTransport');
    const [plaintext, pem] = vi.mocked(encryptForTransport).mock.calls[0];
    expect(JSON.parse(plaintext)).toEqual({
      username: 'demo-user',
      password: 'demo-pass',
    });
    expect(pem).toBe('-----BEGIN PUBLIC KEY-----pem');
    expect((w.get('input[aria-label="PingCode 密码"]').element as HTMLInputElement).value).toBe('');

    expect(w.text()).toContain('已连接');
    expect(w.text()).toContain('demo-user');
  });

  it('保存失败时展示后端的具体原因', async () => {
    api.saveIntegrationCredentials.mockRejectedValueOnce({
      response: { status: 400, data: { detail: '账号或密码错误' } },
    });
    const w = await mountAccounts();
    await w.get('input[aria-label="PingCode 账号"]').setValue('demo-user');
    await w.get('input[aria-label="PingCode 密码"]').setValue('wrong');

    await w.get('form').trigger('submit');
    await flushPromises();

    expect(w.text()).toContain('账号或密码错误');
  });

  it('已绑定的卡片可以测试连接并显示团队信息', async () => {
    const w = await mountAccounts([BOUND, PLM]);

    await button(w, '测试连接').trigger('click');
    await flushPromises();

    expect(api.testIntegrationConnection).toHaveBeenCalledWith('pingcode');
    expect(w.text()).toContain('测试团队');
    expect(w.text()).toContain('张三');
  });

  it('测试连接只展示中文用户名，没有团队信息时不出现空括号', async () => {
    api.testIntegrationConnection.mockResolvedValueOnce({
      display_name: '贾克江',
      team_name: '',
      login_at: '2026-11-12T09:00:00Z',
    });
    const w = await mountAccounts([BOUND, PLM]);

    await button(w, '测试连接').trigger('click');
    await flushPromises();

    expect(w.text()).toContain('连接正常：贾克江');
    expect(w.text()).not.toContain('（）');
    w.unmount();
  });

  it('平台卡片使用品牌图标而不是字母缩写', async () => {
    const w = await mountAccounts([BOUND, PLM]);

    const marks = w.findAll('.pc-mark');
    expect(marks).toHaveLength(2);
    expect(marks.every((mark) => mark.find('svg').exists())).toBe(true);
    expect(marks.map((mark) => mark.text())).toEqual(['', '']);
    w.unmount();
  });

  it('解除绑定需要确认，成功后回到未配置状态', async () => {
    const w = await mountAccounts([BOUND, PLM]);
    api.listIntegrationProviders.mockResolvedValue({ items: [UNBOUND, PLM] });

    await button(w, '解除绑定').trigger('click');
    await flushPromises();

    expect(ElMessageBox.confirm).toHaveBeenCalled();
    expect(api.deleteIntegrationCredentials).toHaveBeenCalledWith('pingcode');
    expect(w.text()).toContain('未配置');
  });
});
