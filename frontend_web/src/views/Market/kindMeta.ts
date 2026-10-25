/**
 * 三种资产形态的元信息 —— **市场页入口**与**上传抽屉**共用同一份,
 * 免得两处各写一套说辞, 改一边忘了另一边。
 *
 * 为什么要有这个文件 (2026-10-24):
 *   以前上传抽屉默认就是「技能」, 要传连接器得先滚到基础信息里改类型下拉,
 *   改了才知道表单会换成 JSON 配置 —— 选类型这一步被藏起来了。
 *   现在: 点「上传资产」→ 先选形态 → 直接进对应表单; 类型元信息集中在这里。
 *
 * 三种形态的差别:
 *   技能 / 插件 → 上传安装包 (zip), 靠包里的文档 + 清单说话
 *   连接器     → **只填一段 MCP JSON 配置**, 没有安装包, 也没有 README
 */
import type { MarketKind } from '@/api/assets';

export interface KindMeta {
  /** 类型值 (后端 kind) */
  value: MarketKind;
  /** 中文名 */
  label: string;
  /** 英文名 (后端 kind 原样) */
  code: string;
  /** 卡片图标 */
  icon: string;
  /** 一句话: 它是什么 */
  tagline: string;
  /** 需要准备什么 —— 给用户看, 免得选错了才被拦 */
  needs: string[];
  /** 表单顶部提示: 这一步要填什么 */
  formHint: string;
  /** 包里要有什么 (只有「有包」的形态才有 —— 连接器没有包) */
  pkgNeed?: string;
}

/**
 * 三种形态 —— 顺序即展示顺序
 *
 * ⚠️ 顺序跟市场页的页签 (marketCatalog.ts 的 MARKET_KINDS) **保持一致**:
 *    页签和 lede 都是「插件 / 技能 / 连接器」, 这里以前是「技能 / 插件 / 连接器」——
 *    同一个东西两处顺序不同, 用户会以为上传入口跟页签对不上.
 */
export const KIND_META: KindMeta[] = [
  {
    value: 'plugin',
    label: '插件',
    code: 'plugin',
    icon: '🧩',
    tagline: '带命令、脚本和工具的扩展包, 能真的动手干活',
    needs: [
      '上传一个 .zip 安装包',
      '包内含 README.md 及配套的 skill、脚本等',
    ],
    formHint: '上传 .zip 安装包 —— 插件包 (README.md + 配套 skill/脚本)',
    pkgNeed: '包内含 README.md + .qoder-plugin/plugin.json',
  },
  {
    value: 'skill',
    label: '技能',
    code: 'skill',
    icon: '🧠',
    tagline: '一段可复用的方法与知识, 装进 Agent 后直接照着做',
    needs: [
      '上传一个 .zip 安装包',
      '包内含 SKILL.md 及配套脚本等',
    ],
    formHint: '上传 .zip 安装包 —— 技能包 (SKILL.md + 配套脚本)',
    pkgNeed: '包内含 SKILL.md',
  },
  {
    value: 'mcp',
    label: '连接器',
    code: 'mcp',
    icon: '🔌',
    tagline: '一段 MCP 配置, 让 Agent 连到外部服务',
    needs: [
      '准备一段 MCP JSON 配置',
      '形如 {"mcpServers": {"名字": {...}}}',
    ],
    formHint: '只填一段 MCP JSON 配置',
  },
];

/**
 * 兜底形态 —— **固定是技能**, 不跟着 KIND_META 的顺序变.
 * (以前用 KIND_META[0], 顺序一改兜底就悄悄变成另一种形态了)
 */
const FALLBACK_KIND: KindMeta = KIND_META.find((k) => k.value === 'skill')!;

/** 取某个类型的元信息 (未知类型兜底回技能) */
export function kindMeta(kind: MarketKind | string | undefined | null): KindMeta {
  return KIND_META.find((k) => k.value === kind) || FALLBACK_KIND;
}
