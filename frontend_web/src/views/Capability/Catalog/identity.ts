/**
 * 作者身份口径 —— 实现已上移到 `@/utils/author` (2026-10-30).
 *
 * ⚠️ 为什么上移: 软件库 (views/Software) 也要用同一套判定, 但不该反过来
 *    import 资产市场的目录 (跨模块反向依赖, 以后拆目录就断链).
 *    这里保留 re-export —— 老的 import 路径 (`./identity`) 照常能用,
 *    不用一次改一片.
 */
export { authorForms, isAuthor } from '@/utils/author';
