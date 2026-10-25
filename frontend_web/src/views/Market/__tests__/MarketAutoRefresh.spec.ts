/**
 * 市场页的**自动刷新** (2026-10-25 用户要求: 首页数据要能自动更新).
 *
 * 三个要点:
 *   ① 20s 定时静默刷新一次 (不闪 spinner, 失败不动页面);
 *   ② 页面**不可见**时暂停 (切到别的标签页了, 没人看, 白费请求);
 *   ③ 切回可见时立刻补一次 (免得用户盯着一个十分钟前的列表).
 */
import { describe, expect, it, vi, beforeEach, afterEach } from 'vitest';
import { mount } from '@vue/test-utils';
import { createPinia, setActivePinia } from 'pinia';

const { listAssets } = vi.hoisted(() => ({ listAssets: vi.fn() }));

vi.mock('@/api/assets', () => ({
  listAssets: (...a: any[]) => listAssets(...a),
  listCategories: vi.fn(async () => ({ items: [] })),
  listJobs: vi.fn(async () => ({ items: [] })),
  listProjects: vi.fn(async () => ({ items: [] })),
  getSyncStatus: vi.fn(async () => ({})),
  retryJob: vi.fn(async () => ({})),
  syncFromGit: vi.fn(async () => ({ added: 0, updated: 0 })),
}));

// 子组件跟自动刷新无关 —— 桩掉, 省得把整抽屉都挂起来
vi.mock('../AssetCard.vue', () => ({ default: { template: '<div class="asset-card" />' } }));
vi.mock('../AssetDetailDrawer.vue', () => ({ default: { template: '<div />' } }));
vi.mock('../AssetUploadDialog.vue', () => ({ default: { template: '<div />' } }));
vi.mock('../AssetAuditDrawer.vue', () => ({ default: { template: '<div />' } }));
vi.mock('vue-router', () => ({ useRouter: () => ({ push: vi.fn() }) }));

const stubs = {
  'el-tooltip': { template: '<div><slot/></div>' },
};

async function mountMarket() {
  const pinia = createPinia();
  setActivePinia(pinia);
  const Market = (await import('../index.vue')).default;
  const w = mount(Market, { global: { plugins: [pinia], stubs } });
  // 让首次加载的 promise 链跑完 (fake timers 下 flushPromises 用的 setTimeout 不会自己走)
  await vi.advanceTimersByTimeAsync(0);
  return w;
}

beforeEach(() => {
  vi.useFakeTimers();
  listAssets.mockReset();
  listAssets.mockResolvedValue({ items: [], total: 0 });
});

afterEach(() => {
  vi.useRealTimers();
});

describe('市场页 · 自动刷新', () => {
  it('20s 后自动静默刷新一次', async () => {
    const w = await mountMarket();
    const before = listAssets.mock.calls.length;
    expect(before).toBeGreaterThan(0);
    await vi.advanceTimersByTimeAsync(20000);
    expect(listAssets.mock.calls.length).toBe(before + 1);
    w.unmount();
  });

  it('页面不可见时**不**刷新 (没人看, 白费请求)', async () => {
    const w = await mountMarket();
    const before = listAssets.mock.calls.length;
    const orig = Object.getOwnPropertyDescriptor(document, 'hidden');
    Object.defineProperty(document, 'hidden', { value: true, configurable: true });
    try {
      await vi.advanceTimersByTimeAsync(20000);
      expect(listAssets.mock.calls.length).toBe(before);
    } finally {
      if (orig) Object.defineProperty(document, 'hidden', orig);
      else delete (document as any).hidden;
    }
    w.unmount();
  });

  it('切回可见时立刻补刷一次', async () => {
    const w = await mountMarket();
    const before = listAssets.mock.calls.length;
    const orig = Object.getOwnPropertyDescriptor(document, 'hidden');
    Object.defineProperty(document, 'hidden', { value: true, configurable: true });
    await vi.advanceTimersByTimeAsync(20000);
    expect(listAssets.mock.calls.length).toBe(before);
    // 切回可见
    Object.defineProperty(document, 'hidden', { value: false, configurable: true });
    document.dispatchEvent(new Event('visibilitychange'));
    await vi.advanceTimersByTimeAsync(0);
    expect(listAssets.mock.calls.length).toBe(before + 1);
    if (orig) Object.defineProperty(document, 'hidden', orig);
    else delete (document as any).hidden;
    w.unmount();
  });

  it('页脚同时说清两个时间源 (GitLab 对齐 vs 本页刷新)', async () => {
    // ⚠️ mock 要在 mount **之前**换 —— 首次加载就已经决定有没有数据了
    listAssets.mockResolvedValue({
      items: [{ code: 'a', name: 'A', kind: 'skill', version: '1.0.0',
        summary: 's', description: '', use_when: '', not_for: '', category: '其他',
        icon: '🧩', project: '', tags: [], keywords: [], author: 'admin', featured: false,
        homepage: null, permissions: {}, install_steps: [], bindings: {},
        git_path: '', git_commit_sha: '', git_web_url: '', download_count: 0,
        updated_at: null, sync_status: 'pushed', last_error: '', publish_status: 'published',
        review_note: '', can_review: false }],
      total: 1,
    });
    const w = await mountMarket();
    const foot = w.find('.foot-hint').text();
    expect(foot).toContain('本页上次刷新');
    expect(foot).not.toContain('· 最近对齐 ');
    w.unmount();
  });
});
