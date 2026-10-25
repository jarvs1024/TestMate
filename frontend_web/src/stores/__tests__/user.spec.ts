/**
 * user store —— 会话收尾 (2026-10-25 前端健壮性).
 *
 * 盯住四件事:
 *   ① logout() 把登录页记的"上次用户名 / 要密码"也一起清掉 ——
 *      不清的话, 共用机器上下一个人打开登录页时用户名已经预填、
 *      免密账号连密码框都不展开, 直接回车就进了上一个同事的号;
 *   ② localStorage 里的坏 JSON 不能让整个应用白屏 (按未登录处理 + 删掉坏 key);
 *   ③ login() 先拿到 /me 再落盘 —— 不留"token 是新账号、user 还是上一个账号"的半登录态;
 *   ④ /me 失败要回滚到登出态 (token 不落盘).
 */
import { describe, expect, it, vi, beforeEach } from 'vitest';
import { createPinia, setActivePinia, type Pinia } from 'pinia';

const { axiosPost, axiosGet } = vi.hoisted(() => ({ axiosPost: vi.fn(), axiosGet: vi.fn() }));

vi.mock('axios', () => ({
  default: { post: axiosPost, get: axiosGet },
}));

import { useUserStore } from '../user';

const TOKEN_KEY = 'testmate:token';
const USER_KEY = 'testmate:user';
const LAST_USERNAME_KEY = 'testmate:last-username';
const NEEDS_PASSWORD_KEY = 'testmate:needs-password';

let pinia: Pinia;

beforeEach(() => {
  localStorage.clear();
  axiosPost.mockReset();
  axiosGet.mockReset();
  pinia = createPinia();
  setActivePinia(pinia);
});

describe('user store · 会话收尾', () => {
  it('logout() 把登录页记的两个 key 也一起清掉', () => {
    localStorage.setItem(TOKEN_KEY, 'tok-a');
    localStorage.setItem(USER_KEY, JSON.stringify({ id: 1, username: 'a', role: 'admin' }));
    localStorage.setItem(LAST_USERNAME_KEY, 'a');
    localStorage.setItem(NEEDS_PASSWORD_KEY, 'a');

    const store = useUserStore(pinia);
    store.logout();

    expect(store.token).toBe('');
    expect(store.user).toBeNull();
    expect(localStorage.getItem(TOKEN_KEY)).toBeNull();
    expect(localStorage.getItem(USER_KEY)).toBeNull();
    // ⚠️ 这两个才是本次修的 —— 共用机器上不能替下一个人"记住"上一个同事的账号
    expect(localStorage.getItem(LAST_USERNAME_KEY)).toBeNull();
    expect(localStorage.getItem(NEEDS_PASSWORD_KEY)).toBeNull();
  });

  it('localStorage 里的坏 JSON → 当未登录, 不抛 (别白屏), 并删掉坏 key', () => {
    localStorage.setItem(USER_KEY, '{这不是 json');
    let store: ReturnType<typeof useUserStore>;
    expect(() => { store = useUserStore(pinia); }).not.toThrow();
    expect(store!.user).toBeNull();
    expect(localStorage.getItem(USER_KEY)).toBeNull();
  });

  it('login(): 先拿到 me 再落盘 —— /me 没回来前 token 不进 localStorage', async () => {
    let resolveMe: (v: any) => void = () => {};
    axiosPost.mockResolvedValue({ data: { access_token: 'tok-b' } });
    axiosGet.mockImplementation(() => new Promise((r) => { resolveMe = r; }));

    const store = useUserStore(pinia);
    const p = store.login('b');
    await Promise.resolve();
    // ⚠️ 半登录态的根源: 以前这里已经把 token 写进去了
    expect(localStorage.getItem(TOKEN_KEY)).toBeNull();

    resolveMe({ data: { id: 2, username: 'b', role: 'admin' } });
    await p;
    expect(localStorage.getItem(TOKEN_KEY)).toBe('tok-b');
    expect(store.user).toEqual({ id: 2, username: 'b', role: 'admin' });
  });

  it('login(): /me 失败 → 回滚到登出态 (不留上一个账号的 user)', async () => {
    axiosPost.mockResolvedValue({ data: { access_token: 'tok-b' } });
    axiosGet.mockRejectedValue(new Error('me 挂了'));

    const store = useUserStore(pinia);
    // 上一个账号的状态
    store.token = 'tok-a';
    store.user = { id: 1, username: 'a', role: 'admin' };
    localStorage.setItem(TOKEN_KEY, 'tok-a');
    localStorage.setItem(USER_KEY, JSON.stringify(store.user));

    await expect(store.login('b')).rejects.toThrow('me 挂了');

    expect(store.token).toBe('');
    expect(store.user).toBeNull();
    expect(localStorage.getItem(TOKEN_KEY)).toBeNull();
    expect(localStorage.getItem(USER_KEY)).toBeNull();
  });

  it('login(): 登录接口本身失败 → 同样回滚到登出态', async () => {
    axiosPost.mockRejectedValue(new Error('密码不对'));

    const store = useUserStore(pinia);
    store.token = 'tok-a';
    store.user = { id: 1, username: 'a', role: 'admin' };
    localStorage.setItem(TOKEN_KEY, 'tok-a');

    await expect(store.login('b')).rejects.toThrow('密码不对');

    expect(store.token).toBe('');
    expect(store.user).toBeNull();
    expect(localStorage.getItem(TOKEN_KEY)).toBeNull();
  });

  it('login(): 失败**不清**"记住用户名" —— 密码打错一次不该把用户的输入也抹掉', async () => {
    axiosPost.mockRejectedValue(new Error('密码不对'));
    localStorage.setItem(LAST_USERNAME_KEY, 'zhangsan');

    const store = useUserStore(pinia);
    await expect(store.login('zhangsan')).rejects.toThrow();

    // ⚠️ 会话清了, 但"记住用户名"要留着 —— 它是给用户省打字用的
    expect(localStorage.getItem(TOKEN_KEY)).toBeNull();
    expect(localStorage.getItem(LAST_USERNAME_KEY)).toBe('zhangsan');
  });
});
