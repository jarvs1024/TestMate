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
import { describe, expect, it, vi, beforeEach } from 'vitest';

const { ElMessageError } = vi.hoisted(() => ({ ElMessageError: vi.fn() }));
const { logout } = vi.hoisted(() => ({ logout: vi.fn() }));

vi.mock('element-plus', () => ({
  ElMessage: { error: ElMessageError },
}));

vi.mock('@/stores/user', () => ({
  useUserStore: () => ({ token: '', logout }),
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
