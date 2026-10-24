/**
 * 上传表单的取值规则 —— 资产 code 的命名约定 + 图标自动分配.
 *
 * 两条硬约定 (2026-10-24):
 *  1. code = 包名 = 插件名 → 英文, 且统一以 "dml-" 开头
 *  2. 图标自动分配, 且**不能跟现有资产重复** (重复图标在卡片上分不清谁是谁)
 */
import { describe, expect, it } from 'vitest';
import {
  CODE_PREFIX,
  GENERAL_ICONS,
  ICON_POOLS,
  pickIcon,
  validateCode,
} from '../assetForm';

describe('资产 code 命名约定', () => {
  it('必须以 dml- 开头', () => {
    expect(validateCode('dml-ssd-log-doctor')).toBe('');
    expect(validateCode('ssd-log-doctor')).toContain('dml-');
    expect(validateCode('')).toContain('必填');
  });

  it('只能是英文小写/数字/连字符', () => {
    expect(validateCode('dml-SSD-Log')).toContain('小写字母');
    expect(validateCode('dml-日志医生')).toContain('小写字母');
    expect(validateCode('dml-中文')).toContain('小写字母');
  });

  it('不能有连续/首尾连字符', () => {
    expect(validateCode('dml--abc')).toContain('小写字母');
    expect(validateCode('dml-abc-')).toContain('小写字母');
  });

  it('合法例子', () => {
    for (const c of ['dml-a', 'dml-ssd-log-doctor', 'dml-trace-kit-2', 'dml-qoder123']) {
      expect(validateCode(c)).toBe('');
    }
  });

  it('前缀常量跟校验规则一致', () => {
    expect(CODE_PREFIX).toBe('dml-');
  });
});

describe('图标自动分配', () => {
  it('不跟现有资产重复', () => {
    const used = ['🔍', '🩺', '📈'];
    const icon = pickIcon({ category: '质量诊断', name: '日志诊断', used });
    expect(used).not.toContain(icon);
  });

  it('按名称关键词猜 (比分类更精准)', () => {
    expect(pickIcon({ name: 'SSD 日志诊断助手' })).toBe('🔍');
    expect(pickIcon({ name: '周报生成' })).toBe('📈');
    expect(pickIcon({ name: '测试报告生成' })).toBe('📊');
    expect(pickIcon({ name: '测试方案助手' })).toBe('📝');
  });

  it('猜不到就按分类池', () => {
    const icon = pickIcon({ category: '知识资产', name: 'zzz' });
    expect(ICON_POOLS['知识资产']).toContain(icon);
  });

  it('分类池用完了会退到通用池, 通用池也用完还有兜底池', () => {
    const all = Object.values(ICON_POOLS).flat();
    const used = new Set([...all, ...GENERAL_ICONS]);
    const icon = pickIcon({ category: '知识资产', name: 'zzz', used });
    expect(used.has(icon)).toBe(false);
    expect(icon).toBeTruthy();
  });

  it('全都被占用时也有兜底 (不返回空)', () => {
    const everything = new Set([
      ...Object.values(ICON_POOLS).flat(),
      ...GENERAL_ICONS,
    ]);
    expect(pickIcon({ name: '日志诊断', used: everything })).toBeTruthy();
  });
});
