/**
 * 使用统计区块 (UsageStats) —— 在线 / 活跃曲线 / 下载排行 / 用户明细.
 *
 * 盯住这几件事:
 *   ① 三块 KPI 用后端数: 当前在线、今日活跃、两库累计下载;
 *   ② 活跃曲线按所选周期渲染 (7/30/90), 切周期要重新取数;
 *   ③ 下载排行默认软件库, 能切到扩展库;
 *   ④ 用户明细给出每人活跃天数和两库下载数, 可按活跃/下载排序;
 *   ⑤ 展开用户才去取资产下钻, 不拖慢首屏;
 *   ⑥ 在线名单每 60 秒刷新一次, 卸载后不再轮询;
 *   ⑦ 取数失败要说清楚并给重试入口, 不能显示成"没有数据".
 */
import { describe, expect, it, vi, beforeEach, afterEach } from 'vitest';
import { mount, flushPromises } from '@vue/test-utils';
import { readFileSync } from 'node:fs';
import path from 'node:path';
import UsageStats from '../UsageStats.vue';
import type { UsageSummary, StatsUsers } from '@/api/stats';

const api = vi.hoisted(() => ({
  getUsageSummary: vi.fn(),
  getOnlineUsers: vi.fn(),
  getStatsUsers: vi.fn(),
  getUserDownloads: vi.fn(),
}));

vi.mock('@/api/stats', () => api);

function users(days = 30): StatsUsers {
  return {
    days,
    since: '2026-11-10',
    anonymous_downloads: 2,
    users: [
      {
        id: 1,
        username: 'zhangsan@twsc.com.cn',
        role: 'tester',
        is_active: true,
        is_online: true,
        active_days: 5,
        active_dates: ['2026-11-12', '2026-11-13', '2026-11-14', '2026-11-15', '2026-11-16'],
        last_seen_at: '2026-11-16T10:01:00',
        software_downloads: 3,
        extension_downloads: 2,
        total_downloads: 5,
      },
      {
        id: 2,
        username: 'lisi@twsc.com.cn',
        role: 'viewer',
        is_active: true,
        is_online: false,
        active_days: 2,
        active_dates: ['2026-11-15', '2026-11-16'],
        last_seen_at: '2026-11-16T09:00:00',
        software_downloads: 1,
        extension_downloads: 8,
        total_downloads: 9,
      },
    ],
  };
}

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
  api.getStatsUsers.mockReset();
  api.getUserDownloads.mockReset();
  api.getUsageSummary.mockImplementation(async (days: number) => summary(days));
  api.getStatsUsers.mockImplementation(async (days: number) => users(days));
  api.getUserDownloads.mockResolvedValue({
    user_id: 1,
    days: 30,
    items: [
      {
        kind: 'software',
        action: 'download',
        code: 'soft-1',
        name: '演示软件',
        count: 3,
        last_at: '2026-11-16T10:00:00',
      },
      {
        kind: 'extension',
        action: 'copy',
        code: 'mcp-1',
        name: '需求连接器',
        count: 2,
        last_at: '2026-11-15T18:00:00',
      },
    ],
  });
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
    expect(api.getStatsUsers).toHaveBeenLastCalledWith(90);
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

describe('使用统计 · 用户明细', () => {
  it('列出每人的活跃天数和两库下载数, 并说明统计起点与匿名下载', async () => {
    const w = await mountComp();

    expect(api.getStatsUsers).toHaveBeenCalledWith(30);
    expect(w.get('[data-testid="user-row-1"]').text()).toContain('zhangsan@twsc.com.cn');
    expect(w.get('[data-testid="user-active-1"]').text()).toContain('5');
    expect(w.get('[data-testid="user-software-1"]').text()).toContain('3');
    expect(w.get('[data-testid="user-extension-1"]').text()).toContain('2');
    expect(w.get('[data-testid="user-total-1"]').text()).toContain('5');
    expect(w.get('[data-testid="stats-since"]').text()).toContain('2026-11-10');
    expect(w.get('[data-testid="anonymous-note"]').text()).toContain('2');
    w.unmount();
  });

  it('默认按活跃天数排, 可切到按下载合计排', async () => {
    const w = await mountComp();

    expect(w.findAll('[data-testid^="user-row-"]')[0].attributes('data-testid')).toBe('user-row-1');

    await w.get('[data-testid="sort-downloads"]').trigger('click');
    expect(w.findAll('[data-testid^="user-row-"]')[0].attributes('data-testid')).toBe('user-row-2');

    await w.get('[data-testid="sort-active"]').trigger('click');
    expect(w.findAll('[data-testid^="user-row-"]')[0].attributes('data-testid')).toBe('user-row-1');
    w.unmount();
  });

  it('展开用户才拉资产下钻, 再点收起', async () => {
    const w = await mountComp();

    expect(api.getUserDownloads).not.toHaveBeenCalled();

    await w.get('[data-testid="user-row-1"]').trigger('click');
    await flushPromises();

    expect(api.getUserDownloads).toHaveBeenCalledWith(1, 30);
    const detail = w.get('[data-testid="user-detail-1"]');
    expect(detail.text()).toContain('演示软件');
    expect(detail.text()).toContain('需求连接器');
    expect(detail.text()).toContain('配置复制');

    await w.get('[data-testid="user-row-1"]').trigger('click');
    expect(w.find('[data-testid="user-detail-1"]').exists()).toBe(false);
    w.unmount();
  });

  it('用户明细取数失败只在明细区报错, 图表保留并可重试', async () => {
    api.getStatsUsers.mockRejectedValueOnce({
      response: { data: { detail: '用户统计暂不可用' } },
    });
    const w = await mountComp();

    expect(w.find('[data-testid="active-chart"]').exists()).toBe(true);
    expect(w.get('[data-testid="users-error"]').text()).toContain('用户统计暂不可用');

    await w.get('[data-testid="users-retry"]').trigger('click');
    await flushPromises();

    expect(w.find('[data-testid="users-error"]').exists()).toBe(false);
    expect(w.find('[data-testid="user-row-1"]').exists()).toBe(true);
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

describe('使用统计 · 深色主题', () => {
  it('只使用 tokens.css 里已定义的变量, 否则暗色会回退成浅色', () => {
    /* ⚠️ 2026-11-17 用户报「深色模式不对」: 卡片是银白渐变、边框发白、标题发灰.
       根因不是暗色 token 没定义, 而是这个组件用了**不存在的变量名** ——
       `--surface-2` / `--line` / `--ink-400` / `--ink-600` / `--ink-800`.
       var() 找不到变量时会用兜底值 (浅色), 于是暗色下只有一半样式跟着主题走.
       这里直接锁源码: 这些名字以后不能再出现. */
    const src = readFileSync(
      path.resolve(process.cwd(), 'src/views/Settings/components/UsageStats.vue'),
      'utf-8',
    );
    expect(src).not.toMatch(/--surface-2\b/);
    expect(src).not.toMatch(/--line\b/);
    expect(src).not.toMatch(/--ink-(400|600|800)\b/);
  });
});
