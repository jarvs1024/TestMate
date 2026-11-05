/**
 * 扩展 (原「AI 扩展」) — 前端常量。
 *
 * ⚠️ 资产数据**不再写死在前端**: 真实数据存放在 GitLab 仓库 root/testmate-extensions,
 *    后端 /api/v1/extensions 提供索引. 这里只保留纯展示用的类型枚举,
 *    以及类型再导出 (统一从 @/api/assets 引入, 避免两处定义漂移).
 *
 * ⚠️ 分类清单 (EXT_CATEGORIES) 已经删掉了 —— 分类是后端下发的
 *    (用户可以自建分类), 前端写死一份只会让新建的分类**没有 chip**、筛不出来.
 */
export type { AssetItem, AssetJob, ExtKind, ExtPermissions } from '@/api/assets';
import type { ExtKind } from '@/api/assets';

export const EXT_KINDS: { value: ExtKind; label: string }[] = [
  { value: 'plugin', label: '插件' },
  { value: 'skill', label: '技能' },
  { value: 'mcp', label: '连接器' },
];

/**
 * 扩展页的排序方式 —— 与后端 sort 参数一一对应
 * (后端: extensions.py list_assets 的 sort, pattern="^(hot|new|name)$")
 */
export type ExtSort = 'hot' | 'new' | 'name';

export const EXT_SORT_OPTIONS: { value: ExtSort; label: string }[] = [
  { value: 'hot', label: '热门' },
  { value: 'new', label: '最新' },
  { value: 'name', label: '名称' },
];

/**
 * 项目列表项 (后端 listProjects 返回的结构)
 *
 * ⚠️ 「通用」的 code 是 `general` —— 它是**筛选参数**, 不是资产里的 project 值
 *    (资产里通用 = 空串). 真要发给后端, 记得换成 `__general` (见 Catalog/index.vue).
 */
export interface ExtProjectItem {
  code: string;
  name: string;
  total: number;
}
