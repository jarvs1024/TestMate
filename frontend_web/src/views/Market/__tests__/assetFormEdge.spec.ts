/**
 * 资产市场的**边界与异常** —— 正常路径之外最容易出事的地方.
 *
 * 覆盖: 长度/字符边界、规则在 create 与 update 下的差异、
 *       池子用尽时的兜底、空数据不崩.
 */
import { describe, expect, it } from 'vitest';
import {
  CODE_PREFIX, FALLBACK_ICONS, GENERAL_ICONS, ICON_POOLS,
  checkCodeSync, codeFromPackageName, pickIcon, validateCode, validatePackageName,
} from '../assetForm';

describe('code 校验: 边界', () => {
  it('长度 3-64 (与后端一致)', () => {
    expect(validateCode('dml-a')).toBe('');                 // 3 个
    expect(validateCode('dml-' + 'a'.repeat(60))).toBe('');  // 64 个
    expect(validateCode('dml-' + 'a'.repeat(61))).toContain('长度');
  });

  it('空 / 空白', () => {
    expect(validateCode('')).toContain('必填');
    expect(validateCode('   ')).toContain('必填');
  });

  it('连续连字符 / 首尾连字符 / 大小写 / 下划线 / 中文 都拒', () => {
    for (const bad of ['dml--x', 'dml-x-', '-dml-x', 'dml-Bad', 'dml_bad', 'dml-中文']) {
      expect(validateCode(bad), bad).not.toBe('');
    }
  });

  it('缺 dml- 前缀 → 明确提示', () => {
    expect(validateCode('weekly-report')).toContain(CODE_PREFIX);
  });
});

describe('包名校验: 边界 + create/update 差异', () => {
  it('新建要求 dml- 前缀, 更新不要求 (存量资产的 code 没有前缀)', () => {
    expect(validatePackageName('weekly-report.zip', { requirePrefix: true })).toContain('dml-');
    expect(validatePackageName('weekly-report.zip', { requirePrefix: false })).toBe('');
  });

  it('扩展名只认 zip / tar.gz / tgz', () => {
    expect(validatePackageName('dml-x.rar')).toContain('.zip');
    expect(validatePackageName('dml-x.exe')).toContain('.zip');
    expect(validatePackageName('dml-x.tar.gz')).toBe('');
    expect(validatePackageName('dml-x.tgz')).toBe('');
    expect(validatePackageName('dml-x')).toContain('.zip');
  });

  it('空文件名 → 提示选包', () => {
    expect(validatePackageName('')).toContain('请选择');
  });

  it('中文/空格/大写 → 拒', () => {
    for (const bad of ['dml-中文.zip', 'dml-my package.zip', 'dml-My-Pkg.zip']) {
      expect(validatePackageName(bad), bad).not.toBe('');
    }
  });
});

describe('包名 → code 推导', () => {
  it('各种扩展名都能正确去掉', () => {
    expect(codeFromPackageName('dml-a.zip')).toBe('dml-a');
    expect(codeFromPackageName('dml-a.tar.gz')).toBe('dml-a');
    expect(codeFromPackageName('dml-a.tgz')).toBe('dml-a');
    expect(codeFromPackageName('')).toBe('');
    expect(codeFromPackageName('noext')).toBe('noext');
  });
});

describe('一致性校验: 边界', () => {
  it('没选包 / 没填 code → 不报「不一致」(交给必填去报)', () => {
    expect(checkCodeSync('', { pkgBase: 'dml-a' })).toBe('');
    expect(checkCodeSync('dml-a', {})).toBe('');
    expect(checkCodeSync('dml-a', { isMcp: true, mcpNames: [] })).toBe('');
  });

  it('包名大小写不同也算不一致', () => {
    expect(checkCodeSync('dml-A', { pkgBase: 'dml-a' })).toContain('安装包名');
  });

  it('MCP: 多个连接器名里任意一个都算一致', () => {
    const names = ['dml-a', 'dml-b'];
    expect(checkCodeSync('dml-a', { isMcp: true, mcpNames: names })).toBe('');
    expect(checkCodeSync('dml-b', { isMcp: true, mcpNames: names })).toBe('');
    expect(checkCodeSync('dml-c', { isMcp: true, mcpNames: names })).toContain('连接器名');
  });
});

describe('图标分配: 兜底', () => {
  it('常用图标全被占用时, 还能从兜底池里挑到一个不重复的', () => {
    const used = new Set([...Object.values(ICON_POOLS).flat(), ...GENERAL_ICONS]);
    const icon = pickIcon({ category: '质量诊断', name: '诊断', used });
    expect(icon).toBeTruthy();
    expect(used.has(icon)).toBe(false);
  });

  it('连兜底池都用完了 → 也不返回空 (宁可重复也别没有图标)', () => {
    const everything = new Set([
      ...Object.values(ICON_POOLS).flat(), ...GENERAL_ICONS, ...FALLBACK_ICONS,
    ]);
    expect(pickIcon({ name: '诊断', used: everything })).toBeTruthy();
  });

  it('池子总量够大 —— 资产多了也有的选', () => {
    const all = new Set([
      ...Object.values(ICON_POOLS).flat(), ...GENERAL_ICONS, ...FALLBACK_ICONS,
    ]);
    expect(all.size).toBeGreaterThan(80);
  });
});
