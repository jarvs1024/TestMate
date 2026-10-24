/**
 * 上传抽屉的**形态选择流程** (2026-10-24).
 *
 * 改之前: 抽屉默认就是「技能」表单, 要传连接器得滚到基础信息里改类型下拉,
 *         改完才知道表单会换成 JSON 配置 —— 选类型这一步被藏起来了。
 * 改之后: 入口先选形态 → 直接进对应表单; 抽屉里也能随时换回去。
 */
import { describe, expect, it, vi } from 'vitest';
import { mount } from '@vue/test-utils';
import AssetUploadDialog from '../AssetUploadDialog.vue';

// 抽屉一打开就会去拉分类表 / 现有资产图标 —— 这里把接口打桩
vi.mock('@/api/assets', () => ({
  listAssets: vi.fn(async () => ({ items: [] })),
  listCategories: vi.fn(async () => ({ items: [] })),
  getAsset: vi.fn(async () => ({})),
  getJob: vi.fn(async () => ({})),
  previewPackage: vi.fn(async () => ({})),
  retryJob: vi.fn(async () => ({})),
  uploadAsset: vi.fn(async () => ({})),
  updateAsset: vi.fn(async () => ({})),
}));

/** element-plus 组件打桩 —— 只留结构, 不关心内部实现 */
const stubs = {
  'el-drawer': { template: '<div class="el-drawer"><slot/><slot name="footer"/></div>' },
  'el-form': { template: '<form><slot/></form>' },
  'el-form-item': { template: '<div class="el-form-item"><slot/></div>' },
  'el-input': { template: '<input class="el-input"/>' },
  'el-select': { template: '<select class="el-select"><slot/></select>' },
  'el-option': { template: '<option/>' },
  'el-button': { template: '<button><slot/></button>' },
  'el-checkbox': { template: '<label><slot/></label>' },
};

async function open(props: Record<string, any> = {}) {
  const w = mount(AssetUploadDialog, {
    props: { modelValue: false, mode: 'create', ...props },
    global: { stubs },
  });
  // 抽屉是 modelValue 从 false → true 时才初始化的 (watch)
  await w.setProps({ modelValue: true });
  await w.vm.$nextTick();
  return w;
}

/** 一个够用的 AssetItem (测试只关心这几个字段) */
function assetOf(kind: string, code = 'dml-x') {
  return {
    code, kind, name: 'x', version: '1.0.0', summary: 's',
    description: '', use_when: '', not_for: '', category: '其他', icon: '🧩',
    featured: false, tags: [], keywords: [], install_steps: [], permissions: {},
  } as any;
}

describe('上传抽屉: 先选形态', () => {
  it('没带形态时先停在第 ① 步 —— 不再默认「技能」', async () => {
    const w = await open();
    expect(w.findAll('.kp-card').length).toBe(3);
    expect(w.find('.up-form').exists()).toBe(false);
  });

  it('选「连接器」→ 直接进 MCP 配置表单, 没有安装包', async () => {
    const w = await open();
    const card = w.findAll('.kp-card').find((c) => c.text().includes('连接器'))!;
    await card.trigger('click');
    expect(w.find('.up-form').exists()).toBe(true);
    expect(w.text()).toContain('MCP 配置');
    expect(w.find('.file-input').exists()).toBe(false);
  });

  it('选「技能」→ 进安装包表单', async () => {
    const w = await open();
    const card = w.findAll('.kp-card').find((c) => c.text().includes('技能'))!;
    await card.trigger('click');
    expect(w.find('.file-input').exists()).toBe(true);
    expect(w.text()).not.toContain('MCP 配置');
  });

  it('入口已选定形态 → 跳过第 ① 步, 直接是配置表单', async () => {
    const w = await open({ initialKind: 'mcp' });
    expect(w.findAll('.kp-card').length).toBe(0);
    expect(w.find('.up-form').exists()).toBe(true);
    expect(w.text()).toContain('MCP 配置');
  });
});

describe('上传抽屉: 类型头与换类型', () => {
  it('类型头显示当前形态', async () => {
    const w = await open({ initialKind: 'plugin' });
    expect(w.find('.type-bar').text()).toContain('插件');
  });

  it('点「更换类型」能退回第 ① 步', async () => {
    const w = await open({ initialKind: 'skill' });
    await w.find('.tb-change').trigger('click');
    expect(w.findAll('.kp-card').length).toBe(3);
  });

  it('表单里不再有「类型」下拉 —— 形态在第 ① 步就定了', async () => {
    const w = await open({ initialKind: 'skill' });
    // 抽屉里唯一的下拉是「分类」
    expect(w.findAll('.el-select').length).toBe(1);
  });

  it('更新版本时类型不可改 —— 没有「更换类型」按钮', async () => {
    const w = await open({ mode: 'update', asset: assetOf('skill') });
    expect(w.find('.tb-change').exists()).toBe(false);
    expect(w.find('.type-bar').text()).toContain('技能');
  });

  it('先开新建 (停在第 ① 步), 再开更新 → 直接进表单, 不会卡在选形态', async () => {
    const w = await open();
    expect(w.findAll('.kp-card').length).toBe(3);
    await w.setProps({ mode: 'update', asset: assetOf('plugin') });
    await w.setProps({ modelValue: false });
    await w.setProps({ modelValue: true });
    await w.vm.$nextTick();
    expect(w.find('.up-form').exists()).toBe(true);
    expect(w.find('.type-bar').text()).toContain('插件');
  });
});
