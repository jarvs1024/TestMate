/**
 * 消息页 —— 全部站内通知 (2026-11-16).
 *
 * 盯住: 列表 / 未读筛选 / 单条已读 / 全部已读 / 点进评论深链.
 */
import { describe, expect, it, vi, beforeEach } from 'vitest';
import { mount, flushPromises } from '@vue/test-utils';
import { createRouter, createMemoryHistory } from 'vue-router';
import { createPinia, setActivePinia } from 'pinia';
import ElementPlus from 'element-plus';
import { defineComponent } from 'vue';
import NotificationsPage from '../index.vue';
import { useUserStore } from '@/stores/user';
import type { NotificationItem } from '@/api/notifications';

const api = vi.hoisted(() => ({
  listNotifications: vi.fn(),
  getUnreadCount: vi.fn(async () => ({ count: 1 })),
  markNotificationRead: vi.fn(async () => ({ ok: true })),
  markAllNotificationsRead: vi.fn(async () => ({ ok: true, updated: 1 })),
}));
vi.mock('@/api/notifications', () => api);

const Stub = defineComponent({ template: '<div />' });

function note(over: Partial<NotificationItem> = {}): NotificationItem {
  return {
    id: 7, kind: 'comment_reply', actor_name: 'lisi',
    asset_code: 'demo', asset_name: '演示资产',
    comment_id: 501, parent_comment_id: 400,
    title: 'lisi 回复了你在「演示资产」下的评论',
    body: '收到, 已修', event_count: 2,
    read_at: null, created_at: '2026-11-16T09:00:00', updated_at: '2026-11-16T09:30:00',
    ...over,
  };
}

async function mountPage() {
  const pinia = createPinia();
  setActivePinia(pinia);
  const user = useUserStore(pinia);
  user.token = 't';
  user.user = { id: 1, username: 'jarvs', role: 'tester' };
  const router = createRouter({
    history: createMemoryHistory(),
    routes: [
      { path: '/', name: 'home', component: Stub },
      { path: '/extensions', name: 'extensions', component: Stub },
      { path: '/notifications', name: 'notifications', component: Stub },
    ],
  });
  await router.replace('/notifications');
  await router.isReady();
  const w = mount(NotificationsPage, { global: { plugins: [pinia, router, ElementPlus] } });
  await flushPromises();
  return { w, router };
}

beforeEach(() => {
  api.listNotifications.mockReset().mockResolvedValue({
    items: [note(), note({ id: 6, read_at: '2026-11-15T10:00:00', event_count: 1 })],
    total: 2,
    unread_count: 1,
  });
  api.getUnreadCount.mockClear();
  api.markNotificationRead.mockClear();
  api.markAllNotificationsRead.mockClear();
});

describe('消息页', () => {
  it('挂载即拉列表, 未读的标出来', async () => {
    const { w } = await mountPage();
    expect(api.listNotifications).toHaveBeenCalled();
    const rows = w.findAll('.nt-row');
    expect(rows.length).toBe(2);
    expect(rows[0].classes()).toContain('unread');
    expect(rows[1].classes()).not.toContain('unread');
    expect(rows[0].text()).toContain('回复了你在「演示资产」下的评论');
    expect(rows[0].text()).toContain('2 条');
  });

  it('切到「未读」只请求未读, 列表刷新', async () => {
    const { w } = await mountPage();
    api.listNotifications.mockResolvedValueOnce({
      items: [note({ id: 9 })], total: 1, unread_count: 1,
    });
    const tab = w.findAll('.kind-tab').find((t) => t.text() === '未读');
    expect(tab).toBeTruthy();
    await tab!.trigger('click');
    await flushPromises();
    expect(api.listNotifications).toHaveBeenLastCalledWith(
      expect.objectContaining({ unread_only: true }),
    );
    expect(w.findAll('.nt-row').length).toBe(1);
  });

  it('点一条 → 标已读 + 跳资产评论深链', async () => {
    const { w, router } = await mountPage();
    await w.findAll('.nt-row')[0].trigger('click');
    await flushPromises();
    expect(api.markNotificationRead).toHaveBeenCalledWith(7);
    expect(router.currentRoute.value.name).toBe('extensions');
    expect(router.currentRoute.value.query).toMatchObject({ asset: 'demo', comment: '501' });
  });

  it('「全部标为已读」清空未读样式', async () => {
    const { w } = await mountPage();
    const btn = w.findAll('button').find((b) => b.text().includes('全部标为已读'));
    expect(btn).toBeTruthy();
    await btn!.trigger('click');
    await flushPromises();
    expect(api.markAllNotificationsRead).toHaveBeenCalled();
    expect(w.findAll('.nt-row.unread').length).toBe(0);
  });
});
