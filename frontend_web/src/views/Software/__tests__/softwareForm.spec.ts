/**
 * 软件库 表单规则 —— 校验必须跟后端一致 (app/core/software_store.py 的 CODE_RE).
 *
 * ⚠️ 前端不拦的话, 后端会 422, 用户只看到一句没头没尾的报错 ——
 *    所以这些规则必须有单测锁住, 改后端时也要跟着改.
 */
import { describe, expect, it } from 'vitest';
import {
  CODE_PATTERN, FILE_NAME_PATTERN, RESERVED_CODES, codeFromFileName, formatSize,
  splitFeatures, splitTags, validateCode, validateFileName, validateFileSize,
  validateName, validateVersion,
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

describe('软件包文件名 (2026-10-28)', () => {
  it('合法: 字母/数字开头, 可含 . _ -', () => {
    expect(validateFileName('ssd-log-doctor.bin')).toBe('');
    expect(validateFileName('Dify-Web-Entrypoint.sh')).toBe('');
    expect(validateFileName('tool_7.2.1.exe')).toBe('');
  });

  it('中文 / 空格 / 括号 → 拒绝 (会变成服务器目录名, 也影响下载)', () => {
    expect(validateFileName('SSD 日志医生.exe')).toContain('不合规');
    expect(validateFileName('demo (1).zip')).toContain('不合规');
    expect(validateFileName('demo .bin')).toContain('不合规');
  });

  it('不能以点开头 (那是隐藏文件), 不能有路径分隔符', () => {
    expect(validateFileName('..hidden.bin')).toContain('不合规');
    expect(validateFileName('../../etc/passwd')).toContain('不合规');
    expect(validateFileName('a/b.bin')).toContain('不合规');
  });

  it('空名 → 提示', () => {
    expect(validateFileName('')).toContain('不能为空');
  });

  it('正则跟后端一致 (抽样核对)', () => {
    expect(FILE_NAME_PATTERN.test('demo.bin')).toBe(true);
    expect(FILE_NAME_PATTERN.test('Demo.bin')).toBe(true);
    expect(FILE_NAME_PATTERN.test('demo 中文.bin')).toBe(false);
    expect(FILE_NAME_PATTERN.test('.demo')).toBe(false);
  });
});

describe('软件标识自动生成 (codeFromFileName)', () => {
  it('去扩展名 + 转小写', () => {
    expect(codeFromFileName('Dify-Web-Entrypoint.sh')).toBe('dify-web-entrypoint');
    expect(codeFromFileName('ssd_log_doctor.bin')).toBe('ssd_log_doctor');
  });

  it('只去掉最后一段扩展名 (a.tar.gz → a.tar)', () => {
    expect(codeFromFileName('a.tar.gz')).toBe('a.tar');
  });

  it('非法字符 → 连字符, 连续连字符合并', () => {
    expect(codeFromFileName('my tool!!v2.bin')).toBe('my-tool-v2');
  });

  it('空 / 全非法 → 兜底', () => {
    expect(codeFromFileName('.bin')).toBe('software');
    expect(codeFromFileName('')).toBe('software');
  });

  it('太短补齐到 2 位 (后端 CODE_RE 至少 2 位)', () => {
    expect(codeFromFileName('a.bin')).toBe('a0');
    expect(codeFromFileName('7.zip')).toBe('70');
  });

  it('长度截断到 64', () => {
    expect(codeFromFileName(`${'a'.repeat(100)}.bin`).length).toBe(64);
  });

  it('派生结果必须是合法 code (能过 validateCode)', () => {
    for (const n of ['Dify-Web-Entrypoint.sh', 'my tool!!v2.bin', 'a.tar.gz', '7.zip']) {
      expect(validateCode(codeFromFileName(n))).toBe('');
    }
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
