/**
 * 知识库 · 第七轮 (2026-10-29).
 *
 * 用户提的:
 *   ① 数据集列表: 去掉名字后面的 id 哈希 / 折叠不明显 / 点名字也能展开;
 *   ② 文档在 admin 下支持删除; 新建数据集的切片默认通用,
 *      还能选 language、parser_id (默认 general);
 *   ③ 「数据集」卡片挪到「知识检索」卡片前面.
 *
 * ⚠️ **parser_id 在这版 RAGFlow 上不能直接传** —— 对外字段是 `chunk_method`,
 *    合法值里也**没有** `general` (通用 = `naive`). 详见
 *    `backend_gateway/app/core/ragflow_client.py` 的注释.
 */
import { describe, expect, it, vi, beforeEach } from 'vitest';
import { mount, flushPromises } from '@vue/test-utils';
import Library from '../index.vue';

// ---------- 打桩 ----------

const h = vi.hoisted(() => ({
  listDatasets: vi.fn(async () => ({ items: [] as any[], total: 0 })),
  listDocuments: vi.fn(async () => ({ docs: [] as any[], total: 0 })),
  listKbAudits: vi.fn(async () => ({ items: [] as any[], total: 0 })),
  createKbDataset: vi.fn(async (): Promise<any> => ({
    ok: true,
    dataset: {
      id: 'ds-new', name: '新建的库', description: '', chunk_method: 'naive',
      embedding_model: 'emb', permission: 'me', document_count: 0, chunk_count: 0,
      language: 'Chinese',
    },
  })),
  deleteKbDocuments: vi.fn(async () => ({ ok: true })),
  deleteKbDataset: vi.fn(),
  msg: { success: vi.fn(), error: vi.fn(), warning: vi.fn(), info: vi.fn() },
  // ⚠️ 返回类型必须放宽成 any —— 默认的 `async () => { throw }` 推成 Promise<never>,
  //    后面 mockResolvedValue(确认框的值) 就编译不过
  confirm: vi.fn(async (): Promise<any> => { throw 'cancel'; }),
  prompt: vi.fn(async (): Promise<any> => { throw 'cancel'; }),
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
  uploadKbDocuments: vi.fn(async () => ({ ok: true, uploaded: 1, ingest_started: true, docs: [] })),
  downloadKbDocument: vi.fn(async () => {}),
  listKbAudits: h.listKbAudits,
  createKbDataset: h.createKbDataset,
  deleteKbDocuments: h.deleteKbDocuments,
  deleteKbDataset: h.deleteKbDataset,
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
    id: 'ec40ed92837c11f1ab4eefda79d2f959', name: '协议文档', description: '',
    chunk_count: 796, document_count: 5, chunk_method: 'manual', embedding_model: 'emb',
    permission: 'me', status: '1', language: 'Chinese', token_num: 1,
    similarity_threshold: 0.2, vector_similarity_weight: 0.7, pagerank: 0.3,
    update_date: '', create_date: '', create_time: 0, update_time: 0, parser_config: {},
    created_by_name: '', created_by: null, created_at: '2026-10-29T04:30:00Z',
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

async function mountLib() {
  const w = mount(Library, { global: { stubs } });
  await flushPromises();
  return w;
}

beforeEach(() => {
  vi.clearAllMocks();
  userState.user = { role: 'tester', username: 'zhangsan' };
  h.listDatasets.mockResolvedValue({ items: DS.map((d) => ({ ...d })), total: DS.length });
  h.listDocuments.mockResolvedValue({ docs: [DOC], total: 1 });
  h.listKbAudits.mockResolvedValue({ items: [], total: 0 });
  h.createKbDataset.mockResolvedValue({
    ok: true,
    dataset: {
      id: 'ds-new', name: '新建的库', description: '', chunk_method: 'naive',
      embedding_model: 'emb', permission: 'me', document_count: 0, chunk_count: 0,
      language: 'Chinese',
    },
  } as any);
});

// ---------- ① 数据集列表 ----------

describe('数据集列表', () => {
  it('⚠️ 名字后面**不再显示 id 哈希** —— 对用户没意义, 还占地方', async () => {
    const w = await mountLib();
    const row = w.find('.ds-row');
    expect(row.exists()).toBe(true);
    // 以前这里渲染的是 `ec40ed92…`
    expect(row.text()).not.toContain('ec40ed92');
    expect(row.find('.ds-id').exists()).toBe(false);
  });

  it('折叠按钮要**看得见能展开** —— 得有「展开/收起」的字', async () => {
    const w = await mountLib();
    const exp = w.find('.exp');
    expect(exp.exists()).toBe(true);
    expect(exp.text()).toContain('展开');
    expect(exp.classes()).toContain('exp');
  });

  it('⚠️ 点**名字**也能展开 —— 用户看到名字就想点', async () => {
    const w = await mountLib();
    const name = w.find('.ds-name');
    expect(name.exists(), '数据集名字应该可点').toBe(true);
    expect(w.find('.doc-panel').exists(), '一开始是收起的').toBe(false);
    await name.trigger('click');
    await flushPromises();
    // 展开了 → 文档子表出现
    expect(w.find('.doc-panel').exists(), '点名字应该能展开').toBe(true);
    // 按钮文案跟着变成「收起」
    expect(w.find('.exp').text()).toContain('收起');
  });
});

// ---------- ② 文档删除 (admin only) ----------

describe('删除文档', () => {
  async function expand(w: any) {
    await w.find('.exp').trigger('click');
    await flushPromises();
  }

  it('admin 能看到「🗑 删除」', async () => {
    userState.user = { role: 'admin', username: 'admin' };
    const w = await mountLib();
    await expand(w);
    const del = w.findAll('.doc-tbl tbody tr .link-btn')
      .find((b: any) => b.text().includes('删除'));
    expect(del, 'admin 看不到删除按钮').toBeTruthy();
  });

  it('⚠️ tester / viewer **看不到**删除按钮 (硬删只给 admin)', async () => {
    const w = await mountLib();
    await expand(w);
    const del = w.findAll('.doc-tbl tbody tr .link-btn')
      .find((b: any) => b.text().includes('删除'));
    expect(del, 'tester 不该看到删除按钮').toBeFalsy();
  });

  it('⚠️ 删除要**输入文档名**二次确认 —— 跟删数据集一个口径', async () => {
    userState.user = { role: 'admin', username: 'admin' };
    h.prompt.mockResolvedValue({ value: '接口规范.pdf' } as any);
    const w = await mountLib();
    await expand(w);
    const del = w.findAll('.doc-tbl tbody tr .link-btn')
      .find((b: any) => b.text().includes('删除'))!;
    await del.trigger('click');
    await flushPromises();
    expect(h.prompt).toHaveBeenCalled();
    // 确认框里得写清楚"永久删除"
    const msg = String((h.prompt.mock.calls[0] as any)[0]);
    expect(msg).toContain('接口规范.pdf');
    expect(msg).toContain('永久删除');
    // ⚠️ 第三个参数 deleteAll=false, 第四个是 { silent: true } ——
    //    silent 是 2026-10-29 加的: 页面自己会弹错误提示, 全局拦截器就别再弹一遍
    //    (一次失败弹两个一模一样的红条, 用户分不清哪个是哪个).
    expect(h.deleteKbDocuments).toHaveBeenCalledWith(
      'ec40ed92837c11f1ab4eefda79d2f959', ['doc-1'], false, { silent: true });
  });

  it('取消 → 不调删除接口', async () => {
    userState.user = { role: 'admin', username: 'admin' };
    h.prompt.mockRejectedValue('cancel');
    const w = await mountLib();
    await expand(w);
    const del = w.findAll('.doc-tbl tbody tr .link-btn')
      .find((b: any) => b.text().includes('删除'))!;
    await del.trigger('click');
    await flushPromises();
    expect(h.deleteKbDocuments).not.toHaveBeenCalled();
  });
});

// ---------- ③ 新建数据集: 解析方式 + 语言 ----------

describe('新建数据集的解析方式与语言', () => {
  async function openCreate(w: any) {
    const btn = w.findAll('.ds-tools button').find((b: any) => b.text().includes('新建数据集'));
    await btn!.trigger('click');
    await flushPromises();
    return w.find('.cd-panel');
  }

  it('默认就是「通用」(naive) —— 不是 general', async () => {
    const w = await mountLib();
    const panel = await openCreate(w);
    const naive = panel.findAll('input[type="radio"]').find((r: any) => r.element.value === 'naive');
    expect((naive!.element as HTMLInputElement).checked).toBe(true);
  });

  it('有「更多解析方式」下拉, 里面是 RAGFlow 的**内部名**', async () => {
    const w = await mountLib();
    const panel = await openCreate(w);
    const sel = panel.find('.cd-select2');
    expect(sel.exists(), '没有「更多解析方式」下拉').toBe(true);
    const values = sel.findAll('option').map((o: any) => o.element.value);
    expect(values).toContain('qa');
    expect(values).toContain('table');
    // ⚠️ 'general' 在这版 RAGFlow 上**不合法** —— 不能出现在选项里
    expect(values).not.toContain('general');
  });

  it('⚠️ 选了「更多解析方式」→ 传给后端的是那个值', async () => {
    const w = await mountLib();
    const panel = await openCreate(w);
    await panel.find('input.cd-input').setValue('问答库');
    const sel = panel.find('.cd-select2');
    await sel.setValue('qa');
    await sel.trigger('change');
    await flushPromises();
    const submit = panel.findAll('.up-foot button').find((b: any) => b.text().includes('创建'));
    await submit.trigger('click');
    await flushPromises();
    expect(h.createKbDataset).toHaveBeenCalledWith('问答库', '', 'qa', 'Chinese');
  });

  it('⚠️ 语言默认中文, 能改成英文', async () => {
    const w = await mountLib();
    const panel = await openCreate(w);
    await panel.find('input.cd-input').setValue('英文库');
    const en = panel.findAll('input[type="radio"]').find((r: any) => r.element.value === 'English');
    await en!.setValue();
    await flushPromises();
    const submit = panel.findAll('.up-foot button').find((b: any) => b.text().includes('创建'));
    await submit.trigger('click');
    await flushPromises();
    expect(h.createKbDataset).toHaveBeenCalledWith('英文库', '', 'naive', 'English');
  });

  it('⚠️ 后端回 warning (比如语言没设上) → 如实告诉用户', async () => {    h.createKbDataset.mockResolvedValue({
      ok: true,
      dataset: {
        id: 'ds-new', name: '新建的库', description: '', chunk_method: 'naive',
        embedding_model: 'emb', permission: 'me', document_count: 0, chunk_count: 0,
        language: 'Chinese',
      },
      warning: '语言没能设成「Chinese」',
    } as any);
    const w = await mountLib();
    const panel = await openCreate(w);
    await panel.find('input.cd-input').setValue('半成品库');
    const submit = panel.findAll('.up-foot button').find((b: any) => b.text().includes('创建'));
    await submit.trigger('click');
    await flushPromises();
    expect(h.msg.warning).toHaveBeenCalled();
    expect(String((h.msg.warning.mock.calls[0] as any)[0])).toContain('语言没能设成');
  });

  // ---------- ⑤ 文案: 别让用户懵 (2026-10-29 第七轮补) ----------

  it('⚠️ 语言的说明要说「按实际要存的文档内容选」—— 别写「默认…」', async () => {
    const w = await mountLib();
    const panel = await openCreate(w);
    const lang = panel.findAll('.cd-field').find((f: any) => f.text().includes('文档语言'))!;
    const text = lang.text();
    expect(text).toContain('中文');
    expect(text).toContain('英文');
    // ⚠️ 说明里**不该**出现「默认」两个字 —— 用户要的是"按内容选", 不是"默认就完事"
    expect(text).not.toContain('默认');
    // ⚠️ 也不该再提 RAGFlow 的内部默认值 (那是实现细节, 用户不关心)
    expect(text).not.toContain('RAGFlow');
  });

  it('⚠️ 解析方式要引导用户「不确定就用通用」', async () => {
    const w = await mountLib();
    const panel = await openCreate(w);
    expect(panel.text()).toContain('不确定就用');
    expect(panel.text()).toContain('通用');
  });
});

// ---------- ④ 卡片顺序 ----------

describe('卡片顺序', () => {
  it('⚠️ 「数据集」卡片在「知识检索」卡片**前面**', async () => {
    const w = await mountLib();
    const cards = w.findAll('.card');
    const idxDs = cards.findIndex((c: any) => {
      const h2 = c.find('.ds-hd h2');
      return h2.exists() && (h2.text() || '').includes('数据集');
    });
    const idxSearch = cards.findIndex((c: any) => c.classes().includes('card-share'));
    expect(idxDs).toBeGreaterThanOrEqual(0);
    expect(idxSearch).toBeGreaterThanOrEqual(0);
    expect(idxDs, '「数据集」应该在「知识检索」前面').toBeLessThan(idxSearch);
  });
});
