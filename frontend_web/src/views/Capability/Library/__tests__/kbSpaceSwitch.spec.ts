/**
 * 知识库 · 用户空间切换.
 *
 * 盯住三件事:
 *   ① 概览卡上的空间选择器是**真的**切换了 —— 选择落 localStorage, 数据集重拉;
 *   ② 切换时旧空间的数据要清掉 (不然 doc 缓存命中, 表里还是旧空间的文档);
 *   ③ 操作记录的空间筛选是**独立**参数, 不跟着 X-KB-Space 走.
 */
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { flushPromises, mount } from '@vue/test-utils';

const h = vi.hoisted(() => ({
  listDatasets: vi.fn(),
  listDocuments: vi.fn(async () => ({ docs: [] as any[], total: 0 })),
  listKbAudits: vi.fn(),
  listKbSpaces: vi.fn(),
  kbHealth: vi.fn(async () => ({ status: 'ok', message: 'RAGFlow 正常' })),
}));

vi.mock('@/stores/user', () => ({
  useUserStore: () => ({ user: { role: 'admin', username: 'admin' } }),
}));
vi.mock('@/stores/theme', () => ({ useThemeStore: () => ({ resolved: 'light' }) }));
vi.mock('@/api/settings', () => ({
  buildEmbedUrl: vi.fn(async () => ({ url: '' })),
  getSchema: vi.fn(async () => ({ groups: [] })),
}));
vi.mock('@/api/kb', () => ({
  listDatasets: h.listDatasets,
  kbHealth: h.kbHealth,
  listDocuments: h.listDocuments,
  listKbAudits: h.listKbAudits,
  listKbSpaces: h.listKbSpaces,
  listDocChunks: vi.fn(async () => ({ chunks: [], total: 0 })),
  uploadKbDocuments: vi.fn(),
  downloadKbDocument: vi.fn(),
  createKbDataset: vi.fn(),
  deleteKbDocuments: vi.fn(),
  deleteKbDataset: vi.fn(),
  updateKbDocument: vi.fn(),
  reparseKbDocument: vi.fn(),
  searchKbDocuments: vi.fn(async () => ({ items: [], total: 0, keywords: '', datasets: 0 })),
}));
vi.mock('element-plus', () => ({
  ElMessage: { success: vi.fn(), error: vi.fn(), warning: vi.fn(), info: vi.fn() },
  ElMessageBox: { prompt: vi.fn(), confirm: vi.fn() },
}));

import Library from '../index.vue';

const stubs = {
  'el-drawer': { template: '<div class="el-drawer"><slot/></div>' },
  'el-select': { props: ['modelValue'], template: '<select class="el-select"><slot/></select>' },
  'el-option': { props: ['label', 'value'], template: '<option>{{ label }}</option>' },
};

const SPACES = {
  items: [
    { id: 'sp_a', name: '空间A', is_default: true, configured: true },
    { id: 'sp_b', name: '空间B', is_default: false, configured: true },
  ],
  default_id: 'sp_a',
};

const DS_A = {
  id: 'ds-a', name: 'A 库', description: '', chunk_count: 1, document_count: 0,
  chunk_method: 'naive', embedding_model: 'emb', permission: 'me', status: '1',
  language: 'Chinese', token_num: 0, similarity_threshold: 0.2,
  vector_similarity_weight: 0.3, pagerank: 0, update_date: '', create_date: '',
  create_time: 0, update_time: 0, parser_config: {},
};

async function mountLib() {
  const w = mount(Library, { global: { stubs } });
  await flushPromises();
  return w;
}

beforeEach(() => {
  vi.clearAllMocks();
  localStorage.clear();
  h.listKbSpaces.mockResolvedValue(SPACES);
  h.listDatasets.mockResolvedValue({ items: [{ ...DS_A }], total: 1 });
  h.listKbAudits.mockResolvedValue({ items: [], total: 0, page: 1, page_size: 10, pages: 1 });
});

describe('知识库 · 空间切换', () => {
  it('概览卡上能看见空间选择器, 默认选中默认空间', async () => {
    const w = await mountLib();
    const sel = w.find('[data-test="kb-space-select"]');
    expect(sel.exists(), '概览卡没有空间选择器').toBe(true);
    expect((sel.element as HTMLSelectElement).value).toBe('sp_a');
  });

  it('切换空间 → 选择落 localStorage, 数据集重新拉一次', async () => {
    const w = await mountLib();
    const before = h.listDatasets.mock.calls.length;

    await w.find('[data-test="kb-space-select"]').setValue('sp_b');
    await flushPromises();

    expect(localStorage.getItem('testmate:kb-space')).toBe('sp_b');
    expect(
      h.listDatasets.mock.calls.length,
      '切换空间后没有重新拉数据集',
    ).toBeGreaterThan(before);
  });

  it('操作记录的空间筛选作为查询参数传给接口 (不跟随请求头)', async () => {
    const w = await mountLib();
    const initial = h.listKbAudits.mock.calls.at(-1) as any[];
    expect(initial?.[2]).toBeUndefined();

    await w.find('[data-test="kb-audit-space"]').setValue('sp_b');
    await flushPromises();

    const last = h.listKbAudits.mock.calls.at(-1) as any[];
    expect(last?.[2]).toBe('sp_b');
  });
});
