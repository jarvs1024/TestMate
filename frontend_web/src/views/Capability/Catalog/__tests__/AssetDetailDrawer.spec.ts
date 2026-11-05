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
  recordMcpCopy: vi.fn(async () => ({ code: 'demo', copy_count: 3 })),
}));

vi.mock('@/api/assets', () => api);

const clipboard = vi.hoisted(() => ({
  copyToClipboard: vi.fn(async () => true),
}));

vi.mock('@/utils/clipboard', () => clipboard);

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

  it('⚠️ 「适用场景」显示出来 (2026-11-03 第二十二轮加回来)', async () => {
    // ⚠️ 2026-11-03 (第二十二轮) 翻转了 2026-10-25 的决定:
    //    以前整块删掉, 理由是"上传表单已经不让人填" —— 但后来发现上架表单里
    //    **压根没有**这几个输入框 → 新资产的字段恒为空 → 编辑页 4 个空框,
    //    详情页又只有包里的 SKILL.md → "编辑页和上架内容对不上".
    //    现在上架也能填 → 这里把它显示出来, 编辑完立刻可见.
    const w = await mountDrawer({ it: item({ use_when: '拿到 dmesg 时用它' }) });
    expect(w.text()).toContain('适用场景');
    expect(w.text()).toContain('拿到 dmesg 时用它');
  });

  it('「不适合的场景」「安装步骤」有值才显示 (没填就不占位)', async () => {
    const w = await mountDrawer({
      it: item({ use_when: '该用它时', not_for: '别用它时', install_steps: ['第一步', '第二步'] }),
    });
    expect(w.text()).toContain('别用它时');
    expect(w.text()).toContain('安装步骤');
    expect(w.text()).toContain('第一步');

    const w2 = await mountDrawer({ it: item({ use_when: '', not_for: '', install_steps: [] }) });
    expect(w2.text()).not.toContain('不适合的场景');
    expect(w2.text()).not.toContain('安装步骤');
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

  it('内置连接器 (builtin) 提示引导 API Token; 普通连接器仍是通用话术', async () => {
    const w = await mountDrawer({ it: item({ kind: 'mcp', builtin: true }) });
    const tip = w.findAll('.ins-tip')[0].text();
    expect(tip).toContain('API Token');
    expect(tip).toContain('<你的API Token>');

    const plain = await mountDrawer({ it: item({ kind: 'mcp', builtin: false }) });
    expect(plain.findAll('.ins-tip')[0].text()).toContain('连接器是配置型资产');
  });
});

/**
 * 下载次数 (2026-10-31 第十四轮; 2026-11-04 第二十四轮改口径).
 *
 * ⚠️ **连接器 (mcp) 没有安装包** —— 后端下载接口直接 400.
 *    2026-11-04 起 download_count 对连接器记的是「MCP 配置被复制的次数」,
 *    技术信息里显示「MCP 配置已复制 N 次」而不是「下载 N 次」.
 */
describe('详情抽屉 · 下载次数', () => {
  beforeEach(() => {
    api.downloadAssetPackage.mockClear();
  });

  it('技能/插件 → 技术信息里有「下载 N 次」', async () => {
    const w = await mountDrawer({ it: item({ kind: 'skill', download_count: 7 }) });
    await w.find('.tech-toggle').trigger('click');
    expect(w.text()).toContain('下载 7 次');
  });

  it('连接器 (mcp) → 技术信息显示「MCP 配置已复制 N 次」, 不写「下载」', async () => {
    const w = await mountDrawer({ it: item({ kind: 'mcp', download_count: 5 }) });
    await w.find('.tech-toggle').trigger('click');
    expect(w.text()).toContain('MCP 配置已复制 5 次');
    expect(w.text()).not.toContain('下载');
  });
});

/**
 * 连接器复制计数 (2026-11-04 第二十四轮).
 *
 * ⚠️ 用户原话: 「连接器加回下载图标, 计算方式是复制 json 配置
 *    (注意有两个复制按钮) 一次累加一次」——
 *    抽屉里**两个**复制按钮 (吸顶卡「复制 JSON」+ MCP 配置块「复制」)
 *    都走同一个 copyMcpConfig, 每次复制成功后 recordMcpCopy +1.
 */
describe('详情抽屉 · 连接器复制计数', () => {
  beforeEach(() => {
    clipboard.copyToClipboard.mockClear();
    api.recordMcpCopy.mockClear();
  });

  it('点「复制 JSON」→ 复制成功后计数 +1, 页面数字跟着刷新', async () => {
    api.recordMcpCopy.mockResolvedValue({ code: 'demo', copy_count: 4 });
    const w = await mountDrawer({
      it: item({ kind: 'mcp', download_count: 3, mcp_config: { mcpServers: { demo: { url: 'http://x' } } } }),
    });
    const btn = w.findAll('button').find((b) => b.text().replace(/\s+/g, '').includes('复制JSON'));
    expect(btn).toBeTruthy();
    await btn!.trigger('click');
    await flushPromises();
    expect(clipboard.copyToClipboard).toHaveBeenCalledTimes(1);
    expect(api.recordMcpCopy).toHaveBeenCalledWith('demo');
    await w.find('.tech-toggle').trigger('click');
    expect(w.text()).toContain('MCP 配置已复制 4 次');
  });

  it('两个复制按钮都计数 —— 各点一次 = 两次', async () => {
    api.recordMcpCopy.mockResolvedValue({ code: 'demo', copy_count: 9 });
    const w = await mountDrawer({
      it: item({ kind: 'mcp', mcp_config: { mcpServers: { demo: { url: 'http://x' } } } }),
    });
    const btns = w.findAll('button').filter((b) => b.text().includes('复制'));
    expect(btns.length).toBe(2);
    await btns[0].trigger('click');
    await flushPromises();
    await btns[1].trigger('click');
    await flushPromises();
    expect(api.recordMcpCopy).toHaveBeenCalledTimes(2);
  });

  it('复制失败 → 不计数', async () => {
    clipboard.copyToClipboard.mockResolvedValue(false);
    const w = await mountDrawer({
      it: item({ kind: 'mcp', mcp_config: { mcpServers: { demo: { url: 'http://x' } } } }),
    });
    const btn = w.findAll('button').find((b) => b.text().replace(/\s+/g, '').includes('复制JSON'));
    expect(btn).toBeTruthy();
    await btn!.trigger('click');
    await flushPromises();
    expect(api.recordMcpCopy).not.toHaveBeenCalled();
  });
});

/**
 * 内置资产 (2026-11-04 第二十四轮).
 *
 * ⚠️ 平台内置资产 (如「TestMate 扩展库助手」连接器) 不落 GitLab,
 *    底栏**不摆**编辑/下架/删除等作者动作 (后端本来就会 400),
 *    换成一行说明文字.
 */
describe('详情抽屉 · 内置资产', () => {
  it('内置资产 → 没有编辑/下架/删除按钮, 显示内置说明', async () => {
    const w = await mountDrawer({
      it: item({ builtin: true, kind: 'mcp', publish_status: 'published' }),
      role: 'admin',
    });
    const texts = buttonTexts(w).join(' ');
    expect(texts).not.toContain('编辑信息');
    expect(texts).not.toContain('发布新版本');
    expect(texts).not.toContain('申请下架');
    expect(texts).not.toContain('删除');
    expect(w.find('.ad-builtin-note').exists()).toBe(true);
    expect(w.find('.ad-builtin-note').text()).toContain('内置');
  });

  it('内置资产的「复制 JSON」仍在 (连接器配置可以照常复制)', async () => {
    const w = await mountDrawer({ it: item({ builtin: true, kind: 'mcp' }) });
    const btn = w.findAll('button').find((b) => b.text().replace(/\s+/g, '').includes('复制JSON'));
    expect(btn).toBeTruthy();
  });
});
