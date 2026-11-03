/**
 * **第二十二轮验收** (2026-11-03).
 *
 * 用户报的三件事:
 *   ① 图1/图2: 抽屉太窄 → 暗色下背景文字透上来叠字; 软件详情头部被超长版本名挤成竖排
 *   ② 图3:    编辑页面的内容和实际上架的内容不一致 (上架表单里压根没那几个输入框)
 *   ③ 图4:    软件要一个**固定**的 wget 下载链接 (URL 永不变, 永远给推荐版本)
 *
 * 这个文件锁的是**结构性**的东西 (宽度 / 底色 / 端点 / 链接),
 * 交互行为在各自的组件测试里 (AssetDetailDrawer.spec / assetUploadFlow.spec /
 * SoftwareDetailDrawer*.spec)。
 */
import { describe, expect, it, vi, beforeEach } from 'vitest';
import { readFileSync } from 'node:fs';
import { resolve } from 'node:path';
import { mount, flushPromises } from '@vue/test-utils';
import { createPinia, setActivePinia } from 'pinia';

const read = (p: string) =>
  readFileSync(resolve(process.cwd(), p), 'utf8');

const css = read('src/styles/tokens.css');
const detailDrawer = read('src/views/Capability/Catalog/AssetDetailDrawer.vue');
const uploadDialog = read('src/views/Capability/Catalog/AssetUploadDialog.vue');
const swDetail = read('src/views/Software/SoftwareDetailDrawer.vue');
const swUpload = read('src/views/Software/SoftwareUploadDialog.vue');
const boardView = read('src/views/Capability/BoardView.vue');
const libraryView = read('src/views/Capability/Library/index.vue');

/** 从 CSS 里抠出某个变量在某个块里的值 */
function cssVar(src: string, name: string): string {
  const m = src.match(new RegExp(`${name}\\s*:\\s*([^;]+);`));
  return m ? m[1].trim() : '';
}

// ═══════════════ ① 抽屉宽度 ═══════════════

describe('① 抽屉宽度 —— 别再窄到挤字 (2026-11-03)', () => {
  const drawers: [string, string][] = [
    ['扩展详情', detailDrawer],
    ['扩展上传/编辑', uploadDialog],
    ['软件详情', swDetail],
    ['软件上架', swUpload],
    ['看板', boardView],
    ['知识库', libraryView],
  ];

  it.each(drawers)('%s: 抽屉宽度都 ≥ 760px', (_name, src) => {
    const sizes = [...src.matchAll(/size="([^"]+)"/g)].map((m) => m[1]);
    expect(sizes.length).toBeGreaterThan(0);
    for (const s of sizes) {
      // 形如 min(860px, 94vw) / min(900px, 94vw)
      const px = Number(s.match(/min\((\d+)px/)?.[1] || s.match(/(\d+)px/)?.[1] || 0);
      expect(px, `${_name} 的抽屉宽度 ${s}`).toBeGreaterThanOrEqual(760);
    }
  });

  it('每个抽屉都用 min(…, 94vw) —— 窄屏下不能整个跑到屏幕外', () => {
    for (const [name, src] of drawers) {
      const sizes = [...src.matchAll(/<el-drawer[^>]*size="([^"]+)"/g)].map((m) => m[1]);
      for (const s of sizes) {
        expect(s, `${name} 的抽屉 size=${s}`).toMatch(/min\(\d+px,\s*9[0-9]vw\)/);
      }
    }
  });

  it('软件详情头部: 标题区有最小宽度, 按钮不会把标题挤成竖排', () => {
    // ⚠️ 用户图2 的病根: .sw-hd-actions 是 flex-shrink:0, 按钮里的超长版本名
    //    把 .sw-hd-main 压成 1 个字宽 → 标题竖着排.
    expect(swDetail).toMatch(/\.sw-hd-main\s*\{[^}]*min-width:\s*2\d\dpx/);
    expect(swDetail).toMatch(/\.sw-hd\s*\{[^}]*flex-wrap:\s*wrap/);
    // 按钮文字限宽 + 省略号 (完整值在 title 里)
    expect(swDetail).toMatch(/\.sw-hd-actions \.mini-btn\s*\{[^}]*text-overflow:\s*ellipsis/);
    // 下载按钮的完整版本名进 title
    expect(swDetail).toContain(':title="defaultLabel');
  });
});

// ═══════════════ ① 暗色抽屉底色 ═══════════════

describe('① 暗色主题: 抽屉底色必须近乎不透明 (否则背景字透上来叠字)', () => {
  it('--surface-panel 暗色下 alpha ≥ 0.9', () => {
    // ⚠️ 以前是 rgba(15,22,40,.55) —— 抽屉背后的**页面卡片文字直接透上来**,
    //    跟抽屉正文叠在一起 (用户图1 报的"字体会被覆盖").
    const dark = css.slice(css.indexOf('html[data-theme="dark"]'));
    const panel = cssVar(dark, '--surface-panel');
    expect(panel).toMatch(/rgba?\(/);
    const alpha = Number(panel.match(/rgba?\([^)]*?,\s*([\d.]+)\s*\)/)?.[1] ?? 1);
    expect(alpha, `暗色 --surface-panel = ${panel}`).toBeGreaterThanOrEqual(0.9);
  });

  it('两个暗色块 (data-theme=dark 和 prefers-color-scheme) 都改了', () => {
    // data-theme="dark" 块 + @media (prefers-color-scheme: dark) 块
    const alphas = [...css.matchAll(/--surface-panel:\s*rgba\([^)]*?,\s*([\d.]+)\s*\)/g)]
      .map((m) => Number(m[1]));
    expect(alphas.length).toBeGreaterThanOrEqual(2);
    for (const a of alphas) expect(a).toBeGreaterThanOrEqual(0.9);
  });

  it('页面**卡片**的 --surface 还是半透明 (毛玻璃本来的意思, 别一起改死)', () => {
    const dark = css.slice(css.indexOf('html[data-theme="dark"]'));
    const surface = cssVar(dark, '--surface');
    const alpha = Number(surface.match(/rgba?\([^)]*?,\s*([\d.]+)\s*\)/)?.[1] ?? 1);
    expect(alpha, `暗色 --surface = ${surface}`).toBeLessThan(0.9);
  });
});

// ═══════════════ ② 编辑页 ↔ 上架内容对齐 ═══════════════

describe('② 上架表单和详情页要对得上 (2026-11-03)', () => {
  it('扩展上架表单: 详细说明 / 适用场景 / 不适合的场景 / 安装步骤 都有输入框', () => {
    expect(uploadDialog).toContain('v-model="form.description"');
    expect(uploadDialog).toContain('v-model="form.use_when"');
    expect(uploadDialog).toContain('v-model="form.not_for"');
    expect(uploadDialog).toContain('v-model="form.installStepsText"');
  });

  it('扩展上架表单: 这几项在 create / edit 都有, update (发新版本) 保留原值', () => {
    // ⚠️ 发新版本那一路**不显示**这几项 → 提交时必须带原值, 别把老字段清空
    expect(uploadDialog).toContain('v-if="mode !== \'update\'"');
    expect(uploadDialog).toMatch(/description:\s*props\.mode === 'update'\s*\?\s*\(props\.asset\?\.description \|\| ''\)\s*:\s*form\.description/);
    expect(uploadDialog).toMatch(/not_for:\s*props\.mode === 'update'\s*\?\s*\(props\.asset\?\.not_for \|\| ''\)\s*:\s*form\.not_for/);
  });

  it('扩展详情页: 适用场景 / 不适合的场景 / 安装步骤 又显示出来了', () => {
    expect(detailDrawer).toContain('item.use_when');
    expect(detailDrawer).toContain('item.not_for');
    expect(detailDrawer).toContain('installStepList');
  });

  it('软件上架表单: 「详细说明」「不适合的场景」也补上了 (跟扩展一致)', () => {
    expect(swUpload).toContain('v-model="form.description"');
    expect(swUpload).toContain('v-model="form.not_for"');
    expect(swUpload).toMatch(/description:\s*form\.value\.description/);
    expect(swUpload).toMatch(/not_for:\s*form\.value\.not_for/);
  });
});

// ═══════════════ ③ 固定下载链接 ═══════════════

const { getSoftware } = vi.hoisted(() => ({ getSoftware: vi.fn() }));

vi.mock('@/api/software', () => ({
  getSoftware: (...a: any[]) => getSoftware(...a),
  deleteSoftwareVersion: vi.fn(),
  downloadSoftware: vi.fn(),
  purgeSoftware: vi.fn(),
  updateSoftwareVersion: vi.fn(),
}));

function swItem(over: Record<string, any> = {}) {
  return {
    code: 'fio', name: 'fio', icon: '🧰', version: '3.42',
    summary: 's', description: '', features: [], use_when: '', not_for: '',
    install_steps: '', caveats: '', platform: 'linux', category: '工具',
    tags: [], keywords: [], author: 'admin', download_count: 0,
    publish_status: 'published', created_at: null, updated_at: null,
    can_edit: true, download_version: '3.42',
    versions: [
      { id: 2, version: '3.42', release_notes: '', variant: '', is_default: true,
        file_name: 'fio-3.42.tar.gz', file_size: 10, sha256: 'a', status: 'ready',
        last_error: '', author: 'admin', download_count: 0, created_at: null },
      { id: 1, version: '3.41', release_notes: '', variant: '', is_default: false,
        file_name: 'fio-3.41.tar.gz', file_size: 10, sha256: 'b', status: 'ready',
        last_error: '', author: 'admin', download_count: 0, created_at: null },
    ],
    fixed_download_url: '/api/v1/software/fio/download',
    fixed_download_name: 'fio.tar.gz',
    ...over,
  };
}

async function mountSw(over: Record<string, any> = {}) {
  const pinia = createPinia();
  setActivePinia(pinia);
  getSoftware.mockResolvedValue(swItem(over));
  const SoftwareDetailDrawer = (await import('@/views/Software/SoftwareDetailDrawer.vue')).default;
  const w = mount(SoftwareDetailDrawer, {
    props: { modelValue: false, code: 'fio' },
    global: { stubs: { 'el-drawer': { template: '<div><slot/></div>' } }, plugins: [pinia] },
  });
  await w.setProps({ modelValue: true });
  await flushPromises();
  await flushPromises();
  return w;
}

beforeEach(() => {
  getSoftware.mockReset();
});

describe('③ 软件的固定下载链接 (免登录 · 永不变 · 给推荐版本)', () => {
  it('详情页显示固定链接 + 一条能直接贴走的 wget 命令', async () => {
    const w = await mountSw();
    const text = w.text();
    expect(text).toContain('固定下载链接');
    expect(text).toContain('/api/v1/software/fio/download');
    // ⚠️ wget 命令要能直接用: 带 -O (文件名) + 完整地址
    expect(text).toContain('wget -O fio.tar.gz');
    w.unmount();
  });

  it('相对地址会拼上当前 origin (用户从哪个地址访问就给哪个)', async () => {
    const w = await mountSw();
    const url = w.find('.fx-url').text();
    expect(url).toContain(window.location.origin);
    expect(url).toContain('/api/v1/software/fio/download');
    w.unmount();
  });

  it('后端给了绝对地址就直接用 (配了 software.public_base_url 的场景)', async () => {
    const w = await mountSw({
      fixed_download_url: 'https://tm.internal/api/v1/software/fio/download',
    });
    const url = w.find('.fx-url').text();
    expect(url).toBe('https://tm.internal/api/v1/software/fio/download');
    w.unmount();
  });

  it('没有固定链接 (未上架) → 整块不显示', async () => {
    const w = await mountSw({ fixed_download_url: '' });
    expect(w.text()).not.toContain('固定下载链接');
    w.unmount();
  });

  it('⚠️ 链接里**不含版本号** —— 版本会变, 链接不能变', async () => {
    const w = await mountSw();
    const url = w.find('.fx-url').text();
    expect(url).not.toContain('3.42');
    expect(url).not.toContain('3.41');
    w.unmount();
  });
});
