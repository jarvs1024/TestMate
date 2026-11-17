/**
 * 评论深链定位 —— 从站内通知点进来时 (2026-11-16).
 *
 * 通知里带 comment=<id>: 抽屉打开后评论请求要带 focus_comment_id,
 * 目标评论 (回复则连同父评论) 要有高亮样式, 并且尝试滚到可见位置.
 */
import { describe, expect, it, vi } from 'vitest';
import { mount, flushPromises } from '@vue/test-utils';
import { createPinia, setActivePinia } from 'pinia';
import ElementPlus from 'element-plus';
import AssetDetailDrawer from '../AssetDetailDrawer.vue';
import { useUserStore } from '@/stores/user';
import type { AssetComment, AssetItem } from '@/api/assets';

const api = vi.hoisted(() => ({
  unpublishAsset: vi.fn(async () => ({ ok: true })),
  reviewUnpublish: vi.fn(async () => ({ ok: true })),
  cancelUnpublish: vi.fn(async () => ({ ok: true })),
  publishAsset: vi.fn(async () => undefined),
  reviewAsset: vi.fn(async () => ({ ok: true })),
  submitForReview: vi.fn(async () => ({ ok: true })),
  getAssetDoc: vi.fn(async () => ({ kind: 'skill', filename: 'SKILL.md', frontmatter: {}, content: '# x' })),
  downloadAssetPackage: vi.fn(async () => new Blob(['x'])),
  recordMcpCopy: vi.fn(async () => ({ code: 'demo', copy_count: 1 })),
  listAssetComments: vi.fn(),
  createAssetComment: vi.fn(),
  updateAssetComment: vi.fn(),
  deleteAssetComment: vi.fn(),
}));
vi.mock('@/api/assets', () => api);
vi.mock('@/utils/clipboard', () => ({ copyToClipboard: vi.fn(async () => true) }));

function item(): AssetItem {
  return {
    code: 'demo', name: '演示资产', icon: '🧩', kind: 'skill', version: '1.0.0',
    summary: '摘要', description: '说明', use_when: '', not_for: '',
    category: 'misc', project: '', tags: [], keywords: [], author: 'jarvs', featured: false,
    homepage: null, permissions: {}, install_steps: [], bindings: {},
    git_path: 'assets/skills/misc/demo', git_commit_sha: '', git_web_url: '',
    download_count: 0, updated_at: null,
    sync_status: 'pushed', last_error: '', publish_status: 'published',
    review_note: '', can_review: false,
  };
}

const root: AssetComment = {
  id: 400, code: 'demo', user_id: 2, username: 'zhangsan', content: '主评论',
  parent_id: null, can_delete: false, can_edit: false, can_reply: true,
  created_at: '2026-11-16T09:00:00',
};
const reply: AssetComment = {
  id: 501, code: 'demo', user_id: 3, username: 'lisi', content: '回复内容',
  parent_id: 400, can_delete: false, can_edit: false, can_reply: true,
  created_at: '2026-11-16T09:30:00',
};

async function mountDrawer(focusCommentId?: number) {
  const pinia = createPinia();
  setActivePinia(pinia);
  const store = useUserStore(pinia);
  store.user = { id: 1, username: 'jarvs', role: 'tester' };
  const w = mount(AssetDetailDrawer, {
    props: { modelValue: true, item: item(), canEdit: true, reviewEnabled: false, focusCommentId },
    global: { plugins: [pinia, ElementPlus] },
  });
  await flushPromises();
  return w;
}

describe('评论深链定位', () => {
  it('带 focusCommentId → 评论请求带 focus_comment_id', async () => {
    api.listAssetComments.mockResolvedValue({ items: [{ ...root, replies: [reply] }], total: 1 });
    await mountDrawer(501);
    expect(api.listAssetComments).toHaveBeenCalledWith(
      'demo', expect.objectContaining({ focus_comment_id: 501 }),
    );
  });

  it('目标评论高亮, 回复也带定位锚点', async () => {
    api.listAssetComments.mockResolvedValue({ items: [{ ...root, replies: [reply] }], total: 1 });
    const w = await mountDrawer(501);
    const target = w.find('[data-comment-id="501"]');
    expect(target.exists()).toBe(true);
    expect(target.classes()).toContain('cm-focus');
    // 父评论也有锚点, 便于回复定位
    expect(w.find('[data-comment-id="400"]').exists()).toBe(true);
  });

  it('没有 focusCommentId → 不带定位参数也不高亮', async () => {
    api.listAssetComments.mockResolvedValue({ items: [{ ...root, replies: [reply] }], total: 1 });
    const w = await mountDrawer();
    const params = api.listAssetComments.mock.calls.at(-1)?.[1] || {};
    expect(params.focus_comment_id).toBeUndefined();
    expect(w.find('.cm-focus').exists()).toBe(false);
  });
});
