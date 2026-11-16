/**
 * 使用统计区块 (UsageStats) —— 在线 / 活跃曲线 / 下载排行.
 *
 * 盯住这几件事:
 *   ① 三块 KPI 用后端数: 当前在线、今日活跃、两库累计下载;
 *   ② 活跃曲线按所选周期渲染 (7/30/90), 切周期要重新取数;
 *   ③ 下载排行默认软件库, 能切到扩展库;
 *   ④ 在线名单每 60 秒刷新一次, 卸载后不再轮询;
 *   ⑤ 取数失败要说清楚并给重试入口, 不能显示成"没有数据".
 */
import { describe, expect, it, vi, beforeEach, afterEach } from 'vitest';
import { mount, flushPromises } from '@vue/test-utils';
import UsageStats from '../UsageStats.vue';
import type { UsageSummary } from '@/api/stats';

const api = vi.hoisted(() => ({
  getUsageSummary: vi.fn(),
  getOnlineUsers: vi.fn(),
}));

vi.mock('@/api/stats', () => api);

function summary(days = 30): UsageSummary {
  return {
    online: {
      count: 3,
      window_minutes: 5,
      users: [
        { id: 1, username: 'admin_t', role: 'admin', last_seen_at: '2026-11-16T10:00:00' },
        { id: 2, username: 'zhangsan@twsc.com.cn', role: 'tester', last_seen_at: '2026-11-16T10:01:00' },
        { id: 3, username: 'lisi@twsc.com.cn', role: 'viewer', last_seen_at: '2026-11-16T10:02:00' },
      ],
    },
    active: {
      today: 5,
      series: Array.from({ length: days }, (_, i) => ({
        date: `2026-11-${String((i % 28) + 1).padStart(2, '0')}`,
        count: (i % 4) + 1,
      })),
    },
    downloads: {
      software: {
        total: 26,
        items: [
          { code: 'soft-high', name: '高下载软件', icon: '📦', count: 9, kind: '' },
          { code: 'soft-low', name: '低下载软件', icon: '', count: 2, kind: '' },
        ],
      },
      extensions: {
        total: 45,
        items: [
          { code: 'ext-9', name: '扩展9', icon: '🧩', count: 9, kind: 'skill' },
          { code: 'ext-mcp', name: '扩展MCP', icon: '', count: 4, kind: 'mcp' },
        ],
      },
    },
  };
}

async function mountComp() {
  const w = mount(UsageStats);
  await flushPromises();
  return w;
}

beforeEach(() => {
  api.getUsageSummary.mockReset();
  api.getOnlineUsers.mockReset();
  api.getUsageSummary.mockImplementation(async (days: number) => summary(days));
  api.getOnlineUsers.mockResolvedValue({
    count: 4,
    window_minutes: 5,
    users: [
      { id: 1, username: 'admin_t', role: 'admin', last_seen_at: '2026-11-16T10:00:00' },
      { id: 2, username: 'zhangsan@twsc.com.cn', role: 'tester', last_seen_at: '2026-11-16T10:01:00' },
      { id: 3, username: 'lisi@twsc.com.cn', role: 'viewer', last_seen_at: '2026-11-16T10:02:00' },
      { id: 4, username: 'wangwu@twsc.com.cn', role: 'tester', last_seen_at: '2026-11-16T10:03:00' },
    ],
  });
});

afterEach(() => {
  vi.useRealTimers();
});

describe('使用统计 · KPI 与图表', () => {
  it('三块 KPI 用后端数, 默认取 30 天活跃曲线', async () => {
    const w = await mountComp();

    expect(api.getUsageSummary).toHaveBeenCalledWith(30);
    expect(w.get('[data-testid="kpi-online"]').text()).toContain('3');
    expect(w.get('[data-testid="kpi-active"]').text()).toContain('5');
    // 26 + 45
    expect(w.get('[data-testid="kpi-downloads"]').text()).toContain('71');
    expect(w.findAll('[data-testid="active-chart"] circle')).toHaveLength(30);
    expect(w.emitted('online')?.at(-1)).toEqual([3]);
    w.unmount();
  });

  it('切到 90 天 → 重新取数并按新周期画点', async () => {
    const w = await mountComp();

    await w.get('[data-testid="range-90"]').trigger('click');
    await flushPromises();

    expect(api.getUsageSummary).toHaveBeenLastCalledWith(90);
    expect(w.findAll('[data-testid="active-chart"] circle')).toHaveLength(90);
    w.unmount();
  });

  it('下载排行默认软件库, 可切到扩展库', async () => {
    const w = await mountComp();

    expect(w.get('[data-testid="download-bars"]').text()).toContain('高下载软件');
    expect(w.get('[data-testid="download-bars"]').text()).not.toContain('扩展9');

    await w.get('[data-testid="lib-extensions"]').trigger('click');

    expect(w.get('[data-testid="download-bars"]').text()).toContain('扩展9');
    expect(w.get('[data-testid="download-bars"]').text()).toContain('配置复制');
    w.unmount();
  });

  it('在线名单可展开, 显示用户名', async () => {
    const w = await mountComp();

    await w.get('[data-testid="online-toggle"]').trigger('click');

    expect(w.get('[data-testid="online-list"]').text()).toContain('zhangsan@twsc.com.cn');
    w.unmount();
  });

  it('取数失败 → 显示后端原因和重试, 不冒充空数据', async () => {
    api.getUsageSummary.mockRejectedValueOnce({
      response: { data: { detail: '仅管理员可以查看用户统计' } },
    });
    const w = await mountComp();

    expect(w.get('[data-testid="stats-error"]').text()).toContain('仅管理员可以查看用户统计');
    expect(w.find('[data-testid="active-chart"]').exists()).toBe(false);

    await w.get('[data-testid="stats-retry"]').trigger('click');
    await flushPromises();

    expect(api.getUsageSummary).toHaveBeenCalledTimes(2);
    expect(w.find('[data-testid="stats-error"]').exists()).toBe(false);
    expect(w.find('[data-testid="active-chart"]').exists()).toBe(true);
    w.unmount();
  });
});

describe('使用统计 · 在线轮询', () => {
  it('每 60 秒刷新在线人数, 卸载后停止', async () => {
    vi.useFakeTimers();
    const w = mount(UsageStats);
    await flushPromises();

    expect(w.get('[data-testid="kpi-online"]').text()).toContain('3');

    await vi.advanceTimersByTimeAsync(60_000);
    await flushPromises();

    expect(api.getOnlineUsers).toHaveBeenCalledTimes(1);
    expect(w.get('[data-testid="kpi-online"]').text()).toContain('4');
    expect(w.emitted('online')?.at(-1)).toEqual([4]);

    w.unmount();
    await vi.advanceTimersByTimeAsync(120_000);
    expect(api.getOnlineUsers).toHaveBeenCalledTimes(1);
  });
});
