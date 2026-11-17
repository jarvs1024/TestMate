/**
 * 站内通知的页面接线 (2026-11-16).
 *
 * 结构层面锁住三件事 (行为由 NotificationBell / 消息页 / 抽屉各自的用例覆盖):
 *  ① 页头挂了铃铛
 *  ② 路由里有「消息」页
 *  ③ 扩展库认 `?asset=<code>&comment=<id>` —— 打开抽屉并把 comment 传下去
 */
import { describe, expect, it, vi } from 'vitest';
import { readFileSync } from 'node:fs';
import { resolve } from 'node:path';
import router, { routes } from '@/router';

vi.mock('@/stores/platform', async () => ({
  platformName: (await import('vue')).ref('TestMate'),
}));

const read = (p: string) => readFileSync(resolve(process.cwd(), p), 'utf8');
const header = read('src/components/AppHeader.vue');
const catalog = read('src/views/Capability/Catalog/index.vue');

describe('站内通知 · 页面接线', () => {
  it('页头有铃铛入口', () => {
    expect(header).toContain('NotificationBell');
    expect(header).toContain('<NotificationBell');
  });

  it('路由里有消息页 (登录可进)', () => {
    const main = routes.find((r) => r.path === '/')!;
    const child = (main.children || []).find((c) => c.name === 'notifications');
    expect(child).toBeTruthy();
    expect(child!.path).toBe('notifications');
    expect((child!.meta as any)?.title).toBe('消息');
    expect(router.hasRoute('notifications')).toBe(true);
  });

  it('扩展库认 ?asset=&comment= 深链', () => {
    expect(catalog).toContain('route.query.asset');
    expect(catalog).toContain('route.query.comment');
    expect(catalog).toContain('getAsset');
    expect(catalog).toMatch(/:focus-comment-id="focusCommentId"/);
  });
});
