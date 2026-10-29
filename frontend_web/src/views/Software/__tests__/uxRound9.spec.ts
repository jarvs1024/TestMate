/**
 * 软件库 · 第 9 轮前端整改 (2026-10-30).
 *
 * ⚠️ 这五条盯的都是**用户会被坑到**的地方, 不是样式细节:
 *   ① 详情抽屉读失败时**继续渲染上一个软件的旧数据** —— 用户以为在看 B,
 *      点下载下到的却是 A 的包 (**下错包**);
 *   ② 确认框 (ElMessageBox) 里写了 markdown 的 `**加粗**` —— 它**不渲染** Markdown,
 *      用户看到的是字面的星号;
 *   ③ 搜索/分类没结果时显示「这里还没有软件」—— 库里明明有几十个,
 *      用户以为整个库空了, 甚至真去上架重复条目;
 *   ④ 配置接口挂了被说成「没有上架权限」—— 其实用户有权限, 是服务挂了, 还没处重试;
 *   ⑤ 平台名大小写不一致 (卡片 'windows' vs 表单 'Windows') / 拖拽上传毫无反馈.
 */
import { describe, expect, it, vi, beforeEach } from 'vitest';
import { mount, flushPromises } from '@vue/test-utils';

// ⚠️ vi.mock 的工厂函数会被**提升**到文件顶部 —— 直接用模块级的 const 会
//    "Cannot access 'getSoftware' before initialization". 必须用 vi.hoisted.
const {
  getSoftware, listSoftware, listSoftwareCategories, getSoftwareConfig,
  elMessage, elMessageBox,
} = vi.hoisted(() => ({
  getSoftware: vi.fn(),
  listSoftware: vi.fn(),
  listSoftwareCategories: vi.fn(),
  getSoftwareConfig: vi.fn(),
  elMessage: { success: vi.fn(), error: vi.fn(), warning: vi.fn() },
  // ⚠️ 参数要带 any —— 断言要看 confirm 的**第 1 个入参**(文案) 和**第 3 个**(选项)
  elMessageBox: { confirm: vi.fn(async (..._a: any[]) => true) },
}));

vi.mock('@/api/software', () => ({
  getSoftware: (...a: any[]) => getSoftware(...a),
  listSoftware: (...a: any[]) => listSoftware(...a),
  listSoftwareCategories: (...a: any[]) => listSoftwareCategories(...a),
  getSoftwareConfig: (...a: any[]) => getSoftwareConfig(...a),
  downloadSoftware: vi.fn(async () => {}),
  purgeSoftware: vi.fn(async () => ({ ok: true, deleted_files: 1 })),
  updateSoftwareVersion: vi.fn(async () => ({})),
  deleteSoftwareVersion: vi.fn(async () => ({
    ok: true, deleted_files: 1, item_unpublished: false, remaining_versions: 1,
  })),
  createSoftware: vi.fn(async () => ({
    ok: true, code: 'demo-sw', version: '1.0.0', upload_path: '',
  })),
  createSoftwareVersion: vi.fn(async () => ({
    ok: true, code: 'demo-sw', version: '1.0.0', upload_path: '',
  })),
  uploadSoftwareFile: vi.fn(async () => ({
    ok: true, code: 'demo-sw', version: '1.0.0', size: 1, sha256: 'x',
  })),
}));

vi.mock('element-plus', () => ({
  ElMessage: elMessage,
  ElMessageBox: elMessageBox,
}));

vi.mock('@/stores/user', () => ({
  useUserStore: () => ({ user: { role: 'admin', username: 'admin' }, token: 'test-token' }),
}));

import SoftwareDetailDrawer from '../SoftwareDetailDrawer.vue';
import SoftwareUploadDialog from '../SoftwareUploadDialog.vue';
import SoftwareList from '../index.vue';
import { PLATFORMS } from '../softwareForm';
import type { SoftwareDetail, SoftwareVersion } from '@/api/software';

// ---------- 测试用的数据 ----------

function version(over: Partial<SoftwareVersion> = {}): SoftwareVersion {
  return {
    id: 1, version: '1.0.0', release_notes: '', variant: '', is_default: false,
    file_name: 'a.bin', file_size: 100, sha256: 'x', status: 'ready',
    last_error: '', author: 'admin', download_count: 0, created_at: '2026-10-30 10:00:00',
    ...over,
  };
}

function detail(over: Partial<SoftwareDetail> = {}): SoftwareDetail {
  return {
    code: 'sw-a', name: '软件A', icon: '🧰', version: '1.0.0',
    summary: 'A 的简介', description: '', features: [], use_when: '', not_for: '',
    install_steps: '', caveats: '',
    platform: 'windows', category: '工具', tags: [], keywords: [], author: 'admin',
    download_count: 0, publish_status: 'published',
    created_at: '2026-10-30 10:00:00', updated_at: '2026-10-30 10:00:00',
    can_edit: true, download_version: '1.0.0',
    versions: [version()],
    ...over,
  };
}

/** 一次"后端挂了"的失败 (502) */
function backendDown() {
  return { response: { status: 502, data: { detail: '网关没起来' } } };
}

// ---------- 抽屉 ----------

const drawerStubs = { 'el-drawer': { template: '<div class="el-drawer"><slot /></div>' } };

async function mountDrawer(code = 'sw-a') {
  const w = mount(SoftwareDetailDrawer, {
    props: { modelValue: false, code },
    global: { stubs: drawerStubs },
  });
  // ⚠️ 先挂成"关闭"再打开 —— 抽屉靠 watch(modelValue) 触发读取
  await w.setProps({ modelValue: true });
  await flushPromises();
  await flushPromises();
  return w;
}

/**
 * ① 详情抽屉: 读失败时**不许**继续渲染上一个软件的旧数据.
 */
describe('详情抽屉: 加载失败不许显示上一个软件的旧数据', () => {
  beforeEach(() => {
    getSoftware.mockReset();
    elMessage.error.mockClear();
  });

  it('先打开 A, 再打开读失败的 B → A 的数据必须消失, 出现错误态 + 重试按钮', async () => {
    getSoftware.mockResolvedValueOnce(detail({ code: 'sw-a', name: '软件A' }));
    const w = await mountDrawer('sw-a');
    expect(w.text()).toContain('软件A');

    // B 读失败
    getSoftware.mockRejectedValueOnce(backendDown());
    await w.setProps({ code: 'sw-b' });
    await flushPromises();
    await flushPromises();

    // ⚠️ 关键: 旧数据**必须没了** —— 留着的话用户以为在看 B, 下到的却是 A 的包
    expect(w.text()).not.toContain('软件A');
    // 抽屉标题也不能再是 A 的名字
    expect(w.find('.el-drawer').text()).not.toContain('软件A');

    // 错误态 + 原因
    const err = w.find('.state.err');
    expect(err.exists()).toBe(true);
    expect(err.text()).toContain('加载失败');
    expect(err.text()).toContain('网关没起来');
    // ⚠️ 失败不能拿"读不到详情"冒充 (那是另一个分支)
    expect(w.text()).not.toContain('读不到这个软件的详情');

    // 重试按钮 —— 失败后必须有重试入口
    const retry = w.findAll('.reset').find((b) => b.text().includes('重试'));
    expect(retry).toBeTruthy();
  });

  it('点「重试」→ 真的重新拉一次详情', async () => {
    getSoftware.mockResolvedValueOnce(detail({ code: 'sw-a', name: '软件A' }));
    const w = await mountDrawer('sw-a');

    getSoftware.mockRejectedValueOnce(backendDown());
    await w.setProps({ code: 'sw-b' });
    await flushPromises();
    await flushPromises();
    expect(getSoftware).toHaveBeenCalledTimes(2);

    // 重试成功 → 换成 B 的内容
    getSoftware.mockResolvedValueOnce(detail({ code: 'sw-b', name: '软件B' }));
    const retry = w.findAll('.reset').find((b) => b.text().includes('重试'))!;
    await retry.trigger('click');
    await flushPromises();
    await flushPromises();

    expect(getSoftware).toHaveBeenCalledTimes(3);
    expect(w.text()).toContain('软件B');
    expect(w.find('.state.err').exists()).toBe(false);
  });
});

/**
 * ② 确认框 (ElMessageBox) 是**纯文本** —— 不渲染 Markdown.
 */
describe('详情抽屉: 确认框文案里不该出现 markdown 星号', () => {
  beforeEach(() => {
    getSoftware.mockReset();
    elMessageBox.confirm.mockClear();
  });

  it('下架软件 / 下架某个版本的确认框文案里没有 `**`', async () => {
    getSoftware.mockResolvedValueOnce(detail({ can_edit: true }));
    const w = await mountDrawer('sw-a');

    // 下架整个软件
    await w.findAll('.sw-danger .mini-btn.danger')[0].trigger('click');
    await flushPromises();
    // 下架某个版本
    await w.findAll('.ver-row .vr-hd .mini-btn')
      .find((b) => b.text().includes('下架这版'))!
      .trigger('click');
    await flushPromises();

    expect(elMessageBox.confirm).toHaveBeenCalledTimes(2);
    for (const call of elMessageBox.confirm.mock.calls) {
      const msg = String(call[0]);
      expect(msg).not.toContain('**');
      // ⚠️ 也**不许**把 dangerouslyUseHTMLString 改成 true ——
      //    确认框正文里插了软件名, 开了就是 HTML 注入面
      expect(call[2]?.dangerouslyUseHTMLString).toBe(false);
    }
  });

  it('页面上那段"下架会删文件"的提示里也没有 `**` (普通文本, 不是 Markdown)', async () => {
    getSoftware.mockResolvedValueOnce(detail({ can_edit: true }));
    const w = await mountDrawer('sw-a');
    expect(w.text()).not.toContain('**');
  });
});

// ---------- 列表页 ----------

const listStubs = {
  'el-drawer': { template: '<div><slot /></div>' },
  CapabilityShell: { template: '<div class="cap-shell-stub" />' },
  SoftwareCard: { template: '<div class="card-stub" />' },
  SoftwareDetailDrawer: { template: '<div class="detail-stub" />' },
  SoftwareUploadDialog: { template: '<div class="upload-stub" />' },
};

async function mountList() {
  const w = mount(SoftwareList, { global: { stubs: listStubs } });
  await flushPromises();
  await flushPromises();
  return w;
}

describe('列表页: 筛选没结果 ≠ 库里没有软件', () => {
  beforeEach(() => {
    listSoftware.mockReset();
    listSoftwareCategories.mockReset();
    getSoftwareConfig.mockReset();
    listSoftwareCategories.mockResolvedValue({ items: [], total: 0 });
    getSoftwareConfig.mockResolvedValue({
      max_bytes: 1024, can_publish: true, is_admin: true, public_download: true,
      storage_root: '/tmp/sw', storage_source: 'env', path_ok: true,
      used_bytes: 0, free_bytes: 1024,
    });
  });

  it('有搜索词但搜不到 → 显示「没有匹配」, 不显示「这里还没有软件」', async () => {
    listSoftware.mockResolvedValue({ items: [], total: 0 });
    const w = await mountList();

    const input = w.find('.search input');
    await input.setValue('不存在的关键词');
    // 搜索是防抖的 (300ms) —— 等它真的去查一次
    await new Promise((r) => setTimeout(r, 400));
    await flushPromises();

    expect(w.text()).toContain('没有匹配');
    expect(w.text()).not.toContain('这里还没有软件');
    // 空态里要给个"清空筛选"的出路
    const clear = w.findAll('.reset').find((b) => b.text().includes('清空筛选'));
    expect(clear).toBeTruthy();
  });

  it('点了「清空筛选」→ keyword 清掉, 重新按"全部"查一次', async () => {
    listSoftware.mockResolvedValue({ items: [], total: 0 });
    const w = await mountList();

    const input = w.find('.search input');
    await input.setValue('不存在的关键词');
    await new Promise((r) => setTimeout(r, 400));
    await flushPromises();

    const clear = w.findAll('.reset').find((b) => b.text().includes('清空筛选'))!;
    await clear.trigger('click');
    await flushPromises();

    const last = listSoftware.mock.calls[listSoftware.mock.calls.length - 1][0];
    expect(last.q).toBe('');
    expect(last.category).toBe('');
  });

  it('没有任何筛选条件 + 库里真的空的 → 还是那句「这里还没有软件」', async () => {
    listSoftware.mockResolvedValue({ items: [], total: 0 });
    const w = await mountList();
    expect(w.text()).toContain('这里还没有软件');
    expect(w.text()).not.toContain('没有匹配');
  });
});

describe('列表页: 配置读不到 ≠ 没有上架权限', () => {
  beforeEach(() => {
    listSoftware.mockReset();
    listSoftwareCategories.mockReset();
    getSoftwareConfig.mockReset();
    listSoftware.mockResolvedValue({ items: [], total: 0 });
    listSoftwareCategories.mockResolvedValue({ items: [], total: 0 });
  });

  it('配置接口挂了 → 提示"读不到发布配置", 不说"没有上架权限"', async () => {
    getSoftwareConfig.mockRejectedValue(backendDown());
    const w = await mountList();

    expect(w.text()).toContain('读不到发布配置');
    expect(w.text()).not.toContain('没有上架权限');
    // ⚠️ 配置错误不该显示在分类 chip 下面 (那是分类读失败才管的)
    expect(w.find('.filter-err').exists()).toBe(false);
  });

  it('配置读不到 → 给一个重试入口, 点了会再拉一次配置', async () => {
    getSoftwareConfig.mockRejectedValueOnce(backendDown());
    const w = await mountList();
    expect(getSoftwareConfig).toHaveBeenCalledTimes(1);

    getSoftwareConfig.mockResolvedValueOnce({
      max_bytes: 1024, can_publish: false, is_admin: false, public_download: true,
      storage_root: '/tmp/sw', storage_source: 'env', path_ok: true,
      used_bytes: 0, free_bytes: 1024,
    });
    const retry = w.findAll('.reset').find((b) => b.text().includes('重试'));
    expect(retry).toBeTruthy();
    await retry!.trigger('click');
    await flushPromises();

    expect(getSoftwareConfig).toHaveBeenCalledTimes(2);
    // 配置读到了, 且确实没权限 → 这时候才该说"没有上架权限"
    expect(w.text()).toContain('没有上架权限');
    expect(w.text()).not.toContain('读不到发布配置');
  });
});

// ---------- 上传对话框 ----------

const uploadStubs = {
  'el-drawer': { template: '<div class="el-drawer"><slot/><slot name="footer"/></div>' },
  'el-form': { template: '<form><slot/></form>' },
  'el-form-item': {
    props: ['label'],
    template: '<div class="el-form-item"><label v-if="label">{{ label }}</label><slot/></div>',
  },
  'el-input': { template: '<input class="el-input"/>' },
  'el-select': { template: '<select class="el-select"><slot/></select>' },
  'el-option': { props: ['label'], template: '<option>{{ label }}<slot/></option>' },
  'el-checkbox': { template: '<label><slot/></label>' },
  'el-progress': { template: '<div class="el-progress" />' },
};

async function mountUpload() {
  const w = mount(SoftwareUploadDialog, {
    props: { modelValue: false, mode: 'create' },
    global: { stubs: uploadStubs },
  });
  await w.setProps({ modelValue: true });
  await flushPromises();
  return w;
}

describe('上传对话框: 平台选项 + 拖拽反馈', () => {
  beforeEach(() => {
    getSoftwareConfig.mockReset();
    getSoftwareConfig.mockResolvedValue({
      max_bytes: 1024, can_publish: true, is_admin: true, public_download: true,
      storage_root: '/tmp/sw', storage_source: 'env', path_ok: true,
      used_bytes: 0, free_bytes: 1024, used_icons: {},
    });
  });

  it('平台选项的 label 不含「——」 (选中后输入框里会被截断成「通用 —— 哪个…」)', async () => {
    for (const p of PLATFORMS) {
      expect(p.label).not.toContain('——');
      expect(p.label).not.toContain('--');
    }
    const w = await mountUpload();
    const optTexts = w.findAll('option').map((o) => o.text());
    for (const t of optTexts) {
      expect(t).not.toContain('——');
    }
    // 平台名的大小写要统一 —— 卡片/详情页显示 'Windows', 这里也必须是 'Windows'
    // (⚠️ option 文字里还带着下拉里那一行的补充说明, 所以用 includes 判)
    expect(optTexts.some((t) => t.includes('Windows'))).toBe(true);
    expect(optTexts.some((t) => t.includes('Linux'))).toBe(true);
    expect(optTexts.some((t) => t.includes('macOS'))).toBe(true);
    // 旧的"小写原值"不该再作为**可见文字**出现
    expect(optTexts.some((t) => t.startsWith('windows'))).toBe(false);
  });

  it('拖文件进来 → .file-pick 有 dragging 类 (以前这个状态只写不读, 毫无反馈)', async () => {
    const w = await mountUpload();
    const pick = w.find('.file-pick');
    expect(pick.classes()).not.toContain('dragging');

    await pick.trigger('dragover');
    expect(w.find('.file-pick').classes()).toContain('dragging');

    await w.find('.file-pick').trigger('dragleave');
    expect(w.find('.file-pick').classes()).not.toContain('dragging');
  });

  it('清空已选文件的「×」是能聚焦的 button (以前是 <b>, 键盘用户清不掉)', async () => {
    const w = await mountUpload();
    const file = new File(['x'], 'demo-sw.bin');
    const input = w.find('input[type=file]').element as HTMLInputElement;
    Object.defineProperty(input, 'files', { value: [file], writable: true });
    await w.find('input[type=file]').trigger('change');
    await w.vm.$nextTick();

    const x = w.find('.file-chip .file-x');
    expect(x.exists()).toBe(true);
    expect(x.element.tagName).toBe('BUTTON');
    expect(x.attributes('aria-label')).toContain('demo-sw.bin');
    // 文件名太长时给个 title (完整名字)
    expect(w.find('.fc-name').attributes('title')).toBe('demo-sw.bin');
  });
});
