/**
 * 页头铃铛 —— 站内消息入口 (2026-11-16).
 *
 * 盯住:
 *  ① 未读数角标 (0 不显示)
 *  ② 点开才拉列表, 点消息 → 标已读 + 跳到资产评论处
 *  ③ 「全部已读」→ 调接口 + 角标清零
 *  ④ 未登录不渲染 (接口要登录, 摆了也是死路)
 */
import { describe, expect, it, vi, beforeEach, afterEach } from 'vitest';
import { mount, flushPromises } from '@vue/test-utils';
import { createRouter, createMemoryHistory } from 'vue-router';
import { createPinia, setActivePinia } from 'pinia';
import ElementPlus from 'element-plus';
import { defineComponent } from 'vue';
import NotificationBell from '../NotificationBell.vue';
import { useUserStore } from '@/stores/user';
import { useNotificationsStore } from '@/stores/notifications';
import { useAssetDeepLinkStore } from '@/stores/assetDeepLink';
import type { NotificationItem } from '@/api/notifications';

const api = vi.hoisted(() => ({
  listNotifications: vi.fn(),
  getUnreadCount: vi.fn(),
  markNotificationRead: vi.fn(async () => ({ ok: true, id: 1, read_at: '2026-11-16T10:00:00' })),
  markAllNotificationsRead: vi.fn(async () => ({ ok: true, updated: 2 })),
}));
vi.mock('@/api/notifications', () => api);

function note(over: Partial<NotificationItem> = {}): NotificationItem {
  return {
    id: 1, kind: 'asset_comment', actor_name: 'zhangsan',
    asset_code: 'demo', asset_name: '演示资产',
    comment_id: 101, parent_comment_id: null,
    title: 'zhangsan 评论了你的资产「演示资产」',
    body: '这个技能很好用', event_count: 1,
    read_at: null, created_at: '2026-11-16T09:00:00', updated_at: '2026-11-16T09:00:00',
    ...over,
  };
}

const Stub = defineComponent({ template: '<div />' });

async function mountBell(loggedIn = true) {
  const pinia = createPinia();
  setActivePinia(pinia);
  const user = useUserStore(pinia);
  if (loggedIn) {
    user.token = 't';
    user.user = { id: 1, username: 'jarvs', role: 'tester' };
  }
  const router = createRouter({
    history: createMemoryHistory(),
    routes: [
      { path: '/', name: 'home', component: Stub },
      { path: '/extensions', name: 'extensions', component: Stub },
      { path: '/notifications', name: 'notifications', component: Stub },
    ],
  });
  await router.replace('/');
  await router.isReady();
  const w = mount(NotificationBell, {
    attachTo: document.body,
    global: { plugins: [pinia, router, ElementPlus] },
  });
  await flushPromises();
  return { w, router, pinia };
}

beforeEach(() => {
  document.body.innerHTML = '';
  api.getUnreadCount.mockReset().mockResolvedValue({ count: 2 });
  api.listNotifications.mockReset().mockResolvedValue({
    items: [note(), note({ id: 2, read_at: '2026-11-16T08:00:00', event_count: 3 })],
    total: 2,
    unread_count: 1,
  });
  api.markNotificationRead.mockClear();
  api.markAllNotificationsRead.mockClear();
});

afterEach(() => {
  document.body.innerHTML = '';
});

describe('NotificationBell', () => {
  it('未登录不渲染铃铛', async () => {
    const { w } = await mountBell(false);
    expect(w.find('.tm-bell').exists()).toBe(false);
    expect(api.getUnreadCount).not.toHaveBeenCalled();
  });

  it('未读数显示在角标上, 点开才拉列表', async () => {
    const { w } = await mountBell();
    expect(w.find('.tm-bell').exists()).toBe(true);
    expect(w.find('.tm-bell .badge').text()).toBe('2');
    // 点开前不拉列表, 省一次请求
    expect(api.listNotifications).not.toHaveBeenCalled();

    await w.find('.tm-bell').trigger('click');
    await flushPromises();
    expect(api.listNotifications).toHaveBeenCalled();
    const items = document.body.querySelectorAll('.nt-item');
    expect(items.length).toBe(2);
    expect(items[0].textContent).toContain('评论了你的资产');
  });

  it('点消息 → 标已读, 并跳到对应资产的评论处', async () => {
    const { w, router } = await mountBell();
    await w.find('.tm-bell').trigger('click');
    await flushPromises();

    const first = document.body.querySelector('.nt-item') as HTMLElement;
    first.click();
    await flushPromises();

    expect(api.markNotificationRead).toHaveBeenCalledWith(1);
    expect(router.currentRoute.value.name).toBe('extensions');
    expect(router.currentRoute.value.query).toMatchObject({ asset: 'demo', comment: '101' });
  });

  it('已停在同一条深链上再点同一条 → 额外发一次打开请求', async () => {
    // 同地址导航: 路由不动, 扩展库也不会重挂 —— 不补这一下, 抽屉关了就打不开
    const { w, router, pinia } = await mountBell();
    await router.replace({ name: 'extensions', query: { asset: 'demo', comment: '101' } });
    await w.find('.tm-bell').trigger('click');
    await flushPromises();

    (document.body.querySelector('.nt-item') as HTMLElement).click();
    await flushPromises();

    const deep = useAssetDeepLinkStore(pinia);
    expect(deep.seq).toBe(1);
    expect(deep.asset).toBe('demo');
    expect(deep.comment).toBe(101);
    expect(router.currentRoute.value.query).toMatchObject({ asset: 'demo', comment: '101' });
  });

  it('从别的页面点通知 → 只走路由跳转, 不额外发打开请求', async () => {
    const { w, pinia } = await mountBell();
    await w.find('.tm-bell').trigger('click');
    await flushPromises();

    (document.body.querySelector('.nt-item') as HTMLElement).click();
    await flushPromises();

    expect(useAssetDeepLinkStore(pinia).seq).toBe(0);
  });

  it('「全部已读」调接口并把角标清零', async () => {
    const { w, pinia } = await mountBell();
    await w.find('.tm-bell').trigger('click');
    await flushPromises();

    const btn = document.body.querySelector('.nt-head .nt-link') as HTMLElement;
    expect(btn).toBeTruthy();
    btn.click();
    await flushPromises();

    expect(api.markAllNotificationsRead).toHaveBeenCalled();
    expect(useNotificationsStore(pinia).unread).toBe(0);
    expect(w.find('.tm-bell .badge').exists()).toBe(false);
  });
});
