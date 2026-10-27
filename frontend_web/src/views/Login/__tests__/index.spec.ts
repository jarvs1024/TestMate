/**
 * 登录页 —— 免密优先.
 *
 * 账号口径: 账号**必须管理员先建过**才能登录 (免的是密码, 不是身份);
 *          普通用户 = 公司邮箱 (后缀固定), 建号时没设密码就是免密;
 *          管理员 = 账号名 → 必须密码.
 *
 * 盯住这几件事:
 *   ① 默认只有用户名一个框 (真"一键") —— 密码框**按需**才出现;
 *   ② 后端探测说"这个号要密码" → 立刻摆出密码框 (不用先失败一次);
 *   ③ 后端探测说"这个号免密"   → 不摆密码框, 按钮写成「免密登录」;
 *   ④ 探测失败 → 退回老路 (提交时后端回 password_required 再展开), 页面不报错;
 *   ⑤ 记住用户名: 上次登录过的名字自动填好;
 *   ⑥ 固定后缀 @twsc.com.cn 作为输入框的附加段显示 (输入里有 @ 就不显示;
 *      管理员账号是纯账号名, 探测出是管理员也不显示后缀);
 *   ⑦ 后端说 account_not_found → 把"请联系管理员开通"显示出来 (别只弹"登录失败").
 */
import { describe, expect, it, vi, beforeEach } from 'vitest';
import { mount, flushPromises } from '@vue/test-utils';
import { createPinia, setActivePinia } from 'pinia';
import { useUserStore } from '@/stores/user';
import { getAccountHint } from '@/api/users';
import router from '@/router';

// ⚠️ 探测接口是**被测行为的一部分** —— 必须 mock, 否则测试会真去发请求
//    (单元测试里注定失败 → 拿不到"要密码"这个结论).
vi.mock('@/api/users', () => ({
  getAuthConfig: vi.fn(async () => ({ email_domain: '@twsc.com.cn' })),
  getAccountHint: vi.fn(async () => null),
}));

const LAST_USERNAME_KEY = 'testmate:last-username';
const NEEDS_PASSWORD_KEY = 'testmate:needs-password';

/** 等防抖 (300ms) + 探测返回 */
async function settle(ms = 360) {
  await new Promise((r) => setTimeout(r, ms));
  await flushPromises();
}

async function mountLogin(loginImpl: (u: string, p?: string) => Promise<void>) {
  const pinia = createPinia();
  setActivePinia(pinia);
  const store = useUserStore(pinia);
  // ⚠️ 路由守卫里 useUserStore() 拿的是**当前 active** 的 pinia,
  //    没 token 会被踢去 /login (登录页自己就是 /login, 绕一圈没意义)
  store.token = 'test-token';
  const spy = vi.fn(loginImpl);
  // 替换 store 里的 login action
  (store as any).login = spy;
  const mod = await import('@/views/Login/index.vue');
  const w = mount(mod.default, { global: { plugins: [pinia, router] } });
  await flushPromises();
  return { w, store, spy };
}

beforeEach(() => {
  localStorage.clear();
  vi.mocked(getAccountHint).mockReset();
  vi.mocked(getAccountHint).mockResolvedValue(null);
});

describe('登录页 · 免密优先', () => {
  it('默认只有用户名一个框, 密码框不占版面', async () => {
    const { w } = await mountLogin(async () => {});
    expect(w.find('input[autocomplete="username"]').exists()).toBe(true);
    expect(w.find('input[autocomplete="current-password"]').exists()).toBe(false);
    w.unmount();
  });

  it('记住上次用户名 → 自动填好', async () => {
    localStorage.setItem(LAST_USERNAME_KEY, 'zhangsan');
    const { w } = await mountLogin(async () => {});
    expect((w.find('input[autocomplete="username"]').element as HTMLInputElement).value).toBe('zhangsan');
    w.unmount();
  });

  it('一键登录: 只填用户名就调接口 (密码传空)', async () => {
    const { w, spy } = await mountLogin(async () => {});
    await w.find('input[autocomplete="username"]').setValue('zhangsan');
    await w.find('form').trigger('submit');
    await flushPromises();
    expect(spy).toHaveBeenCalledWith('zhangsan', '');
    w.unmount();
  });

  it('探测到免密账号 → 不摆密码框, 按钮写明"免密登录"', async () => {
    vi.mocked(getAccountHint).mockResolvedValue({
      account: 'ok',
      needs_password: false,
      role: 'tester',
      username: 'zhangsan@twsc.com.cn',
    });
    const { w } = await mountLogin(async () => {});
    await w.find('input[autocomplete="username"]').setValue('zhangsan');
    await settle();
    expect(w.find('input[autocomplete="current-password"]').exists()).toBe(false);
    expect(w.find('button.primary').text()).toContain('免密登录');
    expect(w.find('.hint').text()).toContain('免密登录');
    w.unmount();
  });

  it('探测到要密码的账号 → 立刻摆出密码框并说清楚', async () => {
    vi.mocked(getAccountHint).mockResolvedValue({
      account: 'ok',
      needs_password: true,
      role: 'admin',
      username: 'admin',
    });
    const { w } = await mountLogin(async () => {});
    await w.find('input[autocomplete="username"]').setValue('admin');
    await settle();
    expect(w.find('input[autocomplete="current-password"]').exists()).toBe(true);
    expect(w.find('.hint').text()).toContain('已设置密码');
    expect(w.find('button.primary').text()).toContain('登录');
    expect(w.find('button.primary').text()).not.toContain('免密');
    w.unmount();
  });

  it('探测到"没开通" → 直接说尚未开通 (不用试一次)', async () => {
    vi.mocked(getAccountHint).mockResolvedValue({
      account: 'missing',
      needs_password: false,
      role: null,
      username: null,
    });
    const { w } = await mountLogin(async () => {});
    await w.find('input[autocomplete="username"]').setValue('nobody');
    await settle();
    expect(w.find('.hint').text()).toContain('尚未开通');
    expect(w.find('input[autocomplete="current-password"]').exists()).toBe(false);
    w.unmount();
  });

  it('探测到"已停用" → 说已停用', async () => {
    vi.mocked(getAccountHint).mockResolvedValue({
      account: 'disabled',
      needs_password: false,
      role: null,
      username: null,
    });
    const { w } = await mountLogin(async () => {});
    await w.find('input[autocomplete="username"]').setValue('leaver');
    await settle();
    expect(w.find('.hint').text()).toContain('已停用');
    w.unmount();
  });

  it('探测失败 → 不报错, 退回"提交后再说"的老路', async () => {
    vi.mocked(getAccountHint).mockResolvedValue(null);
    const { w } = await mountLogin(async () => {});
    await w.find('input[autocomplete="username"]').setValue('zhangsan');
    await settle();
    // 没密码框, 但留了个兜底口子
    expect(w.find('input[autocomplete="current-password"]').exists()).toBe(false);
    expect(w.find('button.link').exists()).toBe(true);
    // 页面没有"失败"提示
    expect(w.find('.err').exists()).toBe(false);
    w.unmount();
  });

  it('管理员账号 (纯账号名) → 不显示 @域名 后缀', async () => {
    vi.mocked(getAccountHint).mockResolvedValue({
      account: 'ok',
      needs_password: true,
      role: 'admin',
      username: 'admin',
    });
    const { w } = await mountLogin(async () => {});
    await w.find('input[autocomplete="username"]').setValue('admin');
    await settle();
    expect(w.find('.suffix').exists()).toBe(false);
    w.unmount();
  });

  it('后端回 password_required → 展开密码框 + 提示', async () => {
    const { w } = await mountLogin(async () => {
      const err: any = new Error('401');
      err.response = { data: { detail: { code: 'password_required', message: '管理员账号需要密码' } } };
      throw err;
    });
    await w.find('input[autocomplete="username"]').setValue('admin');
    await w.find('form').trigger('submit');
    await flushPromises();
    expect(w.find('input[autocomplete="current-password"]').exists()).toBe(true);
    expect(w.find('.err').text()).toContain('管理员账号需要密码');
    w.unmount();
  });

  it('记住"这个账号要密码" → 下次直接把密码框摆出来', async () => {
    localStorage.setItem(LAST_USERNAME_KEY, 'admin');
    localStorage.setItem(NEEDS_PASSWORD_KEY, 'admin');
    const { w } = await mountLogin(async () => {});
    expect(w.find('input[autocomplete="current-password"]').exists()).toBe(true);
    w.unmount();
  });

  it('换个账号 → 密码框收起来 (新账号大概率是普通用户)', async () => {
    localStorage.setItem(LAST_USERNAME_KEY, 'admin');
    localStorage.setItem(NEEDS_PASSWORD_KEY, 'admin');
    const { w } = await mountLogin(async () => {});
    await w.find('input[autocomplete="username"]').setValue('zhangsan');
    await flushPromises();
    expect(w.find('input[autocomplete="current-password"]').exists()).toBe(false);
    w.unmount();
  });

  it('登录成功 → 把用户名记下来', async () => {
    const { w } = await mountLogin(async () => {});
    await w.find('input[autocomplete="username"]').setValue('zhangsan');
    await w.find('form').trigger('submit');
    await flushPromises();
    expect(localStorage.getItem(LAST_USERNAME_KEY)).toBe('zhangsan');
    w.unmount();
  });

  it('带密码登录成功 → 记住"这个账号要密码" (下次直接摆出密码框)', async () => {
    // 第一次没密码 → 后端说 password_required; 第二次带密码 → 成功
    let first = true;
    const { w } = await mountLogin(async (_u: string, p?: string) => {
      if (first && !p) {
        first = false;
        const err: any = new Error('401');
        err.response = { data: { detail: { code: 'password_required', message: '管理员账号需要密码' } } };
        throw err;
      }
    });
    await w.find('input[autocomplete="username"]').setValue('admin');
    await w.find('form').trigger('submit');
    await flushPromises();
    expect(w.find('input[autocomplete="current-password"]').exists()).toBe(true);
    await w.find('input[autocomplete="current-password"]').setValue('Admin@123');
    await w.find('form').trigger('submit');
    await flushPromises();
    expect(localStorage.getItem(NEEDS_PASSWORD_KEY)).toBe('admin');
    w.unmount();
  });

  it('免密登录成功 → 不留"要密码"的标记', async () => {
    localStorage.setItem(NEEDS_PASSWORD_KEY, 'zhangsan');
    const { w } = await mountLogin(async () => {});
    await w.find('input[autocomplete="username"]').setValue('zhangsan');
    await w.find('form').trigger('submit');
    await flushPromises();
    expect(localStorage.getItem(NEEDS_PASSWORD_KEY)).toBeNull();
    w.unmount();
  });

  it('固定后缀显示在输入框右边; 输入了完整邮箱就不显示', async () => {
    const { w } = await mountLogin(async () => {});
    expect(w.find('.suffix').text()).toBe('@twsc.com.cn');
    await w.find('input[autocomplete="username"]').setValue('zhangsan@twsc.com.cn');
    await flushPromises();
    expect(w.find('.suffix').exists()).toBe(false);
    w.unmount();
  });

  it('普通登录失败 → 显示后端的错误文案', async () => {
    const { w } = await mountLogin(async () => {
      const err: any = new Error('401');
      err.response = { data: { detail: '用户名或密码错误' } };
      throw err;
    });
    await w.find('input[autocomplete="username"]').setValue('nobody');
    await w.find('form').trigger('submit');
    await flushPromises();
    expect(w.find('.err').text()).toContain('用户名或密码错误');
    w.unmount();
  });

  it('账号没开通 → 显示"请联系管理员开通" (不是笼统的登录失败)', async () => {
    const { w } = await mountLogin(async () => {
      const err: any = new Error('401');
      err.response = {
        data: { detail: { code: 'account_not_found', message: '账号不存在, 请联系管理员开通' } },
      };
      throw err;
    });
    await w.find('input[autocomplete="username"]').setValue('nobody');
    await w.find('form').trigger('submit');
    await flushPromises();
    expect(w.find('.err').text()).toContain('请联系管理员开通');
    // 账号不存在 ≠ 要密码 —— 密码框不该冒出来
    expect(w.find('input[autocomplete="current-password"]').exists()).toBe(false);
    w.unmount();
  });

  it('账号被停用 → 显示后端给的话', async () => {
    const { w } = await mountLogin(async () => {
      const err: any = new Error('401');
      err.response = {
        data: { detail: { code: 'account_disabled', message: '账号已停用, 请联系管理员' } },
      };
      throw err;
    });
    await w.find('input[autocomplete="username"]').setValue('leaver');
    await w.find('form').trigger('submit');
    await flushPromises();
    expect(w.find('.err').text()).toContain('已停用');
    w.unmount();
  });

  it('页面文案说清楚"账号要管理员先开通"', async () => {
    const { w } = await mountLogin(async () => {});
    expect(w.text()).toContain('管理员提前开通');
    w.unmount();
  });
});
