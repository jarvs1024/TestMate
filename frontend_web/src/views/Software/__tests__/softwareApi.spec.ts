/**
 * 软件库 API 层 —— **两条最容易写错的约定**:
 *
 *  1. 上传必须走**独立的 axios 实例** (timeout 0 + 原始字节流),
 *     公共实例的 30s 超时会让 5G 的包传到一半就断;
 *     而且 body 必须直接是 File —— 走 multipart 的话 starlette 会把文件
 *     先 spool 到系统临时目录, 5G 在临时目录再存一份.
 *  2. 下载必须走**短时票据 + 浏览器原生下载器**,
 *     绝不能 fetch 成 blob —— 5G 的 blob 会把浏览器内存打爆.
 */
import { describe, expect, it, vi } from 'vitest';

// ⚠️ vi.mock 的工厂函数会被**提升**到文件顶部 —— 直接用模块级的 const 会
//    "Cannot access 'instances' before initialization". 必须用 vi.hoisted.
const { instances } = vi.hoisted(() => ({ instances: [] as any[] }));

vi.mock('axios', () => {
  // ⚠️ 必须**照传入的配置**建实例 —— 否则 timeout: 0 那个上传实例就没了
  const make = (cfg: any = {}) => {
    const inst: any = {
      defaults: { baseURL: '', timeout: 30000, ...cfg },
      interceptors: {
        request: { use: vi.fn() },
        response: { use: vi.fn() },
      },
      get: vi.fn(async () => ({ data: {} })),
      post: vi.fn(async () => ({ data: {} })),
      put: vi.fn(async () => ({ data: {} })),
      delete: vi.fn(async () => ({ data: {} })),
    };
    instances.push(inst);
    return inst;
  };
  return { default: { create: make } };
});

vi.mock('@/stores/user', () => ({
  useUserStore: () => ({ token: 'test-token' }),
}));

vi.mock('@/utils/download', () => ({
  nativeDownload: vi.fn(),
}));

import request from '@/utils/request';
import { nativeDownload } from '@/utils/download';
import { downloadSoftware, uploadSoftwareFile } from '@/api/software';

/** 上传专用的那个实例 —— timeout 是 0 的那个 */
function lastPutCall(): any[] {
  const calls = uploadClient().put.mock.calls;
  return calls[calls.length - 1];
}

function uploadClient() {
  const found = instances.find((i) => i.defaults?.timeout === 0);
  if (!found) throw new Error('找不到上传用的 axios 实例 (timeout=0)');
  return found;
}

describe('上传: 独立的 axios 实例', () => {
  it('上传实例的 timeout 必须是 0 —— 公共实例的 30s 会把 5G 的包掐断', async () => {
    await uploadSoftwareFile('demo', new File(['x'], 'a.bin'));
    expect(uploadClient().defaults.timeout).toBe(0);
  });

  it('body 直接传 File —— 不能是 FormData (multipart 会多落一份盘)', async () => {
    const f = new File(['hello'], 'demo.bin');
    await uploadSoftwareFile('demo', f);
    const [, body] = lastPutCall();
    expect(body).toBe(f);
    expect(body instanceof FormData).toBe(false);
  });

  it('带文件名与大小头 —— 后端拿它们做校验', async () => {
    const f = new File(['hello'], '演示 软件.bin');
    await uploadSoftwareFile('demo', f);
    const [, , config] = lastPutCall();
    expect(config.headers['Content-Type']).toBe('application/octet-stream');
    // 文件名要 URL 编码 —— 原始文件名可能带中文/空格
    expect(config.headers['X-File-Name']).toBe(encodeURIComponent('演示 软件.bin'));
    expect(config.headers['X-File-Size']).toBe(String(f.size));
    expect(config.headers.Authorization).toBe('Bearer test-token');
  });

  it('URL 指向流式上传端点', async () => {
    await uploadSoftwareFile('demo-sw', new File(['x'], 'a.bin'));
    expect(lastPutCall()[0]).toBe('/software/demo-sw/file');
  });

  it('挂了 onUploadProgress —— 没有进度条用户会以为卡死了', async () => {
    await uploadSoftwareFile('demo', new File(['x'], 'a.bin'));
    const [, , config] = lastPutCall();
    expect(typeof config.onUploadProgress).toBe('function');
  });

  it('进度回调把 loaded/total 换算成 0~100 的整数百分比', async () => {
    const seen: number[] = [];
    await uploadSoftwareFile('demo', new File(['x'], 'a.bin'), (p) => seen.push(p));
    const [, , config] = lastPutCall();
    config.onUploadProgress({ loaded: 50, total: 100 });
    config.onUploadProgress({ loaded: 100, total: 100 });
    expect(seen).toEqual([50, 100]);
  });
});

describe('下载: 短时票据 + 浏览器原生下载器', () => {
  it('先拿票据, 再把 url 交给浏览器 —— 不走 blob', async () => {
    const post = vi.fn(async () => ({ url: '/api/v1/software/dl?t=abc&v=1.0.0', expires_in: 600 }));
    (request as any).post = post;

    await downloadSoftware('demo-sw');

    expect(post).toHaveBeenCalledWith(
      '/software/demo-sw/download-ticket',
      undefined,
      { params: undefined },
    );
    expect(nativeDownload).toHaveBeenCalledWith('/api/v1/software/dl?t=abc&v=1.0.0');
  });

  it('指定版本时把版本带上', async () => {
    const post = vi.fn(async () => ({ url: '/x', expires_in: 600 }));
    (request as any).post = post;

    await downloadSoftware('demo-sw', '2.0.0');

    expect(post).toHaveBeenCalledWith(
      '/software/demo-sw/download-ticket',
      undefined,
      { params: { version: '2.0.0' } },
    );
  });
});
