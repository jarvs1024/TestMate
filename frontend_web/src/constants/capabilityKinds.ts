/**
 * 能力形态 (kind) —— 首页能力墙的**形态元信息**。
 *
 * 为什么要有这个文件 (2026-10-25):
 *   以前首页叫「智能体广场」, 每张卡都当智能体渲染 —— 显示引擎 / 调用次数 / 最近调用.
 *   但代码检视是看板, AI 资产市场是目录, 知识库存是知识, 这些字段对它们全是假信息.
 *   现在把「这张卡怎么用」显式建模成 kind, 卡片按 kind 决定:
 *   形态徽标 / 状态词 / CTA / meta 行怎么取数.
 *
 * ⚠️ kind 跟 category (业务域标签) **正交**:
 *   kind     = 交互形态 —— 工具 / 看板 / 目录 / 知识
 *   category = 业务域   —— Trace 诊断 / FW 比对 / Spec 问答 …
 *   两者由后端一起下发, 前端只做展示映射, 不要在前端反推.
 */

export type CapabilityKind = 'tool' | 'board' | 'catalog' | 'library';

export interface CapabilityKindMeta {
  /** 形态值 (后端 kind) */
  value: CapabilityKind;
  /** 中文名 (徽标上显示) */
  label: string;
  /** 徽标图标 */
  icon: string;
  /** 点进详情页的按钮文案 —— 必须说清"点下去会发生什么" */
  cta: string;
  /** 侧栏 / 筛选条的展示顺序 */
  order: number;
  /** 一句话说明这个形态是干什么的 (空态 / tooltip 用) */
  hint: string;
}

/**
 * 四种形态 —— 顺序即展示顺序 (侧栏分组 / 首页筛选 chips 共用这份).
 */
export const CAPABILITY_KINDS: CapabilityKindMeta[] = [
  {
    value: 'tool',
    label: '工具',
    icon: '🛠',
    cta: '开始使用',
    order: 1,
    hint: '填参数, 出结果 —— 跑一次就有一份产出',
  },
  {
    value: 'board',
    label: '看板',
    icon: '📊',
    cta: '查看看板',
    order: 2,
    hint: '只读指标 —— 看趋势、覆盖率、命中率',
  },
  {
    value: 'catalog',
    label: '目录',
    icon: '🗂',
    cta: '浏览资产',
    order: 3,
    hint: '可浏览的共享清单 —— 找东西、装东西',
  },
  {
    value: 'library',
    label: '知识',
    icon: '📚',
    cta: '管理知识',
    order: 4,
    hint: '知识库存 —— 喂资料、查资料',
  },
];

/**
 * 状态词 —— **按形态换词**.
 *
 * 为什么: 对看板 / 目录 / 知识说 "Beta / 稳定" 没有决策价值, 用户不会因为
 * "这个知识库是 Beta" 而改变行为; 但"未接入"是必须说清楚的 (服务没配 = 用不了).
 */
export const STATUS_LABELS: Record<CapabilityKind, Record<string, string>> = {
  tool: {
    draft: '规划中',
    alpha: '内测',
    beta: '公测',
    stable: '可用',
    deprecated: '已下线',
  },
  board: {
    draft: '未接入',
    alpha: '未接入',
    beta: '正常',
    stable: '正常',
    deprecated: '已下线',
  },
  catalog: {
    draft: '未接入',
    alpha: '内测',
    beta: '正常',
    stable: '正常',
    deprecated: '已下线',
  },
  library: {
    draft: '未接入',
    alpha: '未接入',
    beta: '正常',
    stable: '正常',
    deprecated: '已下线',
  },
};

/** 兜底形态 —— 未知 kind 一律当工具处理 (最保守: 有引擎有参数, 能跑) */
const FALLBACK_KIND: CapabilityKindMeta = CAPABILITY_KINDS.find((k) => k.value === 'tool')!;

/** 取某个形态的元信息 (未知形态兜底回工具) */
export function kindMeta(kind: CapabilityKind | string | undefined | null): CapabilityKindMeta {
  return CAPABILITY_KINDS.find((k) => k.value === kind) || FALLBACK_KIND;
}

/** 形态中文名 */
export function kindLabel(kind: CapabilityKind | string | undefined | null): string {
  return kindMeta(kind).label;
}

/**
 * 状态词 —— 按形态翻译.
 * @param kind  形态
 * @param status 后端 status (draft/alpha/beta/stable/deprecated)
 */
export function statusLabel(
  kind: CapabilityKind | string | undefined | null,
  status: string | undefined | null,
): string {
  const byKind = STATUS_LABELS[kindMeta(kind).value];
  return byKind[status || ''] || status || '—';
}

/**
 * 规划中的能力 —— 不可点, 卡片显示"规划中"遮罩.
 *
 * ⚠️ 语义是"还没上线", 不是"deprecated": deprecated 的卡根本不返回 (后端过滤掉).
 */
export function isPlanned(status: string | undefined | null): boolean {
  return status === 'draft';
}

/**
 * 业务域标签 —— 卡上跟形态徽标并排显示的那个 (如 "Trace 诊断").
 * 跟形态分开: 形态说"怎么用", 域标签说"管哪块业务".
 */
export const CATEGORY_LABELS: Record<string, string> = {
  'ssd-trace': 'Trace 诊断',
  'ssd-fw': 'FW 比对',
  'ssd-fio': 'FIO 性能',
  'ssd-burn': '老化任务',
  'ssd-spec': 'Spec 问答',
  'ssd-report': '测试报告',
  'ssd-ops': '机台运维',
  'auto-code': '自动化代码',
  'ai-market': 'AI 资产',
  'ssd-kb': '知识库存',
};

/** 业务域中文名 (未知域回退成原值, 不吞掉信息) */
export function categoryLabel(category: string | undefined | null): string {
  if (!category) return '—';
  return CATEGORY_LABELS[category] || category;
}
