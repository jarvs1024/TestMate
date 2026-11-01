/** 上传表单规则与纯函数; 命名/分类/项目规则只从后端 /assets/rules 获取. */
import { ref } from 'vue';
import request from '@/utils/request';
import { errorDetail, errorStatus, httpErrorText } from '@/utils/httpError';

export interface MarketRequiredRules {
  common: string[];
  skill: string[];
  plugin: string[];
  mcp: string[];
}

export interface MarketRules {
  code: {
    prefix: string;
    pattern: string;
    example: string;
    min_length: number;
    max_length: number;
  };
  segment: { pattern: string; min_length: number; max_length: number };
  package: { suffixes: string[] };
  required: {
    create: MarketRequiredRules;
    update: MarketRequiredRules;
    edit: string[];
  };
  categories: { name: string; slug: string; desc?: string; order?: number }[];
  projects: string[];
  enforcement: {
    require_code_prefix_on_create: boolean;
    require_code_prefix_on_update: boolean;
    code_must_match_package: boolean;
    code_must_match_mcp_server: boolean;
    unknown_category: string;
    unknown_project: string;
  };
}

/** 当前市场上下文共享的规则状态; 页面错误条与上传抽屉看到同一次加载结果. */
export const marketRules = ref<MarketRules | null>(null);
export const marketRulesError = ref('');
export const marketRulesLoading = ref(false);
let rulesRequest: Promise<void> | null = null;

/** 加载或重试规则; 失败时清空旧规则, 绝不回退到前端硬编码校验. */
export async function loadMarketRules(): Promise<void> {
  if (rulesRequest) return rulesRequest;
  marketRulesLoading.value = true;
  marketRules.value = null;
  marketRulesError.value = '';
  rulesRequest = (async () => {
    try {
      marketRules.value = (await request.get('/assets/rules')) as unknown as MarketRules;
      marketRulesError.value = '';
    } catch (e: any) {
      marketRules.value = null;
      marketRulesError.value = httpErrorText(errorStatus(e), errorDetail(e), '未知错误');
    } finally {
      marketRulesLoading.value = false;
      rulesRequest = null;
    }
  })();
  return rulesRequest;
}

/** 仅用于新建空白表单的初始占位, 不参与校验. */
export const CODE_PREFIX = 'dml-';
export const CODE_EXAMPLE = 'dml-ssd-log-doctor';

function activePattern(source: string | undefined): { test(value: string): boolean } {
  return {
    test(value: string): boolean {
      return source ? new RegExp(source).test(value) : false;
    },
  };
}

/** mcpConfig 沿用这两个入口, 但实际表达式始终来自当前后端规则. */
export const CODE_PATTERN = {
  test(value: string): boolean {
    return activePattern(marketRules.value?.code.pattern).test(value);
  },
};
export const SEGMENT_PATTERN = {
  test(value: string): boolean {
    return activePattern(marketRules.value?.segment.pattern).test(value);
  },
};

function packagePattern(rules: MarketRules): RegExp {
  const suffixes = rules.package.suffixes
    .map((s) => s.replace(/[.*+?^${}()|[\]\\]/g, '\\$&'))
    .join('|');
  return new RegExp(`(?:${suffixes})$`, 'i');
}

/** 校验安装包文件名; 没有后端规则时明确失败, 不使用本地兜底. */
export function validatePackageName(
  filename: string,
  opts: { requirePrefix?: boolean; rules?: MarketRules | null } = {},
): string {
  const rules = opts.rules === undefined ? marketRules.value : opts.rules;
  const requirePrefix = opts.requirePrefix !== false;
  const name = (filename || '').trim();
  if (!name) return '请选择安装包';
  if (!rules) return '市场规则尚未加载, 请重试';
  const ext = packagePattern(rules);
  if (!ext.test(name)) return `安装包只支持 ${rules.package.suffixes.join(' / ')}`;
  const base = name.replace(ext, '');
  const example = rules.code.example;
  if (requirePrefix) {
    if (!base.startsWith(rules.code.prefix)) {
      return `安装包名必须以 "${rules.code.prefix}" 开头 (如 ${example}.zip)`;
    }
    if (base.length < rules.code.min_length || base.length > rules.code.max_length) {
      return `安装包名长度要在 ${rules.code.min_length}-${rules.code.max_length} 个字符之间 (现在 ${base.length} 个)`;
    }
    if (!new RegExp(rules.code.pattern).test(base)) {
      return `安装包名只能用小写字母/数字/连字符, 如 ${example}.zip`;
    }
  } else {
    if (base.length < rules.segment.min_length || base.length > rules.segment.max_length) {
      return `安装包名长度要在 ${rules.segment.min_length}-${rules.segment.max_length} 个字符之间 (现在 ${base.length} 个)`;
    }
    if (!new RegExp(rules.segment.pattern).test(base)) {
      return `安装包名只能用小写字母/数字/连字符, 如 ${example}.zip`;
    }
  }
  return '';
}

/** 从安装包文件名推导出资产 code; 未加载规则时不猜测后缀. */
export function codeFromPackageName(
  filename: string,
  rules: MarketRules | null = marketRules.value,
): string {
  const name = (filename || '').trim();
  if (!name || !rules) return '';
  return name.replace(packagePattern(rules), '');
}

/** 校验资产 code, 返回空串 = 通过. */
export function validateCode(
  code: string,
  rules: MarketRules | null = marketRules.value,
): string {
  const c = (code || '').trim();
  if (!c) return '资产 code 必填';
  if (!rules) return '市场规则尚未加载, 请重试';
  if (!c.startsWith(rules.code.prefix)) {
    return `资产 code 必须以 "${rules.code.prefix}" 开头 (如 ${rules.code.example})`;
  }
  if (c.length < rules.code.min_length || c.length > rules.code.max_length) {
    return `资产 code 长度要在 ${rules.code.min_length}-${rules.code.max_length} 个字符之间 (现在 ${c.length} 个)`;
  }
  if (!new RegExp(rules.code.pattern).test(c)) {
    return '只能用小写字母/数字/连字符, 如 ' + rules.code.example;
  }
  return '';
}

/**
 * code 与「包名 / MCP 连接器名」的**一致性**校验.
 *
 * 约定 (2026-10-24): **code 就是那个名字本身** ——
 *   技能 / 插件 → code = 安装包名 (去扩展名)
 *   连接器      → code = MCP 配置里的**某一个**连接器名 (可能配了多个)
 *
 * 为什么这么严: 装出来 / 抄下来要对得上 ——
 *   包名决定装到哪, code 决定市场里的资产号; 两边对不上, 用的人一脸懵。
 *
 * @returns 错误文案 (空串 = 一致 / 还不用管)
 */
export function checkCodeSync(
  code: string,
  opts: { isMcp?: boolean; pkgBase?: string; mcpNames?: string[] } = {},
): string {
  const c = (code || '').trim();
  if (!c) return '';                       // 还没填 —— 交给「必填」去报
  if (opts.isMcp) {
    const names = opts.mcpNames || [];
    if (!names.length) return '';          // 配置还没填 —— 交给配置校验去报
    if (names.includes(c)) return '';
    return `资产 code 必须与 MCP 配置里的连接器名一致 (配置里是 ${names.join(' / ')})`;
  }
  const base = (opts.pkgBase || '').trim();
  if (!base) return '';                    // 还没选包 —— 交给「必填」去报
  if (c === base) return '';
  return `资产 code 必须与安装包名一致 (包名是 ${base})`;
}

/**
 * 分类 → 图标池 (按测试全流程的阶段给)
 *
 * ⚠️ 每个分类给到 8 个 —— 资产一多, 池子不够就会被迫重复用图标,
 *   卡片上就分不清谁是谁了。
 */
export const ICON_POOLS: Record<string, string[]> = {
  质量保障: ['🔍', '🩺', '📉', '🔬', '🧬', '📈', '🫀', '🧪'],
  效率工具: ['⚡', '🚀', '🛠', '⏱', '🔄', '📦', '🪄', '🧰'],
  流程规范: ['🔀', '🧭', '🧾', '🪜', '🔒', '✅', '🛡', '🧱'],
  管理协同: ['📊', '🗓', '💬', '📣', '👥', '🤝', '📌', '📢'],
  其他: ['🧩', '✨', '🎯', '🎁', '🧵', '🪅', '🌟', '🎪'],
};

/** 通用池 (任何分类都能用) */
export const GENERAL_ICONS = [
  '🧩', '✨', '🎯', '🪄', '🧰', '🛠', '📦', '🧭',
  '🧪', '📎', '🔧', '🔩', '⚙', '🧲', '🪛', '🧮',
  '🔮', '🧿', '🪞', '🎨', '🖌', '🖥', '⌨', '🖱',
  '💽', '🔌', '🔗', '🪙', '🎁', '🧵',
];

/** 兜底池 (通用池也用完了从这里找) —— 尽量不跟别人撞图标
 *
 * 池子总量要**远大于**现有资产数 —— 否则资产一多, 就没图标可选了。
 */
export const FALLBACK_ICONS = [
  '🔬', '🗺', '🪈', '🎼', '🔭', '📡', '🗃', '🧱',
  '🪚', '🔦', '🕯', '🛞', '🚁', '🛸', '⛵', '🚂',
  '🧹', '🧺', '🪣', '🧽', '🪥', '🧸', '🪆', '🎪',
  '🛶', '🏕', '🗼', '🏖', '🌋', '🏔', '⛲', '🌌',
  '🪐', '🌠', '☄', '🌊', '🍀', '🦄', '🐢', '🦉',
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
