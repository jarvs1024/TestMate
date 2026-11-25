/**
 * 规则命中聚类 (2026-11-25).
 *
 * Why: ReviewAgent 的规则键有 400 个, 其中 363 个是 `R-OTHER` 系的细粒度子键:
 *   R-OTHER / R-OTHER:magic_number / R-OTHER-IMPACT:caller_param / ...
 * 展开全部后榜单被这 363 行撑爆, 真正有独立含义的规则 (R-ERR /
 * CODE-RULE-* / BEHAVIOR-RULE-*) 反而被淹没.
 * → 统一归到 `R-OTHER` 一行. 效果: 400 个键 → 38 行.
 *
 * ⚠️ 踩过的坑 (2026-11-25 第一次实现):
 *   第一版把聚合写在组件里, 用 `if (!cur) { agg.set(零值); continue; }` 的写法 ——
 *   **第一个来源的计数被丢掉了**! 单来源的规则 (占绝大多数) 显示「0 次」,
 *   多来源的 R-OTHER 少算了第一条 (755 而不是 831).
 *   → 所以把逻辑抽到**独立可测的纯函数**里, 并且必须有 fixture 单测.
 */

/** 聚类后的规则统计 (计数已累加, 采纳率/忽略率已重算) */
export interface ClusteredRule {
  rule_key: string;
  total: number;
  applied: number;
  dismissed: number;
  open: number;
  adoption_rate: number;
  dismissal_rate?: number;
  /** 这一类合并了多少个原始规则键 (1 = 没合并) */
  sources: number;
}

/** 聚类前的规则统计 (后端给的形状) */
export interface RawRule {
  rule_key: string;
  total?: number;
  applied?: number;
  dismissed?: number;
  open?: number;
  [k: string]: unknown;
}

/**
 * 规则键 → 聚类键.
 *
 * ⚠️ 只归 `R-OTHER*` 一种 —— 其他前缀 (R-ERR / R-ASSERT / CODE-RULE-* /
 *    BEHAVIOR-RULE-* / SSD-RULE-*) 都是**有独立含义**的规则, 不能混.
 *    也不能用「按第一个连字符截断」这种粗暴规则 —— 那会把 CODE-RULE-* 切坏.
 */
export function clusterRuleKey(key: string): string {
  const k = (key || '').trim();
  if (k === 'R-OTHER' || k.startsWith('R-OTHER:') || k.startsWith('R-OTHER-')) {
    return 'R-OTHER';
  }
  return k;
}

/**
 * 把原始规则列表聚类 + 聚合.
 *
 * ⚠️ 计数必须**全部累加** (含第一个来源) —— 第一版漏了第一个来源,
 *    导致单来源规则显示「0 次」.
 */
export function clusterRules(rules: RawRule[]): ClusteredRule[] {
  const agg = new Map<string, ClusteredRule>();
  for (const r of rules || []) {
    const key = clusterRuleKey(r.rule_key);
    const cur = agg.get(key);
    if (cur) {
      // ⚠️ 这里必须累加 —— 第一个来源也要算进去
      cur.total += r.total ?? 0;
      cur.applied += r.applied ?? 0;
      cur.dismissed += r.dismissed ?? 0;
      cur.open += r.open ?? 0;
      cur.sources += 1;
    } else {
      agg.set(key, {
        rule_key: key,
        total: r.total ?? 0,
        applied: r.applied ?? 0,
        dismissed: r.dismissed ?? 0,
        open: r.open ?? 0,
        adoption_rate: 0,
        dismissal_rate: undefined,
        sources: 1,
      });
    }
  }
  const out = [...agg.values()];
  for (const v of out) {
    v.adoption_rate = v.total ? Math.round((v.applied / v.total) * 10000) / 10000 : 0;
    v.dismissal_rate = v.total
      ? Math.round((v.dismissed / v.total) * 10000) / 10000
      : undefined;
  }
  return out;
}

/** 按命中数降序 (同数按规则名排, 保证顺序稳定) */
export function sortRulesByCited(rules: ClusteredRule[]): ClusteredRule[] {
  return [...(rules || [])].sort((a, b) => {
    const d = (b.total ?? 0) - (a.total ?? 0);
    if (d !== 0) return d;
    return (a.rule_key || '').localeCompare(b.rule_key || '');
  });
}
