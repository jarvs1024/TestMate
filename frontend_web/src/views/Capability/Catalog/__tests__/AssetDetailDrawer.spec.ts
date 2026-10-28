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
    category: 'misc', project: '', tags: [], keywords: [], author: 'jarvs', featured: false,
    homepage: null, permissions: {}, install_steps: [], bindings: {},
    git_path: 'assets/skills/misc/demo', git_commit_sha: '', git_web_url: '',
    download_count: 0, updated_at: null,
    sync_status: 'pushed', last_error: '', publish_status: 'published',
    review_note: '', can_review: false,
    ...over,
  };
}

async function mountDrawer(opts: {
  it?: AssetItem; canEdit?: boolean; role?: 'admin' | 'tester'; reviewEnabled?: boolean;
} = {}) {
  // ⚠️ 必须用**同一个** pinia 实例: setActivePinia 给测试代码用, mount 的 plugins
  //    给组件用 —— 两个实例的话组件拿到的是另一个空 store (user 为 null).
  const pinia = createPinia();
  setActivePinia(pinia);
  const store = useUserStore(pinia);
  store.user = { id: 1, username: 'jarvs', role: opts.role || 'tester' };
  const w = mount(AssetDetailDrawer, {
    props: {
      modelValue: true,
      item: opts.it || item(),
      canEdit: opts.canEdit ?? true,
      // ⚠️ 缺省**不传** reviewEnabled —— 测的正是"取不到开关时按开着处理"
      reviewEnabled: opts.reviewEnabled,
    },
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

  it('待下架审核时: 管理员看到「通过下架并删除」', async () => {
    const w = await mountDrawer({
      it: item({ publish_status: 'unpublish_pending' }),
      role: 'admin',
    });
    const texts = buttonTexts(w);
    expect(texts).toContain('通过下架并删除');
  });

  it('待下架审核时: 没有「驳回下架」按钮 (下架审核不支持驳回)', async () => {
    const w = await mountDrawer({
      it: item({ publish_status: 'unpublish_pending' }),
      role: 'admin',
    });
    expect(buttonTexts(w).join(' ')).not.toContain('驳回下架');
  });

  it('已下架 (unpublished) 的资产显示「重新上架」', async () => {
    const w = await mountDrawer({ it: item({ publish_status: 'unpublished' }) });
    expect(buttonTexts(w)).toContain('重新上架');
  });

  // ---------- 免审核 (审核总开关关掉) ----------

  it('免审时按钮是「下架」而不是「申请下架」', async () => {
    const w = await mountDrawer({ reviewEnabled: false });
    const texts = buttonTexts(w);
    expect(texts).toContain('下架');
    expect(texts).not.toContain('申请下架');
  });

  it('开关开着时按钮仍是「申请下架」', async () => {
    const w = await mountDrawer({ reviewEnabled: true });
    expect(buttonTexts(w)).toContain('申请下架');
  });

  it('取不到开关时按「开着」处理 (保守: 宁可多走一次审核)', async () => {
    // ⚠️ 这是 Vue Boolean prop 的坑: 不显式给 `default: undefined` 的话,
    //    缺省会被**强转成 false** —— "取不到 → 按开着处理" 就反成了
    //    "取不到 → 按免审处理" (方向正好反了: 拿不准时该多走一次审核).
    const w = await mountDrawer({ reviewEnabled: undefined });
    expect(buttonTexts(w)).toContain('申请下架');
  });
});

describe('资产详情抽屉 · 删除未上架的资产', () => {
  it('待审核 + 是作者本人 → 显示「删除」', async () => {
    const w = await mountDrawer({ it: item({ publish_status: 'pending', author: 'jarvs' }) });
    expect(buttonTexts(w).join(' ')).toContain('删除');
  });

  it('待审核但**不是**作者 → 不显示 (别人的东西不能删)', async () => {
    const w = await mountDrawer({ it: item({ publish_status: 'pending', author: '别人' }) });
    expect(buttonTexts(w).join(' ')).not.toContain('删除');
  });

  it('在架的资产 → 不显示「删除」 (必须走申请下架)', async () => {
    const w = await mountDrawer({ it: item({ publish_status: 'published', author: 'jarvs' }) });
    const labels = buttonTexts(w).join(' ');
    expect(labels).not.toContain('删除');
    expect(labels).toContain('申请下架');
  });

  it('被驳回 + 是作者本人 → 也显示「删除」 (留着也没用)', async () => {
    const w = await mountDrawer({ it: item({ publish_status: 'rejected', author: 'jarvs' }) });
    expect(buttonTexts(w).join(' ')).toContain('删除');
  });
});

describe('资产详情抽屉 · 适用项目与适用场景', () => {
  it('项目归属显示成「适用项目」', async () => {
    const w = await mountDrawer({ it: item({ project: '6100' }) });
    expect(w.find('.ad-scope').text()).toContain('6100');
  });

  it('形态并入「适用项目」块 (头部不再显示英文 kind)', async () => {
    const w = await mountDrawer({ it: item({ kind: 'plugin', project: '' }) });
    const scope = w.find('.ad-scope').text();
    expect(scope).toContain('通用资产');
    expect(scope).toContain('插件');
    // 头部不再有后端原值 (plugin)
    expect(w.find('.ad-meta').text()).not.toContain('plugin');
  });

  it('「适用场景」整块不存在 (上传表单已不让填, 页面不再重复一遍)', async () => {
    // ⚠️ 2026-10-25: 从"有内容才显示"改成**整块删掉** ——
    //    字段还在 (存量资产有值), 但页面上不再单列一块.
    const w = await mountDrawer({ it: item({ use_when: '拿到 dmesg 时用它' }) });
    expect(w.text()).not.toContain('适用场景');
    expect(w.text()).not.toContain('拿到 dmesg 时用它');
  });

  it('安装提示是通用话术, 不写死某个 Agent 的目录', async () => {
    const w = await mountDrawer({ it: item({ kind: 'skill' }) });
    // ⚠️ 主提示 (第一条 .ins-tip) 必须是通用话术
    const tip = w.findAll('.ins-tip')[0].text();
    expect(tip).toContain('导入');
    expect(tip).toContain('压缩包');
    expect(tip).not.toContain('~/.qoder-cn');
    // 目录只是**参考**, 折叠在 details 里 (想手动装的人点开看)
    expect(w.find('.ins-more').exists()).toBe(true);
    expect(w.find('.ins-more').text()).toContain('~/.qoder-cn');
  });
});
