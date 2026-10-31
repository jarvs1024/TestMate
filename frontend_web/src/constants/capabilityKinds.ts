/**
 * 能力角色 (kind) —— 首页能力墙的**角色元信息**。
 *
 * 为什么是"角色"而不是"形态" (2026-10-25 第二版):
 *   第一版分四种形态 (工具 / 看板 / 目录 / 知识), 但「目录」「知识」都在**泄漏实现** ——
 *   一个说的是目录结构, 一个说的是内容形态, 跟用户脑子里的"这东西能干嘛"对不上.
 *   实际上资产市场里三种资产的官方说明写得很清楚:
 *   "一段可复用的方法与知识, 装进 Agent 后直接照着做" / "让 Agent 连到外部服务"
 *   —— 资产本来就是**装进 Agent 的扩展**; 知识库是 RAGFlow 的数据集/分段, 是**检索语料**.
 *   两者同属一类: 给上面两类能力**供料**的一组东西.
 *
 *   所以角色只回答三件事: 供料 / 干活 / 看数.
 *   细分信息没丢 —— 靠 category (业务域: ai-market / ssd-kb / sw-library) 区分, 不该由徽标来背.
 *
 * ⚠️ 2026-10-27 角色名从「底座」改成「资产」:
 *    "底座"说的是**架构位置**(谁垫在底下), 用户看不懂; "资产"说的是
 *    **这里放的是可复用的东西** —— 插件 / 技能 / 连接器、知识、软件, 都是资产.
 *    顺序也跟着改: 资产组排**最上面** —— 用户先看到"平台能给我什么",
 *    再看"平台能替我干什么"(工具)、"平台上有什么数"(看板).
 *
 * ⚠️ kind 跟 category (业务域标签) **正交**:
 *   kind     = 角色 —— 资产 / 工具 / 看板
 *   category = 业务域 —— Trace 诊断 / FW 比对 / 插件技能 / 知识库 / 软件库 …
 *   两者由后端一起下发, 前端只做展示映射, 不要在前端反推.
 */

export type CapabilityKind = 'tool' | 'board' | 'platform';

export interface CapabilityKindMeta {
  /** 角色值 (后端 kind) */
  value: CapabilityKind;
  /** 中文名 (徽标上显示) */
  label: string;
  /** 徽标图标 */
  icon: string;
  /** 默认动作词 —— 具体卡片可以用自己的 cta 覆盖 (资产里"浏览资产" vs "检索语料" vs "浏览软件") */
  cta: string;
  /** 侧栏 / 筛选条的展示顺序 */
  order: number;
  /** 一句话说明这个角色是干什么的 (tooltip / 文档用) */
  hint: string;
}

/**
 * 三种角色 —— 顺序即展示顺序 (侧栏分组 / 首页筛选 chips 共用这份).
 */
export const CAPABILITY_KINDS: CapabilityKindMeta[] = [
  {
    value: 'platform',
    label: '资产',
    icon: '📦',
    cta: '打开',
    order: 1,
    hint: '资产 —— 可复用的插件 / 技能 / 连接器、知识、软件',
  },
  {
    value: 'tool',
    label: '工具',
    icon: '🛠',
    cta: '开始使用',
    order: 2,
    hint: '干活 —— 填参数, 出结果',
  },
  {
    value: 'board',
    label: '看板',
    icon: '📊',
    cta: '查看看板',
    order: 3,
    hint: '看数 —— 只读指标, 不改数据',
  },
];

/**
 * 状态词 —— **按角色换词**.
 *
 * 为什么: 对看板和资产说 "Beta / 稳定" 没有决策价值, 用户不会因为
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
  platform: {
    draft: '未接入',
    alpha: '未接入',
    beta: '正常',
    stable: '正常',
    deprecated: '已下线',
  },
};

/**
 * 语义色调 —— 徽标的**颜色**只跟"好不好 / 危不危险"走, 跟原始 status 无关.
 *
 * ⚠️ 2026-10-31 (第十九轮) 为什么要有这层:
 *    以前徽标的 class 是按**原始 status** 生成的 (`st-${status}`),
 *    而看板 / 资产两种角色的 `beta` 和 `stable` **文案都是「正常」** ——
 *    于是同一句话出现两个颜色 (code-review 绿 / agent-market 橙), 用户看着莫名其妙.
 *    现在 class 按**色调**生成 (`st-${statusTone(...)}`), 所有「正常」都是绿色.
 */
export type StatusTone = 'ok' | 'warn' | 'muted' | 'danger';

/**
 * 状态 → 语义色调. 文案可以有多个来源, 颜色只有一个口径.
 *
 * ⚠️ 关键点: 看板 / 资产的 `beta` 跟 `stable` **都是绿色** ——
 *    对这两种角色来说, beta 不代表"还在公测", 它就是"正常".
 */
export const STATUS_TONES: Record<CapabilityKind, Record<string, StatusTone>> = {
  tool: {
    draft: 'muted',       // 规划中 —— 还没上线
    alpha: 'warn',        // 内测
    beta: 'warn',         // 公测
    stable: 'ok',         // 可用
    deprecated: 'danger', // 已下线
  },
  board: {
    draft: 'muted',       // 未接入
    alpha: 'muted',       // 未接入
    beta: 'ok',           // 正常 ← 跟 stable 一样绿
    stable: 'ok',         // 正常
    deprecated: 'danger', // 已下线
  },
  platform: {
    draft: 'muted',       // 未接入
    alpha: 'muted',       // 未接入
    beta: 'ok',           // 正常 ← 跟 stable 一样绿
    stable: 'ok',         // 正常
    deprecated: 'danger', // 已下线
  },
};

/** 取某个状态的语义色调 (未知 kind / 未知 status 一律兜底成 muted) */
export function statusTone(
  kind: CapabilityKind | string | undefined | null,
  status: string | undefined | null,
): StatusTone {
  const byKind = STATUS_TONES[kindMeta(kind).value];
  return byKind[status || ''] || 'muted';
}

/** 兜底角色 —— 未知 kind 一律当工具处理 (最保守: 有引擎有参数, 能跑) */
const FALLBACK_KIND: CapabilityKindMeta = CAPABILITY_KINDS.find((k) => k.value === 'tool')!;

/** 取某个角色的元信息 (未知角色兜底回工具) */
export function kindMeta(kind: CapabilityKind | string | undefined | null): CapabilityKindMeta {
  return CAPABILITY_KINDS.find((k) => k.value === kind) || FALLBACK_KIND;
}

/** 角色中文名 */
export function kindLabel(kind: CapabilityKind | string | undefined | null): string {
  return kindMeta(kind).label;
}

/**
 * 状态词 —— 按角色翻译.
 * @param kind  角色
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
 * 业务域标签 —— 卡上跟角色徽标并排显示的那个 (如 "Trace 诊断").
 * 跟角色分开: 角色说"扮演什么", 域标签说"管哪块业务".
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
  'ai-market': '插件技能',
  'ssd-kb': '知识库',
  'sw-library': '软件库',
};

/** 业务域中文名 (未知域回退成原值, 不吞掉信息) */
export function categoryLabel(category: string | undefined | null): string {
  if (!category) return '—';
  return CATEGORY_LABELS[category] || category;
}
