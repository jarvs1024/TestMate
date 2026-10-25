/**
 * 能力形态常量 (2026-10-25 能力墙重构).
 *
 * 这个文件看着像"纯展示映射", 但它承载的是**产品规则**, 所以必须有单测锁住:
 *   ① 状态词按形态换 —— 对看板/目录/知识说 "Beta / 稳定" 没有决策价值,
 *      但"未接入"是必须说清楚的 (服务没配 = 用不了);
 *   ② 未知 kind 必须兜底成 tool —— 后端加新形态时前端不能白屏;
 *   ③ 规划中 (draft) 的判定 —— 它决定卡片能不能点.
 */
import { describe, expect, it } from 'vitest';
import {
  CAPABILITY_KINDS,
  CATEGORY_LABELS,
  categoryLabel,
  isPlanned,
  kindLabel,
  kindMeta,
  statusLabel,
} from '@/constants/capabilityKinds';

describe('能力形态常量', () => {
  it('四种形态齐全, 顺序固定 (侧栏分组 / 筛选 chips 靠它)', () => {
    expect(CAPABILITY_KINDS.map((k) => k.value)).toEqual(['tool', 'board', 'catalog', 'library']);
    expect(CAPABILITY_KINDS.map((k) => k.label)).toEqual(['工具', '看板', '目录', '知识']);
  });

  it('每种形态都有 CTA —— 卡片不全是智能体后, 用户必须知道点下去会发生什么', () => {
    for (const k of CAPABILITY_KINDS) {
      expect(k.cta).toBeTruthy();
    }
    expect(kindMeta('tool').cta).toBe('开始使用');
    expect(kindMeta('board').cta).toBe('查看看板');
    expect(kindMeta('catalog').cta).toBe('浏览资产');
    expect(kindMeta('library').cta).toBe('管理知识');
  });

  it('未知 kind 兜底成工具 (不白屏)', () => {
    expect(kindMeta('unknown' as any).value).toBe('tool');
    expect(kindMeta(undefined).value).toBe('tool');
    expect(kindMeta(null).value).toBe('tool');
    expect(kindLabel('nope' as any)).toBe('工具');
  });

  it('状态词按形态换: 工具说"规划中/公测", 知识说"未接入/正常"', () => {
    expect(statusLabel('tool', 'draft')).toBe('规划中');
    expect(statusLabel('tool', 'beta')).toBe('公测');
    expect(statusLabel('tool', 'stable')).toBe('可用');
    expect(statusLabel('library', 'draft')).toBe('未接入');
    expect(statusLabel('library', 'stable')).toBe('正常');
    expect(statusLabel('board', 'beta')).toBe('正常');
    expect(statusLabel('catalog', 'stable')).toBe('正常');
  });

  it('已下线对所有形态一致', () => {
    for (const k of CAPABILITY_KINDS) {
      expect(statusLabel(k.value, 'deprecated')).toBe('已下线');
    }
  });

  it('未知状态回退成原值 (不吞信息)', () => {
    expect(statusLabel('tool', 'weird')).toBe('weird');
    expect(statusLabel('tool', undefined)).toBe('—');
  });

  it('draft = 规划中 = 不可点', () => {
    expect(isPlanned('draft')).toBe(true);
    expect(isPlanned('beta')).toBe(false);
    expect(isPlanned('stable')).toBe(false);
    expect(isPlanned(undefined)).toBe(false);
  });

  it('业务域标签: 已知映射 + 未知回退原值 + 空值兜底', () => {
    expect(categoryLabel('ssd-trace')).toBe('Trace 诊断');
    expect(categoryLabel('ssd-kb')).toBe('知识库存');
    expect(categoryLabel('ai-market')).toBe('AI 资产');
    expect(categoryLabel('what-ever')).toBe('what-ever');
    expect(categoryLabel('')).toBe('—');
    expect(CATEGORY_LABELS['auto-code']).toBe('自动化代码');
  });
});
