/**
 * **第二十一轮 · 下载到本地的安装包名不带版本号** (2026-11-03).
 *
 * 用户的要求:
 *   「下载技能和插件都不需要带版本号, 下载到本地就应该是 dml-xxx.zip
 *     而不是 dml-xxx-1.0.0.zip」
 *
 * 背景: 仓库里存的原始安装包叫 "{version}.zip" (1.0.0.zip / 1.1.0.zip …),
 *   以前直接把这个名字发给浏览器 → 用户存到本地全是 "1.0.0.zip",
 *   一屏下三四个扩展就互相覆盖, 还根本认不出谁是谁.
 *   code 才是这个扩展的**身份**, 所以文件名统一成 "{code}.zip".
 *
 * 锁住三件事:
 *   1. 纯函数 downloadFileName —— 文件名 = code + 真实后缀, **不含版本号**
 *   2. 详情抽屉里显示的文件名是 "{code}.zip"
 *   3. 真的点「下载」→ 落盘文件名是 "{code}.zip" (不是 "{code}-1.0.0.zip")
 */
import { describe, expect, it, vi, beforeEach } from 'vitest';
import { mount, flushPromises } from '@vue/test-utils';
import { createPinia, setActivePinia } from 'pinia';
import ElementPlus from 'element-plus';
import AssetDetailDrawer from '../AssetDetailDrawer.vue';
import { downloadFileName } from '../assetForm';
import { useUserStore } from '@/stores/user';
import type { AssetItem } from '@/api/assets';

const dl = vi.hoisted(() => ({ downloadBlob: vi.fn() }));
const msg = vi.hoisted(() => ({ success: vi.fn(), error: vi.fn(), warning: vi.fn() }));

const api = vi.hoisted(() => ({
  unpublishAsset: vi.fn(async () => ({ ok: true })),
  reviewUnpublish: vi.fn(async () => ({ ok: true })),
  cancelUnpublish: vi.fn(async () => ({ ok: true })),
  publishAsset: vi.fn(async () => undefined),
  reviewAsset: vi.fn(async () => ({ ok: true })),
  submitForReview: vi.fn(async () => ({ ok: true })),
  getAssetDoc: vi.fn(async () => ({ kind: 'skill', filename: 'SKILL.md', frontmatter: {}, content: '# x' })),
  deleteAsset: vi.fn(async () => ({ ok: true })),
  downloadAssetPackage: vi.fn(async () => new Blob(['x'])),
}));

vi.mock('@/api/assets', () => api);
vi.mock('@/utils/download', () => ({
  downloadBlob: dl.downloadBlob,
  nativeDownload: vi.fn(),
}));
// ⚠️ 只换掉 ElMessage —— el-button / el-drawer 这些组件还得用真的
vi.mock('element-plus', async (importOriginal) => {
  const actual = await importOriginal<typeof import('element-plus')>();
  return { ...actual, ElMessage: msg };
});

function item(over: Partial<AssetItem> = {}): AssetItem {
  return {
    code: 'dml-ssd-log-doctor', name: '演示资产', icon: '🧩', kind: 'skill', version: '1.0.0',
    summary: '摘要', description: '说明', use_when: '何时', not_for: '何时不',
    category: 'misc', project: '', tags: [], keywords: [], author: 'jarvs', featured: false,
    homepage: null, permissions: {}, install_steps: [], bindings: {},
    git_path: 'assets/skills/misc/demo', git_commit_sha: '', git_web_url: '',
    download_count: 0, updated_at: null,
    sync_status: 'pushed', last_error: '', publish_status: 'published',
    review_note: '', can_review: false,
    ...over,
  };
}

async function mountDrawer(opts: { it?: AssetItem } = {}) {
  const pinia = createPinia();
  setActivePinia(pinia);
  const store = useUserStore(pinia);
  store.user = { id: 1, username: 'jarvs', role: 'tester' };
  const w = mount(AssetDetailDrawer, {
    props: { modelValue: true, item: opts.it || item(), canEdit: true, reviewEnabled: undefined },
    global: { plugins: [pinia, ElementPlus] },
  });
  await flushPromises();
  return w;
}

beforeEach(() => {
  vi.clearAllMocks();
});

// ---------- 纯函数 ----------

describe('downloadFileName · 文件名不带版本号', () => {
  it('文件名 = code + .zip (不含版本号)', () => {
    expect(downloadFileName('dml-ssd-log-doctor')).toBe('dml-ssd-log-doctor.zip');
  });

  it('⚠️ 绝不出现 "-1.0.0.zip" 这种形态', () => {
    const name = downloadFileName('dml-ssd-log-doctor', 'application/zip');
    expect(name).not.toContain('-1.0.0');
    expect(name).not.toContain('1.0.0');
  });

  it('gzip 的包 → .tar.gz (别硬给个 .zip 的名字, 浏览器会当成 zip 解)', () => {
    expect(downloadFileName('dml-a', 'application/gzip')).toBe('dml-a.tar.gz');
  });

  it('code 里的危险字符被过滤 (文件名要进 Content-Disposition 头)', () => {
    expect(downloadFileName('dml-a"b')).toBe('dml-a_b.zip');
    expect(downloadFileName('dml-a\r\nX-Evil')).toBe('dml-a__X-Evil.zip');
    expect(downloadFileName('')).toBe('package.zip');
  });
});

// ---------- 详情抽屉 ----------

describe('详情抽屉 · 下载文件名', () => {
  it('安装卡上显示的是 "{code}.zip"', async () => {
    const w = await mountDrawer();
    expect(w.find('.ins-file').text()).toBe('dml-ssd-log-doctor.zip');
    expect(w.find('.ins-file').text()).not.toContain('1.0.0');
    w.unmount();
  });

  it('点「下载」→ 落盘文件名是 "{code}.zip"', async () => {
    const w = await mountDrawer();
    await w.find('.ins-btn').trigger('click');
    await flushPromises();

    expect(api.downloadAssetPackage).toHaveBeenCalledWith('dml-ssd-log-doctor', '1.0.0');
    expect(dl.downloadBlob).toHaveBeenCalledTimes(1);
    const filename = dl.downloadBlob.mock.calls[0][1];
    expect(filename).toBe('dml-ssd-log-doctor.zip');
    expect(String(filename)).not.toContain('1.0.0');
    w.unmount();
  });

  it('成功提示里也是 "{code}.zip"', async () => {
    const w = await mountDrawer();
    await w.find('.ins-btn').trigger('click');
    await flushPromises();

    expect(msg.success).toHaveBeenCalled();
    const text = String(msg.success.mock.calls[0][0]);
    expect(text).toContain('dml-ssd-log-doctor.zip');
    expect(text).not.toContain('1.0.0');
    w.unmount();
  });

  it('插件也一样 (技能/插件共用这条下载路径)', async () => {
    const w = await mountDrawer({ it: item({ kind: 'plugin' }) });
    expect(w.find('.ins-file').text()).toBe('dml-ssd-log-doctor.zip');
    await w.find('.ins-btn').trigger('click');
    await flushPromises();
    expect(dl.downloadBlob.mock.calls[0][1]).toBe('dml-ssd-log-doctor.zip');
    w.unmount();
  });
});
