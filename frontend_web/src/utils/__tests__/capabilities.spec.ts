/**
 * 能力工具函数 (排序 / 搜索 / 路由解析 / 相对时间).
 *
 * 排序规则是这次重构里最容易被悄悄改坏的一条:
 *   以前 draft 卡和 stable 卡混排, 用户第一眼看到的是"建设中".
 *   现在规划中的能力必须沉底 —— 所以这条要有单测钉住.
 */
import { describe, expect, it } from 'vitest';
import {
  PLATFORM_META_SOURCE,
  capabilityCta,
  capabilityRouteName,
  engineLabel,
  matchesKeyword,
  relativeTime,
  sortCapabilities,
} from '@/utils/capabilities';
import type { Capability } from '@/api/capabilities';

function cap(over: Partial<Capability> = {}): Capability {
  return {
    id: 1,
    code: 'c1',
    name: '能力',
    icon: '🛠',
    category: 'ssd-trace',
    kind: 'tool',
    version: 'v0.1.0',
    status: 'stable',
    summary: '摘要',
    use_when: '',
    not_for: '',
    tags: [],
    engine: 'builtin',
    engine_config: {},
    input_schema: [],
    data_sources: [],
    tools: [],
    call_count: 0,
    last_called_at: null,
    is_featured: false,
    ...over,
  } as Capability;
}

describe('能力工具函数', () => {
  it('规划中的能力沉底', () => {
    const list = [
      cap({ id: 1, code: 'planned', status: 'draft' }),
      cap({ id: 2, code: 'ready', status: 'stable' }),
    ];
    expect(sortCapabilities(list).map((c) => c.code)).toEqual(['ready', 'planned']);
  });

  it('同组内精选优先, 再按注册顺序', () => {
    const list = [
      cap({ id: 3, code: 'c' }),
      cap({ id: 1, code: 'a', is_featured: true }),
      cap({ id: 2, code: 'b' }),
    ];
    expect(sortCapabilities(list).map((c) => c.code)).toEqual(['a', 'b', 'c']);
  });

  it('排序不改动原数组 (别把 store 里的顺序搅乱)', () => {
    const list = [cap({ id: 2, code: 'b' }), cap({ id: 1, code: 'a' })];
    sortCapabilities(list);
    expect(list.map((c) => c.code)).toEqual(['b', 'a']);
  });

  it('关键词匹配: 名称 / 摘要 / 标签任一命中', () => {
    const c = cap({ name: '日志分析', summary: '贴 kernel ring buffer', tags: ['诊断'] });
    expect(matchesKeyword(c, '')).toBe(true);
    expect(matchesKeyword(c, '日志')).toBe(true);
    expect(matchesKeyword(c, 'kernel')).toBe(true);
    expect(matchesKeyword(c, '诊断')).toBe(true);
    expect(matchesKeyword(c, '不存在')).toBe(false);
  });

  it('路由解析: page: 前缀走自定义页, 其余走工具型运行页', () => {
    expect(capabilityRouteName(cap({ route: 'page:code-review' }))).toBe('code-review');
    expect(capabilityRouteName(cap({ route: 'page:market' }))).toBe('market');
    expect(capabilityRouteName(cap({ route: null }))).toBe('tool-runner');
    expect(capabilityRouteName(cap({ route: '' }))).toBe('tool-runner');
  });

  it('相对时间: 没调用过 / 刚刚 / 分钟 / 小时 / 天', () => {
    expect(relativeTime(null)).toBe('还没用过');
    expect(relativeTime(new Date().toISOString())).toBe('刚刚');
    expect(relativeTime(new Date(Date.now() - 5 * 60000).toISOString())).toBe('5 分钟前');
    expect(relativeTime(new Date(Date.now() - 3 * 3600000).toISOString())).toBe('3 小时前');
    expect(relativeTime(new Date(Date.now() - 2 * 86400000).toISOString())).toBe('2 天前');
    expect(relativeTime('not-a-date')).toBe('—');
  });

  it('CTA 优先用卡片自带的, 空才回落角色默认词', () => {
    // 资产组两张卡动法不同: 浏览资产 vs 检索语料 —— 所以 CTA 必须来自卡片
    expect(capabilityCta({ kind: 'platform', cta: '浏览技能包' })).toBe('浏览技能包');
    expect(capabilityCta({ kind: 'platform', cta: '检索语料' })).toBe('检索语料');
    expect(capabilityCta({ kind: 'platform', cta: '' })).toBe('打开');
    expect(capabilityCta({ kind: 'platform' })).toBe('打开');
    expect(capabilityCta({ kind: 'tool', cta: '开始使用' })).toBe('开始使用');
    expect(capabilityCta({ kind: 'board' })).toBe('查看看板');
  });

  it('资产取数来源: 插件·技能·连接数资产, 知识库数语料', () => {
    expect(PLATFORM_META_SOURCE['agent-market']).toBe('assets');
    expect(PLATFORM_META_SOURCE['kb-inventory']).toBe('kb');
  });

  it('引擎名: 短名可读', () => {
    expect(engineLabel('n8n')).toBe('n8n');
    expect(engineLabel('builtin')).toBe('平台内置');
    expect(engineLabel('')).toBe('—');
  });

  /**
   * Dify 2026-10-25 已整个下线 (平台不再接入) —— 界面上不能再出现这个词.
   * 存量行由迁移 0019 改成 builtin, engineLabel 再兜一层, 万一有环境漏跑迁移
   * 也不能让 "Dify" 漏到卡片上.
   */
  it('引擎名里不再有 Dify (下线了, 存量值也不许露出来)', () => {
    expect(engineLabel('dify')).not.toContain('Dify');
    expect(engineLabel('dify')).toBe('AI 引擎');
  });
});
