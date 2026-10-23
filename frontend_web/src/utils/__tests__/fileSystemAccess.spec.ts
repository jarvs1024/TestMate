/**
 * fileSystemAccess —— 能力检测、目录选择与写盘.
 *
 * 安装通道现在是"选目录 → 写盘"这一条手动路径:
 * 浏览器不记住授权目录, 每次都要用户选 —— 这是安全模型决定的, 绕不过去.
 */
import { describe, it, expect, vi, afterEach } from 'vitest';
import {
  base64ToArrayBuffer, downloadBlob, pickDirectory, supportsFileSystemAccess,
  writeFileInto,
} from '../fileSystemAccess';

/** 假的目录句柄: 记录逐级 getDirectoryHandle / getFileHandle 的调用 */
function fakeDir(name: string, cache = new Map<string, any>()) {
  const h: any = {
    kind: 'directory',
    name,
    getDirectoryHandle: vi.fn(async (child: string) => {
      // 同一个名字要返回**同一个**句柄 (跟浏览器一致), 否则测不了调用参数
      if (!cache.has(child)) cache.set(child, fakeDir(child, cache));
      return cache.get(child);
    }),
    getFileHandle: vi.fn(async (file: string) => {
      if (!cache.has(file)) {
        // createWritable 也要缓存 —— 否则测试拿到的不是实际写入用的那个流
        const writable = {
          write: vi.fn(async () => undefined),
          close: vi.fn(async () => undefined),
        };
        cache.set(file, {
          kind: 'file', name: file,
          createWritable: vi.fn(async () => writable),
        });
      }
      return cache.get(file);
    }),
  };
  return h;
}

describe('能力检测', () => {
  const orig = (window as any).showDirectoryPicker;
  afterEach(() => {
    (window as any).showDirectoryPicker = orig;
  });

  it('没有 showDirectoryPicker 时不支持选目录安装', () => {
    (window as any).showDirectoryPicker = undefined;
    expect(supportsFileSystemAccess()).toBe(false);
  });

  it('有 showDirectoryPicker 时支持', () => {
    (window as any).showDirectoryPicker = vi.fn();
    expect(supportsFileSystemAccess()).toBe(true);
  });
});

describe('pickDirectory', () => {
  const orig = (window as any).showDirectoryPicker;
  afterEach(() => {
    (window as any).showDirectoryPicker = orig;
  });

  it('浏览器不支持时给出能看懂的提示', async () => {
    (window as any).showDirectoryPicker = undefined;
    await expect(pickDirectory()).rejects.toThrow(/不支持/);
  });

  it('以 readwrite 模式调起选择器', async () => {
    const picker = vi.fn(async () => fakeDir('picked'));
    (window as any).showDirectoryPicker = picker;
    const dir = await pickDirectory();
    expect(dir.name).toBe('picked');
    expect(picker).toHaveBeenCalledWith({ mode: 'readwrite' });
  });
});

describe('writeFileInto', () => {
  it('多级目录逐级创建', async () => {
    const root = fakeDir('root');
    await writeFileInto(root, 'a/b/c.txt', 'hello');
    expect(root.getDirectoryHandle).toHaveBeenCalledWith('a', { create: true });
    const a = await root.getDirectoryHandle('a');
    expect(a.getDirectoryHandle).toHaveBeenCalledWith('b', { create: true });
    const b = await a.getDirectoryHandle('b');
    expect(b.getFileHandle).toHaveBeenCalledWith('c.txt', { create: true });
  });

  it('根目录下的文件直接写', async () => {
    const root = fakeDir('root');
    await writeFileInto(root, 'SKILL.md', 'x');
    expect(root.getDirectoryHandle).not.toHaveBeenCalled();
    expect(root.getFileHandle).toHaveBeenCalledWith('SKILL.md', { create: true });
  });

  it('写入并关闭文件', async () => {
    const root = fakeDir('root');
    await writeFileInto(root, 'f.txt', 'data');
    const fh = await root.getFileHandle('f.txt');
    const ws = await fh.createWritable();
    expect(ws.write).toHaveBeenCalledWith('data');
    expect(ws.close).toHaveBeenCalled();
  });
});

describe('base64ToArrayBuffer', () => {
  it('base64 → 字节', () => {
    const buf = base64ToArrayBuffer('aGVsbG8=');
    expect(new TextDecoder().decode(buf)).toBe('hello');
  });
});

describe('downloadBlob', () => {
  it('用 <a download> 触发保存', () => {
    const origCreate = (URL as any).createObjectURL;
    const origRevoke = (URL as any).revokeObjectURL;
    (URL as any).createObjectURL = vi.fn(() => 'blob:fake');
    (URL as any).revokeObjectURL = vi.fn();
    const clicked: any[] = [];
    const origClick = HTMLAnchorElement.prototype.click;
    HTMLAnchorElement.prototype.click = function () { clicked.push(this); };

    try {
      downloadBlob(new Blob(['x']), 'pkg.zip');
      expect((URL as any).createObjectURL).toHaveBeenCalled();
      expect(clicked.length).toBe(1);
      expect(clicked[0].download).toBe('pkg.zip');
      expect(clicked[0].getAttribute('href')).toBe('blob:fake');
    } finally {
      HTMLAnchorElement.prototype.click = origClick;
      (URL as any).createObjectURL = origCreate;
      (URL as any).revokeObjectURL = origRevoke;
    }
  });
});
