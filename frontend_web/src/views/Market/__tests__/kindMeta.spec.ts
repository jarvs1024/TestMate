/**
 * 资产形态的元信息 —— 上传入口与抽屉共用同一份.
 *
 * 这份数据决定了「先选形态」那一步能不能说清话:
 * 连接器必须一眼看出**不需要安装包**, 否则用户还会去找上传框。
 */
import { describe, expect, it } from 'vitest';
import { KIND_META, kindMeta } from '../kindMeta';

describe('资产形态元信息', () => {
  it('三种形态齐全, 值不重复', () => {
    expect(KIND_META.map((k) => k.value)).toEqual(['skill', 'plugin', 'mcp']);
    expect(new Set(KIND_META.map((k) => k.value)).size).toBe(3);
  });

  it('每种形态都说明了「需要准备什么」', () => {
    for (const k of KIND_META) {
      expect(k.needs.length).toBeGreaterThan(0);
      expect(k.tagline.length).toBeGreaterThan(0);
      expect(k.formHint.length).toBeGreaterThan(0);
      expect(k.icon.length).toBeGreaterThan(0);
    }
  });

  it('连接器明确写了「不需要安装包」', () => {
    const mcp = kindMeta('mcp');
    expect(mcp.needs.join(' ')).toContain('不需要安装包');
    expect(mcp.formHint).toContain('不需要安装包');
  });

  it('技能 / 插件说明的是安装包里要有什么', () => {
    expect(kindMeta('skill').needs.join(' ')).toContain('SKILL.md');
    expect(kindMeta('plugin').needs.join(' ')).toContain('plugin.json');
  });

  it('未知类型兜底回技能, 不返回空', () => {
    expect(kindMeta('nope').value).toBe('skill');
    expect(kindMeta(undefined).value).toBe('skill');
  });
});
