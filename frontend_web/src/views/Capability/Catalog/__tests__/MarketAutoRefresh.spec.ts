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
import { useUserStore } from '@/stores/user';

const { listAssets, listJobs } = vi.hoisted(() => ({ listAssets: vi.fn(), listJobs: vi.fn() }));

vi.mock('@/api/assets', () => ({
  listAssets: (...a: any[]) => listAssets(...a),
  listCategories: vi.fn(async () => ({ items: [] })),
  listJobs: (...a: any[]) => listJobs(...a),
  listProjects: vi.fn(async () => ({ items: [] })),
  getSyncStatus: vi.fn(async () => ({})),
  retryJob: vi.fn(async () => ({})),
  syncFromGit: vi.fn(async () => ({ added: 0, updated: 0 })),
}));

// 子组件跟自动刷新无关 —— 桩掉, 省得把整抽屉都挂起来
// (AssetCard 把 code 渲染出来 —— 用来断言"页面上是哪一份数据")
vi.mock('../AssetCard.vue', () => ({
  default: { props: ['item'], template: '<div class="asset-card" :data-code="item.code" />' },
}));
vi.mock('../AssetDetailDrawer.vue', () => ({ default: { template: '<div />' } }));
vi.mock('../AssetUploadDialog.vue', () => ({ default: { template: '<div />' } }));
vi.mock('../AssetAuditDrawer.vue', () => ({ default: { template: '<div />' } }));
vi.mock('vue-router', () => ({ useRouter: () => ({ push: vi.fn() }) }));

const stubs = {
  'el-tooltip': { template: '<div><slot/></div>' },
};

/** 造一条市场资产 (code 用来断言页面上是哪一份数据) */
function asset(code: string) {
  return {
    code, name: code, kind: 'plugin', version: '1.0.0',
    summary: 's', description: '', use_when: '', not_for: '', category: '其他',
    icon: '🧩', project: '', tags: [], keywords: [], author: 'admin', featured: true,
    homepage: null, permissions: {}, install_steps: [], bindings: {},
    git_path: '', git_commit_sha: '', git_web_url: '', download_count: 0,
    updated_at: null, sync_status: 'pushed', last_error: '', publish_status: 'published',
    review_note: '', can_review: false,
  };
}

async function mountMarket(opts: { role?: 'admin' | 'tester' } = {}) {
  const pinia = createPinia();
  setActivePinia(pinia);
  const store = useUserStore(pinia);
  store.user = {
    id: 1, username: 'jarvs',
    role: opts.role === 'admin' ? 'admin' : 'tester',
  } as any;
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
  listJobs.mockReset();
  listJobs.mockResolvedValue({ items: [] });
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

  it('轮询遇到同步中的任务 → 静默刷新 (列表不闪 loading 态)', async () => {
    // ⚠️ 以前 pollJobs 调的是**非静默**的 load() —— 每 5s 遇到一个同步中的任务
    //    就整页切 loading 态, 列表反复消失.
    listJobs.mockResolvedValue({ items: [{ id: 1, status: 'syncing' }] });
    const w = await mountMarket();
    // 让后续的列表请求一直悬着 —— 走非静默路径的话页面会卡在 loading 态
    listAssets.mockImplementation(() => new Promise(() => {}));
    await vi.advanceTimersByTimeAsync(5000);
    expect(w.find('.spinner').exists()).toBe(false);
    w.unmount();
  });

  it('快速切分类 → 旧响应不覆盖新结果 (只认最后一次请求)', async () => {
    // ⚠️ 以前没有请求序号 —— 慢的旧响应回来后会把列表覆盖成旧结果
    //    (Tab 高亮已经是新分类, 列表却是旧分类的).
    const w = await mountMarket();
    // 确认挂载期的请求都落地了 (后面 mock 的"下一次调用"才是我们要控制的那个)
    const settled = listAssets.mock.calls.length;
    await vi.advanceTimersByTimeAsync(0);
    expect(listAssets.mock.calls.length).toBe(settled);

    let slow: (v: any) => void = () => {};
    listAssets.mockImplementationOnce(() => new Promise((r) => { slow = r; }));
    listAssets.mockResolvedValue({ items: [asset('new')], total: 1 });

    // 点「⭐ 精选」→ 慢请求在飞
    await w.findAll('.chip')[1].trigger('click');
    // 再点「全部」→ 快请求先回
    await w.findAll('.chip')[0].trigger('click');
    await vi.advanceTimersByTimeAsync(0);

    // 慢请求这时才回来 (旧结果) —— 必须被丢弃
    slow({ items: [asset('old')], total: 1 });
    await vi.advanceTimersByTimeAsync(0);

    const codes = w.findAll('.asset-card').map((c) => c.attributes('data-code'));
    expect(codes).toEqual(['new']);
    w.unmount();
  });
});

describe('市场页 · 管理员专属入口', () => {
  it('普通用户看不到「操作记录」(审计 = 运营数据, 后端也收紧了)', async () => {
    const w = await mountMarket({ role: 'tester' });
    const labels = w.findAll('.mini-btn').map((b) => b.text()).join(' | ');
    expect(labels).not.toContain('操作记录');
    w.unmount();
  });

  it('管理员看得到「操作记录」', async () => {
    const w = await mountMarket({ role: 'admin' });
    const labels = w.findAll('.mini-btn').map((b) => b.text()).join(' | ');
    expect(labels).toContain('操作记录');
    w.unmount();
  });
});
