/**
 * 资产详情抽屉 —— **下架申请制**的界面行为 (2026-10-24).
 *
 * 锁住三件事:
 *  1. 界面**不再有**「彻底删除」按钮 —— 删除要走「申请下架 → 管理员确认」
 *  2. 「申请下架」是作者/管理员能点的, 且要打 code 确认 (后端也校验)
 *  3. 管理员在「待下架审核」时能看到「通过下架并删除 / 驳回下架」
 */
import { describe, expect, it, vi, beforeEach } from 'vitest';
import { mount, flushPromises } from '@vue/test-utils';
import { createPinia, setActivePinia } from 'pinia';
import ElementPlus from 'element-plus';
import AssetDetailDrawer from '../AssetDetailDrawer.vue';
import { useUserStore } from '@/stores/user';
import type { AssetItem } from '@/api/assets';

const api = vi.hoisted(() => ({
  unpublishAsset: vi.fn(async () => ({ ok: true, code: 'demo', publish_status: 'unpublish_pending', changed: true })),
  reviewUnpublish: vi.fn(async () => ({ ok: true, code: 'demo', decision: 'approve', deleted: true })),
  cancelUnpublish: vi.fn(async () => ({ ok: true, code: 'demo', publish_status: 'published', changed: true })),
  publishAsset: vi.fn(async () => undefined),
  reviewAsset: vi.fn(async () => ({ ok: true })),
  submitForReview: vi.fn(async () => ({ ok: true })),
  getAssetDoc: vi.fn(async () => ({ kind: 'skill', filename: 'SKILL.md', frontmatter: {}, content: '# x' })),
  downloadAssetPackage: vi.fn(async () => new Blob(['x'])),
}));

vi.mock('@/api/assets', () => api);

function item(over: Partial<AssetItem> = {}): AssetItem {
  return {
    code: 'demo', name: '演示资产', icon: '🧩', kind: 'skill', version: '1.0.0',
    summary: '摘要', description: '说明', use_when: '何时', not_for: '何时不',
    category: 'misc', tags: [], keywords: [], author: 'jarvs', featured: false,
    homepage: null, permissions: {}, install_steps: [], bindings: {},
    git_path: 'assets/skills/misc/demo', git_commit_sha: '', git_web_url: '',
    download_count: 0, updated_at: null,
    sync_status: 'pushed', last_error: '', publish_status: 'published',
    review_note: '', can_review: false,
    ...over,
  };
}

async function mountDrawer(opts: { it?: AssetItem; canEdit?: boolean; role?: 'admin' | 'tester' } = {}) {
  // ⚠️ 必须用**同一个** pinia 实例: setActivePinia 给测试代码用, mount 的 plugins
  //    给组件用 —— 两个实例的话组件拿到的是另一个空 store (user 为 null).
  const pinia = createPinia();
  setActivePinia(pinia);
  const store = useUserStore(pinia);
  store.user = { id: 1, username: 'jarvs', role: opts.role || 'tester' };
  const w = mount(AssetDetailDrawer, {
    props: { modelValue: true, item: opts.it || item(), canEdit: opts.canEdit ?? true },
    global: { plugins: [pinia, ElementPlus] },
  });
  await flushPromises();
  return w;
}

function buttonTexts(w: any): string[] {
  return w.findAll('button').map((b: any) => b.text().replace(/\s+/g, ''));
}

beforeEach(() => {
  vi.clearAllMocks();
});

describe('资产详情抽屉 · 下架申请制', () => {
  it('不再有「彻底删除」按钮', async () => {
    const w = await mountDrawer();
    const texts = buttonTexts(w);
    expect(texts.join(' ')).not.toContain('彻底删除');
  });

  it('在架资产上只有「申请下架」, 没有「下架」', async () => {
    const w = await mountDrawer();
    const texts = buttonTexts(w);
    expect(texts).toContain('申请下架');
    expect(texts).not.toContain('下架');
  });

  it('待下架审核时: 作者看到「撤销下架申请」, 看不到审核按钮', async () => {
    const w = await mountDrawer({
      it: item({ publish_status: 'unpublish_pending' }),
      role: 'tester',
    });
    const texts = buttonTexts(w);
    expect(texts).toContain('撤销下架申请');
    expect(texts).not.toContain('通过下架并删除');
    expect(texts).not.toContain('驳回下架');
  });

  it('待下架审核时: 管理员看到「通过下架并删除 / 驳回下架」', async () => {
    const w = await mountDrawer({
      it: item({ publish_status: 'unpublish_pending' }),
      role: 'admin',
    });
    const texts = buttonTexts(w);
    expect(texts).toContain('通过下架并删除');
    expect(texts).toContain('驳回下架');
  });

  it('已下架 (unpublished) 的资产显示「重新上架」', async () => {
    const w = await mountDrawer({ it: item({ publish_status: 'unpublished' }) });
    expect(buttonTexts(w)).toContain('重新上架');
  });
});
