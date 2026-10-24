/**
 * 上传表单的**取值规则** —— 抽出来是为了能单测 (界面逻辑不��写死在组件里).
 *
 * 两条约定:
 *  1. 资产 code = 包名 = 插件名 → 必须英文, 且统一以 "dml-" 开头
 *  2. 图标自动分配, 且**不能跟现有资产重复** (重复的图标在卡片上根本分不清)
 */

/** 资产 code 的统一前缀 */
export const CODE_PREFIX = 'dml-';

/**
 * 资产 code 的合法格式 (新建时): dml- 开头 + 小写字母/数字/连字符分段.
 *
 * ⚠️ 与「不带前缀的分段规则」是两回事:
 *   更新**存量**资产时, 它的 code 可能就没有 dml- 前缀 (存量 14 个资产),
 *   那时不能拿这条正则去卡包名 —— 否则那批资产永远更新不了.
 */
export const CODE_PATTERN = /^dml-[a-z0-9]+(?:-[a-z0-9]+)*$/;

/** 不要求前缀的"分段"规则 (存量资产的 code / 包名) */
export const SEGMENT_PATTERN = /^[a-z0-9]+(?:-[a-z0-9]+)*$/;

/** 示例 code (表单 placeholder / 报错提示用) */
export const CODE_EXAMPLE = 'dml-ssd-log-doctor';

/** 安装包允许的扩展名 */
export const PACKAGE_EXT_RE = /\.(zip|tar\.gz|tgz)$/i;

/**
 * 校验**安装包文件名**, 返回空串 = 通过, 否则是给用户看的原因.
 *
 * 约定: 包名 = 资产 code = 插件名 —— 统一 dml- 开头 + 英文.
 * (包名会进 GitLab 目录和安装路径, 空格/中文会到处出问题)
 *
 * ⚠️ `requirePrefix` 只是**团队命名约定** (dml- 开头), 不是技术限制:
 *   新建资产要遵守 (requirePrefix=true, 默认);
 *   更新**存量**资产时不能强制 —— 存量的 code 本身就没有 dml- 前缀,
 *   强制的话那些资产永远更新不了 (后端也是这么分的, 见 market_naming)。
 */
export function validatePackageName(
  filename: string,
  opts: { requirePrefix?: boolean } = {},
): string {
  const requirePrefix = opts.requirePrefix !== false;
  const name = (filename || '').trim();
  if (!name) return '请选择安装包';
  if (!PACKAGE_EXT_RE.test(name)) {
    return '安装包只支持 .zip / .tar.gz / .tgz';
  }
  const base = name.replace(PACKAGE_EXT_RE, '');
  if (requirePrefix) {
    if (!base.startsWith(CODE_PREFIX)) {
      return `安装包名必须以 "${CODE_PREFIX}" 开头 (如 ${CODE_EXAMPLE}.zip)`;
    }
    if (!CODE_PATTERN.test(base)) {
      return `安装包名只能用小写字母/数字/连字符, 如 ${CODE_EXAMPLE}.zip`;
    }
  } else if (!SEGMENT_PATTERN.test(base)) {
    // ⚠️ 不要求前缀时, 也要守住"分段 + 字符集" —— 只是不强制 dml- 开头
    return `安装包名只能用小写字母/数字/连字符, 如 ${CODE_EXAMPLE}.zip`;
  }
  if (base.length < 3 || base.length > 64) {
    return `安装包名长度要在 3-64 个字符之间 (现在 ${base.length} 个)`;
  }
  return '';
}

/** 从安装包文件名推导出资产 code (包名 = code) */
export function codeFromPackageName(filename: string): string {
  const name = (filename || '').trim();
  if (!name) return '';
  return name.replace(PACKAGE_EXT_RE, '');
}

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
  // ⚠️ 长度与后端一致 (3-64) —— 前端不拦的话, 后端会 422, 用户只看到一句没头没尾的报错
  if (c.length < 3 || c.length > 64) {
    return `资产 code 长度要在 3-64 个字符之间 (现在 ${c.length} 个)`;
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
  方案用例: ['📝', '🧪', '📋', '📌', '🗒', '📑', '📐', '🖊'],
  环境运维: ['🛠', '🔧', '🏭', '🧰', '⚙', '🔩', '🪛', '🏗'],
  任务调度: ['⏱', '🔄', '📊', '🚀', '⏳', '📆', '🗓', '⚡'],
  流程管控: ['🔀', '📄', '🧭', '🗂', '🧾', '🔗', '🪜', '🧱'],
  质量诊断: ['🔍', '🩺', '📈', '🧬', '🧪', '📉', '🔬', '🫀'],
  知识资产: ['📚', '📖', '🗂', '💡', '🧠', '📝', '🔖', '🗞'],
  其他: ['🧩', '✨', '🎯', '🪄', '🎁', '🧵', '🪅', '🌟'],
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
