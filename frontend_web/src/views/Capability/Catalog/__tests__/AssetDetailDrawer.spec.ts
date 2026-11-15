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
import ElementPlus, { ElMessageBox } from 'element-plus';
import AssetDetailDrawer from '../AssetDetailDrawer.vue';
import { useUserStore } from '@/stores/user';
import type { AssetComment, AssetItem } from '@/api/assets';

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
  listAssetComments: vi.fn(async (): Promise<{ items: AssetComment[]; total: number }> => ({ items: [], total: 0 })),
  createAssetComment: vi.fn(async (_code: string, content: string) => ({
    id: 101, code: 'demo', user_id: 1, username: 'jarvs', content,
    parent_id: null as number | null, can_delete: false, can_edit: true,
    created_at: '2026-11-15T10:00:00',
  })),
  updateAssetComment: vi.fn(async (_code: string, id: number, content: string) => ({
    id, code: 'demo', user_id: 1, username: 'jarvs', content,
    can_delete: false, can_edit: true, created_at: '2026-11-15T10:00:00',
  })),
  deleteAssetComment: vi.fn(async () => ({ ok: true, id: 7 })),
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

describe('资产详情抽屉 · 适用项目与推荐问法', () => {
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

  it('通用资产块是单行紧凑条 (副说明并进同一行)', async () => {
    const w = await mountDrawer({ it: item({ project: '' }) });
    expect(w.find('.ad-scope .sc-sub').text()).toContain('所有项目通用');

    const w2 = await mountDrawer({ it: item({ project: '6100' }) });
    expect(w2.find('.ad-scope .sc-sub').text()).toContain('仅 6100 项目可用');
  });

  it('「推荐问法」按行拆成多条, 每条带复制按钮', async () => {
    const w = await mountDrawer({
      it: item({ use_when: '帮我看下 6100 本周的测试结果\n分析这段 dmesg 日志' }),
    });
    expect(w.text()).toContain('推荐问法');
    const prompts = w.findAll('.ad-prompt');
    expect(prompts).toHaveLength(2);
    expect(prompts[0].text()).toContain('帮我看下 6100 本周的测试结果');
    expect(prompts[0].find('button').text()).toContain('复制');
  });

  it('点推荐问法旁的「复制」→ 复制那句原文', async () => {
    clipboard.copyToClipboard.mockClear();
    const w = await mountDrawer({ it: item({ use_when: '分析这段 dmesg 日志' }) });
    await w.find('.ad-prompt button').trigger('click');
    await flushPromises();
    expect(clipboard.copyToClipboard).toHaveBeenCalledWith('分析这段 dmesg 日志');
  });

  it('不再显示「适合 / 不适合」', async () => {
    const w = await mountDrawer({ it: item({ use_when: '该用它时', not_for: '别用它时' }) });
    expect(w.text()).not.toContain('适合');
    expect(w.text()).not.toContain('别用它时');
  });

  it('「推荐问法」有值才显示; 安装步骤不再展示', async () => {
    const w = await mountDrawer({
      it: item({ use_when: '该用它时', install_steps: ['第一步', '第二步'] }),
    });
    expect(w.text()).toContain('推荐问法');
    expect(w.text()).not.toContain('安装步骤');
    expect(w.text()).not.toContain('第一步');

    const w2 = await mountDrawer({ it: item({ use_when: '', not_for: '', install_steps: [] }) });
    expect(w2.text()).not.toContain('推荐问法');
    expect(w2.text()).not.toContain('安装步骤');
  });

  it('文档正文里的「## 安装步骤」段也一并隐藏, 其他小节照旧', async () => {
    api.getAssetDoc.mockResolvedValue({
      kind: 'skill', filename: 'SKILL.md', frontmatter: {},
      content: '# 用例模板生成\n\n## 适用场景\n\n展开用例\n\n## 安装步骤\n\n1. 复制目录\n2. 重启会话\n\n## 注意\n\n仅限本地',
    });
    try {
      const w = await mountDrawer();
      await flushPromises();
      const doc = w.find('.ad-doc');
      expect(doc.text()).toContain('适用场景');
      expect(doc.text()).toContain('展开用例');
      expect(doc.text()).not.toContain('安装步骤');
      expect(doc.text()).not.toContain('复制目录');
      expect(doc.text()).toContain('注意');
      expect(doc.text()).toContain('仅限本地');
    } finally {
      api.getAssetDoc.mockResolvedValue({ kind: 'skill', filename: 'SKILL.md', frontmatter: {}, content: '# x' });
    }
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

  it('内置连接器 (builtin) 提示引导访问令牌; 普通连接器仍是通用话术', async () => {
    const w = await mountDrawer({ it: item({ kind: 'mcp', builtin: true }) });
    const tip = w.findAll('.ins-tip')[0].text();
    expect(tip).toContain('访问令牌');
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
 * 「技术信息」折叠头 (2026-11-15 用户反馈: 展开符号太弱, 像个普通文字).
 * 锁住: 默认收起 + 有动作提示 + aria-expanded 跟状态同步.
 */
describe('详情抽屉 · 技术信息折叠头', () => {
  it('默认收起, 折叠头上有「展开」提示', async () => {
    const w = await mountDrawer();
    const btn = w.find('.tech-toggle');
    expect(btn.text()).toContain('展开');
    expect(btn.attributes('aria-expanded')).toBe('false');
    expect(w.find('.tech-body').isVisible()).toBe(false);
  });

  it('点开后提示变「收起」, aria-expanded=true, 内容可见', async () => {
    const w = await mountDrawer();
    await w.find('.tech-toggle').trigger('click');
    const btn = w.find('.tech-toggle');
    expect(btn.text()).toContain('收起');
    expect(btn.attributes('aria-expanded')).toBe('true');
    expect(w.find('.tech-body').isVisible()).toBe(true);
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
    const btns = w.findAll('button')
      .filter((b) => b.text().includes('复制') && !b.classes().includes('pr-copy'));
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

/**
 * 用户评论 (2026-11-15).
 *
 * 平铺展示, 最新在前; 发表后立刻出现在列表顶部; 删除入口只给本人/管理员
 * (后端按 can_delete 算, 前端照它显示).
 */
describe('资产详情抽屉 · 用户评论', () => {
  beforeEach(() => {
    api.listAssetComments.mockReset().mockResolvedValue({ items: [], total: 0 });
    api.createAssetComment.mockClear();
    api.updateAssetComment.mockClear();
    api.deleteAssetComment.mockClear();
  });

  it('空态: 没有评论时说「还没有评论」', async () => {
    const w = await mountDrawer();
    expect(w.find('.ad-comments').text()).toContain('还没有评论');
    expect(api.listAssetComments).toHaveBeenCalledWith('demo', { limit: 10, offset: 0 });
  });

  it('输入框提示引导写感受 / 建议 / 吐槽', async () => {
    const w = await mountDrawer();
    const ph = w.find('textarea').attributes('placeholder') || '';
    expect(ph).toContain('感受');
    expect(ph).toContain('建议');
    expect(ph).toContain('吐槽');
  });

  it('有评论 → 显示用户名 / 内容 / 时间; 编辑/删除按后端权限显示', async () => {
    api.listAssetComments.mockResolvedValue({
      items: [
        { id: 2, code: 'demo', user_id: 3, username: '别人', content: '挺好用',
          can_delete: false, can_edit: false, created_at: '2026-11-15T10:00:00' },
        { id: 1, code: 'demo', user_id: 1, username: 'jarvs', content: '第一条',
          can_delete: false, can_edit: true, created_at: '2026-11-14T09:00:00' },
      ],
      total: 2,
    });
    const w = await mountDrawer();
    const items = w.findAll('.cm-item');
    expect(items).toHaveLength(2);
    expect(items[0].text()).toContain('别人');
    expect(items[0].text()).toContain('挺好用');
    expect(items[0].find('.cm-del').exists()).toBe(false);
    expect(items[0].find('.cm-edit').exists()).toBe(false);
    // 自己的评论: 能编辑, 不能删 (删除只给管理员)
    expect(items[1].find('.cm-del').exists()).toBe(false);
    expect(items[1].find('.cm-edit').exists()).toBe(true);
    expect(w.find('.cm-count').text()).toBe('2');
  });

  it('发表评论 → 调接口, 新评论出现在最上面, 输入框清空', async () => {
    const w = await mountDrawer();
    await w.find('textarea').setValue('这个技能好用');
    const btn = w.findAll('button').find((b) => b.text().includes('发表评论'))!;
    expect(btn.attributes('disabled')).toBeUndefined();
    await btn.trigger('click');
    await flushPromises();
    expect(api.createAssetComment).toHaveBeenCalledWith('demo', '这个技能好用');
    expect(w.find('.cm-item').text()).toContain('这个技能好用');
    expect((w.find('textarea').element as HTMLTextAreaElement).value).toBe('');
  });

  it('空白内容 → 发表按钮禁用 (不请求接口)', async () => {
    const w = await mountDrawer();
    await w.find('textarea').setValue('   ');
    const btn = w.findAll('button').find((b) => b.text().includes('发表评论'))!;
    expect(btn.attributes('disabled')).toBeDefined();
  });

  it('管理员点删除 → 确认后调接口, 列表移除', async () => {
    api.listAssetComments.mockResolvedValue({
      items: [{ id: 7, code: 'demo', user_id: 1, username: 'jarvs', content: '旧评论',
                can_delete: true, created_at: '2026-11-14T09:00:00' }],
      total: 1,
    });
    const spy = vi.spyOn(ElMessageBox, 'confirm').mockResolvedValue('confirm' as any);
    const w = await mountDrawer();
    await w.find('.cm-del').trigger('click');
    await flushPromises();
    expect(api.deleteAssetComment).toHaveBeenCalledWith('demo', 7);
    expect(w.findAll('.cm-item')).toHaveLength(0);
    expect(w.find('.cm-count').exists()).toBe(false);
    spy.mockRestore();
  });

  it('编辑自己的评论 → 预填原文, 保存后原地更新', async () => {
    api.listAssetComments.mockResolvedValue({
      items: [{ id: 7, code: 'demo', user_id: 1, username: 'jarvs', content: '旧正文',
                can_delete: false, can_edit: true, created_at: '2026-11-14T09:00:00' }],
      total: 1,
    });
    const w = await mountDrawer();
    await w.find('.cm-edit').trigger('click');

    const form = w.find('.cm-edit-form');
    expect(form.exists()).toBe(true);
    const input = form.find('textarea');
    expect((input.element as HTMLTextAreaElement).value).toBe('旧正文');

    await input.setValue('新正文');
    await form.findAll('button').find((b) => b.text() === '保存')!.trigger('click');
    await flushPromises();

    expect(api.updateAssetComment).toHaveBeenCalledWith('demo', 7, '新正文');
    expect(w.find('.cm-edit-form').exists()).toBe(false);
    expect(w.find('.cm-item .cm-text').text()).toBe('新正文');
  });

  it('取消编辑 → 正文不变, 不调接口', async () => {
    api.listAssetComments.mockResolvedValue({
      items: [{ id: 7, code: 'demo', user_id: 1, username: 'jarvs', content: '旧正文',
                can_delete: false, can_edit: true, created_at: '2026-11-14T09:00:00' }],
      total: 1,
    });
    const w = await mountDrawer();
    await w.find('.cm-edit').trigger('click');
    await w.find('.cm-edit-form').findAll('button').find((b) => b.text() === '取消')!.trigger('click');

    expect(w.find('.cm-edit-form').exists()).toBe(false);
    expect(w.find('.cm-item .cm-text').text()).toBe('旧正文');
    expect(api.updateAssetComment).not.toHaveBeenCalled();
  });

  it('回复也能编辑 (权限按回复作者算)', async () => {
    api.listAssetComments.mockResolvedValue({
      items: [{ id: 5, code: 'demo', user_id: 3, username: '别人', content: '主评论',
                can_delete: false, can_reply: true,
                replies: [{ id: 9, code: 'demo', user_id: 1, username: 'jarvs', content: '旧回复',
                            parent_id: 5, can_delete: false, can_edit: true,
                            created_at: '2026-11-15T11:00:00' }],
                created_at: '2026-11-15T10:00:00' }],
      total: 1,
    });
    const w = await mountDrawer();
    await w.find('.cm-reply .cm-edit').trigger('click');
    const form = w.find('.cm-reply .cm-edit-form');
    expect(form.exists()).toBe(true);

    await form.find('textarea').setValue('新回复');
    await form.findAll('button').find((b) => b.text() === '保存')!.trigger('click');
    await flushPromises();

    expect(api.updateAssetComment).toHaveBeenCalledWith('demo', 9, '新回复');
    expect(w.find('.cm-reply .cm-text').text()).toBe('新回复');
  });

  it('还有更多 → 显示「加载更多」, 点击按已加载条数做 offset', async () => {
    api.listAssetComments.mockResolvedValue({
      items: [{ id: 1, code: 'demo', user_id: 1, username: 'jarvs', content: '一',
                can_delete: false, created_at: '2026-11-14T09:00:00' }],
      total: 12,
    });
    const w = await mountDrawer();
    const more = w.findAll('button').find((b) => b.text().includes('加载更多'))!;
    expect(more.text()).toContain('还有 11 条');
    await more.trigger('click');
    await flushPromises();
    expect(api.listAssetComments).toHaveBeenLastCalledWith('demo', { limit: 10, offset: 1 });
  });

  it('评论区在「技术信息」下方', async () => {
    const w = await mountDrawer();
    const html = w.html();
    expect(html.indexOf('ad-tech')).toBeGreaterThan(-1);
    expect(html.indexOf('ad-comments')).toBeGreaterThan(html.indexOf('ad-tech'));
  });

  it('can_reply 才显示「回复」按钮 (普通用户看不到)', async () => {
    api.listAssetComments.mockResolvedValue({
      items: [
        { id: 2, code: 'demo', user_id: 3, username: '别人', content: '问一下',
          can_delete: false, can_reply: false, created_at: '2026-11-15T10:00:00' },
        { id: 1, code: 'demo', user_id: 1, username: 'jarvs', content: '作者视角',
          can_delete: false, can_reply: true, created_at: '2026-11-14T09:00:00' },
      ],
      total: 2,
    });
    const w = await mountDrawer();
    const items = w.findAll('.cm-item');
    expect(items[0].findAll('button').some((b) => b.text() === '回复')).toBe(false);
    expect(items[1].findAll('button').some((b) => b.text() === '回复')).toBe(true);
  });

  it('回复: 点回复 → 发表 → 带 parent_id 调接口, 回复挂在主评论下', async () => {
    api.listAssetComments.mockResolvedValue({
      items: [{ id: 5, code: 'demo', user_id: 3, username: '别人', content: '主评论',
                can_delete: false, can_reply: true, replies: [],
                created_at: '2026-11-15T10:00:00' }],
      total: 1,
    });
    api.createAssetComment.mockResolvedValueOnce({
      id: 102, code: 'demo', user_id: 1, username: 'jarvs', content: '作者回复',
      parent_id: 5, can_delete: false, can_edit: true, created_at: '2026-11-15T11:00:00',
    });
    const w = await mountDrawer();
    const replyBtn = w.findAll('button').find((b) => b.text() === '回复')!;
    await replyBtn.trigger('click');

    const form = w.find('.cm-reply-form');
    expect(form.exists()).toBe(true);
    await form.find('textarea').setValue('作者回复');
    await form.findAll('button').find((b) => b.text() === '发表回复')!.trigger('click');
    await flushPromises();

    expect(api.createAssetComment).toHaveBeenCalledWith('demo', '作者回复', 5);
    expect(w.find('.cm-replies').text()).toContain('作者回复');
    expect(w.find('.cm-reply-form').exists()).toBe(false);
    expect(w.find('.cm-count').text()).toBe('1');
  });

  it('取消回复 → 收起输入框, 不调接口', async () => {
    api.listAssetComments.mockResolvedValue({
      items: [{ id: 5, code: 'demo', user_id: 3, username: '别人', content: '主评论',
                can_delete: false, can_reply: true, replies: [],
                created_at: '2026-11-15T10:00:00' }],
      total: 1,
    });
    const w = await mountDrawer();
    await w.findAll('button').find((b) => b.text() === '回复')!.trigger('click');
    await w.find('.cm-reply-form').findAll('button').find((b) => b.text() === '取消')!.trigger('click');
    expect(w.find('.cm-reply-form').exists()).toBe(false);
    expect(api.createAssetComment).not.toHaveBeenCalled();
  });

  it('删除回复 → 确认后调接口, 回复从列表移除', async () => {
    api.listAssetComments.mockResolvedValue({
      items: [{ id: 5, code: 'demo', user_id: 3, username: '别人', content: '主评论',
                can_delete: false, can_reply: true,
                replies: [{ id: 9, code: 'demo', user_id: 1, username: 'jarvs', content: '旧回复',
                            parent_id: 5, can_delete: true, created_at: '2026-11-15T11:00:00' }],
                created_at: '2026-11-15T10:00:00' }],
      total: 1,
    });
    const spy = vi.spyOn(ElMessageBox, 'confirm').mockResolvedValue('confirm' as any);
    const w = await mountDrawer();
    expect(w.find('.cm-replies').text()).toContain('旧回复');
    await w.find('.cm-reply .cm-del').trigger('click');
    await flushPromises();
    expect(api.deleteAssetComment).toHaveBeenCalledWith('demo', 9);
    expect(w.find('.cm-replies').exists()).toBe(false);
    // 主评论还在
    expect(w.find('.cm-item').text()).toContain('主评论');
    spy.mockRestore();
  });
});
