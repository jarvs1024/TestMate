/**
 * axios 拦截器: 静默模式 (silent).
 *
 * 为什么要有这条 (2026-10-25 部署验证时发现):
 *   首页给每张能力卡取指标数字 (资产数 / 数据集数 / MR 数), 这些接口在
 *   **环境没配好时本来就会失败** (RAGFlow 没配 → /kb/datasets 返 502).
 *   卡片会自己降级显示兜底文案, 但拦截器会额外弹一个全局错误条 ——
 *   首页一进来就飘红, 用户以为平台坏了, 实际一切正常.
 *
 * 所以给"调用方自己会兜底"的请求加 `silent: true`: 失败**不弹**全局提示.
 */
import { describe, expect, it, vi, beforeEach, beforeAll, afterAll } from 'vitest';

const { ElMessageError } = vi.hoisted(() => ({ ElMessageError: vi.fn() }));
// ⚠️ 拦截器现在只调 clearSession() (不清「记住的用户名」), logout() 不再被 401 路径调用
const { logout, clearSession, userState } = vi.hoisted(() => ({
  logout: vi.fn(),
  clearSession: vi.fn(),
  userState: { token: '' },
}));

vi.mock('element-plus', () => ({
  ElMessage: { error: ElMessageError },
}));

vi.mock('@/stores/user', () => ({
  // token 可变 —— 要测"带着用户 token"和"匿名"两种 401
  useUserStore: () => ({
    get token() { return userState.token; },
    logout,
    clearSession,
  }),
}));

import request from '../request';

/** 造一个"必定失败"的 adapter */
function failWith(status: number, detail = 'boom') {
  request.defaults.adapter = async (config: any) => {
    const err: any = new Error(detail);
    err.config = config;
    err.response = { status, data: { detail } };
    throw err;
  };
}

/** 造一个"必定成功"的 adapter */
function okWith(data: any) {
  request.defaults.adapter = async (config: any) => ({
    data,
    status: 200,
    statusText: 'OK',
    headers: {} as any,
    config,
  });
}

beforeEach(() => {
  ElMessageError.mockClear();
  logout.mockClear();
  clearSession.mockClear();
  userState.token = '';
  jumpedTo = '';
});

// jsdom 不支持真跳转 —— 把 location 换成可写的桩 (顺便能断言跳去哪)
const realLocation = window.location;
let jumpedTo = '';
beforeAll(() => {
  Object.defineProperty(window, 'location', {
    configurable: true,
    value: {
      // pathname 要留着 —— 拦截器靠它判断是不是 publicRead 路由
      pathname: realLocation.pathname,
      search: '',
      get href() { return jumpedTo; },
      set href(v: string) { jumpedTo = v; },
    },
  });
});
afterAll(() => {
  Object.defineProperty(window, 'location', { configurable: true, value: realLocation });
});

describe('axios 拦截器', () => {
  it('成功时返回响应体 (整个项目都靠这个约定)', async () => {
    okWith({ items: [1, 2] });
    await expect(request.get('/x')).resolves.toEqual({ items: [1, 2] });
  });

  it('普通失败 → 弹全局错误提示', async () => {
    failWith(500, '服务器炸了');
    await expect(request.get('/x')).rejects.toBeTruthy();
    expect(ElMessageError).toHaveBeenCalledWith('服务器炸了');
  });

  it('silent 请求失败 → 不弹全局提示 (调用方自己降级)', async () => {
    failWith(502, 'ragflow error');
    await expect(request.get('/x', { silent: true })).rejects.toBeTruthy();
    expect(ElMessageError).not.toHaveBeenCalled();
  });

  it('silent 只影响提示, 不影响错误继续抛给调用方', async () => {
    failWith(404, '没有这个能力');
    const p = request.get('/x', { silent: true });
    await expect(p).rejects.toBeTruthy();
    await expect(p).rejects.toMatchObject({ response: { status: 404 } });
  });
});

/**
 * 401 的处理 (2026-10-25 前端健壮性).
 *
 * ⚠️ 以前 publicRead 路由 (首页 / 代码检视) 的 401 一律放行 ——
 *    token 过期后用户停在首页, 首页的鉴权请求 401 被静默 catch,
 *    页面仍显示"已登录", 待办静默消失, 用户以为"今天没待办".
 *
 * 现在: **带着用户 token** 的 401 → 清会话 + 跳登录;
 *      匿名访问 (带 ANONYMOUS_TOKEN) 的 401 → 不处理 (那是后端配置问题).
 */
describe('axios 拦截器 · 401', () => {
  it('publicRead 路由上带着用户 token 的 401 → 清会话 + 跳登录 (带 redirect)', async () => {
    userState.token = 'user-token';
    failWith(401, 'token 过期');
    await expect(request.get('/x')).rejects.toBeTruthy();
    // ⚠️ 只清会话 (clearSession), **不**调 logout() ——
    //    logout() 会把「记住的用户名」也抹掉, 被过期踢出去的人连用户名都得重打
    expect(clearSession).toHaveBeenCalled();
    expect(logout).not.toHaveBeenCalled();
    // 跳登录时带上 redirect, 登录完能回原来那页 (草稿不至于全蒸发)
    expect(jumpedTo).toContain('/login?redirect=');
  });

  it('匿名访问的 401 → 不清会话 (用户压根没登录, 跟用户无关)', async () => {
    userState.token = '';
    failWith(401, '后端没配好');
    await expect(request.get('/x')).rejects.toBeTruthy();
    expect(clearSession).not.toHaveBeenCalled();
    expect(jumpedTo).toBe('');
  });
});
