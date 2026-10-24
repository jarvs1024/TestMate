/**
 * 上传表单的**取值规则** —— 抽出来是为了能单测 (界面逻辑不��写死在组件里).
 *
 * 两条约定:
 *  1. 资产 code = 包名 = 插件名 → 必须英文, 且统一以 "dml-" 开头
 *  2. 图标自动分配, 且**不能跟现有资产重复** (重复的图标在卡片上根本分不清)
 */

/** 资产 code 的统一前缀 */
export const CODE_PREFIX = 'dml-';

/** 资产 code 的合法格式: dml- 开头 + 小写字母/数字/连字符分段 */
export const CODE_PATTERN = /^dml-[a-z0-9]+(?:-[a-z0-9]+)*$/;

/** 示例 code (表单 placeholder / 报错提示用) */
export const CODE_EXAMPLE = 'dml-ssd-log-doctor';

/**
 * 校验资产 code, 返回空串 = 通过, 否则是给用户看的原因.
 */
export function validateCode(code: string): string {
  const c = (code || '').trim();
  if (!c) return '资产 code 必填';
  if (!c.startsWith(CODE_PREFIX)) {
    return `资产 code 必须以 "${CODE_PREFIX}" 开头 (如 ${CODE_EXAMPLE})`;
  }
  if (!CODE_PATTERN.test(c)) {
    return '只能用小写字母/数字/连字符, 如 ' + CODE_EXAMPLE;
  }
  return '';
}

/** 分类 → 图标池 (按测试全流程的阶段给) */
export const ICON_POOLS: Record<string, string[]> = {
  方案用例: ['📝', '🧪', '📋', '📌'],
  环境运维: ['🛠', '🔧', '🏭', '🧰'],
  任务调度: ['⏱', '🔄', '📊', '🚀'],
  流程管控: ['🔀', '📄', '🧭', '🗂️'],
  质量诊断: ['🔍', '🩺', '📈', '🧬'],
  知识资产: ['📚', '📖', '🗂', '💡'],
  其他: ['🧩', '✨', '🎯', '🪄'],
};

/** 通用池 (分类池用完了从这里找) */
export const GENERAL_ICONS = ['🧩', '✨', '🎯', '🪄', '🧰', '🛠', '📦', '🧭', '🧪', '📎'];

/** 兜底池 (通用池也用完了从这里找) —— 尽量不跟别人撞图标 */
export const FALLBACK_ICONS = [
  '🔬', '🧿', '🗺️', '🪄', '🧬', '🔭', '📡', '🖥️', '🗃️', '🧱',
  '🪚', '🧵', '🎼', '🎯', '🪅', '🧵', '🔦', '🕯️', '🪞', '🧿',
];

/** 关键词 → 图标 (比分类池更精准: 先按名字猜, 猜不到再按分类) */
const KEYWORD_ICONS: Array<[RegExp, string]> = [
  [/诊断|排查|定位|日志|debug/i, '🔍'],
  [/报告|报表|汇总|report/i, '📊'],
  [/方案|计划|规划/i, '📝'],
  [/用例|测试|case/i, '🧪'],
  [/运维|机台|设备|部署/i, '🛠'],
  [/速查|知识|手册|规范|cheat/i, '📚'],
  [/流程|审批|审核|review/i, '🔀'],
  [/调度|批处理|任务|定时/i, '⏱'],
  [/周报|日报|简报/i, '📈'],
  [/看板|仪表|监控/i, '📊'],
  [/插件|plugin/i, '🧩'],
  [/技能|skill/i, '🧠'],
  [/连接器|connector|mcp/i, '🔌'],
];

/**
 * 自动分配一个图标:
 *   1. 先按名称/简介的关键词猜一个
 *   2. 猜不到就用分类池
 *   3. 都用完了用通用池
 *   4. **全程跳过已经被别的资产用掉的图标** —— 重复的图标在卡片上分不清谁是谁
 *
 * @param used 已存在的资产用过的图标 (可以为空)
 */
export function pickIcon(opts: {
  category?: string;
  name?: string;
  summary?: string;
  used?: Iterable<string>;
}): string {
  const used = new Set(opts.used || []);
  const take = (pool: string[]): string | '' => {
    for (const ic of pool) if (!used.has(ic)) return ic;
    return '';
  };
  const text = `${opts.name || ''} ${opts.summary || ''}`;
  for (const [re, icon] of KEYWORD_ICONS) {
    if (re.test(text) && !used.has(icon)) return icon;
  }
  const pool = ICON_POOLS[opts.category || ''] || [];
  return take(pool) || take(GENERAL_ICONS) || take(FALLBACK_ICONS) || '🧩';
}
