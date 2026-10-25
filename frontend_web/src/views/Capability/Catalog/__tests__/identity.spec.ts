/**
 * 作者身份口径 —— 前端必须跟后端 `app/core/identity.py` 一致.
 *
 * ⚠️ 这组用例盯的是**真实故障**: 用户名改成邮箱式之后, 存量资产的 author
 * 还是短名 ('zhangsan' vs 'zhangsan@twsc.com.cn')。
 * 后端认两种写法, 前端如果只认一种, 就会出现:
 *   · 详情抽屉不显示「发布新版本」→ 作者更新不了自己的资产 (后端却放行)
 *   · 「只看这些」空空的 → 自己提交的资产整片消失
 *   · 被驳回后没有「重新提交审核」
 *   · 不能删掉自己还没上架的资产
 *
 * 所以任何"这是不是我的资产"的判断都得走 identity.isAuthor。
 */
import { describe, expect, it } from 'vitest';
import { authorForms, isAuthor } from '../identity';

describe('作者身份口径 (前端 ↔ 后端对齐)', () => {
  it('用户名是邮箱式 → 两种写法都认', () => {
    expect(isAuthor('zhangsan', 'zhangsan@twsc.com.cn')).toBe(true);
    expect(isAuthor('zhangsan@twsc.com.cn', 'zhangsan@twsc.com.cn')).toBe(true);
  });

  it('用户名是短名 → 两种写法都认', () => {
    expect(isAuthor('zhangsan@twsc.com.cn', 'zhangsan')).toBe(true);
    expect(isAuthor('zhangsan', 'zhangsan')).toBe(true);
  });

  it('大小写不敏感', () => {
    expect(isAuthor('ZhangSan', 'zhangsan@twsc.com.cn')).toBe(true);
    expect(isAuthor('zhangsan@twsc.com.cn', 'ZHANGSAN@TWSC.COM.CN')).toBe(true);
  });

  it('不是作者 → false', () => {
    expect(isAuthor('lisi', 'zhangsan@twsc.com.cn')).toBe(false);
    // ⚠️ 前缀相同但本地部分不同 → 不能算命中
    expect(isAuthor('zhangsan2', 'zhangsan@twsc.com.cn')).toBe(false);
  });

  it('空值不误判', () => {
    expect(isAuthor('', 'zhangsan@twsc.com.cn')).toBe(false);
    expect(isAuthor(null, null)).toBe(false);
    expect(isAuthor('zhangsan', '')).toBe(false);
  });

  it('authorForms 给出两种写法', () => {
    expect(authorForms('ZhangSan@twsc.com.cn')).toEqual(['zhangsan@twsc.com.cn', 'zhangsan']);
    expect(authorForms('zhangsan')).toEqual(['zhangsan']);
    expect(authorForms('')).toEqual([]);
  });
});
