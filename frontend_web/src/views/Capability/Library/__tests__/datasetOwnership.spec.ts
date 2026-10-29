/**
 * 知识库 · 归属展示 + 删除数据集 (2026-10-29 第三轮).
 *
 * 这轮的需求:
 *   ① 「删除只给 admin」 —— 而且删除是**硬删**, 所以要**输入库名**才能删;
 *   ② 「数据集谁建的、文档谁上传的」—— 在**详情**里能看到.
 *
 * ⚠️ 删数据集的不可逆性: RAGFlow 是逐个文档走 `remove_document`, 连同
 *    MinIO 里的源文件、ES 里的分段一起没了, **没有回收站**.
 *    所以前端光给一个「确定」按钮是不够的 —— 必须让用户把库名敲出来.
 */
import { describe, expect, it, vi, beforeEach } from 'vitest';
import { mount, flushPromises } from '@vue/test-utils';
import Library from '../index.vue';

// ---------- 打桩 ----------

const h = vi.hoisted(() => ({
  listDatasets: vi.fn(async () => ({ items: [] as any[], total: 0 })),
  listDocuments: vi.fn(async () => ({ docs: [] as any[], total: 0 })),
  listKbAudits: vi.fn(async () => ({ items: [] as any[], total: 0 })),
  createKbDataset: vi.fn(),
  deleteKbDataset: vi.fn(async () => ({
    ok: true,
    deleted: { dataset_id: 'ds-2', name: '项目管理', documents: 0, chunks: 0 },
  })),
  uploadKbDocuments: vi.fn(),
  msg: { success: vi.fn(), error: vi.fn(), warning: vi.fn(), info: vi.fn() },
  /** 默认 reject = 用户取消 / 校验没过 */
  prompt: vi.fn(async (_msg?: string, _title?: string, _opts?: any): Promise<any> => {
    throw 'cancel';
  }),
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
  uploadKbDocuments: h.uploadKbDocuments,
  downloadKbDocument: vi.fn(async () => {}),
  listKbAudits: h.listKbAudits,
  createKbDataset: h.createKbDataset,
  deleteKbDataset: h.deleteKbDataset,
}));
vi.mock('element-plus', () => ({
  ElMessage: h.msg,
  ElMessageBox: { prompt: h.prompt },
}));

const stubs = {
  'el-drawer': { template: '<div class="el-drawer"><slot/></div>' },
  'el-select': { props: ['modelValue'], template: '<select class="el-select"><slot/></select>' },
  'el-option': { props: ['label', 'value'], template: '<option>{{ label }}</option>' },
};

const DS = [
  {
    id: 'ds-1', name: '协议文档', description: '', chunk_count: 796, document_count: 5,
    chunk_method: 'manual', embedding_model: 'emb', permission: 'me', status: '1',
    language: 'Chinese', token_num: 1, similarity_threshold: 0.2,
    vector_similarity_weight: 0.7, pagerank: 0.3, update_date: '', create_date: '',
    create_time: 0, update_time: 0, parser_config: {},
    // ⚠️ 建库功能上线前手工建的 → 没有归属
    created_by_name: '', created_at: '',
  },
  {
    id: 'ds-2', name: '项目管理', description: '项目文档', chunk_count: 0, document_count: 0,
    chunk_method: 'naive', embedding_model: 'emb', permission: 'me', status: '1',
    language: 'Chinese', token_num: 0, similarity_threshold: 0.2,
    vector_similarity_weight: 0.7, pagerank: 0.3, update_date: '', create_date: '',
    create_time: 0, update_time: 0, parser_config: {},
    // ⚠️ 新建的库 → 有归属
    created_by_name: 'zhangsan@twsc.com.cn', created_by: 349,
    created_at: '2026-10-29T04:30:00Z',
  },
];

const DOC = {
  id: 'doc-1', name: '验收说明.txt', location: '验收说明.txt', type: 'txt', size: 550,
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

beforeEach(() => {
  vi.clearAllMocks();
  userState.user = { role: 'tester', username: 'zhangsan' };
  h.listDatasets.mockResolvedValue({ items: DS.map((d) => ({ ...d })), total: DS.length });
  h.listDocuments.mockResolvedValue({ docs: [{ ...DOC }], total: 1 });
  h.prompt.mockImplementation(async () => { throw 'cancel'; });
  h.deleteKbDataset.mockResolvedValue({
    ok: true,
    deleted: { dataset_id: 'ds-2', name: '项目管理', documents: 0, chunks: 0 },
  });
});

// ---------- ① 删除只给 admin ----------

describe('删除数据集的权限', () => {
  it('tester 看不到删除按钮', async () => {
    const w = await mountLib();
    expect(w.find('.ds-ops .link-btn.danger').exists()).toBe(false);
  });

  it('viewer 看不到删除按钮', async () => {
    userState.user = { role: 'viewer', username: 'lisi' };
    const w = await mountLib();
    expect(w.find('.ds-ops .link-btn.danger').exists()).toBe(false);
  });

  it('admin 能看到删除按钮', async () => {
    userState.user = { role: 'admin', username: 'admin' };
    const w = await mountLib();
    const btns = w.findAll('.ds-ops .link-btn.danger');
    expect(btns).toHaveLength(DS.length);
    expect(btns[0].text()).toContain('删除');
  });
});

// ---------- ② 必须输入库名才能删 ----------

describe('删除数据集的二次确认', () => {
  it('admin 点删除 → 弹框要输入库名', async () => {
    userState.user = { role: 'admin', username: 'admin' };
    const w = await mountLib();
    await w.findAll('.ds-ops .link-btn.danger')[1].trigger('click');
    await flushPromises();

    expect(h.prompt).toHaveBeenCalledTimes(1);
    const [msg, title, opts] = h.prompt.mock.calls[0] as any[];
    expect(title).toContain('删除');
    // ⚠️ 提示里要说清楚会删掉多少内容 —— 用户得知道自己在删什么
    expect(msg).toContain('项目管理');
    expect(opts.inputPlaceholder).toBe('项目管理');
    // 没通过确认 → 不该真删
    expect(h.deleteKbDataset).not.toHaveBeenCalled();
  });

  it('校验器: 库名对得上才放行', async () => {
    userState.user = { role: 'admin', username: 'admin' };
    const w = await mountLib();
    await w.findAll('.ds-ops .link-btn.danger')[1].trigger('click');
    await flushPromises();

    const opts = (h.prompt.mock.calls[0] as any)[2];
    expect(opts.inputValidator('项目管理')).toBe(true);
    // ⚠️ 对不上要**返回一句提示**(Element Plus 会把它显示在输入框下面)
    expect(typeof opts.inputValidator('别的库')).toBe('string');
    expect(typeof opts.inputValidator('')).toBe('string');
  });

  it('输入对了 → 真删', async () => {
    userState.user = { role: 'admin', username: 'admin' };
    h.prompt.mockResolvedValueOnce({ value: '项目管理' } as any);
    const w = await mountLib();
    await w.findAll('.ds-ops .link-btn.danger')[1].trigger('click');
    await flushPromises();

    expect(h.deleteKbDataset).toHaveBeenCalledWith('ds-2');
    expect(h.msg.success).toHaveBeenCalled();
  });

  it('取消 → 不删, 也不报错', async () => {
    userState.user = { role: 'admin', username: 'admin' };
    const w = await mountLib();
    await w.findAll('.ds-ops .link-btn.danger')[1].trigger('click');
    await flushPromises();

    expect(h.deleteKbDataset).not.toHaveBeenCalled();
    expect(h.msg.error).not.toHaveBeenCalled();
  });

  it('删失败 → 弹错误, 别说成功', async () => {
    userState.user = { role: 'admin', username: 'admin' };
    h.prompt.mockResolvedValueOnce({ value: '项目管理' } as any);
    h.deleteKbDataset.mockRejectedValueOnce({
      response: { status: 502, data: { detail: 'ragflow error: 连不上' } },
    });
    const w = await mountLib();
    await w.findAll('.ds-ops .link-btn.danger')[1].trigger('click');
    await flushPromises();

    expect(h.msg.error).toHaveBeenCalled();
    expect(h.msg.success).not.toHaveBeenCalled();
  });
});

// ---------- ④ 操作记录收紧到 admin only ----------

describe('操作记录的可见范围', () => {
  /** 页面上的「操作记录」卡片在不在 */
  function hasAuditCard(w: any): boolean {
    return w.findAll('.card').some((c: any) => {
      const h2 = c.find('.ds-hd h2');
      return h2.exists() && (h2.text() || '').includes('操作记录');
    });
  }

  it('viewer 看不到「操作记录」卡片', async () => {
    userState.user = { role: 'viewer', username: 'lisi' };
    const w = await mountLib();
    expect(hasAuditCard(w)).toBe(false);
  });

  it('tester 也看不到「操作记录」卡片 —— 能上传 ≠ 能看治理信息', async () => {
    const w = await mountLib();
    expect(hasAuditCard(w)).toBe(false);
  });

  it('非 admin 连请求都不该发 (后端会 403, 还会弹没意义的错误)', async () => {
    await mountLib();
    expect(h.listKbAudits).not.toHaveBeenCalled();
  });

  it('admin 能看到「操作记录」卡片', async () => {
    userState.user = { role: 'admin', username: 'admin' };
    const w = await mountLib();
    expect(hasAuditCard(w)).toBe(true);
    expect(h.listKbAudits).toHaveBeenCalled();
  });
});

// ---------- ③ 归属: 详情里能看到谁建的 / 谁传的 ----------

describe('归属展示', () => {
  it('数据集详情里显示创建者', async () => {
    const w = await mountLib();
    // 点第二个库(项目管理)的「详情」
    await w.findAll('.ds-ops .ghost-btn')[1].trigger('click');
    await flushPromises();

    const drawer = w.findAll('.dt').at(-1)!;
    const text = drawer.text();
    expect(text).toContain('创建者');
    expect(text).toContain('zhangsan@twsc.com.cn');
  });

  it('没有归属记录的历史库 → 显示「—」, 不瞎猜', async () => {
    const w = await mountLib();
    await w.findAll('.ds-ops .ghost-btn')[0].trigger('click');
    await flushPromises();

    const drawer = w.findAll('.dt').at(-1)!;
    // ⚠️ 「协议文档」是建库功能上线前手工建的 → 没有归属
    expect(drawer.text()).toContain('创建者');
    expect(drawer.text()).not.toContain('zhangsan@twsc.com.cn');
  });

  it('文档详情里显示上传者', async () => {
    const w = await mountLib();
    // 展开第一个数据集 → 点文档名 → 打开文档详情
    await w.findAll('.ds-row .exp')[0].trigger('click');
    await flushPromises();
    await w.find('.doc-name').trigger('click');
    await flushPromises();

    const drawer = w.findAll('.dt').at(-1)!;
    const text = drawer.text();
    expect(text).toContain('上传者');
    expect(text).toContain('zhangsan@twsc.com.cn');
  });
});
