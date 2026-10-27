/**
 * 能力卡片 (首页能力墙里的一张卡).
 *
 * 这张卡是这次重构的**核心产物** —— 以前它假设每张卡都是智能体,
 * 现在它按角色渲染. 所以要盯住三件事:
 *   ① 角色徽标 + 状态徽标都在 (角色说"扮演什么", 状态说"能不能用");
 *   ② CTA 文案按角色/卡片变 (点下去会发生什么, 用户必须一眼看出);
 *   ③ 规划中的卡**不可点**且有"规划中"遮罩 (别让用户点进一个空页面).
 */
import { describe, expect, it } from 'vitest';
import { mount } from '@vue/test-utils';
import CapabilityCard from '../CapabilityCard.vue';
import type { Capability } from '@/api/capabilities';

function cap(over: Partial<Capability> = {}): Capability {
  return {
    id: 1,
    code: 'log-analysis',
    name: '日志分析',
    icon: '📜',
    category: 'ssd-trace',
    kind: 'tool',
    version: 'v0.1.0-demo',
    status: 'beta',
    summary: '贴 kernel ring buffer, 自动分段 + 异常标注',
    use_when: '',
    not_for: '',
    tags: ['日志', '诊断'],
    engine: 'builtin',
    engine_config: {},
    input_schema: [],
    data_sources: [],
    tools: [],
    call_count: 12,
    last_called_at: null,
    is_featured: false,
    ...over,
  } as Capability;
}

describe('能力卡片', () => {
  it('渲染名称 / 摘要 / 标签', () => {
    const w = mount(CapabilityCard, { props: { capability: cap() } });
    expect(w.find('.cc-name').text()).toContain('日志分析');
    expect(w.find('.cc-summary').text()).toContain('kernel ring buffer');
    expect(w.findAll('.tag').map((t) => t.text())).toEqual(['#日志', '#诊断']);
  });

  it('显示角色徽标 (工具) + 状态徽标', () => {
    const w = mount(CapabilityCard, { props: { capability: cap() } });
    expect(w.find('.cc-kind').text()).toContain('工具');
    expect(w.find('.cc-badge').text()).toContain('公测');
  });

  it('角色不同 → 徽标与 CTA 都跟着变', () => {
    const board = mount(CapabilityCard, { props: { capability: cap({ kind: 'board', status: 'stable' }) } });
    expect(board.find('.cc-kind').text()).toContain('看板');
    expect(board.find('.cc-badge').text()).toContain('正常');
    expect(board.find('.cc-cta').text()).toContain('查看看板');

    const base = mount(CapabilityCard, { props: { capability: cap({ kind: 'platform', category: 'ssd-kb', status: 'stable', cta: '检索语料' }) } });
    expect(base.find('.cc-kind').text()).toContain('资产');
    expect(base.find('.cc-cta').text()).toContain('检索语料');
    expect(base.find('.cc-cat').text()).toContain('知识库');
  });

  it('CTA 用卡片自带的 cta (资产组里"浏览资产" vs "检索语料")', () => {
    const mkt = mount(CapabilityCard, { props: { capability: cap({ kind: 'platform', category: 'ai-market', cta: '浏览资产' }) } });
    expect(mkt.find('.cc-cta').text()).toContain('浏览资产');
    const kb = mount(CapabilityCard, { props: { capability: cap({ kind: 'platform', category: 'ssd-kb', cta: '检索语料' }) } });
    expect(kb.find('.cc-cta').text()).toContain('检索语料');
  });

  it('卡片没给 cta → 回落角色默认词', () => {
    const w = mount(CapabilityCard, { props: { capability: cap({ kind: 'tool', cta: '' }) } });
    expect(w.find('.cc-cta').text()).toContain('开始使用');
  });

  it('meta 行按角色渲染传入的真实指标', () => {
    const w = mount(CapabilityCard, {
      props: { capability: cap(), meta: [{ icon: '🔧', text: '平台内置' }, { icon: '🕐', text: '3 小时前' }] },
    });
    const items = w.findAll('.meta-item').map((i) => i.text());
    expect(items).toHaveLength(2);
    expect(items[0]).toContain('平台内置');
    expect(items[1]).toContain('3 小时前');
  });

  it('没有 meta 时给一个占位, 不留空白', () => {
    const w = mount(CapabilityCard, { props: { capability: cap() } });
    expect(w.find('.meta-empty').exists()).toBe(true);
  });

  it('规划中的卡: 有遮罩、不可点、没有 CTA', async () => {
    const w = mount(CapabilityCard, { props: { capability: cap({ status: 'draft' }) } });
    expect(w.find('.cc-overlay').text()).toContain('规划中');
    expect(w.find('.cc-cta').exists()).toBe(false);
    expect(w.attributes('role')).toBe('img');
    expect(w.attributes('tabindex')).toBe('-1');

    await w.trigger('click');
    expect(w.emitted('open')).toBeUndefined();
  });

  it('可用的卡: 点一下 emit open', async () => {
    const w = mount(CapabilityCard, { props: { capability: cap() } });
    expect(w.attributes('role')).toBe('button');
    await w.trigger('click');
    expect(w.emitted('open')?.[0]?.[0]).toMatchObject({ code: 'log-analysis' });
  });

  it('键盘也能打开 (enter / space)', async () => {
    const w = mount(CapabilityCard, { props: { capability: cap() } });
    await w.trigger('keydown.enter');
    await w.trigger('keydown.space');
    expect(w.emitted('open')).toHaveLength(2);
  });
});
