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

/**
 * 市场页的排序方式 —— 与后端 sort 参数一一对应
 * (后端: marketplace.py list_assets 的 sort, pattern="^(hot|new|name)$")
 */
export type MarketSort = 'hot' | 'new' | 'name';

export const MARKET_SORT_OPTIONS: { value: MarketSort; label: string }[] = [
  { value: 'hot', label: '热门' },
  { value: 'new', label: '最新' },
  { value: 'name', label: '名称' },
];

/**
 * 项目列表项 (后端 listProjects 返回的结构)
 *
 * ⚠️ 「通用」的 code 是 `general` —— 它是**筛选参数**, 不是资产里的 project 值
 *    (资产里通用 = 空串). 真要发给后端, 记得换成 `__general` (见 market/index.vue).
 */
export interface MarketProjectItem {
  code: string;
  name: string;
  total: number;
}

export const MARKET_CATEGORIES = [
  'Trace 诊断',
  'FW 比对',
  '老化任务',
  'Spec 问答',
  '机台运维',
  '自动化代码',
  '测试报告',
];
