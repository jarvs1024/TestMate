/**
 * 知识库 · 第六轮 UI 整改 (2026-10-29).
 *
 * 覆盖用户提的 4 个问题:
 *   ① 操作记录**分页** (以前一次拉 50 条, 后面发生的操作根本看不见);
 *   ② 「选择文件」按钮不协调 (浏览器自带的灰色小按钮);
 *   ③ 文档子表里那个重复的「⬆ 上传文档」按钮;
 *   ④ 「↻ 刷新」按钮**无效** (缓存守卫把两个刷新按钮全挡了) +
 *      解析状态不自动刷新.
 *
 * ⚠️ ④ 的根因: `loadDocs` 里以前只有 `if (已缓存) return` —— 点「↻」时
 *    缓存命中 → 直接 return → 什么都没干. 用户看着就是"按钮坏了".
 */
import { describe, expect, it, vi, beforeEach } from 'vitest';
import { mount, flushPromises } from '@vue/test-utils';
import Library from '../index.vue';

// ---------- 打桩 ----------

const h = vi.hoisted(() => ({
  listDatasets: vi.fn(async () => ({ items: [] as any[], total: 0 })),
  listDocuments: vi.fn(async () => ({ docs: [] as any[], total: 0 })),
  listKbAudits: vi.fn(async (_page?: number, _pageSize?: number): Promise<any> => ({
    items: [] as any[], total: 0,
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
  searchKbDocuments: vi.fn(async () => ({ items: [] as any[], total: 0, keywords: '', datasets: 0 })),
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
    created_by_name: 'zhangsan', created_by: 349, created_at: '2026-10-29T04:30:00Z',
  },
];

const DOC = {
  id: 'doc-1', name: '接口规范.pdf', location: '接口规范.pdf', type: 'pdf',
  size: 2048, chunk_count: 12, token_count: 900, chunk_method: 'naive',
  run: 'DONE', progress: 1, progress_msg: '', process_begin_at: null,
  process_duration: 3, source_type: 'local', parser_config: {}, status: '1',
  create_date: '', update_date: '', create_time: 0, update_time: 0,
  uploaded_by_name: 'zhangsan', uploaded_by: 349, uploaded_at: '2026-10-29T04:35:00Z',
};

function auditRow(i: number) {
  return {
    id: 100 - i, dataset_id: 'ds-1', dataset_name: '技术文档',
    document_id: `doc-${i}`, doc_name: `文件${i}.pdf`,
    action: 'upload', actor_name: 'zhangsan', error: '', size: 100,
    created_at: '2026-10-29T04:35:00Z',
  };
}

async function mountLib() {
  const w = mount(Library, { global: { stubs } });
  await flushPromises();
  return w;
}

/** 按标题找卡片 —— 页面里有好几个「↻ 刷新」, 必须按卡片定位, 别按文本找 */
function cardByTitle(w: any, title: string) {
  return w.findAll('.card').find((c: any) => {
    const h2 = c.find('.ds-hd h2');
    return h2.exists() && (h2.text() || '').includes(title);
  });
}

/** 卡片标题行里的「↻ 刷新」按钮 */
function reloadIn(card: any) {
  return card.findAll('.reload').find((b: any) => (b.text() || '').includes('刷新'));
}

beforeEach(() => {
  vi.clearAllMocks();
  userState.user = { role: 'tester', username: 'zhangsan' };
  h.listDatasets.mockResolvedValue({ items: DS.map((d) => ({ ...d })), total: DS.length });
  h.listDocuments.mockResolvedValue({ docs: [], total: 0 });
  h.listKbAudits.mockResolvedValue({ items: [], total: 0 });
});

// ---------- ① 操作记录分页 ----------

describe('操作记录分页', () => {
  it('admin 看不到分页条 —— 记录少的时候别占地方', async () => {
    userState.user = { role: 'admin', username: 'admin' };
    h.listKbAudits.mockResolvedValue({
      items: [auditRow(1)], total: 1, page: 1, page_size: 20, pages: 1,
    });
    const w = await mountLib();
    expect(w.find('.pg-bar').exists()).toBe(false);
  });

  it('多页时显示分页条 + 总条数', async () => {
    userState.user = { role: 'admin', username: 'admin' };
    h.listKbAudits.mockResolvedValue({
      items: [auditRow(1), auditRow(2)], total: 57, page: 1, page_size: 20, pages: 3,
    });
    const w = await mountLib();
    expect(w.find('.pg-bar').exists()).toBe(true);
    expect(w.text()).toContain('共 57 条');
    expect(w.find('.pg-info').text()).toContain('1');
    expect(w.find('.pg-info').text()).toContain('3');
  });

  it('点「下一页」→ 带上正确的页码去请求', async () => {
    userState.user = { role: 'admin', username: 'admin' };
    h.listKbAudits.mockResolvedValue({
      items: [auditRow(1)], total: 57, page: 1, page_size: 20, pages: 3,
    });
    const w = await mountLib();
    const next = w.findAll('.pg-btn').find((b: any) => b.text().includes('下一页'));
    await next!.trigger('click');
    await flushPromises();
    // ⚠️ 后端约定: listKbAudits(page, pageSize)
    const call = h.listKbAudits.mock.calls[h.listKbAudits.mock.calls.length - 1] as any;
    expect(call[0]).toBe(2);
  });

  it('「首页 / 上一页」在第 1 页时是禁用的', async () => {
    userState.user = { role: 'admin', username: 'admin' };
    h.listKbAudits.mockResolvedValue({
      items: [auditRow(1)], total: 57, page: 1, page_size: 20, pages: 3,
    });
    const w = await mountLib();
    const btns = w.findAll('.pg-btn');
    const home = btns.find((b: any) => b.text().includes('首页'))!;
    const prev = btns.find((b: any) => b.text().includes('上一页'))!;
    expect(home.attributes('disabled')).toBeDefined();
    expect(prev.attributes('disabled')).toBeDefined();
  });

  it('⚠️ 改每页条数 → 回到第 1 页重新拉', async () => {
    userState.user = { role: 'admin', username: 'admin' };
    h.listKbAudits.mockResolvedValue({
      items: [auditRow(1)], total: 57, page: 1, page_size: 20, pages: 3,
    });
    const w = await mountLib();
    const sel = w.find('.pg-select');
    await sel.setValue('50');
    await sel.trigger('change');
    await flushPromises();
    const call = h.listKbAudits.mock.calls[h.listKbAudits.mock.calls.length - 1] as any;
    expect(call[0]).toBe(1);
    expect(call[1]).toBe(50);
  });

  it('⚠️ 「↻ 刷新」不能把 MouseEvent 当页码传进去 (页码会变成 NaN)', async () => {
    userState.user = { role: 'admin', username: 'admin' };
    h.listKbAudits.mockResolvedValue({
      items: [auditRow(1)], total: 57, page: 1, page_size: 20, pages: 3,
    });
    const w = await mountLib();
    const card = cardByTitle(w, '操作记录');
    expect(card, '找不到操作记录卡片').toBeTruthy();
    const reload = reloadIn(card!);
    expect(reload, '操作记录卡片里没有刷新按钮').toBeTruthy();
    await reload!.trigger('click');
    await flushPromises();
    const call = h.listKbAudits.mock.calls[h.listKbAudits.mock.calls.length - 1] as any;
    expect(typeof call[0]).toBe('number');
    expect(Number.isNaN(call[0])).toBe(false);
    expect(call[0]).toBe(1);
  });

  it('后端缺 pages 字段时也不能把页码搞成 NaN (老 mock 兼容)', async () => {
    userState.user = { role: 'admin', username: 'admin' };
    // ⚠️ 故意不返回 pages / page
    h.listKbAudits.mockResolvedValue({ items: [auditRow(1)], total: 1 });
    const w = await mountLib();
    expect(w.find('.pg-bar').exists()).toBe(false);
    expect(w.text()).not.toContain('NaN');
  });
});

// ---------- ④ 「↻ 刷新」要真的重新拉 ----------

describe('刷新按钮', () => {
  it('文档子表的「↻」→ 真的重新拉一次文档列表', async () => {
    h.listDocuments.mockResolvedValue({ docs: [DOC], total: 1 });
    const w = await mountLib();
    // 先展开数据集
    const exp = w.find('.exp');
    await exp.trigger('click');
    await flushPromises();
    const before = h.listDocuments.mock.calls.length;
    expect(before).toBeGreaterThan(0);

    // 点子表里的 ↻
    const docReload = w.findAll('.doc-tools .reload').find((b: any) => b.text() === '↻');
    expect(docReload, '找不到文档子表的刷新按钮').toBeTruthy();
    await docReload!.trigger('click');
    await flushPromises();
    // ⚠️ 以前这里被缓存守卫挡了 —— 数字不会变
    expect(h.listDocuments.mock.calls.length).toBeGreaterThan(before);
  });

  it('「数据集」卡片的「↻ 刷新」→ 数据集和文档都重新拉', async () => {
    h.listDocuments.mockResolvedValue({ docs: [DOC], total: 1 });
    const w = await mountLib();
    await w.find('.exp').trigger('click');
    await flushPromises();
    const dsBefore = h.listDatasets.mock.calls.length;
    const docBefore = h.listDocuments.mock.calls.length;

    const card = cardByTitle(w, '数据集');
    expect(card, '找不到数据集卡片').toBeTruthy();
    const reload = reloadIn(card!);
    expect(reload, '数据集卡片里没有刷新按钮').toBeTruthy();
    await reload!.trigger('click');
    await flushPromises();

    expect(h.listDatasets.mock.calls.length).toBeGreaterThan(dsBefore);
    // ⚠️ 文档也要跟着重拉 —— 以前只刷了数据集, 文档还是旧的
    expect(h.listDocuments.mock.calls.length).toBeGreaterThan(docBefore);
  });

  it('⚠️ 有文档在解析中 → 会安排轮询, 状态自己会跟上 (不用手动刷新)', async () => {
    const spy = vi.spyOn(globalThis, 'setTimeout');
    h.listDocuments.mockResolvedValue({ docs: [{ ...DOC, run: 'RUNNING' }], total: 1 });
    const w = await mountLib();
    await w.find('.exp').trigger('click');
    await flushPromises();
    const delays = spy.mock.calls.map((c) => c[1]);
    // ⚠️ 解析是 RAGFlow 后台异步跑的 —— 必须有人定时去问它
    expect(delays).toContain(3000);
    spy.mockRestore();
  });

  it('⚠️ 文档不在解析中 (UNSTART/DONE) → **不轮询**, 别白刷 RAGFlow', async () => {
    // ⚠️ UNSTART 尤其重要 —— 手动分块的数据集永远停在 UNSTART,
    //    算成"在解析"就是无限轮询, 把 RAGFlow 拖死
    const spy = vi.spyOn(globalThis, 'setTimeout');
    h.listDocuments.mockResolvedValue({ docs: [{ ...DOC, run: 'UNSTART' }], total: 1 });
    const w = await mountLib();
    await w.find('.exp').trigger('click');
    await flushPromises();
    const delays = spy.mock.calls.map((c) => c[1]);
    expect(delays).not.toContain(3000);
    spy.mockRestore();
  });
});

// ---------- ③ 重复的「⬆ 上传文档」按钮 ----------

describe('上传入口不重复', () => {
  it('文档子表里**没有**重复的「⬆ 上传文档」按钮', async () => {
    h.listDocuments.mockResolvedValue({ docs: [DOC], total: 1 });
    const w = await mountLib();
    await w.find('.exp').trigger('click');
    await flushPromises();
    const tools = w.find('.doc-tools');
    expect(tools.exists()).toBe(true);
    // ⚠️ 子表工具条里只剩「↻」
    expect(tools.text()).not.toContain('上传');
  });

  it('行内「⬆ 上传」还得在 —— 那是**不重复**的那个入口', async () => {
    const w = await mountLib();
    const ops = w.findAll('.ds-ops .link-btn');
    const up = ops.find((b: any) => b.text().includes('上传'));
    expect(up, '行内上传按钮丢了').toBeTruthy();
  });

  it('页面顶部还有一个全局的「⬆ 上传文档」', async () => {
    const w = await mountLib();
    const tools = w.findAll('.ds-tools button');
    const up = tools.find((b: any) => b.text().includes('上传文档'));
    expect(up, '顶部全局上传入口丢了').toBeTruthy();
  });
});

// ---------- ② 自定义文件选择器 ----------

describe('文件选择器', () => {
  it('原生 file input 是藏起来的 —— 浏览器默认那个灰按钮太丑', async () => {
    const w = await mountLib();
    const inp = w.findAll('input[type="file"]');
    expect(inp.length).toBeGreaterThan(0);
    for (const i of inp) {
      expect(i.classes()).toContain('up-file-hidden');
    }
  });

  it('外面套了自定义按钮 —— 点它转发给 input.click()', async () => {
    const w = await mountLib();
    const btn = w.findAll('.fpick-btn');
    expect(btn.length).toBeGreaterThan(0);

    const input = w.findAll('input[type="file"]')[0].element as HTMLInputElement;
    const spy = vi.spyOn(input, 'click').mockImplementation(() => {});
    await btn[0].trigger('click');
    expect(spy).toHaveBeenCalled();
    spy.mockRestore();
  });

  it('自定义按钮上写清楚限制 —— 别让用户白等上传完才报错', async () => {
    const w = await mountLib();
    const hint = w.find('.fpick-hint').text();
    expect(hint).toContain('20MB');
    expect(hint).toContain('5');
  });
});
