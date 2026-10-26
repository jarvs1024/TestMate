import { describe, it, expect } from 'vitest';
import { errorDetail, errorStatus, httpErrorText } from '../httpError';

describe('httpErrorText', () => {
  it('502 必须翻成人话 —— 页面能开但后端没跑, 这是本地部署最常见的故障', () => {
    const t = httpErrorText(502);
    expect(t).toContain('后端');
    expect(t).toContain('502');
    // ⚠️ 原始报文是 "Request failed with status code 502" —— 对用户等于天书
    expect(t).not.toContain('Request failed');
  });

  it('503 / 504 / 500 也得说清楚是哪一环坏了', () => {
    expect(httpErrorText(503)).toContain('数据库');
    // ⚠️ nginx 上游不可达时有时返 504 不是 502 —— 译文也得覆盖"后端没在跑"
    expect(httpErrorText(504)).toContain('后端');
    expect(httpErrorText(500)).toContain('500');
  });

  it('4xx 各有各的说法', () => {
    expect(httpErrorText(404)).toContain('404');
    expect(httpErrorText(403)).toContain('权限');
    expect(httpErrorText(429)).toContain('频繁');
  });

  it('后端给了 detail 就用 detail —— 那比状态码翻译更精确', () => {
    expect(httpErrorText(500, '资产市场工作区被占用')).toBe('资产市场工作区被占用');
    expect(httpErrorText(500, { message: '工作区被占用' })).toBe('工作区被占用');
  });

  it('detail 是空白字符串时不能被当成有效信息', () => {
    expect(httpErrorText(502, '   ')).toContain('后端');
    expect(httpErrorText(502, {})).toContain('后端');
  });

  it('既没状态码也没 detail 才用 fallback', () => {
    expect(httpErrorText(undefined, undefined, '未知错误')).toBe('未知错误');
    expect(httpErrorText(null)).toBe('未知错误');
  });

  it('有状态码但没有对应译文时, 至少带上状态码', () => {
    expect(httpErrorText(418)).toContain('418');
  });
});

describe('errorStatus / errorDetail', () => {
  it('能从 axios 形状的错误里取出状态码和 detail', () => {
    const e = { response: { status: 502, data: { detail: '后端没起来' } } };
    expect(errorStatus(e)).toBe(502);
    expect(errorDetail(e)).toBe('后端没起来');
  });

  it('错误对象形状不对时不能炸', () => {
    expect(errorStatus(null)).toBeNull();
    expect(errorStatus({})).toBeNull();
    expect(errorDetail(undefined)).toBeUndefined();
    expect(errorStatus({ response: { status: '502' } })).toBeNull();
  });
});
