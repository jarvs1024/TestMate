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

  it('连接器不再强调「不需要安装包 / 没有 README」', () => {
    const mcp = kindMeta('mcp');
    const all = [mcp.tagline, mcp.formHint, mcp.needs.join(' ')].join(' ');
    expect(all).not.toContain('不需要安装包');
    expect(all).not.toContain('没有 README');
    expect(all).not.toContain('不用打包');
  });

  it('包内含的东西写通用描述, 不列实现细节', () => {
    const skill = kindMeta('skill');
    expect(skill.needs.join(' ')).toContain('SKILL.md');
    expect(skill.needs.join(' ')).toContain('配套脚本');
    const plugin = kindMeta('plugin');
    expect(plugin.needs.join(' ')).toContain('README.md');
    expect(plugin.needs.join(' ')).not.toContain('plugin.json');
  });

  it('统一叫「Agent」, 不用「宿主」', () => {
    for (const k of KIND_META) {
      const all = [k.tagline, k.formHint, k.needs.join(' ')].join(' ');
      expect(all).not.toContain('宿主');
    }
  });

  it('未知类型兜底回技能, 不返回空', () => {
    expect(kindMeta('nope').value).toBe('skill');
    expect(kindMeta(undefined).value).toBe('skill');
  });
});
