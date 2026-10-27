/**
 * 软件库 表单规则 —— 校验必须跟后端一致 (app/core/software_store.py 的 CODE_RE).
 *
 * ⚠️ 前端不拦的话, 后端会 422, 用户只看到一句没头没尾的报错 ——
 *    所以这些规则必须有单测锁住, 改后端时也要跟着改.
 */
import { describe, expect, it } from 'vitest';
import {
  CODE_PATTERN, RESERVED_CODES, formatSize, splitFeatures, splitTags,
  validateCode, validateFileSize, validateName, validateVersion,
} from '../softwareForm';

describe('软件标识 (code)', () => {
  it('合法: 小写字母数字开头, 可含 - _ .', () => {
    expect(validateCode('ssd-log-doctor')).toBe('');
    expect(validateCode('tool7')).toBe('');
    expect(validateCode('a.b_c-d')).toBe('');
  });

  it('必填', () => {
    expect(validateCode('')).toContain('必填');
    expect(validateCode('   ')).toContain('必填');
  });

  it('不许大写 / 中文 / 空格', () => {
    expect(validateCode('SSDLog')).not.toBe('');
    expect(validateCode('日志医生')).not.toBe('');
    expect(validateCode('a b')).not.toBe('');
  });

  it('不许以符号开头', () => {
    expect(validateCode('-abc')).not.toBe('');
    expect(validateCode('.abc')).not.toBe('');
    expect(validateCode('_abc')).not.toBe('');
  });

  it('路径穿越必须挡住 —— code 会变成服务端目录名', () => {
    expect(validateCode('../etc')).not.toBe('');
    expect(validateCode('a/b')).not.toBe('');
    expect(validateCode('..')).not.toBe('');
  });

  it('保留字不能当 code (跟固定路由撞车)', () => {
    for (const c of RESERVED_CODES) {
      expect(validateCode(c)).toContain('不能叫');
    }
  });

  it('正则跟后端一致 (抽样核对)', () => {
    expect(CODE_PATTERN.test('demo-sw')).toBe(true);
    expect(CODE_PATTERN.test('Demo')).toBe(false);
    expect(CODE_PATTERN.test('a')).toBe(false);   // 至少 2 位
  });
});

describe('版本号', () => {
  it('必填且不许斜杠', () => {
    expect(validateVersion('')).toContain('必填');
    expect(validateVersion('1.0.0')).toBe('');
    expect(validateVersion('1.0.0/../x')).toContain('斜杠');
  });

  it('长度上限 32', () => {
    expect(validateVersion('v'.repeat(33))).toContain('32');
    expect(validateVersion('v'.repeat(32))).toBe('');
  });
});

describe('软件名', () => {
  it('必填 + 长度上限', () => {
    expect(validateName('')).toContain('必填');
    expect(validateName('x'.repeat(129))).toContain('128');
    expect(validateName('演示软件')).toBe('');
  });
});

describe('文件大小', () => {
  it('没选文件 → 提示选文件', () => {
    expect(validateFileSize(0, 1024)).toContain('请选择');
  });

  it('超上限 → 拦下 (前端先拦一道, 省一次白跑的上传)', () => {
    const err = validateFileSize(2048, 1024);
    expect(err).toContain('太大');
    expect(err).toContain('1.0 KB');
  });

  it('没超就放行', () => {
    expect(validateFileSize(512, 1024)).toBe('');
  });
});

describe('体积显示', () => {
  it('B / KB / MB / GB', () => {
    expect(formatSize(512)).toBe('512 B');
    expect(formatSize(2048)).toBe('2.0 KB');
    expect(formatSize(5 * 1024 * 1024)).toBe('5.0 MB');
    expect(formatSize(5 * 1024 * 1024 * 1024)).toBe('5.00 GB');
  });
});

describe('列表拆分', () => {
  it('标签: 逗号/顿号/空格分隔都能拆', () => {
    expect(splitTags('a, b、c d')).toEqual(['a', 'b', 'c', 'd']);
    expect(splitTags('a,a,b')).toEqual(['a', 'b']);   // 去重
    expect(splitTags('')).toEqual([]);
  });

  it('功能清单: 一行一条', () => {
    expect(splitFeatures('功能一\n功能二\n\n  功能三  ')).toEqual(['功能一', '功能二', '功能三']);
    expect(splitFeatures('')).toEqual([]);
  });
});
