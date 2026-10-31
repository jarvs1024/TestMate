/**
 * 软件库 · 第十六轮前端 (2026-10-31).
 *
 * 用户提了三件事, 这里盯前两件 (第三件 = 卡片作者只显示用户名, 在
 * SoftwareCard.spec.ts / AssetCard.spec.ts 里):
 *   ① **顶部两行融合成一行** —— 以前是「搜索 + 排序 + 上架」一行,
 *      下面再来一行「全部 / 我的 / 分类 chip」. 用户要的是**一行**,
 *      而且左边那组 tab 跟「插件·技能·连接」那一页的 tab **同一个长相**
 *      (.kind-tab: 药丸 + 选中渐变底 + 渐变计数徽标 —— 样式在 styles/main.css).
 *   ② 「@某个具体的人」的通知设置**整个去掉** —— 这条是后端的,
 *      前端这边要保证设置页**不再出现**那张映射表.
 */
import { describe, expect, it, vi, beforeEach } from 'vitest';
import { mount, flushPromises } from '@vue/test-utils';
import { readFileSync } from 'node:fs';
import { resolve } from 'node:path';

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

function read(rel: string): string {
  return readFileSync(resolve(process.cwd(), rel), 'utf8');
}

beforeEach(() => {
  listSoftware.mockReset();
  listSoftwareCategories.mockReset();
  getSoftwareConfig.mockReset();
  getSoftware.mockReset();
  listSoftware.mockResolvedValue({ items: [], total: 0 });
  listSoftwareCategories.mockResolvedValue({ items: [] });
  getSoftwareConfig.mockResolvedValue({
    max_bytes: 1024, can_publish: true, is_admin: true, public_download: true,
    storage_root: '/tmp/sw', storage_source: 'env', path_ok: true,
    used_bytes: 0, free_bytes: 1024,
  });
});

describe('软件库顶部: 两行融合成一行', () => {
  it('顶部只有**一个**动作条 —— 分类 tab 和搜索/排序/上架在同一个 .mk-actions 里', async () => {
    const w = await mountList();
    const bars = w.findAll('.mk-actions');
    expect(bars.length).toBe(1);

    // 左边是分类 tab, 右边是搜索 + 排序 + 上架 —— 都在这一行里
    expect(w.find('.mk-actions .kind-tabs').exists()).toBe(true);
    expect(w.find('.mk-actions .ma-right .search').exists()).toBe(true);
    expect(w.find('.mk-actions .ma-right .sort-sel').exists()).toBe(true);
    expect(w.find('.mk-actions .ma-right .mini-btn.primary').exists()).toBe(true);

    // ⚠️ 以前那**单独一行**的筛选条没了
    expect(w.find('.mk-filters').exists()).toBe(false);
    expect(w.find('.cat-chips').exists()).toBe(false);
  });

  it('分类 tab 用的是市场那一套 .kind-tab (不是旧的 .chip)', async () => {
    const w = await mountList();
    const tabs = w.findAll('.mk-actions .kind-tabs .kind-tab');
    expect(tabs.length).toBeGreaterThan(0);
    // 「全部」+「👤 我的」
    expect(tabs.some((t) => t.text().includes('全部'))).toBe(true);
    expect(tabs.some((t) => t.text().includes('我的'))).toBe(true);
    // ⚠️ 旧的小 chip 类不该再出现
    expect(w.findAll('.mk-actions .chip').length).toBe(0);
  });

  it('分类读失败 → 提示还在 (但也在这一行里)', async () => {
    listSoftwareCategories.mockRejectedValue(new Error('boom'));
    const w = await mountList();
    const err = w.find('.filter-err');
    expect(err.exists()).toBe(true);
    expect(err.text()).toContain('分类读取失败');
    // 还是在同一个动作条里
    expect(w.find('.mk-actions .filter-err').exists()).toBe(true);
  });
});

describe('.kind-tab 样式是全局的 (两页共用一份)', () => {
  it('styles/main.css 里有 .kind-tab / .kind-tab.active / 渐变计数徽标', () => {
    const css = read('src/styles/main.css');
    expect(css).toContain('.kind-tab');
    expect(css).toContain('.kind-tab.active');
    expect(css).toContain('.kind-tab .count');
    expect(css).toContain('var(--primary-grad)');
  });

  it('市场页那份 scoped 样式删了 (别各抄一份, 会漂移)', () => {
    const src = read('src/views/Capability/Catalog/index.vue');
    // 只留分类 chip 的 .count, 类型 tab 的样式全在全局
    expect(src).not.toMatch(/^\.kind-tab\s*\{/m);
    expect(src).not.toMatch(/^\.kind-tabs\s*\{/m);
  });
});

/**
 * 顶部动作条跟「插件·技能·连接」那一页**同一个面板** (2026-10-31 第十七轮).
 *
 * ⚠️ 用户原话「图1 的样式保持和图2 的样式一致」——
 *    以前市场那行是**白底圆角面板 + 粘顶**, 软件库是**裸的一行**, 两页不是一套东西.
 */
describe('顶部动作条: 跟市场页同一个面板', () => {
  it('面板样式在全局 main.css 里 (两页共用一份)', () => {
    const css = read('src/styles/main.css');
    expect(css).toMatch(/^\.mk-actions\s*\{/m);
    // 白底 + 圆角 + 边框 + 阴影 + 粘顶 —— 五件套缺一不可
    expect(css).toMatch(/--surface-soft/);
    expect(css).toMatch(/--radius-card/);
    expect(css).toMatch(/--shadow-sm/);
    expect(css).toMatch(/position:\s*sticky/);
    // 右边那组控件靠 margin-left:auto 顶到右边
    expect(css).toMatch(/^\.mk-actions \.ma-right\s*\{/m);
    expect(css).toMatch(/margin-left:\s*auto/);
    // 搜索框也是共用的
    expect(css).toMatch(/^\.mk-actions \.search\s*\{/m);
  });

  it('市场页那份 scoped 副本删了 (白底面板/搜索框都走全局)', () => {
    const src = read('src/views/Capability/Catalog/index.vue');
    expect(src).not.toMatch(/^\.mk-actions\s*\{/m);
    expect(src).not.toMatch(/^\.ma-right\s*\{/m);
    expect(src).not.toMatch(/^\.search\s*\{/m);
  });

  it('软件库自己那份副本也删了 (走全局)', () => {
    const src = read('src/views/Software/index.vue');
    expect(src).not.toMatch(/^\.mk-actions\s*\{/m);
    expect(src).not.toMatch(/^\.ma-right\s*\{/m);
    expect(src).not.toMatch(/^\.search\s*\{/m);
  });

  it('两页的根容器都是「纵向 flex + 14px 间距」(别一个用 gap 一个用 margin)', () => {
    const sw = read('src/views/Software/index.vue');
    const mk = read('src/views/Capability/Catalog/index.vue');
    expect(sw).toMatch(/\.software\s*\{[^}]*flex-direction:\s*column[^}]*gap:\s*14px/);
    expect(mk).toMatch(/\.market\s*\{[^}]*flex-direction:\s*column[^}]*gap:\s*14px/);
  });
});
