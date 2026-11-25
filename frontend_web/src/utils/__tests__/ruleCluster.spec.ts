/**
 * 规则聚类的单元测试 (2026-11-25).
 *
 * ⚠️ 这个文件的存在理由: 第一版实现在组件里写聚合, 漏了**第一个来源**的计数,
 *    导致单来源规则全部显示「0 次」, 多来源的 R-OTHER 少算一条.
 *    源码断言 (读 .vue 文件找字符串) 抓不到这种 bug —— 必须**真的跑**聚合函数.
 */
import { describe, expect, it } from 'vitest';
import {
  clusterRuleKey,
  clusterRules,
  sortRulesByCited,
  type RawRule,
} from '@/utils/ruleCluster';

describe('clusterRuleKey · 键归类', () => {
  it('R-OTHER 系全部归到 R-OTHER', () => {
    expect(clusterRuleKey('R-OTHER')).toBe('R-OTHER');
    expect(clusterRuleKey('R-OTHER:magic_number')).toBe('R-OTHER');
    expect(clusterRuleKey('R-OTHER-IMPACT:caller_param')).toBe('R-OTHER');
    expect(clusterRuleKey('R-OTHER-IMPACT:schema_drift')).toBe('R-OTHER');
  });

  it('其他前缀保持独立', () => {
    for (const k of [
      'R-ERR', 'R-ASSERT', 'R-CLEAN', 'R-NVME',
      'CODE-RULE-CASE-DESCRIPTION',
      'CODE-RULE-COMMON-NO-LOG-EXC',
      'BEHAVIOR-RULE-AI-WORKFLOW',
      'SSD-RULE-CASE-DESCRIPTION',
      '(no_rule_key)',
    ]) {
      expect(clusterRuleKey(k)).toBe(k);
    }
  });

  it('空串/未定义不炸', () => {
    expect(clusterRuleKey('')).toBe('');
    expect(clusterRuleKey('   ')).toBe('');
  });
});

describe('clusterRules · 聚类聚合 (计数必须全部累加)', () => {
  it('⚠️ 单来源规则的计数不能丢 (第一版的 bug)', () => {
    const rules: RawRule[] = [
      { rule_key: 'CODE-RULE-CASE-DESCRIPTION', total: 465, applied: 180, dismissed: 100, open: 185 },
    ];
    const out = clusterRules(rules);
    expect(out).toHaveLength(1);
    expect(out[0].total).toBe(465);       // ← 第一版这里是 0
    expect(out[0].applied).toBe(180);     // ← 第一版这里是 0
    expect(out[0].dismissed).toBe(100);
    expect(out[0].open).toBe(185);
    expect(out[0].sources).toBe(1);
  });

  it('多来源聚类后计数是**全部**来源之和 (含第一个)', () => {
    const rules: RawRule[] = [
      { rule_key: 'R-OTHER:magic_number', total: 76, applied: 20, dismissed: 30, open: 26 },
      { rule_key: 'R-OTHER:stale_comment', total: 72, applied: 15, dismissed: 25, open: 32 },
      { rule_key: 'R-OTHER-IMPACT:caller_param', total: 49, applied: 10, dismissed: 12, open: 27 },
      { rule_key: 'R-OTHER', total: 7, applied: 1, dismissed: 3, open: 3 },
    ];
    const out = clusterRules(rules);
    expect(out).toHaveLength(1);
    expect(out[0].rule_key).toBe('R-OTHER');
    expect(out[0].total).toBe(76 + 72 + 49 + 7);      // 204
    expect(out[0].applied).toBe(20 + 15 + 10 + 1);     // 46
    expect(out[0].dismissed).toBe(30 + 25 + 12 + 3);  // 70
    expect(out[0].open).toBe(26 + 32 + 27 + 3);       // 88
    expect(out[0].sources).toBe(4);
  });

  it('总计数守恒 (聚类前后 total 之和相等)', () => {
    const rules: RawRule[] = [
      { rule_key: 'R-OTHER:a', total: 10, applied: 3 },
      { rule_key: 'R-OTHER:b', total: 20, applied: 5 },
      { rule_key: 'R-ERR', total: 30, applied: 9 },
      { rule_key: 'CODE-RULE-X', total: 40, applied: 12 },
    ];
    const out = clusterRules(rules);
    const rawSum = rules.reduce((s, r) => s + (r.total || 0), 0);
    const clSum = out.reduce((s, r) => s + r.total, 0);
    expect(clSum).toBe(rawSum);
    expect(clSum).toBe(100);
  });

  it('采纳率按聚类后的计数重算 (不是取第一条)', () => {
    const rules: RawRule[] = [
      { rule_key: 'R-OTHER:a', total: 100, applied: 10, dismissed: 50 },
      { rule_key: 'R-OTHER:b', total: 100, applied: 90, dismissed: 0 },
    ];
    const out = clusterRules(rules);
    // (10+90) / (100+100) = 0.5
    expect(out[0].total).toBe(200);
    expect(out[0].applied).toBe(100);
    expect(out[0].adoption_rate).toBe(0.5);
    // 忽略率 (50+0)/200 = 0.25
    expect(out[0].dismissal_rate).toBe(0.25);
  });

  it('采纳率保留 4 位小数', () => {
    const rules: RawRule[] = [{ rule_key: 'R-ERR', total: 3, applied: 1 }];
    const out = clusterRules(rules);
    expect(out[0].adoption_rate).toBe(0.3333);
  });

  it('total=0 时采纳率 0, 忽略率 undefined', () => {
    const out = clusterRules([{ rule_key: 'R-ERR', total: 0, applied: 0, dismissed: 0 }]);
    expect(out[0].adoption_rate).toBe(0);
    expect(out[0].dismissal_rate).toBeUndefined();
  });

  it('缺字段当 0 处理', () => {
    const out = clusterRules([{ rule_key: 'R-ERR' }]);
    expect(out[0].total).toBe(0);
    expect(out[0].applied).toBe(0);
  });

  it('空数组返回空', () => {
    expect(clusterRules([])).toEqual([]);
  });

  it('不同前缀各自独立成行', () => {
    const rules: RawRule[] = [
      { rule_key: 'R-ERR', total: 10, applied: 2 },
      { rule_key: 'R-OTHER:a', total: 5, applied: 1 },
      { rule_key: 'CODE-RULE-X', total: 3, applied: 1 },
    ];
    const out = clusterRules(rules);
    expect(out).toHaveLength(3);
    expect(out.map((r) => r.rule_key).sort()).toEqual(
      ['CODE-RULE-X', 'R-ERR', 'R-OTHER']);
  });
});

describe('sortRulesByCited · 排序', () => {
  it('按命中数降序', () => {
    const out = sortRulesByCited([
      { rule_key: 'A', total: 10, applied: 0, dismissed: 0, open: 0, adoption_rate: 0, sources: 1 },
      { rule_key: 'B', total: 30, applied: 0, dismissed: 0, open: 0, adoption_rate: 0, sources: 1 },
      { rule_key: 'C', total: 20, applied: 0, dismissed: 0, open: 0, adoption_rate: 0, sources: 1 },
    ]);
    expect(out.map((r) => r.rule_key)).toEqual(['B', 'C', 'A']);
  });

  it('同数按规则名排 (顺序稳定)', () => {
    const mk = (k: string) => ({
      rule_key: k, total: 10, applied: 0, dismissed: 0, open: 0,
      adoption_rate: 0, sources: 1,
    });
    const out = sortRulesByCited([mk('Z'), mk('A'), mk('M')]);
    expect(out.map((r) => r.rule_key)).toEqual(['A', 'M', 'Z']);
  });

  it('不修改原数组', () => {
    const arr = [
      { rule_key: 'A', total: 1, applied: 0, dismissed: 0, open: 0, adoption_rate: 0, sources: 1 },
      { rule_key: 'B', total: 2, applied: 0, dismissed: 0, open: 0, adoption_rate: 0, sources: 1 },
    ];
    sortRulesByCited(arr);
    expect(arr[0].rule_key).toBe('A');
  });
});
