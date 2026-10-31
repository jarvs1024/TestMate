/**
 * **第二十轮 · 分类 chip 的计数不许消失** (2026-10-31).
 *
 * 用户报的毛病:
 *   「选中流程规范或者其他，质量保障，效率工具都没数字显示了，其他类似」
 *
 * 根因: 分类 chip 上的数字以前是**前端按当前列表聚合**的 ——
 *   选了某个分类 → 列表里只剩那一类 → 别的分类全被算成 0 →
 *   再被模板里的 `v-if` 一藏 → **别的分类的数字全消失**。
 *
 * 修法: 计数下沉到后端 (`cat_counts`), 口径跟 `all_total` 一致 (忽略 category);
 *   并且 **0 也照样显示** —— 「这个分类确实是 0 条」跟「这个分类没统计」得分得开。
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

vi.mock('../AssetCard.vue', () => ({
  default: { props: ['item'], template: '<div class="asset-card" :data-code="item.code" />' },
}));
vi.mock('../AssetDetailDrawer.vue', () => ({ default: { template: '<div />' } }));
vi.mock('../AssetUploadDialog.vue', () => ({ default: { template: '<div />' } }));
vi.mock('../AssetAuditDrawer.vue', () => ({ default: { template: '<div />' } }));

vi.mock('vue-router', () => ({
  useRouter: () => ({ push: vi.fn() }),
  useRoute: () => ({ query: {} }),
}));

const stubs = { 'el-tooltip': { template: '<div><slot/></div>' } };

function asset(code: string, category = '质量保障') {
  return {
    code, name: code, kind: 'skill', version: '1.0.0',
    summary: 's', description: '', use_when: '', not_for: '', category,
    icon: '🧩', project: '', tags: [], keywords: [], author: 'jarvs', featured: false,
    homepage: null, permissions: {}, install_steps: [], bindings: {},
    git_path: '', git_commit_sha: '', git_web_url: '', download_count: 0,
    updated_at: null, sync_status: 'pushed', last_error: '', publish_status: 'published',
    review_note: '', can_review: false,
  } as any;
}

/** 三个分类: 两个有货, 一个 0 条 */
const CAT_COUNTS: Record<string, number> = { 质量保障: 3, 效率工具: 4 };

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

/** 分类 chip (按文字找) */
function chip(w: any, text: string) {
  const c = w.findAll('.cat-chips .chip').find((x: any) => x.text().includes(text));
  if (!c) throw new Error(`找不到 chip: ${text}`);
  return c;
}

/** chip 上的计数徽标文字 (null = 徽标根本没渲染) */
function countOf(w: any, text: string): string | null {
  const el = chip(w, text).find('.count');
  if (!el.exists()) return null;
  return el.text();
}

beforeEach(() => {
  listAssets.mockReset();
  listCategories.mockReset();
  // ⚠️ 模拟后端: 选分类之后列表**只剩那一类**, 但 cat_counts **不变**
  listAssets.mockImplementation(async (params: any) => {
    const cat = params?.category;
    const items = cat
      ? [asset('a1'), asset('a2'), asset('a3')]
      : [
          asset('a1'), asset('a2'), asset('a3'),
          asset('b1'), asset('b2'), asset('b3'), asset('b4', '效率工具'),
        ];
    return {
      items,
      total: items.length,
      all_total: 7,
      mine_total: 5,
      cat_counts: { ...CAT_COUNTS },
    };
  });
  listCategories.mockResolvedValue({
    items: [
      { name: '质量保障', slug: 'quality', desc: '兜住质量', total: 3 },
      { name: '效率工具', slug: 'efficiency', desc: '提效', total: 4 },
      { name: '流程规范', slug: 'process', desc: '守流程', total: 0 },
    ],
    total: 3,
  });
});

describe('市场页 · 分类 chip 的计数恒定 (第二十轮)', () => {
  it('初始: 每个分类都有计数 (0 也照样显示)', async () => {
    const w = await mountMarket();
    expect(countOf(w, '质量保障')).toBe('3');
    expect(countOf(w, '效率工具')).toBe('4');
    // ⚠️ 0 不是"没统计" —— 徽标必须在, 只是数字是 0
    expect(countOf(w, '流程规范')).toBe('0');
    w.unmount();
  });

  it('⚠️ 选了某个分类 → **别的分类的计数不变** (原来会全变成 0 然后消失)', async () => {
    const w = await mountMarket();
    expect(countOf(w, '效率工具')).toBe('4');

    await chip(w, '质量保障').trigger('click');
    await flushPromises();

    // 列表确实只剩这一类了 (说明请求真的带上了 category)
    expect(listAssets.mock.calls[listAssets.mock.calls.length - 1][0].category).toBe('质量保障');
    // ⚠️ 但计数不许动 —— 这正是原来那个 bug
    expect(countOf(w, '质量保障')).toBe('3');
    expect(countOf(w, '效率工具')).toBe('4');
    expect(countOf(w, '流程规范')).toBe('0');
    w.unmount();
  });

  it('选了「⭐ 精选」也一样 —— 别的分类计数不动', async () => {
    const w = await mountMarket();
    await chip(w, '精选').trigger('click');
    await flushPromises();
    expect(countOf(w, '效率工具')).toBe('4');
    expect(countOf(w, '质量保障')).toBe('3');
    w.unmount();
  });

  it('选了「👤 我的」也一样 —— 别的分类计数不动', async () => {
    const w = await mountMarket();
    await chip(w, '我的').trigger('click');
    await flushPromises();
    expect(countOf(w, '效率工具')).toBe('4');
    expect(countOf(w, '质量保障')).toBe('3');
    w.unmount();
  });

  it('老后端没给 cat_counts → 回退快照, 别的分类**不会全变 0**', async () => {
    // ⚠️ 模拟老后端: 只给 items/total, 不给 cat_counts
    listAssets.mockImplementation(async (params: any) => {
      const cat = params?.category;
      const items = cat ? [asset('a1')] : [asset('a1'), asset('b1', '效率工具')];
      return { items, total: items.length, all_total: 7, mine_total: 5 };
    });
    const w = await mountMarket();
    expect(countOf(w, '效率工具')).toBe('1');

    await chip(w, '质量保障').trigger('click');
    await flushPromises();

    // ⚠️ 兜底快照是"全量口径"时记下的 —— 选了分类之后不该让别的分类归零
    expect(countOf(w, '效率工具')).toBe('1');
    w.unmount();
  });
});
