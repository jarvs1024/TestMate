/**
 * **第十九轮 · 市场页「👤 我的」跟分类 chip 互斥** (2026-10-31).
 *
 * 用户报的毛病: 「👤 我的」和「⭐ 精选」/某个分类能**同时点亮** ——
 *    两个维度一起发给后端 (status=mine + category=xxx), 返回的既不是"我的全部"
 *    也不是"该分类的全部", 用户根本说不清自己看到的是什么.
 *
 * 修法: 这一行 chip 是**同一个维度**, 同一时刻只能有一个亮着 ——
 *    · 点「👤 我的」→ 清掉 category (回到「全部」) + 清掉紧急入口;
 *    · 点「全部」/「⭐精选」/某个分类 → 清掉 mineOnly.
 *
 * ⚠️ 顺带盯 chip 上的两个计数 (后端新给的 all_total / mine_total):
 *    「全部 N」不能跟着当前筛选跳 (以前用 rawItems.length, 一选分类就变成那个分类的条数).
 */
import { describe, expect, it, vi, beforeEach } from 'vitest';
import { mount, flushPromises } from '@vue/test-utils';
import { createPinia, setActivePinia } from 'pinia';
import { useUserStore } from '@/stores/user';

const { listAssets, listCategories } = vi.hoisted(() => ({
  listAssets: vi.fn(),
  listCategories: vi.fn(),
}));

vi.mock('@/api/assets', () => ({
  listAssets: (...a: any[]) => listAssets(...a),
  listCategories: (...a: any[]) => listCategories(...a),
  listJobs: vi.fn(async () => ({ items: [] })),
  listProjects: vi.fn(async () => ({ items: [] })),
  getSyncStatus: vi.fn(async () => ({})),
  getMarketConfig: vi.fn(async () => ({ remote: 'root/testmate-market.git', review_enabled: true })),
  retryJob: vi.fn(async () => ({})),
  syncFromGit: vi.fn(async () => ({ added: 0, updated: 0 })),
}));

// 子组件跟这轮整改无关 —— 桩掉, 省得把整抽屉都挂起来
vi.mock('../AssetCard.vue', () => ({
  default: { props: ['item'], template: '<div class="asset-card" :data-code="item.code" />' },
}));
vi.mock('../AssetDetailDrawer.vue', () => ({ default: { template: '<div />' } }));
vi.mock('../AssetUploadDialog.vue', () => ({ default: { template: '<div />' } }));
vi.mock('../AssetAuditDrawer.vue', () => ({ default: { template: '<div />' } }));

// ⚠️ 市场页会用 useRoute() 读 `?status=pending` —— 少了这个 mock 组件初始化就抛
vi.mock('vue-router', () => ({
  useRouter: () => ({ push: vi.fn() }),
  useRoute: () => ({ query: {} }),
}));

const stubs = {
  'el-tooltip': { template: '<div><slot/></div>' },
};

/** 造一条市场资产 */
function asset(code: string, category = '质量保障') {
  return {
    code, name: code, kind: 'plugin', version: '1.0.0',
    summary: 's', description: '', use_when: '', not_for: '', category,
    icon: '🧩', project: '', tags: [], keywords: [], author: 'jarvs', featured: false,
    homepage: null, permissions: {}, install_steps: [], bindings: {},
    git_path: '', git_commit_sha: '', git_web_url: '', download_count: 0,
    updated_at: null, sync_status: 'pushed', last_error: '', publish_status: 'published',
    review_note: '', can_review: false,
  } as any;
}

async function mountMarket() {
  const pinia = createPinia();
  setActivePinia(pinia);
  const store = useUserStore(pinia);
  store.user = { id: 1, username: 'jarvs', role: 'tester' } as any;
  const Market = (await import('../index.vue')).default;
  const w = mount(Market, { global: { plugins: [pinia], stubs } });
  await flushPromises();
  await flushPromises();
  return w;
}

/** 分类 chip 行里的某个 chip (按文字找) */
function chip(w: any, text: string) {
  const c = w.findAll('.cat-chips .chip').find((x: any) => x.text().includes(text));
  if (!c) throw new Error(`找不到 chip: ${text}`);
  return c;
}
function isActive(c: any): boolean {
  return c.classes().includes('active');
}
/** 最后一次列表请求的参数 */
function lastListCall() {
  return listAssets.mock.calls[listAssets.mock.calls.length - 1][0];
}

/**
 * 真正的**列表**请求 (不是"数各类型有多少"的那种) ——
 * ⚠️ loadKindCounts() 也会调 listAssets({kind, limit:500}) 给类型 tab 数数,
 *    最后一次调用往往是那个 —— 认 sort 字段才能认出列表请求.
 */
function lastRealListCall() {
  const calls = listAssets.mock.calls.map((c: any[]) => c[0]).filter((p: any) => p && 'sort' in p);
  return calls[calls.length - 1];
}

beforeEach(() => {
  listAssets.mockReset();
  listCategories.mockReset();
  listAssets.mockResolvedValue({
    items: [asset('a')], total: 1, all_total: 12, mine_total: 3,
  });
  listCategories.mockResolvedValue({
    items: [{ name: '质量保障', slug: 'quality', desc: '兜住质量', by_kind: {}, total: 1 }],
    total: 1,
  });
});

describe('市场页 · 「👤 我的」跟分类 chip 互斥 (同一维度只能选一个)', () => {
  it('点「👤 我的」→ 「全部」chip 不再高亮 (category 被清空)', async () => {
    const w = await mountMarket();
    expect(isActive(chip(w, '全部'))).toBe(true);
    expect(isActive(chip(w, '我的'))).toBe(false);

    await chip(w, '我的').trigger('click');
    await flushPromises();

    expect(isActive(chip(w, '我的'))).toBe(true);
    // ⚠️ 以前这里两个能同时亮 —— 现在「全部」必须让路
    expect(isActive(chip(w, '全部'))).toBe(false);
    // 请求也要干净: 只带 status=mine, 不带 category
    expect(lastListCall().status).toBe('mine');
    expect(lastListCall().category).toBeUndefined();
    w.unmount();
  });

  it('点某个分类 → 「我的」不再高亮 (两个维度不能同时开)', async () => {
    const w = await mountMarket();

    await chip(w, '我的').trigger('click');
    await flushPromises();
    expect(isActive(chip(w, '我的'))).toBe(true);

    await chip(w, '质量保障').trigger('click');
    await flushPromises();

    expect(isActive(chip(w, '质量保障'))).toBe(true);
    expect(isActive(chip(w, '我的'))).toBe(false);
    expect(isActive(chip(w, '全部'))).toBe(false);
    // 请求带分类, 不带 status=mine
    expect(lastListCall().category).toBe('质量保障');
    expect(lastListCall().status).toBeUndefined();
    w.unmount();
  });

  it('点「⭐ 精选」→ 「我的」让路 (精选也是分类维度的一员)', async () => {
    const w = await mountMarket();

    await chip(w, '我的').trigger('click');
    await flushPromises();
    await chip(w, '精选').trigger('click');
    await flushPromises();

    expect(isActive(chip(w, '精选'))).toBe(true);
    expect(isActive(chip(w, '我的'))).toBe(false);
    w.unmount();
  });

  it('再点一次「👤 我的」→ 切回「全部」(两个都不亮, 不留残留状态)', async () => {
    const w = await mountMarket();

    await chip(w, '我的').trigger('click');
    await flushPromises();
    await chip(w, '我的').trigger('click');
    await flushPromises();

    expect(isActive(chip(w, '我的'))).toBe(false);
    expect(isActive(chip(w, '全部'))).toBe(true);
    expect(lastListCall().status).toBeUndefined();
    w.unmount();
  });
});

describe('市场页 · chip 上的两个计数 (后端 all_total / mine_total)', () => {
  it('「👤 我的」后面显示 mine_total', async () => {
    const w = await mountMarket();
    expect(chip(w, '我的').find('.count').text()).toBe('3');
    w.unmount();
  });

  it('「全部」显示 all_total (不是当前这一批的条数)', async () => {
    const w = await mountMarket();
    // ⚠️ 列表只回来 1 条, 但「全部」该显示后端给的总数 12
    expect(chip(w, '全部').find('.count').text()).toBe('12');
    w.unmount();
  });

  it('后端没给这两个字段 → 回退旧口径, 不白屏', async () => {
    listAssets.mockResolvedValue({ items: [asset('a'), asset('b')], total: 2 });
    const w = await mountMarket();
    // 「全部」回退到当前列表的条数
    expect(chip(w, '全部').find('.count').text()).toBe('2');
    // 「我的」拿不到数 → 0 (不能空着, 空着会让人以为没有这个维度)
    expect(chip(w, '我的').find('.count').text()).toBe('0');
    w.unmount();
  });
});

describe('市场页 · 进入后默认停在「技能」 (2026-10-31 第十九轮, 用户指定)', () => {
  /** 类型 tab (插件 / 技能 / 连接器) —— 按文字找 */
  function kindTab(w: any, text: string) {
    const t = w.findAll('.kind-tabs .kind-tab').find((x: any) => x.text().includes(text));
    if (!t) throw new Error(`找不到类型 tab: ${text}`);
    return t;
  }

  it('一进来「技能」是选中的, 「插件」不是', async () => {
    const w = await mountMarket();
    expect(kindTab(w, '技能').classes()).toContain('active');
    expect(kindTab(w, '插件').classes()).not.toContain('active');
    w.unmount();
  });

  it('首屏列表请求带 kind=skill', async () => {
    const w = await mountMarket();
    expect(lastRealListCall().kind).toBe('skill');
    w.unmount();
  });

  it('「清空筛选」也回到「技能」(跟初始态一致, 别跳到别的类型)', async () => {
    // 空列表 → 空态里有「清空筛选」按钮
    listAssets.mockResolvedValue({ items: [], total: 0, all_total: 0, mine_total: 0 });
    const w = await mountMarket();

    // 先切到「插件」, 再点「清空筛选」
    await kindTab(w, '插件').trigger('click');
    await flushPromises();
    expect(kindTab(w, '插件').classes()).toContain('active');

    const reset = w.findAll('button').find((b: any) => b.text().includes('清空筛选'));
    expect(reset).toBeTruthy();
    await reset!.trigger('click');
    await flushPromises();

    expect(kindTab(w, '技能').classes()).toContain('active');
    expect(lastRealListCall().kind).toBe('skill');
    w.unmount();
  });
});
