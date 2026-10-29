/**
 * 知识库 · 第九轮 (2026-10-30) —— **状态反馈 + 计数时效性** 的回归测试.
 *
 * 这轮修的 (按严重度):
 *   ① 【P0】删库的二次确认对着**过期计数**说话 ——
 *      上传完文档后数据集快照没刷新, `document_count` 还是 0,
 *      确认框就写「这个库目前是空的」, admin 以为只是删个空壳,
 *      结果 3 篇文档连同源文件、分段一起**永久消失** (RAGFlow 硬删, 没有回收站).
 *   ② 【P1】手动刷新文档失败 → 列表被清空成「暂无文档」, 用户以为文档被删了.
 *   ③ 【P1】文档子表展开后没有任何加载提示 —— RAGFlow 慢的时候用户以为"这个库没文档".
 *   ④ 【P1】跨库搜索请求期间挂着**上一个关键词**的结果, 标题却是新关键词.
 *   ⑤ 【P1】删除进行中零反馈, 按钮还能再点 → 弹第二个确认框 → 报「数据集不存在」假错.
 *   ⑥ 【P1】失败时弹**两个**一模一样的错误提示 (全局拦截器 + 页面自己).
 *   ⑦ 【P2】分段抽屉加载失败被伪装成「该文档暂无分段」.
 *   ⑧ 【P2】「删除数据集」和「删除文档」在操作记录里都显示「删除」, 分不清.
 */
import { describe, expect, it, vi, beforeEach } from 'vitest';
import { mount, flushPromises } from '@vue/test-utils';
import Library from '../index.vue';

// ---------- 打桩 (照抄 kbRound7.spec.ts 的写法) ----------

const h = vi.hoisted(() => ({
  listDatasets: vi.fn(async () => ({ items: [] as any[], total: 0 })),
  listDocuments: vi.fn(async () => ({ docs: [] as any[], total: 0 })),
  listKbAudits: vi.fn(async () => ({ items: [] as any[], total: 0 })),
  deleteKbDocuments: vi.fn(async () => ({ ok: true })),
  deleteKbDataset: vi.fn(async () => ({ ok: true, deleted: { name: '协议文档' } })),
  uploadKbDocuments: vi.fn(async () => ({ ok: true, uploaded: 1, ingest_started: true })),
  searchKbDocuments: vi.fn(async () => ({ items: [] as any[], total: 0, keywords: '', datasets: 0 })),
  listDocChunks: vi.fn(async () => ({ chunks: [] as any[], total: 0 })),
  msg: { success: vi.fn(), error: vi.fn(), warning: vi.fn(), info: vi.fn() },
  confirm: vi.fn(async (): Promise<any> => { throw 'cancel'; }),
  prompt: vi.fn(async (): Promise<any> => { throw 'cancel'; }),
}));

const userState = vi.hoisted(() => ({ user: { role: 'admin', username: 'admin' } as any }));

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
  listDocChunks: h.listDocChunks,
  uploadKbDocuments: h.uploadKbDocuments,
  downloadKbDocument: vi.fn(async () => {}),
  listKbAudits: h.listKbAudits,
  createKbDataset: vi.fn(async () => ({ ok: true, dataset: {} })),
  deleteKbDocuments: h.deleteKbDocuments,
  deleteKbDataset: h.deleteKbDataset,
  updateKbDocument: vi.fn(async () => ({ ok: true, updated: {}, ingest_started: true })),
  reparseKbDocument: vi.fn(async () => ({ ok: true, document_id: 'doc-1', name: 'a.pdf' })),
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

const DS_ID = 'ec40ed92837c11f1ab4eefda79d2f959';

/**
 * ⚠️ 数据集快照里的 `document_count: 0` —— 模拟"上传过了但快照没刷新"的过期状态.
 * (这正是 ① 号 bug 的触发条件)
 */
const DS = {
  id: DS_ID, name: '协议文档', description: '', chunk_count: 796,
  document_count: 0, chunk_method: 'manual', embedding_model: 'emb',
  permission: 'me', status: '1', language: 'Chinese', token_num: 1,
  similarity_threshold: 0.2, vector_similarity_weight: 0.7, pagerank: 0.3,
  update_date: '', create_date: '', create_time: 0, update_time: 0, parser_config: {},
  created_by_name: '', created_by: null, created_at: '2026-10-29T04:30:00Z',
};

const DOC = {
  id: 'doc-1', name: '接口规范.pdf', location: '接口规范.pdf', type: 'pdf',
  size: 2048, chunk_count: 12, token_count: 900, chunk_method: 'naive',
  run: 'DONE', progress: 1, progress_msg: '', process_begin_at: null,
  process_duration: 3, source_type: 'local', parser_config: {}, status: '1',
  create_date: '', update_date: '', create_time: 0, update_time: 0,
  uploaded_by_name: 'zhangsan', uploaded_by: 349, uploaded_at: '2026-10-29T04:35:00Z',
};

async function mountLib() {
  const w = mount(Library, { global: { stubs } });
  await flushPromises();
  return w;
}

/** 展开第一个数据集的文档子表 */
async function expand(w: any) {
  await w.find('.exp').trigger('click');
  await flushPromises();
}

beforeEach(() => {
  vi.clearAllMocks();
  userState.user = { role: 'admin', username: 'admin' };
  h.listDatasets.mockResolvedValue({ items: [{ ...DS }], total: 1 });
  h.listDocuments.mockResolvedValue({ docs: [DOC], total: 1 });
  h.listKbAudits.mockResolvedValue({ items: [], total: 0 });
  h.prompt.mockResolvedValue({ value: DS.name } as any);
});

// ---------- ① 【P0】删库确认框不能用过期计数 ----------

describe('删库确认框: 计数必须是真的', () => {
  it('⚠️ 快照写着 0 篇、实际有 3 篇 → 确认框要说 3 篇, **不能**说「目前是空的」', async () => {
    // 快照: document_count = 0 (过期)
    // 真实: 库里有 3 篇
    h.listDocuments.mockResolvedValue({ docs: [DOC], total: 3 });
    const w = await mountLib();
    await expand(w);

    const del = w.findAll('.ds-ops .link-btn').find((b: any) => b.text().includes('删除'))!;
    expect(del, 'admin 看不到删库按钮').toBeTruthy();
    await del.trigger('click');
    await flushPromises();

    expect(h.prompt).toHaveBeenCalled();
    const msg = String((h.prompt.mock.calls[0] as any)[0]);
    // ⚠️ 这条是**不可逆损失**的防线 —— 确认框说 0 篇, admin 就会以为只是删空壳
    expect(msg, '确认框还在说「目前是空的」, 用户会被骗').not.toContain('目前是空的');
    expect(msg, '确认框没说真实篇数').toContain('3 篇');
  });

  it('确实查到了 0 篇 → 可以说「确实是空的」', async () => {
    h.listDocuments.mockResolvedValue({ docs: [], total: 0 });
    const w = await mountLib();
    await expand(w);
    const del = w.findAll('.ds-ops .link-btn').find((b: any) => b.text().includes('删除'))!;
    await del.trigger('click');
    await flushPromises();
    const msg = String((h.prompt.mock.calls[0] as any)[0]);
    expect(msg).toContain('确实是空的');
  });

  it('查不到真实篇数 → 退化成不带数字的措辞 (绝不能瞎报 0)', async () => {
    h.listDocuments.mockRejectedValue(new Error('boom'));
    const w = await mountLib();
    await expand(w);
    const del = w.findAll('.ds-ops .link-btn').find((b: any) => b.text().includes('删除'))!;
    await del.trigger('click');
    await flushPromises();
    const msg = String((h.prompt.mock.calls[0] as any)[0]);
    expect(msg).not.toContain('目前是空的');
    expect(msg).toContain('全部文档');
  });
});

// ---------- ② 上传后要刷新数据集快照 ----------

describe('数据集快照的时效性', () => {
  it('上传成功后 → 数据集列表被重新拉一次 (计数不能停在上传前)', async () => {
    const w = await mountLib();
    const before = h.listDatasets.mock.calls.length;
    await w.findComponent({ name: 'el-drawer' });   // 抽屉在 DOM 里
    // 直接调上传路径: 打开上传抽屉 → 选文件 → 提交
    const vm: any = w.vm;
    vm.uploadFiles = [new File(['x'], 'a.pdf', { type: 'application/pdf' })];
    vm.uploadDsId = DS_ID;
    await vm.doUpload();
    await flushPromises();
    expect(h.listDatasets.mock.calls.length, '上传后没刷新数据集列表').toBeGreaterThan(before);
  });
});

// ---------- ③ 手动刷新失败不该清空列表 ----------

describe('文档加载失败', () => {
  it('刷新失败 → 旧文档**还在**, 并且显示「加载失败」而不是「暂无文档」', async () => {
    const w = await mountLib();
    await expand(w);
    expect(w.text()).toContain('接口规范.pdf');

    // 第二次拉取失败 (模拟刷新时后端挂了)
    h.listDocuments.mockRejectedValueOnce(new Error('502'));
    await w.find('.doc-tools .reload').trigger('click');
    await flushPromises();

    expect(w.text(), '文档被清空了 —— 用户会以为文档没了').toContain('接口规范.pdf');
    expect(w.text()).toContain('加载失败');
    expect(w.text()).not.toContain('暂无文档');
  });
});

// ---------- ④ 文档子表要有加载提示 ----------

describe('文档子表的加载态', () => {
  it('展开时文档还在加载 → 有一行「加载中…」', async () => {
    // ⚠️ 用 `mockImplementation` (持续挂起) 而不是 `Once` ——
    //    组件挂载时就会**预热**所有库的文档列表, `Once` 会被预热那次吃掉.
    h.listDocuments.mockImplementation(() => new Promise(() => {}));
    const w = await mountLib();
    await w.find('.exp').trigger('click');
    await w.vm.$nextTick();
    expect(w.text()).toContain('加载中…');
    // ⚠️ 也不能显示「暂无文档」—— 那会让用户以为这个库没文档
    expect(w.text()).not.toContain('暂无文档');
  });
});

// ---------- ⑤ 跨库搜索不能挂着上一个关键词的结果 ----------

describe('跨库搜索', () => {
  it('请求期间 → 结果被清空, 显示「搜索中…」', async () => {
    const w = await mountLib();
    const vm: any = w.vm;
    vm.docSearchKw = '手册';
    vm.docSearchHits = [{ id: 'old', name: '旧结果.pdf' }];
    vm.docSearchTotal = 1;

    // 让搜索请求一直挂着
    h.searchKbDocuments.mockImplementationOnce(() => new Promise(() => {}));
    vm.onDocSearchInput();
    await new Promise((r) => setTimeout(r, 500));
    await w.vm.$nextTick();

    expect(vm.docSearchHits.length, '旧结果还挂着 —— 用户以为搜错了').toBe(0);
    expect(w.text()).toContain('搜索中…');
  });
});

// ---------- ⑥ 删除进行中要有反馈 ----------

describe('删除进行中', () => {
  it('删库请求在飞 → 按钮置灰 + 文案变成「删除中…」', async () => {
    let release: (v?: any) => void = () => {};
    h.deleteKbDataset.mockImplementationOnce(() => new Promise((res) => { release = res as any; }));
    const w = await mountLib();
    await expand(w);
    const del = w.findAll('.ds-ops .link-btn').find((b: any) => b.text().includes('删除'))!;
    await del.trigger('click');
    await flushPromises();

    const busy = w.findAll('.ds-ops .link-btn').find((b: any) => b.text().includes('删除中'))!;
    expect(busy, '删除中按钮没出现').toBeTruthy();
    expect(busy.attributes('disabled')).toBeDefined();
    release({ ok: true });
    await flushPromises();
  });
});

// ---------- ⑦ 分段抽屉失败要说失败 ----------

describe('分段抽屉', () => {
  it('加载分段失败 → 说「加载分段失败」, 不说「暂无分段」', async () => {
    h.listDocChunks.mockRejectedValueOnce(new Error('502'));
    const w = await mountLib();
    await expand(w);
    const btn = w.findAll('.doc-tbl .link-btn').find((b: any) => b.text().includes('分段'))!;
    await btn.trigger('click');
    await flushPromises();
    expect(w.text()).toContain('加载分段失败');
    expect(w.text()).not.toContain('该文档暂无分段');
  });
});

// ---------- ⑧ 操作记录里分得清删的是库还是文档 ----------

describe('操作记录的动作标签', () => {
  it('delete → 删除数据集; delete_doc → 删除文档', async () => {
    const w = await mountLib();
    const vm: any = w.vm;
    expect(vm.auditActionLabel('delete')).toBe('删除数据集');
    expect(vm.auditActionLabel('delete_doc')).toBe('删除文档');
  });
});
