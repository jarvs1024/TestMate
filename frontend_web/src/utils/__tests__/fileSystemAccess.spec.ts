/**
 * fileSystemAccess —— 目录句柄派生与记忆.
 *
 * 重点测 deriveDirectory: 它是"自动装到家目录"的核心 ——
 * 只用相对路径段逐级 getDirectoryHandle, 不碰路径分隔符,
 * 所以 Linux / macOS / Windows 是同一套逻辑.
 */
import { describe, it, expect, vi, afterEach } from 'vitest';
import {
  deriveDirectory, loadDirHandle, forgetDirHandle, queryPermission,
  supportsFileSystemAccess, pickDirectory, base64ToArrayBuffer,
} from '../fileSystemAccess';

/** 造一个假的目录句柄: 记录逐级 getDirectoryHandle 的调用 */
function fakeDir(name: string, calls: string[] = [], cache = new Map<string, any>()) {
  const h: any = {
    kind: 'directory',
    name,
    getDirectoryHandle: vi.fn(async (child: string) => {
      calls.push(`${name}/${child}`);
      // 同一个子目录名要返回**同一个**句柄 (跟浏览器一致), 否则测不了"逐级 create"
      if (!cache.has(child)) cache.set(child, fakeDir(child, calls, cache));
      return cache.get(child);
    }),
    getFileHandle: vi.fn(async () => ({})),
  };
  return h;
}

describe('deriveDirectory', () => {
  it('逐级派生多级子目录', async () => {
    const calls: string[] = [];
    const root = fakeDir('home', calls);
    const dir = await deriveDirectory(root, ['qoder-cn', 'skills', 'my-skill']);
    expect(calls).toEqual([
      'home/qoder-cn', 'qoder-cn/skills', 'skills/my-skill',
    ]);
    expect(dir.name).toBe('my-skill');
  });

  it('空路径直接返回根目录', async () => {
    const root = fakeDir('home');
    const dir = await deriveDirectory(root, []);
    expect(dir).toBe(root);
  });

  it('每一级都以 create: true 创建 (不存在就建)', async () => {
    const root = fakeDir('home');
    await deriveDirectory(root, ['a', 'b']);
    expect(root.getDirectoryHandle).toHaveBeenCalledWith('a', { create: true });
    const child = await root.getDirectoryHandle('a');
    expect(child.getDirectoryHandle).toHaveBeenCalledWith('b', { create: true });
  });

  it('用 / 分隔的相对路径 —— 不受操作系统路径分隔符影响', async () => {
    const calls: string[] = [];
    const root = fakeDir('home', calls);
    await deriveDirectory(root, '.qoder-cn/skills'.split('/'));
    expect(calls).toEqual(['home/.qoder-cn', '.qoder-cn/skills']);
  });
});

describe('句柄记忆', () => {
  // jsdom 不实现 IndexedDB —— 记忆功能必须**优雅降级**, 不能把安装流程搞崩
  it('环境没有 IndexedDB 时读取返回 null 而不是抛错', async () => {
    await expect(loadDirHandle('home')).resolves.toBeNull();
  });

  it('环境没有 IndexedDB 时写入也不抛错', async () => {
    await expect(forgetDirHandle('home')).resolves.toBeUndefined();
  });
});

describe('queryPermission', () => {
  it('句柄没有 queryPermission 时视为已授权', async () => {
    const h: any = { kind: 'directory', name: 'x' };
    await expect(queryPermission(h)).resolves.toBe('granted');
  });

  it('调用句柄的 queryPermission', async () => {
    const h: any = {
      kind: 'directory', name: 'x',
      queryPermission: vi.fn(async () => 'prompt'),
    };
    await expect(queryPermission(h)).resolves.toBe('prompt');
    expect(h.queryPermission).toHaveBeenCalledWith({ mode: 'readwrite' });
  });

  it('句柄查询抛错时按 prompt 处理', async () => {
    const h: any = {
      kind: 'directory', name: 'x',
      queryPermission: vi.fn(async () => { throw new Error('boom'); }),
    };
    await expect(queryPermission(h)).resolves.toBe('prompt');
  });
});

describe('能力检测', () => {
  const orig = (window as any).showDirectoryPicker;
  afterEach(() => {
    (window as any).showDirectoryPicker = orig;
  });

  it('没有 showDirectoryPicker 时不支持前端通道', () => {
    (window as any).showDirectoryPicker = undefined;
    expect(supportsFileSystemAccess()).toBe(false);
  });

  it('有 showDirectoryPicker 时支持', () => {
    (window as any).showDirectoryPicker = vi.fn();
    expect(supportsFileSystemAccess()).toBe(true);
  });

  it('pickDirectory 传 startIn 时原样传给浏览器', async () => {
    const picker = vi.fn(async () => fakeDir('picked'));
    (window as any).showDirectoryPicker = picker;
    const startIn = fakeDir('remembered');
    await pickDirectory(startIn);
    expect(picker).toHaveBeenCalledWith({ mode: 'readwrite', startIn });
  });

  it('pickDirectory 不传 startIn 时不塞这个键', async () => {
    const picker = vi.fn(async () => fakeDir('picked'));
    (window as any).showDirectoryPicker = picker;
    await pickDirectory();
    expect(picker).toHaveBeenCalledWith({ mode: 'readwrite' });
  });
});

describe('base64ToArrayBuffer', () => {
  it('base64 → 字节', () => {
    const buf = base64ToArrayBuffer('aGVsbG8=');
    expect(new TextDecoder().decode(buf)).toBe('hello');
  });
});
