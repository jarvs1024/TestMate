/**
 * 设置页 —— **能力墙**的分类结构 + 软件库配置 + adminOnly 可见性.
 *
 * ⚠️ 盯的是 2026-10-28 这两轮:
 *   ① software.* 那 4 项后端一直有, 前端**从来没渲染过** —— 现在补上;
 *   ② 设置页整个只给管理员 —— 非管理员进来一个配置项都不该看到;
 *   ③ 设置页的分类要跟**首页能力墙**对齐: 📦 资产 / 🛠 工具 / 📊 看板,
 *      资产下面才是插件·技能·连接 / 知识库 / 软件库 三张卡;
 *   ④ 数据源各归各家 —— RAGFlow 跟知识库, ReviewAgent 跟代码检视看板.
 */
import { describe, expect, it, vi } from 'vitest';
import { mount, flushPromises } from '@vue/test-utils';

const { getSchema, updateSetting, testSoftwareStorage } = vi.hoisted(() => ({
  getSchema: vi.fn(),
  updateSetting: vi.fn(),
  testSoftwareStorage: vi.fn(),
}));

vi.mock('@/api/settings', () => ({
  getSchema: (...a: any[]) => getSchema(...a),
  updateSetting: (...a: any[]) => updateSetting(...a),
  testSoftwareStorage: (...a: any[]) => testSoftwareStorage(...a),
  testRagflow: vi.fn(async () => ({ ok: true, status: 'ok', message: 'ok', detail: null })),
  testReviewAgent: vi.fn(async () => ({ ok: true, status: 'ok', message: 'ok', detail: null })),
  testDingTalk: vi.fn(async () => ({ ok: true, status: 'ok', message: 'ok', detail: null })),
  testGitLab: vi.fn(async () => ({ ok: true, status: 'ok', message: 'ok', detail: null })),
}));

vi.mock('@/api/assets', () => ({
  getMarketConfig: vi.fn(async () => ({ workspace: '/tmp/ws', remote: 'git@x:y.git' })),
  listNotifications: vi.fn(async () => ({ items: [] })),
}));

vi.mock('@/api/users', () => ({
  listUsers: vi.fn(async () => []),
}));

vi.mock('element-plus', () => ({
  ElMessage: { success: vi.fn(), error: vi.fn() },
}));

import SettingsPage from '../index.vue';
import type { SettingItem } from '@/api/settings';
import { useUserStore } from '@/stores/user';
import { createPinia, setActivePinia } from 'pinia';

function schema(withSoftware = true) {
  // ⚠️ 要标类型 —— 否则 TS 把 'int' 推断成 string, 下面 value: 5120 就报错了
  const groups: { category: string; label: string; items: SettingItem[] }[] = [
    { category: 'search', label: '🔎 知识检索', items: [
      { key: 'search.engine', value: 'ragflow', value_type: 'string',
        description: '检索引擎', is_secret: false, is_default: true, default: 'ragflow' },
    ] },
    { category: 'chat', label: '💬 知识对话', items: [
      { key: 'chat.app_url', value: 'http://x/chat', value_type: 'string',
        description: '知识对话页地址', is_secret: false, is_default: true, default: '' },
    ] },
    { category: 'marketplace', label: '🧩 资产市场', items: [
      { key: 'marketplace.git.branch', value: 'main', value_type: 'string',
        description: 'Git 分支', is_secret: false, is_default: true, default: 'main' },
    ] },
    // ⚠️ 数据源 —— 现在要按能力分家 (RAGFlow→知识库, ReviewAgent→看板)
    { category: 'data-source', label: '📡 数据源', items: [
      { key: 'ragflow.base_url', value: 'http://rag/api', value_type: 'url',
        description: 'RAGFlow 地址', is_secret: false, is_default: true, default: '' },
      { key: 'ragflow.api_key', value: 'rk-xxx', value_type: 'secret',
        description: 'RAGFlow Key', is_secret: true, is_default: false, default: '' },
      { key: 'review_agent.base_url', value: 'http://ra/api', value_type: 'url',
        description: 'ReviewAgent 地址', is_secret: false, is_default: true, default: '' },
      { key: 'review_agent.api_token', value: 'tk-xxx', value_type: 'secret',
        description: 'ReviewAgent Token', is_secret: true, is_default: false, default: '' },
    ] },
    { category: 'general', label: '⚙️ 通用', items: [
      { key: 'general.platform_name', value: 'TestMate', value_type: 'string',
        description: '平台显示名', is_secret: false, is_default: false, default: '' },
    ] },
  ];
  if (withSoftware) {
    groups.push({
      category: 'software', label: '🧰 软件库',
      items: [
        { key: 'software.storage_path', value: '', value_type: 'string',
          description: '软件包存放根目录. 留空 = 用环境变量', is_secret: false, is_default: true, default: '' },
        { key: 'software.max_size_mb', value: 5120, value_type: 'int',
          description: '单个软件包大小上限 (MB)', is_secret: false, is_default: true, default: '5120' },
        { key: 'software.keep_versions', value: 10, value_type: 'int',
          description: '每个软件保留几个历史版本 —— 超出就把**最老的**清掉',
          is_secret: false, is_default: true, default: '10' },
        { key: 'software.public_download', value: false, value_type: 'bool',
          description: '未登录的人能不能下载软件包', is_secret: false, is_default: true, default: 'false' },
      ],
    });
  }
  return { groups, total: groups.reduce((n, g) => n + g.items.length, 0) };
}

async function mountPage(opts: { role?: 'admin' | 'tester'; withSoftware?: boolean } = {}) {
  getSchema.mockResolvedValueOnce(schema(opts.withSoftware !== false));
  const pinia = createPinia();
  setActivePinia(pinia);
  const userStore = useUserStore(pinia);
  const role = opts.role || 'admin';
  userStore.token = 'test-token';
  userStore.user = { id: 1, username: role, role } as any;

  const w = mount(SettingsPage, {
    global: { plugins: [pinia], stubs: { 'el-drawer': { template: '<div><slot/></div>' } } },
  });
  await flushPromises();
  await flushPromises();
  return { w, userStore };
}

/** 目录里的所有条目文本 (顶层 + 二层 + 三层) */
function tocTexts(w: any): string[] {
  return w.findAll('.set-toc .toc-item, .set-toc .toc-sub li').map((t: any) => t.text());
}

describe('设置页 · 能力墙的分类结构 (对齐首页能力墙)', () => {
  it('顶级只有「能力墙」, 不再有平级的「知识库」「软件库」', async () => {
    const { w } = await mountPage();
    const top = w.findAll('.set-toc > .toc-item').map((t) => t.text());
    expect(top.some((t) => t.includes('能力墙'))).toBe(true);
    // ⚠️ 以前是三个平级顶级项, 现在知识库/软件库都收进「能力墙 → 资产」下了
    expect(top.some((t) => t.includes('知识库'))).toBe(false);
    expect(top.some((t) => t.includes('软件库'))).toBe(false);
  });

  it('能力墙下面分 📦 资产 / 🛠 工具 / 📊 看板 三类', async () => {
    const { w } = await mountPage();
    const texts = tocTexts(w);
    expect(texts.some((t) => t.includes('资产'))).toBe(true);
    expect(texts.some((t) => t.includes('工具'))).toBe(true);
    expect(texts.some((t) => t.includes('看板'))).toBe(true);
  });

  it('资产下面挂三张卡: 插件·技能·连接 / 知识库 / 软件库', async () => {
    const { w } = await mountPage();
    const texts = tocTexts(w);
    expect(texts.some((t) => t.includes('插件·技能·连接'))).toBe(true);
    expect(texts.some((t) => t.includes('知识库'))).toBe(true);
    expect(texts.some((t) => t.includes('软件库'))).toBe(true);
  });

  it('数据源各归各家: RAGFlow 跟知识库, ReviewAgent 跟代码检视', async () => {
    const { w } = await mountPage();
    const kb = w.find('#sec-asset-kb');
    const board = w.find('#sec-board-code-review');
    expect(kb.exists()).toBe(true);
    expect(board.exists()).toBe(true);
    // RAGFlow 只能在知识库下面
    expect(kb.text()).toContain('RAGFlow');
    expect(kb.text()).toContain('ragflow.base_url');
    expect(board.text()).toContain('ReviewAgent');
    expect(board.text()).toContain('review_agent.base_url');
    // 反过来: 知识库下面不该有 ReviewAgent, 看板下面不该有 RAGFlow
    expect(kb.text()).not.toContain('review_agent.base_url');
    expect(board.text()).not.toContain('ragflow.base_url');
  });

  it('工具组显示出来, 并说清「暂无可配置项」', async () => {
    const { w } = await mountPage();
    const tool = w.find('#sec-tool');
    expect(tool.exists()).toBe(true);
    expect(tool.text()).toContain('还没有');
  });
});

describe('设置页 · 软件库 section', () => {
  it('点进软件库 → 4 项配置都列出来', async () => {
    const { w } = await mountPage();
    await w.findAll('.set-toc .toc-sub3 li')
      .find((t) => t.text().includes('软件库'))!.trigger('click');
    await flushPromises();
    const keys = w.findAll('.lbl-col code').map((c) => c.text());
    expect(keys).toContain('software.storage_path');
    expect(keys).toContain('software.max_size_mb');
    expect(keys).toContain('software.keep_versions');
    expect(keys).toContain('software.public_download');
  });

  it('有「体检存储目录」按钮 (换根目录不会自动搬文件, 得能查缺哪些)', async () => {
    const { w } = await mountPage();
    await w.findAll('.set-toc .toc-sub3 li')
      .find((t) => t.text().includes('软件库'))!.trigger('click');
    await flushPromises();
    const btn = w.findAll('button').find((b) => b.text().includes('体检存储目录'));
    expect(btn).toBeTruthy();
  });

  it('描述里的 **粗体** 渲染成 <strong> (不是一堆星号)', async () => {
    const { w } = await mountPage();
    await w.findAll('.set-toc .toc-sub3 li')
      .find((t) => t.text().includes('软件库'))!.trigger('click');
    await flushPromises();
    // software.keep_versions 的描述带 **最老的**
    const descs = w.findAll('.lbl-col .d').map((d) => d.html());
    expect(descs.some((d) => d.includes('<strong>'))).toBe(true);
    expect(descs.some((d) => d.includes('**'))).toBe(false);
  });
});

describe('设置页 · adminOnly', () => {
  it('非管理员: 一个配置项都不显示', async () => {
    const { w } = await mountPage({ role: 'tester' });
    expect(w.findAll('.lbl-col code').length).toBe(0);
  });

  it('非管理员: 明确说「设置仅管理员可见」', async () => {
    const { w } = await mountPage({ role: 'tester' });
    expect(w.text()).toContain('设置仅管理员可见');
  });

  it('非管理员: 目录也不显示 (连「配置目录」都不渲染)', async () => {
    const { w } = await mountPage({ role: 'tester' });
    expect(w.find('.set-toc').exists()).toBe(false);
  });

  it('管理员: 配置项正常显示', async () => {
    const { w } = await mountPage({ role: 'admin' });
    expect(w.findAll('.lbl-col code').length).toBeGreaterThan(0);
    expect(w.text()).not.toContain('设置仅管理员可见');
  });
});
