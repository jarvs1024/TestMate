/**
 * 知识库 · 文档搜索 (2026-10-29 第五轮).
 *
 * 需求: 在「数据集」后面加一个**按文件名搜文档**的功能.
 *
 * ⚠️ 语义是「**只搜文件名, 不搜内容**」—— RAGFlow 的 keywords 是
 *    `LOWER(name).contains(keywords.lower())`, 不区分大小写的子串匹配.
 *    页面上必须说清楚, 否则用户搜不到会以为文档不存在.
 */
import { describe, expect, it, vi, beforeEach } from 'vitest';
import { mount, flushPromises } from '@vue/test-utils';
import Library from '../index.vue';

// ---------- 打桩 ----------

const h = vi.hoisted(() => ({
  listDatasets: vi.fn(async () => ({ items: [] as any[], total: 0 })),
  listDocuments: vi.fn(async () => ({ docs: [] as any[], total: 0 })),
  listKbAudits: vi.fn(async () => ({ items: [] as any[], total: 0 })),
  searchKbDocuments: vi.fn(async () => ({
    items: [] as any[], total: 0, keywords: '', datasets: 0,
  })),
  msg: { success: vi.fn(), error: vi.fn(), warning: vi.fn(), info: vi.fn() },
  confirm: vi.fn(async () => { throw 'cancel'; }),
  prompt: vi.fn(async () => { throw 'cancel'; }),
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
  uploadKbDocuments: vi.fn(),
  downloadKbDocument: vi.fn(async () => {}),
  listKbAudits: h.listKbAudits,
  createKbDataset: vi.fn(),
  deleteKbDataset: vi.fn(),
  updateKbDocument: vi.fn(),
  reparseKbDocument: vi.fn(),
  searchKbDocuments: h.searchKbDocuments,
}));
vi.mock('element-plus', () => ({
  ElMessage: h.msg,
  ElMessageBox: { prompt: h.prompt, confirm: h.confirm },
}));

const stubs = {
  'el-drawer': { template: '<div class="el-drawer"><slot/></div>' },
  'el-select': { props: ['modelValue'], template: '<select class="el-select"><slot/></select>' },
  'el-option': { props: ['label', 'value'], template: '<option>{{ label }}</option>' },
};

const DS = [
  {
    id: 'ds-1', name: '技术文档', description: '', chunk_count: 3, document_count: 1,
    chunk_method: 'naive', embedding_model: 'emb', permission: 'me', status: '1',
    language: 'Chinese', token_num: 1, similarity_threshold: 0.2,
    vector_similarity_weight: 0.7, pagerank: 0.3, update_date: '', create_date: '',
    create_time: 0, update_time: 0, parser_config: {},
    created_by_name: 'zhangsan@twsc.com.cn', created_by: 349, created_at: '2026-10-29T04:30:00Z',
  },
];

/** 一条搜索命中 */
const HIT = {
  id: 'doc-9', name: '2026年度计划.docx', location: '2026年度计划.docx', type: 'docx',
  size: 2048, chunk_count: 12, token_count: 900, chunk_method: 'naive',
  run: 'DONE', progress: 1, progress_msg: '', process_begin_at: null,
  process_duration: 3, source_type: 'local', parser_config: {}, status: '1',
  create_date: '', update_date: '', create_time: 0, update_time: 0,
  uploaded_by_name: 'zhangsan@twsc.com.cn', uploaded_by: 349,
  uploaded_at: '2026-10-29T04:35:00Z',
  // ⚠️ 跨库搜索必须带上「在哪个库」
  dataset_id: 'ds-9', dataset_name: '项目管理',
};

async function mountLib() {
  const w = mount(Library, { global: { stubs } });
  await flushPromises();
  return w;
}

/** 输入关键词并等防抖过去 */
async function typeKeyword(w: any, kw: string) {
  const input = w.find('.card .search input');
  await input.setValue(kw);
  await input.trigger('input');
  // 防抖 400ms —— 等它过去
  await new Promise((r) => setTimeout(r, 520));
  await flushPromises();
}

beforeEach(() => {
  vi.clearAllMocks();
  userState.user = { role: 'tester', username: 'zhangsan' };
  h.listDatasets.mockResolvedValue({ items: DS.map((d) => ({ ...d })), total: DS.length });
  h.listDocuments.mockResolvedValue({ docs: [], total: 0 });
  h.searchKbDocuments.mockResolvedValue({
    items: [], total: 0, keywords: '', datasets: 0,
  });
});

// ---------- ① 入口 ----------

describe('文档搜索入口', () => {
  it('⚠️ 搜索框在「数据集」这个卡片**里面** —— 不另开一个「文档搜索」卡片', async () => {
    const w = await mountLib();
    const cards = w.findAll('.card');
    const dsCard = cards.find((c: any) => {
      const h2 = c.find('.ds-hd h2');
      return h2.exists() && (h2.text() || '').includes('数据集');
    });
    expect(dsCard, '找不到「数据集」卡片').toBeTruthy();
    // 搜索框就在这个卡片里
    expect(dsCard!.find('.search input').exists()).toBe(true);
    // ⚠️ 而且**没有**独立的「文档搜索」卡片
    const searchCards = cards.filter((c: any) => {
      const h2 = c.find('.ds-hd h2');
      return h2.exists() && (h2.text() || '').includes('文档搜索');
    });
    expect(searchCards).toHaveLength(0);
  });

  it('搜索框一开始就在(不用点任何按钮才出现)', async () => {
    const w = await mountLib();
    expect(w.find('.search input').exists()).toBe(true);
  });

  it('一直告诉用户「只搜文件名」—— 不然搜内容搜不到会以为文档不存在', async () => {
    const w = await mountLib();
    // ⚠️ 「按文件名搜索」是 **placeholder 属性**, 不在 textContent 里
    expect((w.find('.search input').element as HTMLInputElement).placeholder)
      .toContain('按文件名');
    // 这句是**正文**, 一直挂着
    expect(w.text()).toContain('只搜文件名，不搜内容');
  });
});

// ---------- ② 搜出结果 ----------

describe('搜索结果', () => {
  it('输入关键词 → 调搜索接口', async () => {
    const w = await mountLib();
    await typeKeyword(w, '计划');
    expect(h.searchKbDocuments).toHaveBeenCalledTimes(1);
    expect((h.searchKbDocuments.mock.calls[0] as any)[0]).toBe('计划');
  });

  it('结果要显示「在哪个库」—— 跨库搜索不说是哪就找不着东西', async () => {
    h.searchKbDocuments.mockResolvedValue({
      items: [{ ...HIT }], total: 1, keywords: '计划', datasets: 3,
    });
    const w = await mountLib();
    await typeKeyword(w, '计划');
    const text = w.text();
    expect(text).toContain('2026年度计划.docx');
    expect(text).toContain('项目管理');
  });

  it('结果带上上传者', async () => {
    h.searchKbDocuments.mockResolvedValue({
      items: [{ ...HIT }], total: 1, keywords: '计划', datasets: 3,
    });
    const w = await mountLib();
    await typeKeyword(w, '计划');
    expect(w.text()).toContain('zhangsan@twsc.com.cn');
  });

  it('搜不到 → 说清楚「没找到」并提示只搜文件名', async () => {
    const w = await mountLib();
    await typeKeyword(w, '压根没有');
    const text = w.text();
    expect(text).toContain('没找到');
    expect(text).toContain('不搜文档内容');
  });

  it('清空 → 回到初始态, 不用再发请求', async () => {
    const w = await mountLib();
    await typeKeyword(w, '计划');
    expect(h.searchKbDocuments).toHaveBeenCalledTimes(1);
    await w.find('.srch-clear').trigger('click');
    await flushPromises();
    expect(h.searchKbDocuments).toHaveBeenCalledTimes(1);
    expect((w.find('.search input').element as HTMLInputElement).value).toBe('');
  });
});

// ---------- ③ 结果上能接着操作 ----------

describe('搜索结果上的操作', () => {
  beforeEach(() => {
    h.searchKbDocuments.mockResolvedValue({
      items: [{ ...HIT }], total: 1, keywords: '计划', datasets: 3,
    });
  });

  it('tester 能看到更新/重解析', async () => {
    const w = await mountLib();
    await typeKeyword(w, '计划');
    const labels = w.findAll('.srch-tbl tbody tr td:last-child .link-btn').map((b: any) => b.text());
    expect(labels).toContain('分段');
    expect(labels).toContain('下载');
    expect(labels).toContain('更新');
    expect(labels).toContain('重解析');
  });

  it('viewer 只有只读操作', async () => {
    userState.user = { role: 'viewer', username: 'lisi' };
    const w = await mountLib();
    await typeKeyword(w, '计划');
    const labels = w.findAll('.srch-tbl tbody tr td:last-child .link-btn').map((b: any) => b.text());
    expect(labels).toContain('下载');
    expect(labels).not.toContain('更新');
    expect(labels).not.toContain('重解析');
  });

  it('点文档名 → 能打开文档详情', async () => {
    const w = await mountLib();
    await typeKeyword(w, '计划');
    await w.find('.srch-tbl tbody tr .doc-name').trigger('click');
    await flushPromises();
    const drawer = w.findAll('.dt').at(-1)!;
    expect(drawer.text()).toContain('2026年度计划.docx');
  });

  it('⚠️ 点「分段」要带上**所在库**的 id (不是文档 id) —— 否则 404', async () => {
    const w = await mountLib();
    await typeKeyword(w, '计划');
    await w.findAll('.srch-tbl tbody tr td:last-child .link-btn')[0].trigger('click');
    await flushPromises();
    // listDocChunks 被 mock 了, 看它拿到的 datasetId 是不是 ds-9 (库) 而不是 doc-9 (文档)
    const kbMod = await import('@/api/kb');
    expect((kbMod.listDocChunks as any).mock.calls[0][0]).toBe('ds-9');
  });
});

// ---------- ④ 出错 ----------

describe('搜索出错', () => {
  it('失败 → 页面里说清楚, 顺便提示重试', async () => {
    h.searchKbDocuments.mockRejectedValue({
      response: { status: 502, data: { detail: 'ragflow error: 连不上' } },
    });
    const w = await mountLib();
    await typeKeyword(w, '计划');
    expect(w.text()).toContain('搜索失败');
    expect(w.text()).toContain('重试');
  });
});

// ---------- ⑤ 提示文案里不能有字面的 markdown 星号 ----------

describe('⚠️ 纯文本 UI 不渲染 Markdown', () => {
  it('搜索框的 title 里没有 `**` (否则用户看到的是字面星号)', async () => {
    const w = await mountLib();
    const input = w.find('input[placeholder*="文件名"]');
    expect(input.exists()).toBe(true);
    expect(String(input.attributes('title') || '')).not.toContain('**');
  });
});
