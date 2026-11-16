/**
 * 设置-用户「使用统计」API (仅管理员).
 *
 * 口径:
 *   · 在线   = 最近 5 分钟内有已登录操作 (前端每 60 秒轮询在线名单)
 *   · 今日活跃 = 当天有实际操作的去重人数 (不含通知轮询等后台请求)
 *   · 下载数  = 两库**累计**下载次数 (不是所选周期内的增量)
 */
import request from '@/utils/request';
import type { UserRole } from '@/api/users';

export interface StatsOnlineUser {
  id: number;
  username: string;
  role: UserRole;
  last_seen_at: string;
}

export interface StatsOnline {
  count: number;
  window_minutes: number;
  users: StatsOnlineUser[];
}

export interface StatsSeriesPoint {
  date: string;
  count: number;
}

export interface StatsActive {
  today: number;
  series: StatsSeriesPoint[];
}

export interface StatsDownloadItem {
  code: string;
  name: string;
  icon: string;
  count: number;
  /** 扩展细分类型 plugin/skill/mcp; mcp 的数字是「配置复制」而非安装包下载 */
  kind: string;
}

export interface StatsDownloadLibrary {
  total: number;
  items: StatsDownloadItem[];
}

export interface StatsDownloads {
  software: StatsDownloadLibrary;
  extensions: StatsDownloadLibrary;
}

export interface UsageSummary {
  online: StatsOnline;
  active: StatsActive;
  downloads: StatsDownloads;
}

export type StatsLibrary = keyof StatsDownloads;

/** 在线 + 日活曲线 + 两库下载排行 (days 只能是 7/30/90). */
export async function getUsageSummary(days: number): Promise<UsageSummary> {
  return (await request.get('/auth/stats/summary', {
    params: { days },
    silent: true,
  })) as UsageSummary;
}

/** 轻量轮询: 只取在线名单, 不动图表. */
export async function getOnlineUsers(): Promise<StatsOnline> {
  return (await request.get('/auth/stats/online', { silent: true })) as StatsOnline;
}
