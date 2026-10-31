/**
 * 作者口径 (`@/utils/author`) —— 判"是不是我的" + **显示**成什么样.
 *
 * ⚠️ 两件事别混:
 *   · `isAuthor()`  —— **判断**用, 短名/全邮箱**双向**都认 (跟后端 identity 一个口径);
 *   · `displayAuthor()` —— **显示**用, 只给用户名 (2026-10-31 第十六轮:
 *     卡片上作者只显示 `jiakejiang`, 不显示 `jiakejiang@twsc.com.cn`).
 */
import { describe, expect, it } from 'vitest';
import { authorForms, displayAuthor, isAuthor } from '@/utils/author';

describe('authorForms', () => {
  it('全邮箱 → [全邮箱, 短名]', () => {
    expect(authorForms('zhangsan@twsc.com.cn')).toEqual(['zhangsan@twsc.com.cn', 'zhangsan']);
  });

  it('短名 → 只有自己', () => {
    expect(authorForms('zhangsan')).toEqual(['zhangsan']);
  });

  it('空 → 空数组', () => {
    expect(authorForms('')).toEqual([]);
    expect(authorForms(null)).toEqual([]);
    expect(authorForms(undefined)).toEqual([]);
  });
});

describe('isAuthor', () => {
  it('完全相同 → 是我', () => {
    expect(isAuthor('zhangsan', 'zhangsan')).toBe(true);
    expect(isAuthor('zhangsan@twsc.com.cn', 'zhangsan@twsc.com.cn')).toBe(true);
  });

  it('短名 vs 全邮箱 → 仍然是同一个 (双向都认)', () => {
    expect(isAuthor('zhangsan@twsc.com.cn', 'zhangsan')).toBe(true);
    expect(isAuthor('zhangsan', 'zhangsan@twsc.com.cn')).toBe(true);
  });

  it('不是同一个人 → false', () => {
    expect(isAuthor('lisi', 'zhangsan')).toBe(false);
  });

  it('空 → false (别把"没作者"当成"是我的")', () => {
    expect(isAuthor('', 'zhangsan')).toBe(false);
    expect(isAuthor('zhangsan', '')).toBe(false);
  });
});

describe('displayAuthor (卡片上显示的作者名)', () => {
  it('全邮箱 → 只留用户名', () => {
    expect(displayAuthor('jiakejiang@twsc.com.cn')).toBe('jiakejiang');
  });

  it('短名 → 原样', () => {
    expect(displayAuthor('admin')).toBe('admin');
  });

  it('空 → 空串 (调用方自己兜底成「未知」)', () => {
    expect(displayAuthor('')).toBe('');
    expect(displayAuthor(null)).toBe('');
    expect(displayAuthor(undefined)).toBe('');
  });

  it('首尾空格先去掉', () => {
    expect(displayAuthor('  zhangsan@twsc.com.cn  ')).toBe('zhangsan');
  });
});
