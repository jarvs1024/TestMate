/**
 * 本机标识 clientId —— 安装记录按它隔离.
 * 之前硬编码成 'web', 团队多人共用一个 TestMate 时所有人的安装记录会串成一条.
 */
import { beforeEach, describe, expect, it } from 'vitest';
import { getClientId } from '../clientId';

describe('getClientId', () => {
  beforeEach(() => {
    localStorage.clear();
  });

  it('同一浏览器多次调用返回同一个 id', () => {
    const a = getClientId();
    const b = getClientId();
    expect(a).toBe(b);
    expect(a).toBeTruthy();
  });

  it('落到 localStorage 里 (重启后仍是同一个)', () => {
    const id = getClientId();
    expect(localStorage.getItem('testmate.client_id')).toBe(id);
  });

  it('是 uuid 形状 (不泄露机器信息)', () => {
    const id = getClientId();
    expect(id).toMatch(/^[0-9a-f-]{36}$/i);
  });

  it('localStorage 不可用时退化成会话级 id 而不是抛错', () => {
    const orig = Storage.prototype.getItem;
    Storage.prototype.getItem = () => {
      throw new Error('blocked');
    };
    try {
      const id = getClientId();
      expect(id).toMatch(/^anon-/);
    } finally {
      Storage.prototype.getItem = orig;
    }
  });
});
