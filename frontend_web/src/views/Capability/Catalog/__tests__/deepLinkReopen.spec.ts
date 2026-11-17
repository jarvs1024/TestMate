/**
 * 扩展库深链的「第二次打开」—— 2026-11-16.
 *
 * 病根: 深链只在 onMounted 里读一次.
 *   ① 人已经停在 /extensions?asset=a&comment=1, 关掉抽屉后再点同一条通知
 *      → push 是同地址导航, 路由既不动, 也不触发 query watch;
 *   ② 停在扩展库上换成另一条通知 → query 变了, 但组件不重挂, 没人再读.
 * 两条路都要能重新打开抽屉.
 */
import { describe, expect, it, vi, beforeEach, afterEach } from 'vitest';
import { mount } from '@vue/test-utils';
import { createPinia, setActivePinia } from 'pinia';
import { useUserStore } from '@/stores/user';
import { useAssetDeepLinkStore } from '@/stores/assetDeepLink';

const { listAssets, listJobs, requestGet, getAsset } = vi.hoisted(() => ({
  listAssets: vi.fn(),
  listJobs: vi.fn(),
  requestGet: vi.fn(),
  getAsset: vi.fn(),
}));

vi.mock('@/utils/request', () => ({ default: { get: requestGet } }));

vi.mock('@/api/assets', () => ({
  listAssets: (...a: any[]) => listAssets(...a),
  listCategories: vi.fn(async () => ({ items: [] })),
  listJobs: (...a: any[]) => listJobs(...a),
  listProjects: vi.fn(async () => ({ items: [] })),
  getSyncStatus: vi.fn(async () => ({})),
  getExtConfig: vi.fn(async () => ({ remote: '', review_enabled: false })),
  retryJob: vi.fn(async () => ({})),
  syncFromGit: vi.fn(async () => ({ added: 0, updated: 0 })),
  getAsset: (...a: any[]) => getAsset(...a),
}));

vi.mock('../AssetCard.vue', () => ({
  default: { props: ['item'], template: '<div class="asset-card" :data-code="item.code" />' },
}));
// 抽屉只在打开时渲染 —— 用 modelValue 判断「到底有没有跳过去」
vi.mock('../AssetDetailDrawer.vue', () => ({
  default: {
    name: 'AssetDetailDrawer',
    props: ['modelValue', 'item', 'focusCommentId'],
    template:
      '<div v-if="modelValue" class="drawer"'
      + ' :data-code="item && item.code" :data-focus="focusCommentId ?? \'\'" />',
  },
}));
vi.mock('../AssetUploadDialog.vue', () => ({ default: { template: '<div />' } }));
vi.mock('../AssetAuditDrawer.vue', () => ({ default: { template: '<div />' } }));

// 路由 query 要**响应式** —— 深链的第二次打开靠的就是监听它的变化
const tmRoute = await vi.hoisted(async () => {
  const { reactive } = await import('vue');
  return reactive({ query: {} as Record<string, string> });
});

vi.mock('vue-router', () => ({
  useRouter: () => ({
    push: vi.fn(),
    resolve: (r: any) => ({ fullPath: String(r?.path || '') }),
  }),
  useRoute: () => tmRoute,
}));

const stubs = {
  'el-tooltip': { template: '<div><slot/></div>' },
};

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

async function mountExt() {
  const pinia = createPinia();
  setActivePinia(pinia);
  const store = useUserStore(pinia);
  store.user = { id: 1, username: 'jarvs', role: 'tester' } as any;
  const Ext = (await import('../index.vue')).default;
  const w = mount(Ext, { global: { plugins: [pinia], stubs } });
  await vi.advanceTimersByTimeAsync(0);
  return { w, pinia };
}

const route = () => tmRoute as { query: Record<string, string> };

const rulesPayload = {
  code: { pattern: 'x', example: 'x', min_length: 3, max_length: 64 },
  segment: { pattern: 'x', min_length: 3, max_length: 64 },
  package: { suffixes: ['.zip'] },
  required: { create: { common: [], skill: [], plugin: [], mcp: [] }, update: { common: [], skill: [], plugin: [], mcp: [] }, edit: [] },
  categories: [{ name: '其他', slug: 'misc', desc: '', order: 99 }],
  projects: [],
  enforcement: { code_must_match_package: true, code_must_match_mcp_server: true, unknown_category: '其他', unknown_project: '' },
};

beforeEach(() => {
  vi.useFakeTimers();
  route().query = {};
  requestGet.mockReset().mockResolvedValue(rulesPayload);
  listAssets.mockReset().mockResolvedValue({ items: [], total: 0 });
  listJobs.mockReset().mockResolvedValue({ items: [] });
  getAsset.mockReset().mockImplementation(async (code: string) => asset(code));
});

afterEach(() => {
  vi.useRealTimers();
});

describe('扩展库深链 · 再次打开', () => {
  it('初始进入: ?asset=&comment= → 打开抽屉并定位评论 (原有行为别回退)', async () => {
    route().query = { asset: 'demo', comment: '501' };
    const { w } = await mountExt();
    const d = w.find('.drawer');
    expect(d.exists()).toBe(true);
    expect(d.attributes('data-code')).toBe('demo');
    expect(d.attributes('data-focus')).toBe('501');
    w.unmount();
  });

  it('同一条深链再点一次 → store 信号让抽屉重新打开', async () => {
    route().query = { asset: 'demo', comment: '501' };
    const { w, pinia } = await mountExt();
    // 用户手动关掉抽屉, 地址栏还停在原处
    w.findComponent({ name: 'AssetDetailDrawer' }).vm.$emit('update:modelValue', false);
    await vi.advanceTimersByTimeAsync(0);
    expect(w.find('.drawer').exists()).toBe(false);

    useAssetDeepLinkStore(pinia).open('demo', 501);
    await vi.advanceTimersByTimeAsync(0);

    const d = w.find('.drawer');
    expect(d.exists()).toBe(true);
    expect(d.attributes('data-code')).toBe('demo');
    expect(d.attributes('data-focus')).toBe('501');
    w.unmount();
  });

  it('停在本页时换成另一条通知 → query 变化也能打开新资产', async () => {
    route().query = { asset: 'demo', comment: '501' };
    const { w } = await mountExt();
    w.findComponent({ name: 'AssetDetailDrawer' }).vm.$emit('update:modelValue', false);
    await vi.advanceTimersByTimeAsync(0);
    expect(w.find('.drawer').exists()).toBe(false);

    route().query = { asset: 'demo2', comment: '9' };
    await vi.advanceTimersByTimeAsync(0);

    const d = w.find('.drawer');
    expect(d.exists()).toBe(true);
    expect(d.attributes('data-code')).toBe('demo2');
    expect(d.attributes('data-focus')).toBe('9');
    w.unmount();
  });
});
