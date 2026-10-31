/**
 * 能力角色常量 (2026-10-25 能力墙重构 · 第二版).
 *
 * 这个文件看着像"纯展示映射", 但它承载的是**产品规则**, 所以必须有单测锁住:
 *   ① 角色只回答"供料 / 干活 / 看数" —— 徽标**不许**泄漏实现
 *      (第一版的「目录」「知识」就是泄漏: 一个说目录结构, 一个说内容形态);
 *   ② 状态词按角色换 —— 对看板和资产说 "Beta / 稳定" 没有决策价值,
 *      但"未接入"是必须说清楚的 (服务没配 = 用不了);
 *   ③ 未知 kind 必须兜底成 tool —— 后端加新角色时前端不能白屏;
 *   ④ 规划中 (draft) 的判定 —— 它决定卡片能不能点.
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
  statusTone,
} from '@/constants/capabilityKinds';

describe('能力角色常量', () => {
  it('三种角色齐全, 顺序固定 (侧栏分组 / 筛选 chips 靠它)', () => {
    // ⚠️ 2026-10-27: 角色名「底座」→「资产」, 且**资产组排最上面**
    expect(CAPABILITY_KINDS.map((k) => k.value)).toEqual(['platform', 'tool', 'board']);
    expect(CAPABILITY_KINDS.map((k) => k.label)).toEqual(['资产', '工具', '看板']);
  });

  it('角色名不许泄漏实现 (不能再有「目录」「知识」这种)', () => {
    const labels = CAPABILITY_KINDS.map((k) => k.label);
    expect(labels).not.toContain('目录');
    expect(labels).not.toContain('知识');
    // ⚠️ 「底座」也是架构说法, 用户看不懂 —— 统一叫「资产」
    expect(labels).not.toContain('底座');
  });

  it('每种角色都有默认 CTA —— 卡片没自带 cta 时兜底用', () => {
    expect(kindMeta('tool').cta).toBe('开始使用');
    expect(kindMeta('board').cta).toBe('查看看板');
    expect(kindMeta('platform').cta).toBe('打开');
  });

  it('未知 kind 兜底成工具 (不白屏)', () => {
    expect(kindMeta('unknown' as any).value).toBe('tool');
    expect(kindMeta(undefined).value).toBe('tool');
    expect(kindMeta(null).value).toBe('tool');
    expect(kindLabel('nope' as any)).toBe('工具');
  });

  it('状态词按角色换: 工具说"规划中/公测", 资产说"未接入/正常"', () => {
    expect(statusLabel('tool', 'draft')).toBe('规划中');
    expect(statusLabel('tool', 'beta')).toBe('公测');
    expect(statusLabel('tool', 'stable')).toBe('可用');
    expect(statusLabel('platform', 'draft')).toBe('未接入');
    expect(statusLabel('platform', 'stable')).toBe('正常');
    expect(statusLabel('board', 'beta')).toBe('正常');
  });

  it('已下线对所有角色一致', () => {
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
    expect(categoryLabel('ssd-kb')).toBe('知识库');
    expect(categoryLabel('ai-market')).toBe('插件技能');
    expect(categoryLabel('sw-library')).toBe('软件库');
    expect(categoryLabel('what-ever')).toBe('what-ever');
    expect(categoryLabel('')).toBe('—');
    expect(CATEGORY_LABELS['auto-code']).toBe('自动化代码');
  });
});

/**
 * 语义色调 (2026-10-31 第十九轮).
 *
 * ⚠️ 这是本轮修的用户投诉: 状态徽标的 class 以前按**原始 status** 生成,
 *    而看板 / 资产两种角色的 beta 和 stable **文案都是「正常」** ——
 *    同一句话两个颜色 (code-review 绿 / agent-market 橙), 用户看着莫名其妙.
 *    现在颜色按**语义色调**走: 「正常」一律绿色.
 */
describe('状态语义色调', () => {
  it('看板 / 资产的 beta 和 stable **都是绿色** —— 文案是「正常」, 颜色也得是「正常」', () => {
    expect(statusTone('board', 'beta')).toBe('ok');
    expect(statusTone('board', 'stable')).toBe('ok');
    expect(statusTone('platform', 'beta')).toBe('ok');
    expect(statusTone('platform', 'stable')).toBe('ok');
    // 同一句「正常」→ 同一个色调 (这是这次要修的核心)
    expect(statusTone('board', 'beta')).toBe(statusTone('board', 'stable'));
    expect(statusTone('platform', 'beta')).toBe(statusTone('board', 'stable'));
  });

  it('工具角色按真实成熟度分级 (beta 公测是橙色, 不是绿色)', () => {
    expect(statusTone('tool', 'beta')).toBe('warn');
    expect(statusTone('tool', 'alpha')).toBe('warn');
    expect(statusTone('tool', 'stable')).toBe('ok');
    expect(statusTone('tool', 'draft')).toBe('muted');
    expect(statusTone('tool', 'deprecated')).toBe('danger');
  });

  it('未知状态 / 未知角色 / 空值一律兜底成 muted (别白屏, 别乱上色)', () => {
    expect(statusTone('tool', 'weird')).toBe('muted');
    expect(statusTone(undefined, undefined)).toBe('muted');
    expect(statusTone(null, null)).toBe('muted');
    expect(statusTone('what-ever' as any, 'beta')).toBe('warn'); // 未知 kind → 当工具
  });

  it('已下线对所有角色都是红色 (danger)', () => {
    for (const k of CAPABILITY_KINDS) {
      expect(statusTone(k.value, 'deprecated')).toBe('danger');
    }
  });
});
