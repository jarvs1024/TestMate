/**
 * AI 资产市场 — 前端常量。
 *
 * ⚠️ 资产数据**不再写死在前端**: 真实数据存放在 GitLab 仓库 root/testmate-market,
 *    后端 /api/v1/assets 提供索引. 这里只保留纯展示用的分类/类型枚举,
 *    以及类型再导出 (统一从 @/api/assets 引入, 避免两处定义漂移).
 */
export type { AssetItem, AssetJob, MarketKind, MarketPermissions } from '@/api/assets';
import type { MarketKind } from '@/api/assets';

export const MARKET_KINDS: { value: MarketKind; label: string }[] = [
  { value: 'plugin', label: '插件' },
  { value: 'skill', label: '技能' },
  { value: 'mcp', label: '连接器' },
];

export const MARKET_CATEGORIES = [
  'Trace 诊断',
  'FW 比对',
  '老化任务',
  'Spec 问答',
  '机台运维',
  '自动化代码',
  '测试报告',
];
