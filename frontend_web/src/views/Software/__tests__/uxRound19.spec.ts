/**
 * **第十九轮 · 软件库「全部 / 👤 我的」互斥 + tab 计数** (2026-10-31).
 *
 * 用户报的两个毛病:
 *   ① 点过「👤 我的」之后, 「全部」tab **点不亮** —— 它的 active 条件是
 *      `category === '' && !mineOnly`, 而点「全部」只把 category 置空,
 *      mineOnly 还是 true → 用户得多点一次「👤 我的」才切得回去.
 *   ② 「👤 我的」后面没有数字; 而且「全部 N」用的是**当前请求**的 total ——
 *      一选「我的」它就变成"我的"条数 → 用户看到「全部 3 | 我的 3」,
 *      完全不知道这个库里到底有多少东西.
 *
 * 修法: 「全部 / 我的 / 各分类」收敛成**同一个维度**(互斥),
 *      两个数字改用后端给的 all_total / mine_total.
 */
import { describe, expect, it, vi, beforeEach } from 'vitest';
import { mount, flushPromises } from '@vue/test-utils';

const {
  getSoftware, listSoftware, listSoftwareCategories, getSoftwareConfig,
} = vi.hoisted(() => ({
  getSoftware: vi.fn(),
  listSoftware: vi.fn(),
  listSoftwareCategories: vi.fn(),
  getSoftwareConfig: vi.fn(),
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
  createSoftware: vi.fn(async () => ({ ok: true, code: 'demo-sw', version: '1.0.0', upload_path: '' })),
  createSoftwareVersion: vi.fn(async () => ({ ok: true, code: 'demo-sw', version: '1.0.0', upload_path: '' })),
  uploadSoftwareFile: vi.fn(async () => ({ ok: true, code: 'demo-sw', version: '1.0.0', size: 1, sha256: 'x' })),
}));

vi.mock('element-plus', () => ({
  ElMessage: { success: vi.fn(), error: vi.fn(), warning: vi.fn() },
  ElMessageBox: { confirm: vi.fn(async () => true) },
}));

vi.mock('@/stores/user', () => ({
  useUserStore: () => ({ user: { role: 'admin', username: 'admin' }, token: 'test-token' }),
}));

import SoftwareList from '../index.vue';

const listStubs = {
  'el-drawer': { template: '<div class="el-drawer"><slot /></div>' },
  'el-dialog': { template: '<div class="el-dialog"><slot /></div>' },
};

async function mountList() {
  const w = mount(SoftwareList, { global: { stubs: listStubs } });
  await flushPromises();
  await flushPromises();
  return w;
}

/** 分类 tab 行里的某个 tab (按文字找) */
function tab(w: any, text: string) {
  const t = w.findAll('.mk-actions .kind-tabs .kind-tab').find((x: any) => x.text().includes(text));
  if (!t) throw new Error(`找不到 tab: ${text}`);
  return t;
}
function isActive(t: any): boolean {
  return t.classes().includes('active');
}
/** 最后一次列表请求的参数 */
function lastListCall() {
  return listSoftware.mock.calls[listSoftware.mock.calls.length - 1][0];
}

beforeEach(() => {
  listSoftware.mockReset();
  listSoftwareCategories.mockReset();
  getSoftwareConfig.mockReset();
  getSoftware.mockReset();
  listSoftware.mockResolvedValue({ items: [], total: 12, all_total: 12, mine_total: 3 });
  listSoftwareCategories.mockResolvedValue({ items: [{ name: '效率工具', total: 5 }] });
  getSoftwareConfig.mockResolvedValue({
    max_bytes: 1024, can_publish: true, is_admin: true, public_download: true,
    storage_root: '/tmp/sw', storage_source: 'env', path_ok: true,
    used_bytes: 0, free_bytes: 1024,
  });
});

describe('软件库 · 「全部 / 👤 我的 / 各分类」互斥', () => {
  it('点「👤 我的」→ 「全部」tab 不再高亮', async () => {
    const w = await mountList();
    expect(isActive(tab(w, '全部'))).toBe(true);

    await tab(w, '我的').trigger('click');
    await flushPromises();

    expect(isActive(tab(w, '我的'))).toBe(true);
    expect(isActive(tab(w, '全部'))).toBe(false);
    expect(lastListCall().status).toBe('mine');
    w.unmount();
  });

  it('⚠️ 点过「👤 我的」之后, 点「全部」**一次就切回去** (不用点第二次)', async () => {
    const w = await mountList();

    await tab(w, '我的').trigger('click');
    await flushPromises();
    expect(isActive(tab(w, '全部'))).toBe(false);

    // ⚠️ 以前这一步点了没反应 —— 「全部」的高亮条件不成立, 要再点一次「我的」
    await tab(w, '全部').trigger('click');
    await flushPromises();

    expect(isActive(tab(w, '全部'))).toBe(true);
    expect(isActive(tab(w, '我的'))).toBe(false);
    // 请求也不该再带 status=mine
    expect(lastListCall().status).toBeUndefined();
    w.unmount();
  });

  it('点某个分类 → 「我的」让路', async () => {
    const w = await mountList();

    await tab(w, '我的').trigger('click');
    await flushPromises();
    await tab(w, '效率工具').trigger('click');
    await flushPromises();

    expect(isActive(tab(w, '效率工具'))).toBe(true);
    expect(isActive(tab(w, '我的'))).toBe(false);
    expect(isActive(tab(w, '全部'))).toBe(false);
    expect(lastListCall().category).toBe('效率工具');
    w.unmount();
  });

  it('再点一次「👤 我的」→ 切回「全部」', async () => {
    const w = await mountList();

    await tab(w, '我的').trigger('click');
    await flushPromises();
    await tab(w, '我的').trigger('click');
    await flushPromises();

    expect(isActive(tab(w, '我的'))).toBe(false);
    expect(isActive(tab(w, '全部'))).toBe(true);
    w.unmount();
  });
});

describe('软件库 · tab 上的两个计数 (后端 all_total / mine_total)', () => {
  it('「👤 我的」后面显示 mine_total', async () => {
    const w = await mountList();
    expect(tab(w, '我的').find('.count').text()).toBe('3');
    w.unmount();
  });

  it('「全部」显示 all_total —— 不跟着当前筛选跳', async () => {
    const w = await mountList();
    expect(tab(w, '全部').find('.count').text()).toBe('12');

    // ⚠️ 切到「我的」之后, 「全部 N」必须还是 12 (不能变成"我的"条数)
    await tab(w, '我的').trigger('click');
    await flushPromises();
    expect(tab(w, '全部').find('.count').text()).toBe('12');
    w.unmount();
  });

  it('后端没给这两个字段 → 回退旧口径, 不白屏', async () => {
    listSoftware.mockResolvedValue({ items: [], total: 7 });
    const w = await mountList();
    expect(tab(w, '全部').find('.count').text()).toBe('7');
    expect(tab(w, '我的').find('.count').text()).toBe('0');
    w.unmount();
  });
});
