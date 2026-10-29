/**
 * 时间解析的时区契约 —— **后端给的是 UTC**, 缺后缀的一律当 UTC.
 *
 * ⚠️ 这组用例锁的是本项目的老约定: 库里存 naive UTC, API 输出带 `Z`.
 *    JS 的 `new Date("2026-10-28T16:09:01")` 会按**本地时区**解析,
 *    本机是 UTC+8 → 显示出来差 8 小时.
 */
import { describe, it, expect } from 'vitest';
import { parseApiTime, fmtIso, fmtDate, fmtChunkMethod } from '@/utils/format';
import { relativeTime } from '@/utils/capabilities';

/** 造一个"某个固定时刻"的 Date, 跟本机时区无关 */
const UTC = Date.UTC(2026, 9, 28, 16, 9, 1); // 2026-10-28 16:09:01 UTC

describe('parseApiTime', () => {
  it('没时区后缀的当 UTC —— 不是本地时间', () => {
    const d = parseApiTime('2026-10-28T16:09:01');
    expect(d).not.toBeNull();
    expect(d!.getTime()).toBe(UTC);
  });

  it('带 Z 的原样解析', () => {
    const d = parseApiTime('2026-10-28T16:09:01Z');
    expect(d!.getTime()).toBe(UTC);
  });

  it('带偏移量的按偏移解析', () => {
    const d = parseApiTime('2026-10-29T00:09:01+08:00');
    expect(d!.getTime()).toBe(UTC);
  });

  it('带小数秒的也能解析 (毫秒不能丢)', () => {
    const d = parseApiTime('2026-10-28T16:09:01.123456');
    expect(d!.getTime()).toBe(UTC + 123);
  });

  it('只有日期的当 UTC 当天零点', () => {
    const d = parseApiTime('2026-10-28');
    expect(d!.toISOString()).toBe('2026-10-28T00:00:00.000Z');
  });

  it('空格分隔的也能解析', () => {
    const d = parseApiTime('2026-10-28 16:09:01');
    expect(d!.getTime()).toBe(UTC);
  });

  it('epoch ms 原样解析', () => {
    const d = parseApiTime(UTC);
    expect(d!.getTime()).toBe(UTC);
  });

  it('空值 / 坏值返回 null (不抛)', () => {
    expect(parseApiTime(null)).toBeNull();
    expect(parseApiTime(undefined)).toBeNull();
    expect(parseApiTime('')).toBeNull();
    expect(parseApiTime('   ')).toBeNull();
    expect(parseApiTime('不是时间')).toBeNull();
  });
});

describe('fmtIso / fmtDate', () => {
  it('按**本地时区**显示', () => {
    // 本机在 UTC+8 → UTC 16:09 = 本地 2026-10-29 00:09
    const local = new Date(UTC);
    const pad = (n: number) => String(n).padStart(2, '0');
    const expectStr =
      `${local.getFullYear()}-${pad(local.getMonth() + 1)}-${pad(local.getDate())} `
      + `${pad(local.getHours())}:${pad(local.getMinutes())}`;
    expect(fmtIso('2026-10-28T16:09:01')).toBe(expectStr);
    expect(fmtIso('2026-10-28T16:09:01Z')).toBe(expectStr);
  });

  it('带 Z 和不带 Z 显示**同一个**结果 (这是这次要修的核心)', () => {
    expect(fmtIso('2026-10-28T16:09:01')).toBe(fmtIso('2026-10-28T16:09:01Z'));
  });

  it('fmtDate 只到天, 也按本地时区', () => {
    const local = new Date(UTC);
    const pad = (n: number) => String(n).padStart(2, '0');
    expect(fmtDate('2026-10-28T16:09:01')).toBe(
      `${local.getFullYear()}-${pad(local.getMonth() + 1)}-${pad(local.getDate())}`,
    );
  });

  it('空值显示 —', () => {
    expect(fmtIso(null)).toBe('—');
    expect(fmtIso(undefined)).toBe('—');
    expect(fmtIso('')).toBe('—');
    expect(fmtDate(null)).toBe('—');
  });
});

describe('relativeTime', () => {
  it('按 UTC 算差值 —— 不是差 8 小时', () => {
    // 10 分钟前 (UTC)
    const tenMinAgo = new Date(Date.now() - 10 * 60_000).toISOString().replace('Z', '');
    expect(relativeTime(tenMinAgo)).toBe('10 分钟前');
  });

  it('刚发出来的是「刚刚」', () => {
    const now = new Date(Date.now() - 5_000).toISOString().replace('Z', '');
    expect(relativeTime(now)).toBe('刚刚');
  });

  it('空值说「还没用过」', () => {
    expect(relativeTime(null)).toBe('还没用过');
    expect(relativeTime('')).toBe('还没用过');
  });
});

describe('fmtChunkMethod', () => {
  it('⚠️ RAGFlow 1.0 新建的数据集是 "general" —— 老库才是 "naive"', () => {
    // 这俩是同一个东西 (通用切片), 显示上要一样, 不然新建的库看着像异类
    expect(fmtChunkMethod('general')).toBe('通用');
    expect(fmtChunkMethod('naive')).toBe('通用');
  });

  it('其它切片法照旧', () => {
    expect(fmtChunkMethod('manual')).toBe('手册');
    expect(fmtChunkMethod('qa')).toBe('问答');
  });

  it('认不出来的原样返回, 不返回空', () => {
    expect(fmtChunkMethod('brand-new')).toBe('brand-new');
    expect(fmtChunkMethod('')).toBe('—');
  });
});
