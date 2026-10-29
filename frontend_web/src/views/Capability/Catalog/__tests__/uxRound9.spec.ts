/**
 * 第 9 轮 UX 整改的回归测试 (2026-10-30).
 *
 * 锁住这六件事 (每一件都是"用户看不到/点不动"的毛病):
 *  1. 上传抽屉的分类接口失败 → 必须说清楚 + 给「重试」, 不能静默地把「上架」按钮卡死;
 *  2. 列表加载超时 → 必须出现「加载超时」提示条 (以前永远渲染不出来);
 *  3. 分类 chip 上的数字 → 必须来自**当前列表**, 不是后端的 by_kind;
 *  4. 「重新上架」按钮 → 必须有 loading 绑定 (不然连点两次发两次请求);
 *  5. 操作记录按动作筛选后 0 条 → 空态文案不能说「还没有操作记录」(是错的);
 *  6. 资产名被省略号截断 → 必须有 title 兜底.
 */
import { describe, expect, it, vi, beforeEach, afterEach } from 'vitest';
import { mount, flushPromises } from '@vue/test-utils';
import { createPinia, setActivePinia } from 'pinia';
import ElementPlus from 'element-plus';
import { useUserStore } from '@/stores/user';
import AssetUploadDialog from '../AssetUploadDialog.vue';
import AssetAuditDrawer from '../AssetAuditDrawer.vue';
import AssetDetailDrawer from '../AssetDetailDrawer.vue';
import AssetCard from '../AssetCard.vue';

/**
 * ⚠️ 接口全部打桩 —— 跟 assetUploadFlow.spec.ts 一个写法 (vi.mock 整个模块).
 *    这里用 hoisted 的可变对象, 便于不同用例给不同的返回/失败.
 */
const api = vi.hoisted(() => ({
  listAssets: vi.fn(),
  listCategories: vi.fn(),
  listProjects: vi.fn(),
  listJobs: vi.fn(),
  listAudits: vi.fn(),
  listNotifications: vi.fn(),
  getSyncStatus: vi.fn(),
  getMarketConfig: vi.fn(),
  retryJob: vi.fn(),
  syncFromGit: vi.fn(),
  publishAsset: vi.fn(),
  getAsset: vi.fn(),
  getJob: vi.fn(),
  previewPackage: vi.fn(),
  uploadAsset: vi.fn(),
  updateAsset: vi.fn(),
}));

vi.mock('@/api/assets', () => api);

// ⚠️ 市场页用 useRoute() 读 `?status=pending` —— 少了这个 mock 组件初始化就抛
vi.mock('vue-router', () => ({
  useRouter: () => ({ push: vi.fn() }),
  useRoute: () => ({ query: {} }),
}));

/** element-plus 组件打桩 —— 只留结构, 不关心内部实现 */
const dialogStubs = {
  'el-drawer': { template: '<div class="el-drawer"><slot/><slot name="footer"/></div>' },
  'el-form': { template: '<form><slot/></form>' },
  'el-form-item': {
    props: ['label'],
    template: '<div class="el-form-item"><label v-if="label">{{ label }}</label><slot/></div>',
  },
  'el-input': { template: '<input class="el-input"/>' },
  'el-select': { template: '<select class="el-select"><slot/></select>' },
  'el-option': { props: ['label'], template: '<option>{{ label }}<slot/></option>' },
  'el-button': { template: '<button><slot/></button>' },
};

const auditStubs = {
  'el-drawer': { template: '<div class="el-drawer"><slot/></div>' },
  'el-tabs': { template: '<div class="el-tabs"><slot/></div>' },
  'el-tab-pane': { template: '<div class="el-tab-pane"><slot/></div>' },
};

/** 市场页的打桩: 抽屉那些组件跟这轮整改无关, 桩掉省得把整抽屉挂起来 */
const marketStubs = {
  'el-tooltip': { template: '<div><slot/></div>' },
  AssetDetailDrawer: true,
  AssetUploadDialog: true,
  AssetAuditDrawer: true,
};

/** 造一条市场资产 (category 用来验证 chip 计数) */
function asset(code = 'demo', category = '其他') {
  return {
    code, name: '演示资产', kind: 'plugin', version: '1.0.0',
    summary: 's', description: '', use_when: '', not_for: '', category,
    icon: '🧩', project: '', tags: [], keywords: [], author: 'admin', featured: false,
    homepage: null, permissions: {}, install_steps: [], bindings: {},
    git_path: '', git_commit_sha: '', git_web_url: '', download_count: 0,
    updated_at: null, sync_status: 'pushed', last_error: '', publish_status: 'published',
    review_note: '', can_review: false,
  } as any;
}

/** 挂市场页 (fake timers 下用 advanceTimersByTimeAsync(0) 冲 promise 链) */
async function mountMarket(opts: { fake?: boolean } = {}) {
  if (opts.fake) vi.useFakeTimers();
  const pinia = createPinia();
  setActivePinia(pinia);
  const store = useUserStore(pinia);
  store.user = { id: 1, username: 'jarvs', role: 'tester' } as any;
  const Market = (await import('../index.vue')).default;
  const w = mount(Market, { global: { plugins: [pinia], stubs: marketStubs } });
  await vi.advanceTimersByTimeAsync(0);
  await flushPromises();
  return w;
}

beforeEach(() => {
  api.listAssets.mockReset();
  api.listCategories.mockReset();
  api.listProjects.mockReset();
  api.listJobs.mockReset();
  api.listAudits.mockReset();
  api.listNotifications.mockReset();
  api.getSyncStatus.mockReset();
  api.getMarketConfig.mockReset();
  api.publishAsset.mockReset();

  api.listAssets.mockResolvedValue({ items: [], total: 0 });
  api.listCategories.mockResolvedValue({ items: [] });
  api.listProjects.mockResolvedValue({ items: [] });
  api.listJobs.mockResolvedValue({ items: [] });
  api.listAudits.mockResolvedValue({ items: [] });
  api.listNotifications.mockResolvedValue({ items: [] });
  api.getSyncStatus.mockResolvedValue({});
  api.getMarketConfig.mockResolvedValue({ remote: '', review_enabled: true });
  api.publishAsset.mockResolvedValue({});
});

afterEach(() => {
  vi.useRealTimers();
});

// ===================================================================
// ① P0 · 上传抽屉: 分类接口失败不能把「上架」按钮永久卡死
// ===================================================================
describe('上传抽屉 · 分类加载失败', () => {
  async function openDialog() {
    const w = mount(AssetUploadDialog, {
      props: { modelValue: false, mode: 'create', initialKind: 'skill' },
      global: { stubs: dialogStubs },
    });
    // 抽屉是 modelValue 从 false → true 时才初始化的 (watch)
    await w.setProps({ modelValue: true });
    await flushPromises();
    return w;
  }

  it('分类接口失败 → 抽屉里说清楚「分类列表加载失败」, 并给一个「重试」', async () => {
    api.listCategories.mockRejectedValue({
      response: { status: 500, data: { detail: '分类表读取失败' } },
    });
    const w = await openDialog();
    const err = w.find('.cat-err');
    expect(err.exists()).toBe(true);
    expect(err.text()).toContain('分类列表加载失败');
    expect(err.text()).toContain('分类表读取失败');
    // ⚠️ 必须能重试 —— 以前失败后这个按钮永远灰着, 只能关掉抽屉重开
    expect(w.find('.cat-retry').exists()).toBe(true);
  });

  it('点「重试」→ 会真的再发一次分类请求', async () => {
    api.listCategories.mockRejectedValue({ response: { status: 500, data: { detail: 'boom' } } });
    const w = await openDialog();
    const before = api.listCategories.mock.calls.length;
    await w.find('.cat-retry').trigger('click');
    await flushPromises();
    expect(api.listCategories.mock.calls.length).toBe(before + 1);
  });

  it('失败时下拉里注入兜底项「其他」→ 下拉永不为空, 按钮不会永久卡死', async () => {
    api.listCategories.mockRejectedValue({ response: { status: 500, data: { detail: 'boom' } } });
    const w = await openDialog();
    // ⚠️ 第一个 el-select 是「分类」 (row-2 的顺序: 分类 → 适用项目)
    const catSelect = w.findAll('.el-select')[0];
    const labels = catSelect.findAll('option').map((o) => o.text());
    expect(labels.join('|')).toContain('其他');
  });

  it('缺项提示说清是「加载失败」, 而不是「你没选」', async () => {
    api.listCategories.mockRejectedValue({ response: { status: 500, data: { detail: 'boom' } } });
    const w = await openDialog();
    const warn = w.find('.foot-warn');
    expect(warn.exists()).toBe(true);
    expect(warn.text()).toContain('分类');
    expect(warn.text()).toContain('加载失败');
  });

  it('正常返回时**不**注入兜底项 (表里本来就有分类)', async () => {
    api.listCategories.mockResolvedValue({
      items: [
        { name: '质量保障', slug: 'quality', desc: '兜住质量', by_kind: {}, total: 1 },
        { name: '其他', slug: 'misc', desc: '归不到上面任何一类', by_kind: {}, total: 0 },
      ],
    });
    const w = await openDialog();
    expect(w.find('.cat-err').exists()).toBe(false);
    const labels = w.findAll('.el-select')[0].findAll('option').map((o) => o.text());
    // 「其他」只有一个 (不是注入的那一个)
    expect(labels.filter((l) => l.includes('其他')).length).toBe(1);
  });
});

// ===================================================================
// ② P1 · 列表加载超时 —— 提示必须**看得见**
// ===================================================================
describe('市场页 · 加载超时提示', () => {
  it('后端卡住 → 15 秒后出现「加载超时」提示条 (以前永远渲染不出来)', async () => {
    // ⚠️ 请求一直悬着 —— 模拟后端不返回
    api.listAssets.mockImplementation(() => new Promise(() => {}));
    const w = await mountMarket({ fake: true });
    await vi.advanceTimersByTimeAsync(15000);
    await w.vm.$nextTick();
    const bar = w.find('.timeout-bar');
    expect(bar.exists()).toBe(true);
    expect(bar.text()).toContain('加载超时');
    // ⚠️ 以前超时分支排在 `v-if="loading"` 之后 → loading 为真时永远不渲染
    expect(w.find('.state.err').exists()).toBe(false);
    w.unmount();
  });

  it('超时提示条里带一个「重试」按钮', async () => {
    api.listAssets.mockImplementation(() => new Promise(() => {}));
    const w = await mountMarket({ fake: true });
    await vi.advanceTimersByTimeAsync(15000);
    await w.vm.$nextTick();
    const btn = w.find('.timeout-bar .tb-btn');
    expect(btn.exists()).toBe(true);
    expect(btn.text()).toContain('重试');
    w.unmount();
  });
});

// ===================================================================
// ③ P1 · 分类 chip 的数字必须来自当前列表
// ===================================================================
describe('市场页 · 分类 chip 计数', () => {
  it('chip 上的数字按当前列表聚合 (不是后端的 by_kind)', async () => {
    // ⚠️ 后端 by_kind 写的是 8 / 5 —— 那是不受搜索/项目筛选影响的"全局口径"
    api.listCategories.mockResolvedValue({
      items: [
        { name: '质量保障', slug: 'quality', desc: '兜住质量', by_kind: { plugin: 8 }, total: 8 },
        { name: '效率工具', slug: 'efficiency', desc: '提效', by_kind: { plugin: 5 }, total: 5 },
      ],
    });
    // 当前列表只有 1 张卡 (比如搜索「日志」之后)
    api.listAssets.mockResolvedValue({ items: [asset('a', '质量保障')], total: 1 });
    const w = await mountMarket({ fake: true });

    const chips = w.findAll('.cat-chips .chip');
    const all = chips.find((c) => c.text().includes('全部'))!;
    const q = chips.find((c) => c.text().includes('质量保障'))!;
    const e = chips.find((c) => c.text().includes('效率工具'))!;

    expect(all.find('.count').text()).toBe('1');
    // ⚠️ 以前这里写的是 8 (后端 by_kind) → 点进去是空列表
    expect(q.find('.count').text()).toBe('1');
    // 当前列表里没有「效率工具」→ 不显示数字
    expect(e.find('.count').exists()).toBe(false);
    w.unmount();
  });

  it('chip 上的数字 = 按 category 分组的当前列表条数', async () => {
    api.listCategories.mockResolvedValue({
      items: [
        { name: '质量保障', slug: 'quality', desc: '兜住质量', by_kind: {}, total: 0 },
        { name: '效率工具', slug: 'efficiency', desc: '提效', by_kind: {}, total: 0 },
      ],
    });
    api.listAssets.mockResolvedValue({
      items: [asset('a', '质量保障'), asset('b', '质量保障'), asset('c', '效率工具')],
      total: 3,
    });
    const w = await mountMarket({ fake: true });
    const chips = w.findAll('.cat-chips .chip');
    const q = chips.find((c) => c.text().includes('质量保障'))!;
    const e = chips.find((c) => c.text().includes('效率工具'))!;
    expect(q.find('.count').text()).toBe('2');
    expect(e.find('.count').text()).toBe('1');
    w.unmount();
  });
});

// ===================================================================
// ④ P1 · 「重新上架」按钮要有 loading
// ===================================================================
describe('资产详情抽屉 · 重新上架', () => {
  async function mountDrawer(publishStatus = 'unpublished') {
    const pinia = createPinia();
    setActivePinia(pinia);
    const store = useUserStore(pinia);
    store.user = { id: 1, username: 'jarvs', role: 'tester' } as any;
    const w = mount(AssetDetailDrawer, {
      props: {
        modelValue: true,
        item: { ...asset('demo', '其他'), publish_status: publishStatus },
        canEdit: true,
        reviewEnabled: true,
      } as any,
      global: { plugins: [pinia, ElementPlus] },
    });
    await flushPromises();
    return w;
  }

  function republishBtn(w: any) {
    return w.findAll('button').find((b: any) => b.text().includes('重新上架'));
  }

  it('点「重新上架」→ 按钮进入 loading (不是点了没反应)', async () => {
    const w = await mountDrawer('unpublished');
    const btn = republishBtn(w);
    expect(btn).toBeTruthy();
    expect(btn!.classes()).not.toContain('is-loading');

    // ⚠️ 请求悬着 —— 按钮必须显示"在转", 用户才知道点上了 (不然会连点两次)
    api.publishAsset.mockImplementation(() => new Promise(() => {}));
    await btn!.trigger('click');
    await flushPromises();
    expect(republishBtn(w)!.classes()).toContain('is-loading');
    w.unmount();
  });
});

// ===================================================================
// ⑤ P1 · 操作记录空态文案要分情况
// ===================================================================
describe('操作记录抽屉 · 空态文案', () => {
  async function openAudit(items: any[]) {
    api.listAudits.mockResolvedValue({ items });
    const w = mount(AssetAuditDrawer, {
      props: { modelValue: false },
      global: { stubs: auditStubs },
    });
    await w.setProps({ modelValue: true });
    await flushPromises();
    return w;
  }

  it('全部 → 没有记录时说「还没有操作记录」', async () => {
    const w = await openAudit([]);
    expect(w.find('.state').text()).toContain('还没有操作记录');
    w.unmount();
  });

  it('筛到 0 条的动作 → 说「没有「x」的记录」, 不是「还没有操作记录」', async () => {
    const w = await openAudit([
      { id: 1, action: 'create', action_label: '新建', code: 'demo', actor_name: 'jarvs',
        created_at: '2026-01-01T00:00:00Z', detail: {} },
    ]);
    // 点一个恰好 0 条的动作 chip
    const chip = w.findAll('.chip').find((c) => c.text().includes('版本更新'));
    expect(chip).toBeTruthy();
    await chip!.trigger('click');
    await w.vm.$nextTick();
    const state = w.find('.state').text();
    expect(state).toContain('没有「版本更新」的记录');
    // ⚠️ 以前这里是「还没有操作记录」—— 明明有一屏记录, 用户会以为记录丢了
    expect(state).not.toContain('还没有操作记录');
    w.unmount();
  });
});

// ===================================================================
// ⑥ P2 · 资产名要有 title (省略号截断的兜底)
// ===================================================================
describe('资产卡片 · 名字 tooltip', () => {
  it('.ac-name 带 title = 资产全名', () => {
    const item = asset('demo', '其他');
    item.name = '一个很长的资产名字会被省略号截断';
    const w = mount(AssetCard, { props: { item } });
    expect(w.find('.ac-name').attributes('title')).toBe('一个很长的资产名字会被省略号截断');
    w.unmount();
  });
});
