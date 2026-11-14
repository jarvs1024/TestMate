/**
 * kbSpace store —— 空间选择的持久化与失效兜底.
 *
 * 盯住三件事:
 *   ① 没有选择时落到默认空间 (不能是空串, 否则所有 KB 请求都按"默认"发, 看不出问题);
 *   ② 用户的选择要落 localStorage —— 刷新后还在;
 *   ③ 存着的 id 已失效 (空间被删) → 退回默认空间, 不能让 KB 页面整页 404.
 */
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { createPinia, setActivePinia } from 'pinia';

const { listKbSpaces } = vi.hoisted(() => ({ listKbSpaces: vi.fn() }));

vi.mock('@/api/kb', () => ({ listKbSpaces }));

import { KB_SPACE_STORAGE_KEY, useKbSpaceStore } from '../kbSpace';

const SPACES = {
  items: [
    { id: 'sp_a', name: 'A', is_default: true, configured: true },
    { id: 'sp_b', name: 'B', is_default: false, configured: true },
  ],
  default_id: 'sp_a',
};

beforeEach(() => {
  localStorage.clear();
  setActivePinia(createPinia());
  listKbSpaces.mockReset();
  listKbSpaces.mockResolvedValue(SPACES);
});

describe('kbSpace store', () => {
  it('没有保存过选择时落到默认空间', async () => {
    const s = useKbSpaceStore();
    await s.load();
    expect(s.currentId).toBe('sp_a');
    expect(s.currentName).toBe('A');
    expect(localStorage.getItem(KB_SPACE_STORAGE_KEY)).toBe('sp_a');
  });

  it('显式选择会持久化, 未知 id 被忽略', async () => {
    const s = useKbSpaceStore();
    await s.load();
    expect(s.switchTo('sp_b')).toBe(true);
    expect(s.currentId).toBe('sp_b');
    expect(localStorage.getItem(KB_SPACE_STORAGE_KEY)).toBe('sp_b');

    expect(s.switchTo('sp_missing')).toBe(false);
    expect(s.currentId).toBe('sp_b');
    expect(localStorage.getItem(KB_SPACE_STORAGE_KEY)).toBe('sp_b');
  });

  it('保存的空间已失效时退回默认空间', async () => {
    localStorage.setItem(KB_SPACE_STORAGE_KEY, 'sp_deleted');
    const s = useKbSpaceStore();
    await s.load();
    expect(s.currentId).toBe('sp_a');
    expect(localStorage.getItem(KB_SPACE_STORAGE_KEY)).toBe('sp_a');
  });

  it('一个空间都没有时清掉选择并显示未配置', async () => {
    listKbSpaces.mockResolvedValue({ items: [], default_id: '' });
    const s = useKbSpaceStore();
    await s.load();
    expect(s.currentId).toBe('');
    expect(s.currentName).toBe('未配置空间');
    expect(localStorage.getItem(KB_SPACE_STORAGE_KEY)).toBeNull();
  });
});
