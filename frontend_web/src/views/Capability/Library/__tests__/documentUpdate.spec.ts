/**
 * 知识库 · 更新文档 + 重新解析 (2026-10-29 第四轮).
 *
 * 这轮的需求:
 *   ① 「文档要支持更新」—— 传新文件换掉旧内容;
 *   ② 顺带一个「重新解析」—— 内容不变, 重跑一遍切片/向量化.
 *
 * ⚠️ RAGFlow 的文档是**不可变**的 —— 它没有"替换内容"的接口,
 *    后端是「传新文件 → 删旧文档 → 改回目标名 → 迁移归属 + 重新解析」四步.
 *    所以前端有个硬约束: **更新完文档 id 变了**, 必须重新拉列表,
 *    不然拿着旧 id 继续操作会 404.
 */
import { describe, expect, it, vi, beforeEach } from 'vitest';
import { mount, flushPromises } from '@vue/test-utils';
import Library from '../index.vue';

// ---------- 打桩 ----------

const h = vi.hoisted(() => ({
  listDatasets: vi.fn(async () => ({ items: [] as any[], total: 0 })),
  listDocuments: vi.fn(async () => ({ docs: [] as any[], total: 0 })),
  listKbAudits: vi.fn(async () => ({ items: [] as any[], total: 0 })),
  updateKbDocument: vi.fn(),
  reparseKbDocument: vi.fn(async () => ({ ok: true, document_id: 'doc-1', name: 'a.txt' })),
  msg: { success: vi.fn(), error: vi.fn(), warning: vi.fn(), info: vi.fn() },
  /** 默认 reject = 用户取消 */
  confirm: vi.fn(async (_msg?: string, _title?: string, _opts?: any): Promise<any> => {
    throw 'cancel';
  }),
  prompt: vi.fn(async (): Promise<any> => { throw 'cancel'; }),
}));

const userState = vi.hoisted(() => ({ user: { role: 'tester', username: 'zhangsan' } as any }));

vi.mock('@/stores/user', () => ({ useUserStore: () => userState }));
vi.mock('@/stores/theme', () => ({ useUserStore: () => userState, useThemeStore: () => ({ resolved: 'light' }) }));
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
  updateKbDocument: h.updateKbDocument,
  reparseKbDocument: h.reparseKbDocument,
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

const DOC = {
  id: 'doc-1', name: 'a.txt', location: 'a.txt', type: 'txt', size: 550,
  chunk_count: 3, token_count: 100, chunk_method: 'naive', run: 'DONE', progress: 1,
  progress_msg: '', process_begin_at: null, process_duration: 3, source_type: 'local',
  status: '1', create_date: '', update_date: '', create_time: 0, update_time: 0,
  parser_config: {},
  uploaded_by_name: 'zhangsan@twsc.com.cn', uploaded_by: 349,
  uploaded_at: '2026-10-29T04:35:00Z',
};

async function mountLib() {
  const w = mount(Library, { global: { stubs } });
  await flushPromises();
  return w;
}

/** 展开第一个数据集, 让文档子表露出来. */
async function expandDocs(w: any) {
  await w.findAll('.ds-row .exp')[0].trigger('click');
  await flushPromises();
}

/** 在更新抽屉里选一个文件 */
async function pickFile(w: any, name: string, size = 11) {
  const input = w.find('.up-panel-update .up-input-update');
  const file = new File(['x'.repeat(size)], name, { type: 'text/plain' });
  Object.defineProperty(input.element, 'files', { value: [file], configurable: true });
  await input.trigger('change');
  await flushPromises();
  return file;
}

beforeEach(() => {
  vi.clearAllMocks();
  userState.user = { role: 'tester', username: 'zhangsan' };
  h.listDatasets.mockResolvedValue({ items: DS.map((d) => ({ ...d })), total: DS.length });
  h.listDocuments.mockResolvedValue({ docs: [{ ...DOC }], total: 1 });
  h.confirm.mockImplementation(async () => { throw 'cancel'; });
  h.updateKbDocument.mockResolvedValue({
    ok: true,
    updated: { id: 'doc-2', name: 'a.txt', size: 11 },
    replaced: { id: 'doc-1', name: 'a.txt' },
    ingest_started: true,
    warning: '',
  });
  h.reparseKbDocument.mockResolvedValue({ ok: true, document_id: 'doc-1', name: 'a.txt' });
});

// ---------- ① 权限: tester 及以上 ----------

describe('更新/重解析的权限', () => {
  it('tester 能看到「更新」和「重解析」', async () => {
    const w = await mountLib();
    await expandDocs(w);
    const texts = w.findAll('.doc-tbl tbody tr td:last-child .link-btn').map((b: any) => b.text());
    expect(texts).toContain('更新');
    expect(texts).toContain('重解析');
  });

  it('viewer 看不到「更新」和「重解析」(只读角色)', async () => {
    userState.user = { role: 'viewer', username: 'lisi' };
    const w = await mountLib();
    await expandDocs(w);
    const texts = w.findAll('.doc-tbl tbody tr td:last-child .link-btn').map((b: any) => b.text());
    expect(texts).not.toContain('更新');
    expect(texts).not.toContain('重解析');
    // 但只读操作还在
    expect(texts).toContain('下载');
    expect(texts).toContain('分段');
  });
});

// ---------- ② 更新抽屉 ----------

describe('更新文档', () => {
  it('点「更新」→ 抽屉里要写清楚旧版本会被永久删除', async () => {
    const w = await mountLib();
    await expandDocs(w);
    const btns = w.findAll('.doc-tbl tbody tr td:last-child .link-btn');
    await btns[btns.length - 2].trigger('click'); // 「更新」
    await flushPromises();

    const panel = w.find('.up-panel-update');
    expect(panel.exists()).toBe(true);
    const text = panel.text();
    expect(text).toContain('a.txt');
    // ⚠️ 不可逆性必须写出来
    expect(text).toContain('永久删除');
  });

  it('选文件 → 提交 → 调更新接口', async () => {
    const w = await mountLib();
    await expandDocs(w);
    const btns = w.findAll('.doc-tbl tbody tr td:last-child .link-btn');
    await btns[btns.length - 2].trigger('click');
    await flushPromises();

    const file = await pickFile(w, 'a.txt');
    await w.find('.up-panel-update .primary-btn').trigger('click');
    await flushPromises();

    expect(h.updateKbDocument).toHaveBeenCalledTimes(1);
    const [dsId, docId, sent] = h.updateKbDocument.mock.calls[0] as any[];
    expect(dsId).toBe('ds-1');
    expect(docId).toBe('doc-1');
    expect(sent).toBe(file);
  });

  it('⚠️ 更新完文档 id 变了 → 必须重新拉列表 (不然拿着旧 id 继续操作会 404)', async () => {
    const w = await mountLib();
    await expandDocs(w);
    const before = h.listDocuments.mock.calls.length;

    const btns = w.findAll('.doc-tbl tbody tr td:last-child .link-btn');
    await btns[btns.length - 2].trigger('click');
    await flushPromises();
    await pickFile(w, 'a.txt');
    await w.find('.up-panel-update .primary-btn').trigger('click');
    await flushPromises();

    expect(h.listDocuments.mock.calls.length).toBeGreaterThan(before);
  });

  it('成功 → 弹成功提示', async () => {
    const w = await mountLib();
    await expandDocs(w);
    const btns = w.findAll('.doc-tbl tbody tr td:last-child .link-btn');
    await btns[btns.length - 2].trigger('click');
    await flushPromises();
    await pickFile(w, 'a.txt');
    await w.find('.up-panel-update .primary-btn').trigger('click');
    await flushPromises();

    expect(h.msg.success).toHaveBeenCalled();
    expect(h.msg.error).not.toHaveBeenCalled();
  });

  it('⚠️ 后端带 warning → 弹警告不是成功, 抽屉也别关 (话得让用户看完)', async () => {
    h.updateKbDocument.mockResolvedValue({
      ok: true,
      updated: { id: 'doc-2', name: 'a.txt', size: 11 },
      replaced: { id: 'doc-1', name: 'a.txt' },
      ingest_started: false,
      warning: '这是「手动分块」数据集, 需要管理员手动切分后才能被检索.',
    });
    const w = await mountLib();
    await expandDocs(w);
    const btns = w.findAll('.doc-tbl tbody tr td:last-child .link-btn');
    await btns[btns.length - 2].trigger('click');
    await flushPromises();
    await pickFile(w, 'a.txt');
    await w.find('.up-panel-update .primary-btn').trigger('click');
    await flushPromises();

    expect(h.msg.warning).toHaveBeenCalled();
    expect(h.msg.success).not.toHaveBeenCalled();
    // 抽屉还开着, 而且把 warning 显示出来了
    expect(w.find('.up-panel-update .up-err').text()).toContain('手动分块');
  });

  it('⚠️ 解析没启动 (ingest 失败) → 弹警告不是成功', async () => {
    h.updateKbDocument.mockResolvedValue({
      ok: true,
      updated: { id: 'doc-2', name: 'a.txt', size: 11 },
      replaced: { id: 'doc-1', name: 'a.txt' },
      ingest_started: false,
      warning: '',
    });
    const w = await mountLib();
    await expandDocs(w);
    const btns = w.findAll('.doc-tbl tbody tr td:last-child .link-btn');
    await btns[btns.length - 2].trigger('click');
    await flushPromises();
    await pickFile(w, 'a.txt');
    await w.find('.up-panel-update .primary-btn').trigger('click');
    await flushPromises();

    expect(h.msg.warning).toHaveBeenCalled();
    expect(h.msg.success).not.toHaveBeenCalled();
  });

  it('失败 (比如扩展名不一致) → 显示错误, 别说成功', async () => {
    h.updateKbDocument.mockRejectedValue({
      response: { status: 422, data: { detail: '新文件类型 (.pdf) 跟原文档 (.txt) 不一致' } },
    });
    const w = await mountLib();
    await expandDocs(w);
    const btns = w.findAll('.doc-tbl tbody tr td:last-child .link-btn');
    await btns[btns.length - 2].trigger('click');
    await flushPromises();
    await pickFile(w, 'a.txt');
    await w.find('.up-panel-update .primary-btn').trigger('click');
    await flushPromises();

    expect(h.msg.success).not.toHaveBeenCalled();
    expect(w.find('.up-panel-update .up-err').text()).toContain('不一致');
  });

  it('没选文件 → 提交按钮禁用', async () => {
    const w = await mountLib();
    await expandDocs(w);
    const btns = w.findAll('.doc-tbl tbody tr td:last-child .link-btn');
    await btns[btns.length - 2].trigger('click');
    await flushPromises();

    const btn = w.find('.up-panel-update .primary-btn');
    expect((btn.element as any).disabled).toBe(true);
  });

  it('选的文件超 20MB → 直接拦下, 不发请求', async () => {
    const w = await mountLib();
    await expandDocs(w);
    const btns = w.findAll('.doc-tbl tbody tr td:last-child .link-btn');
    await btns[btns.length - 2].trigger('click');
    await flushPromises();

    await pickFile(w, 'big.txt', 21 * 1024 * 1024);
    expect(w.find('.up-panel-update .up-err').text()).toContain('超过单文件上限');
    expect(h.updateKbDocument).not.toHaveBeenCalled();
  });
});

// ---------- ③ 重新解析 ----------

describe('重新解析', () => {
  it('点「重解析」→ 先确认, 确认后才真调', async () => {
    h.confirm.mockResolvedValueOnce({ value: true } as any);
    const w = await mountLib();
    await expandDocs(w);
    const btns = w.findAll('.doc-tbl tbody tr td:last-child .link-btn');
    await btns[btns.length - 1].trigger('click'); // 「重解析」
    await flushPromises();

    expect(h.confirm).toHaveBeenCalledTimes(1);
    // ⚠️ 确认框里要说清楚会清掉多少分段
    expect((h.confirm.mock.calls[0] as any)[0]).toContain('3');
    // ⚠️ { silent: true } —— 页面自己弹错误, 全局拦截器别重复弹
    expect(h.reparseKbDocument).toHaveBeenCalledWith('ds-1', 'doc-1', { silent: true });
  });

  it('取消 → 不调接口, 也不报错', async () => {
    const w = await mountLib();
    await expandDocs(w);
    const btns = w.findAll('.doc-tbl tbody tr td:last-child .link-btn');
    await btns[btns.length - 1].trigger('click');
    await flushPromises();

    expect(h.reparseKbDocument).not.toHaveBeenCalled();
    expect(h.msg.error).not.toHaveBeenCalled();
  });

  it('失败 → 弹错误', async () => {
    h.confirm.mockResolvedValueOnce({ value: true } as any);
    h.reparseKbDocument.mockRejectedValue({
      response: { status: 502, data: { detail: 'ragflow error: 连不上' } },
    });
    const w = await mountLib();
    await expandDocs(w);
    const btns = w.findAll('.doc-tbl tbody tr td:last-child .link-btn');
    await btns[btns.length - 1].trigger('click');
    await flushPromises();

    expect(h.msg.error).toHaveBeenCalled();
    expect(h.msg.success).not.toHaveBeenCalled();
  });
});
