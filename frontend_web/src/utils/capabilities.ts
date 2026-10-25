/**
 * 能力相关的纯函数 —— 不依赖 Vue, 方便单测.
 *
 * 2026-10-25 首页改成「能力墙」之后, 这些规则从组件里抽出来:
 *   排序规则 (规划中的沉底) / 搜索匹配 / 路由解析 / 相对时间,
 *   都是"页面之外的约定", 放组件里会被复制到好几处.
 */
import type { Capability } from '@/api/capabilities';
import { isPlanned } from '@/constants/capabilityKinds';

/**
 * 能力卡片的排序规则.
 *
 * 规则 (2026-10-25):
 *   ① **规划中的沉底** —— 不可用的东西不该占首屏黄金位;
 *      以前 draft 卡和 stable 卡混排, 用户第一眼看到的是"建设中".
 *   ② 精选优先 —— is_featured 的排前面.
 *   ③ 同组内按注册顺序 (id) —— 稳定, 不会每次刷新乱跳.
 */
export function sortCapabilities(list: Capability[]): Capability[] {
  return [...list].sort((a, b) => {
    const pa = isPlanned(a.status) ? 1 : 0;
    const pb = isPlanned(b.status) ? 1 : 0;
    if (pa !== pb) return pa - pb;
    if (a.is_featured !== b.is_featured) return a.is_featured ? -1 : 1;
    return a.id - b.id;
  });
}

/** 关键词匹配 —— 名称 / 摘要 / 标签 任一命中即可 */
export function matchesKeyword(c: Capability, keyword: string): boolean {
  const k = keyword.trim().toLowerCase();
  if (!k) return true;
  return (
    c.name.toLowerCase().includes(k) ||
    (c.summary || '').toLowerCase().includes(k) ||
    (c.tags || []).some((t) => t.toLowerCase().includes(k))
  );
}

/**
 * 能力 → 前端路由名.
 *
 * 后端 route 形如 "page:code-review" 表示跳自定义路由 (看板 / 目录 / 知识),
 * 空则走工具型的运行页.
 */
export function capabilityRouteName(c: Capability): string {
  if (c.route && c.route.startsWith('page:')) return c.route.slice('page:'.length);
  return 'tool-runner';
}

/** 相对时间 —— "刚刚 / 12 分钟前 / 3 小时前 / 2 天前" */
export function relativeTime(iso: string | null | undefined): string {
  if (!iso) return '还没用过';
  const diff = Date.now() - new Date(iso).getTime();
  if (Number.isNaN(diff)) return '—';
  const m = Math.floor(diff / 60000);
  if (m < 1) return '刚刚';
  if (m < 60) return `${m} 分钟前`;
  const h = Math.floor(m / 60);
  if (h < 24) return `${h} 小时前`;
  return `${Math.floor(h / 24)} 天前`;
}

/** 引擎名 —— 卡上显示用的短名 */
export function engineLabel(engine: string | undefined | null): string {
  switch (engine) {
    case 'dify': return 'Dify';
    case 'n8n': return 'n8n';
    case 'builtin': return '平台内置';
    default: return engine || '—';
  }
}
