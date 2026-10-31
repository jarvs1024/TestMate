/**
 * 知识库 · 第九轮 (2026-10-31) —— 「+ 新建数据集」按钮样式对齐软件库.
 *
 * 用户投诉: 知识库的「+ 新建数据集」跟软件库的「＋ 上架软件」**长得完全不一样** ——
 *   前者是局部 `.primary-btn` (纯色 + 边框 + 另一套圆角/padding),
 *   后者是全局 `.mini-btn.primary` (渐变底), 两个页面像两套产品.
 *
 * 修法: 「新建数据集」直接用**完全同一个 class** (`.mini-btn primary`),
 *   样式由全局 styles/main.css 一份提供 —— 跟前面几轮
 *   (.asset-card / .kind-tab / .mk-actions) 同一个套路.
 *
 * ⚠️ 同行的「⬆ 上传文档」(.ghost-btn ds-act) 和「↻ 刷新」**不动** —— 别顺手改.
 */
import { describe, expect, it, vi, beforeEach } from 'vitest';
import { mount, flushPromises } from '@vue/test-utils';
import Library from '../index.vue';

// ---------- 打桩 (照抄 createDataset.spec.ts 的模式) ----------

const h = vi.hoisted(() => ({
  listDatasets: vi.fn(async () => ({ items: [] as any[], total: 0 })),
  listDocuments: vi.fn(async () => ({ docs: [] as any[], total: 0 })),
  listKbAudits: vi.fn(async () => ({ items: [] as any[], total: 0 })),
  msg: { success: vi.fn(), error: vi.fn(), warning: vi.fn(), info: vi.fn() },
}));

const userState = vi.hoisted(() => ({ user: { role: 'tester', username: 'zhangsan' } as any }));

vi.mock('@/stores/user', () => ({ useUserStore: () => userState }));
vi.mock('@/stores/theme', () => ({ useThemeStore: () => ({ resolved: 'light' }) }));
vi.mock('@/api/settings', () => ({
  buildEmbedUrl: vi.fn(async () => ({ url: '' })),
  getSchema: vi.fn(async () => ({ groups: [] })),
}));
vi.mock('@/api/kb', () => ({
  listDatasets: h.listDatasets,
  kbHealth: vi.fn(async () => ({ status: 'ok', message: 'RAGFlow 正常' })),
  listDocuments: h.listDocuments,
  listDocChunks: vi.fn(async () => ({ chunks: [], total: 0 })),
  uploadKbDocuments: vi.fn(async () => ({ ok: true, uploaded: 0, ingest_started: false, docs: [] })),
  downloadKbDocument: vi.fn(async () => {}),
  listKbAudits: h.listKbAudits,
  createKbDataset: vi.fn(async () => ({ ok: true, dataset: {} })),
}));
vi.mock('element-plus', () => ({ ElMessage: h.msg }));

const stubs = {
  'el-drawer': { template: '<div class="el-drawer"><slot/></div>' },
  'el-select': { props: ['modelValue'], template: '<select class="el-select"><slot/></select>' },
  'el-option': { props: ['label', 'value'], template: '<option>{{ label }}</option>' },
};

const DS = [
  {
    id: 'ds-1', name: '协议文档', description: '协议规范', chunk_count: 796, document_count: 5,
    chunk_method: 'manual', embedding_model: 'emb', permission: 'me', status: '1', language: 'Chinese',
    token_num: 1, similarity_threshold: 0.2, vector_similarity_weight: 0.7, pagerank: 0.3,
    update_date: '', create_date: '', create_time: 0, update_time: 0, parser_config: {},
  },
];

async function mountLib() {
  const w = mount(Library, { global: { stubs } });
  await flushPromises();
  return w;
}

/** 工具条里的「新建数据集」按钮 */
function newDatasetBtn(w: any) {
  return w.findAll('.ds-tools button').find((b: any) => b.text().includes('新建数据集'));
}

beforeEach(() => {
  vi.clearAllMocks();
  userState.user = { role: 'tester', username: 'zhangsan' };
  h.listDatasets.mockResolvedValue({ items: DS.map((d) => ({ ...d })), total: DS.length });
});

describe('知识库 · 新建数据集按钮对齐软件库', () => {
  it('用的是**全局** .mini-btn primary (跟软件库「＋ 上架软件」同一个 class)', async () => {
    const w = await mountLib();
    const btn = newDatasetBtn(w);
    expect(btn, '标题行应该有「新建数据集」按钮').toBeTruthy();
    expect(btn!.classes()).toContain('mini-btn');
    expect(btn!.classes()).toContain('primary');
  });

  it('不再用局部 .primary-btn —— 那个是纯色 + 边框, 跟软件库的渐变按钮对不上', async () => {
    const w = await mountLib();
    const btn = newDatasetBtn(w);
    expect(btn!.classes()).not.toContain('primary-btn');
    expect(btn!.classes()).not.toContain('ds-act');
  });

  it('文案跟软件库「＋ 上架软件」一个写法 (全角加号)', async () => {
    const w = await mountLib();
    expect(newDatasetBtn(w)!.text()).toContain('＋ 新建数据集');
  });

  it('同行的「⬆ 上传文档」「↻ 刷新」**没被动过**', async () => {
    const w = await mountLib();
    const upBtn = w.findAll('.ds-tools button').find((b: any) => b.text().includes('上传文档'));
    const reloadBtn = w.findAll('.ds-tools button').find((b: any) => b.text().includes('刷新'));
    expect(upBtn!.classes()).toContain('ghost-btn');
    expect(upBtn!.classes()).toContain('ds-act');
    expect(reloadBtn!.classes()).toContain('reload');
  });

  it('按钮还是能点开「新建数据集」抽屉 (只换皮, 没换功能)', async () => {
    const w = await mountLib();
    await newDatasetBtn(w)!.trigger('click');
    await flushPromises();
    expect(w.find('.cd-panel').exists()).toBe(true);
  });

  it('viewer 是只读角色 → 建库入口不出现', async () => {
    userState.user = { role: 'viewer', username: 'lisi' };
    const w = await mountLib();
    expect(newDatasetBtn(w)).toBeFalsy();
  });
});
