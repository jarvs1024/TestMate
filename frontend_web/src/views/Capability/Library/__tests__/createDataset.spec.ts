/**
 * 知识库 · 新建数据集 + 入口排版 (2026-10-29).
 *
 * 这轮的需求是「建库和上传要放在显眼位置, 方便用户用」, 所以锁三件事:
 *   ① **入口在哪儿** —— 标题行右侧的工具条 + 每个数据集那一行;
 *   ② **谁能看见** —— tester 及以上能建能传, viewer 是只读角色, 按钮不该出现;
 *   ③ **建库流程本身** —— 重名要拦住 (RAGFlow 会自动加 `(1)` 后缀, 用户会懵),
 *      参数要原样传给后端, 选的文件要顺手传进去.
 */
import { describe, expect, it, vi, beforeEach } from 'vitest';
import { mount, flushPromises } from '@vue/test-utils';
import Library from '../index.vue';

// ---------- 打桩 ----------

const h = vi.hoisted(() => ({
  listDatasets: vi.fn(async () => ({ items: [] as any[], total: 0 })),
  listDocuments: vi.fn(async () => ({ docs: [] as any[], total: 0 })),
  listKbAudits: vi.fn(async () => ({ items: [] as any[], total: 0 })),
  createKbDataset: vi.fn(async (_n: string, _d: string, _p: string) => ({
    ok: true,
    dataset: {
      id: 'ds-new', name: '新建的库', description: '', chunk_method: 'general',
      embedding_model: 'emb', permission: 'me', document_count: 0, chunk_count: 0,
    },
  })),
  uploadKbDocuments: vi.fn(async () => ({
    ok: true, uploaded: 1, ingest_started: true, docs: [],
  })),
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
  uploadKbDocuments: h.uploadKbDocuments,
  downloadKbDocument: vi.fn(async () => {}),
  listKbAudits: h.listKbAudits,
  createKbDataset: h.createKbDataset,
}));
vi.mock('element-plus', () => ({ ElMessage: h.msg }));

const stubs = {
  'el-drawer': { template: '<div class="el-drawer"><slot/></div>' },
  'el-select': { props: ['modelValue'], template: '<select class="el-select"><slot/></select>' },
  'el-option': { props: ['label', 'value'], template: '<option>{{ label }}</option>' },
};

const DS = [
  { id: 'ds-1', name: '协议文档', description: '协议规范', chunk_count: 796, document_count: 5, chunk_method: 'manual', embedding_model: 'emb', permission: 'me', status: '1', language: 'Chinese', token_num: 1, similarity_threshold: 0.2, vector_similarity_weight: 0.7, pagerank: 0.3, update_date: '', create_date: '', create_time: 0, update_time: 0, parser_config: {} },
  { id: 'ds-2', name: '项目管理', description: '', chunk_count: 0, document_count: 0, chunk_method: 'general', embedding_model: 'emb', permission: 'me', status: '1', language: 'Chinese', token_num: 0, similarity_threshold: 0.2, vector_similarity_weight: 0.7, pagerank: 0.3, update_date: '', create_date: '', create_time: 0, update_time: 0, parser_config: {} },
];

async function mountLib() {
  const w = mount(Library, {
    global: { stubs },
  });
  await flushPromises();
  return w;
}

/** 打开「新建数据集」抽屉 */
async function openCreate(w: any) {
  const btn = w.findAll('.ds-tools button').find((b: any) => b.text().includes('新建数据集'));
  expect(btn, '标题行应该有「新建数据集」按钮').toBeTruthy();
  await btn.trigger('click');
  await flushPromises();
  return w.find('.cd-panel');
}

beforeEach(() => {
  vi.clearAllMocks();
  userState.user = { role: 'tester', username: 'zhangsan' };
  h.listDatasets.mockResolvedValue({ items: DS.map((d) => ({ ...d })), total: DS.length });
  h.createKbDataset.mockImplementation(async (n: string, d: string, p: string) => ({
    ok: true,
    dataset: {
      id: 'ds-new', name: n, description: d, chunk_method: p,
      embedding_model: 'emb', permission: 'me', document_count: 0, chunk_count: 0,
    },
  }));
});

// ---------- ① 入口在哪儿 ----------

describe('入口排版', () => {
  it('标题行右侧有「新建数据集」和「上传文档」两个显眼按钮', async () => {
    const w = await mountLib();
    const texts = w.findAll('.ds-tools button').map((b: any) => b.text());
    expect(texts.join('|')).toContain('新建数据集');
    expect(texts.join('|')).toContain('上传文档');
    // 「刷新」也得还在 —— 搬了按钮别把原有的弄丢
    expect(texts.join('|')).toContain('刷新');
  });

  it('「新建数据集」是主按钮 —— 视觉上要压得住「上传文档」', async () => {
    const w = await mountLib();
    const newBtn = w.findAll('.ds-tools button').find((b: any) => b.text().includes('新建数据集'));
    const upBtn = w.findAll('.ds-tools button').find((b: any) => b.text().includes('上传文档'));
    expect(newBtn!.classes()).toContain('primary-btn');
    expect(upBtn!.classes()).not.toContain('primary-btn');
  });

  it('每个数据集那一行都有行内上传入口 —— 不用展开子表就能传', async () => {
    const w = await mountLib();
    const rows = w.findAll('.ds-row');
    expect(rows).toHaveLength(2);
    for (const r of rows) {
      const up = r.find('.ds-ops .link-btn');
      expect(up.exists(), '行内要有上传按钮').toBe(true);
      expect(up.text()).toContain('上传');
    }
  });
});

// ---------- ② 谁能看见 ----------

describe('权限可见性', () => {
  it('viewer 是只读角色 —— 建库/上传入口一律不出现', async () => {
    userState.user = { role: 'viewer', username: 'lisi' };
    const w = await mountLib();
    expect(w.findAll('.ds-tools .ds-act')).toHaveLength(0);
    expect(w.find('.ds-ops .link-btn').exists()).toBe(false);
  });

  it('tester 能看见建库入口 (viewer 看不到)', async () => {
    const w = await mountLib();
    expect(w.findAll('.ds-tools .ds-act').length).toBeGreaterThan(0);
  });
});

// ---------- ③ 建库流程 ----------

describe('新建数据集', () => {
  it('重名要拦住 —— RAGFlow 会自动加 `(1)` 后缀, 用户会以为建了个新库', async () => {
    const w = await mountLib();
    const panel = await openCreate(w);
    await panel.find('input.cd-input').setValue('项目管理');
    await flushPromises();

    expect(panel.text()).toContain('已经有一个叫');
    // 提交按钮得是禁用的
    // ⚠️ Vue 把 :disabled="true" 渲染成 `disabled=""` —— 属性**存在但值是空串**,
    //    所以不能判 truthiness, 得判"属性在不在"
    const submit = panel.findAll('.up-foot button').find((b: any) => b.text().includes('创建'));
    expect(submit!.attributes('disabled')).toBeDefined();
    // 而且压根不该发请求
    expect(h.createKbDataset).not.toHaveBeenCalled();
  });

  it('重名判定大小写不敏感 —— RAGFlow 的名字就是大小写不敏感的', async () => {
    const w = await mountLib();
    const panel = await openCreate(w);
    await panel.find('input.cd-input').setValue('项目管理'.toUpperCase());
    await flushPromises();
    expect(panel.text()).toContain('已经有一个叫');
  });

  it('空名字不让提交', async () => {
    const w = await mountLib();
    const panel = await openCreate(w);
    const submit = panel.findAll('.up-foot button').find((b: any) => b.text().includes('创建'));
    expect(submit!.attributes('disabled')).toBeDefined();
  });

  it('名称/说明/切片方式原样传给后端', async () => {
    const w = await mountLib();
    const panel = await openCreate(w);

    const inputs = panel.findAll('input.cd-input');
    await inputs[0].setValue('协议管理');
    await inputs[1].setValue('协议规范类文档');
    // 选「问答」切片 (2026-10-29 第七轮: 「手动」卡片已删, 走「更多解析方式」下拉)
    const sel = panel.find('.cd-select2');
    await sel.setValue('qa');
    await sel.trigger('change');
    await flushPromises();

    const submit = panel.findAll('.up-foot button').find((b: any) => b.text().includes('创建'));
    await submit.trigger('click');
    await flushPromises();

    expect(h.createKbDataset).toHaveBeenCalledWith('协议管理', '协议规范类文档', 'qa', 'Chinese');
  });

  it('⚠️ 「手动」选项**没有**了 —— 分段得自己调, 而前端调不了 (2026-10-29)', async () => {
    const w = await mountLib();
    const panel = await openCreate(w);
    const manual = panel.findAll('input[type="radio"]').find((r: any) => r.element.value === 'manual');
    expect(manual, '「手动」切片应该已经去掉了').toBeFalsy();
    // ⚠️ 下拉里也不能有 manual —— 同样是死路
    const values = panel.find('.cd-select2').findAll('option').map((o: any) => o.element.value);
    expect(values).not.toContain('manual');
  });

  it('默认是「通用」切片 (RAGFlow 的值是 naive, 不是 general)', async () => {
    const w = await mountLib();
    const panel = await openCreate(w);
    await panel.find('input.cd-input').setValue('默认库');
    await flushPromises();
    const submit = panel.findAll('.up-foot button').find((b: any) => b.text().includes('创建'));
    await submit.trigger('click');
    await flushPromises();
    // ⚠️ 第 4 个参数是语言 —— 默认中文
    expect(h.createKbDataset).toHaveBeenCalledWith('默认库', '', 'naive', 'Chinese');
  });

  it('建库时选了文件 → 建完顺手传进去 (少开一次抽屉)', async () => {
    const w = await mountLib();
    const panel = await openCreate(w);
    await panel.find('input.cd-input').setValue('带文件的库');

    // 造一个文件塞进 input
    const fileInput = panel.find('input[type="file"]');
    const file = new File(['hello'], 'a.txt', { type: 'text/plain' });
    Object.defineProperty(fileInput.element, 'files', { value: [file], configurable: true });
    await fileInput.trigger('change');
    await flushPromises();

    // 按钮文案要跟着变 —— 让人知道这会连带上传
    const submit = panel.findAll('.up-foot button').find((b: any) => b.text().includes('创建'));
    expect(submit!.text()).toContain('创建并上传');

    await submit.trigger('click');
    await flushPromises();

    expect(h.createKbDataset).toHaveBeenCalled();
    expect(h.uploadKbDocuments).toHaveBeenCalledWith('ds-new', [file]);
  });

  it('建库失败要把原因显示出来 —— 不能静默失败', async () => {
    h.createKbDataset.mockRejectedValueOnce({
      response: { status: 422, data: { detail: '已经有一个叫「x」的数据集了' } },
    });
    const w = await mountLib();
    const panel = await openCreate(w);
    await panel.find('input.cd-input').setValue('重复的库');
    await flushPromises();

    const submit = panel.findAll('.up-foot button').find((b: any) => b.text().includes('创建'));
    await submit.trigger('click');
    await flushPromises();

    expect(panel.find('.up-err').text()).toContain('已经有一个叫');
  });

  it('后端报错时才弹 error —— 正常建好不该报错', async () => {
    const w = await mountLib();
    const panel = await openCreate(w);
    await panel.find('input.cd-input').setValue('正常的库');
    await flushPromises();
    const submit = panel.findAll('.up-foot button').find((b: any) => b.text().includes('创建'));
    await submit.trigger('click');
    await flushPromises();
    expect(h.msg.error).not.toHaveBeenCalled();
    expect(h.msg.success).toHaveBeenCalled();
  });
});
