/** 站内通知 API —— 后端 /api/v1/notifications/*. */
import request from '@/utils/request';

export interface NotificationItem {
  id: number;
  /** asset_comment = 有人评论了我的资产; comment_reply = 有人回复了我的评论 */
  kind: 'asset_comment' | 'comment_reply';
  actor_name: string;
  asset_code: string;
  asset_name: string;
  /** 深链定位用: 最新一条事件 (回复则指向回复本身) */
  comment_id: number | null;
  parent_comment_id: number | null;
  title: string;
  body: string;
  /** 未读期间聚合的事件数, 1 = 单条 */
  event_count: number;
  read_at: string | null;
  created_at: string | null;
  updated_at: string | null;
}

export interface NotificationList {
  items: NotificationItem[];
  total: number;
  unread_count: number;
}

async function apiGet<T>(url: string, params?: Record<string, unknown>): Promise<T> {
  return (await request.get(url, { params })) as unknown as T;
}
async function apiPost<T>(url: string, body?: unknown): Promise<T> {
  return (await request.post(url, body)) as unknown as T;
}

export async function listNotifications(
  params: { limit?: number; offset?: number; unread_only?: boolean } = {},
): Promise<NotificationList> {
  return apiGet('/notifications', params);
}

export async function getUnreadCount(): Promise<{ count: number }> {
  return apiGet('/notifications/unread-count');
}

export async function markNotificationRead(
  id: number,
): Promise<{ ok: boolean; id: number; read_at: string }> {
  return apiPost(`/notifications/${id}/read`);
}

export async function markAllNotificationsRead(): Promise<{ ok: boolean; updated: number }> {
  return apiPost('/notifications/read-all');
}
