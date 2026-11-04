/**
 * 上传抽屉的**形态选择流程** (2026-10-24).
 *
 * 改之前: 抽屉默认就是「技能」表单, 要传连接器得滚到基础信息里改类型下拉,
 *         改完才知道表单会换成 JSON 配置 —— 选类型这一步被藏起来了。
 * 改之后: 入口先选形态 → 直接进对应表单; 抽屉里也能随时换回去。
 */
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { flushPromises, mount } from '@vue/test-utils';
import AssetUploadDialog from '../AssetUploadDialog.vue';

const { requestGet } = vi.hoisted(() => ({ requestGet: vi.fn() }));

vi.mock('@/utils/request', () => ({ default: { get: requestGet } }));

// 抽屉一打开就会去拉分类表 / 现有资产图标 —— 这里把接口打桩
vi.mock('@/api/assets', () => ({
  listAssets: vi.fn(async () => ({ items: [] })),
  listCategories: vi.fn(async () => ({ items: [] })),
  listProjects: vi.fn(async () => ({
    items: [
      { code: 'general', name: '通用', total: 0 },
      { code: '6100', name: '6100', total: 0 },
    ],
  })),
  getAsset: vi.fn(async () => ({})),
  getJob: vi.fn(async () => ({})),
  previewPackage: vi.fn(async (file: File) => ({
    ok: true, filename: file.name, size_bytes: file.size, kind: 'skill',
    total_files: 1, files: ['SKILL.md'], doc_file: 'SKILL.md',
    has_skill_md: true, has_plugin_manifest: false, has_mcp_config: false,
    installable: true, block_reason: '', issues: [], warnings: [],
  })),
  retryJob: vi.fn(async () => ({})),
  uploadAsset: vi.fn(async () => ({})),
  updateAsset: vi.fn(async () => ({})),
}));

const rulesPayload = {
  code: {
    pattern: '^(?=.{3,64}$)[a-z0-9]+(?:-[a-z0-9]+)*$',
    example: 'ssd-log-doctor', min_length: 3, max_length: 64,
  },
  segment: {
    pattern: '^(?=.{3,64}$)[a-z0-9]+(?:-[a-z0-9]+)*$', min_length: 3, max_length: 64,
  },
  package: { suffixes: ['.zip', '.tar.gz', '.tgz'] },
  required: {
    create: {
      common: ['code', 'name', 'summary', 'category', 'version'],
      skill: ['package'], plugin: ['package'], mcp: ['mcp_config'],
    },
    update: {
      common: ['name', 'summary', 'category', 'version'],
      skill: ['package'], plugin: ['package'], mcp: ['mcp_config'],
    },
    edit: ['name', 'summary', 'category'],
  },
  categories: [{ name: '其他', slug: 'misc', desc: '', order: 99 }],
  projects: ['6100'],
  enforcement: {
    code_must_match_package: true,
    code_must_match_mcp_server: true,
    unknown_category: '其他',
    unknown_project: '',
  },
};

beforeEach(() => {
  requestGet.mockReset();
  requestGet.mockResolvedValue(rulesPayload);
});

/** element-plus 组件打桩 —— 只留结构, 不关心内部实现 */
const stubs = {
  'el-drawer': { template: '<div class="el-drawer"><slot/><slot name="footer"/></div>' },
  'el-form': { template: '<form><slot/></form>' },
  'el-form-item': {
    props: ['label'],
    template: '<div class="el-form-item"><label v-if="label">{{ label }}</label><slot/></div>',
  },
  'el-input': { template: '<input class="el-input"/>' },
  'el-select': { template: '<select class="el-select"><slot/></select>' },
  'el-option': {
    props: ['label'],
    template: '<option>{{ label }}<slot/></option>',
  },
  'el-button': { template: '<button><slot/></button>' },
  'el-checkbox': { template: '<label><slot/></label>' },
};

async function open(props: Record<string, any> = {}, opts: { attach?: boolean } = {}) {
  const w = mount(AssetUploadDialog, {
    props: { modelValue: false, mode: 'create', ...props },
    global: { stubs },
    // ⚠️ 默认 vue-test-utils 把组件挂在**脱离文档**的树上 —— 点它不会冒泡到
    //    document, "点外面收起"这种用例必须真挂上去才测得出来.
    ...(opts.attach ? { attachTo: document.body } : {}),
  });
  // 抽屉是 modelValue 从 false → true 时才初始化的 (watch)
  await w.setProps({ modelValue: true });
  await flushPromises();
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
    const labels = w.findAll('.el-form-item').map((f) => f.text());
    // 有分类 + 适用项目两个下拉, 但没有「类型」
    expect(labels.some((t) => t.includes('分类'))).toBe(true);
    expect(labels.some((t) => t.includes('适用项目'))).toBe(true);
    expect(labels.some((t) => t.includes('类型'))).toBe(false);
    expect(w.findAll('.el-select').length).toBe(2);
  });

  it('适用项目默认是通用, 且项目选项来自后端配置', async () => {
    const w = await open({ initialKind: 'skill' });
    const scope = w.findAll('.el-select').find((s) => s.text().includes('通用'));
    expect(scope).toBeTruthy();
    // 项目列表是配置 (设置项 extensions.projects) —— 下拉里要有它
    expect(scope!.text()).toContain('6100');
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

describe('上传抽屉: 表单内容', () => {
  it('⚠️ 上架时也能填 详细说明 / 适用场景 / 不适合的场景 / 安装步骤 (2026-11-03 加回来)', async () => {
    // ⚠️ 2026-11-03 (第二十二轮) 翻转了 2026-10-25 的决定:
    //    以前上架表单里**没有**这几项 → 新上架的资产这些字段恒为空 →
    //    以后进「编辑」看到 4 个空框, 而详情页明明有一大段说明 →
    //    用户看到的"编辑页和上架内容对不上".
    //    现在上架就能填 → 编辑有值 → 详情页显示, 闭环.
    const w = await open({ initialKind: 'skill' });
    const form = w.find('.up-form').text();
    expect(form).toContain('详细说明');
    expect(form).toContain('适用场景');
    expect(form).toContain('不适合的场景');
    expect(form).toContain('安装步骤');

    // 进阶信息块里仍然只留标签 / 关键词 —— 这几项不在"进阶"里, 在基础信息里
    const adv = w.find('.adv-body').text();
    expect(adv).toContain('标签');
    expect(adv).toContain('搜索关键词');
    expect(adv).not.toContain('设为精选');
    expect(adv).not.toContain('权限声明');
  });

  it('资产 code 是**只读展示**, 不给输入框 (它是包名派生的)', async () => {
    const w = await open({ initialKind: 'skill' });
    // 跟包要求放在同一个块里 —— code 是包名派生的, 挨着来源才说得清
    const view = w.find('.pkg-req .pr-code');
    expect(view.exists()).toBe(true);
    expect(view.text()).toContain('资产 code');
    // 没有任何 code 输入框 —— 用户改不了派生值
    expect(w.find('.pkg-req input').exists()).toBe(false);
  });

  it('进阶信息标题写明「可展开」', async () => {
    const w = await open({ initialKind: 'skill' });
    expect(w.find('.sec-hint').text()).toContain('可展开');
  });

  it('基础信息不再有「怎么填 / 三条约定」那类引导语', async () => {
    const w = await open({ initialKind: 'mcp' });
    expect(w.find('.guide').exists()).toBe(false);
    expect(w.text()).not.toContain('怎么填');
    expect(w.text()).not.toContain('三条约定');
  });

  it('安装包区写清这个形态对包的要求', async () => {
    const w = await open({ initialKind: 'skill' });
    const req = w.find('.pkg-req').text();
    expect(req).toContain('技能包要求');
    expect(req).toContain('小写字母/数字/连字符');
    expect(req).toContain('SKILL.md');
  });

  it('文件 accept 和命名提示使用当前服务端规则', async () => {
    requestGet.mockResolvedValue({
      ...rulesPayload,
      package: { suffixes: ['.bundle', '.tar.zst'] },
    });
    const w = await open({ initialKind: 'skill' });
    expect(w.find('.file-input').attributes('accept')).toBe('.bundle,.tar.zst');
    expect(w.find('.pkg-req').text()).toContain('小写字母/数字/连字符');
    expect(w.find('.pkg-req').text()).not.toContain('dml-');
  });

  it('插件形态的要求与技能不同', async () => {
    const w = await open({ initialKind: 'plugin' });
    const req = w.find('.pkg-req').text();
    expect(req).toContain('插件包要求');
    expect(req).toContain('README.md');
  });
});

/**
 * 2026-10-25 用户反馈: 刷新后上传页一打开就有两条红字 ——
 *   「请选择安装包」+「只能用小写字母/数字/连字符…」
 * 那是**校验时机**错, 不是残留 —— 表单还没开始填就报错了。
 */
describe('上传抽屉: 没开始填时不该有红字', () => {
  it('技能形态刚打开 → 没有任何红色错误提示', async () => {
    const w = await open({ initialKind: 'skill' });
    // 「还没选包」是缺项 —— 底部「还缺」清单会列, 不该以错误形式标红
    expect(w.text()).not.toContain('请选择安装包');
    // code 是派生值, 还没派生出来 → 不该报 code 格式错
    expect(w.text()).not.toContain('只能用小写字母/数字/连字符');
    // 真错误提示的位置 (选包后才会出现) 现在是空的
    expect(w.find('.pick-err').exists()).toBe(false);
    expect(w.find('.cv-err').exists()).toBe(false);
  });

  it('连接器形态刚打开 → 也没有红色错误提示', async () => {
    const w = await open({ initialKind: 'mcp' });
    expect(w.text()).not.toContain('请选择安装包');
    // 说明文案里本来就会提到字符集, 所以按**错误位置**判断, 不按全页文案判断
    expect(w.find('.cv-err').exists()).toBe(false);
    // 配置还没填 = 缺项, 不是错误 → 中性提示, 不标红
    expect(w.find('.mcp-msg.bad').exists()).toBe(false);
    expect(w.find('.mcp-msg').text()).toContain('还没填配置');
  });

  it('没选包时 code 只显示占位文案', async () => {
    const w = await open({ initialKind: 'skill' });
    const code = w.find('.pkg-req .pr-code .pc-val').text();
    expect(code).toContain('自动生成');
    expect(code).not.toContain('dml-');
  });

  it('选了包之后 → 显示出派生出来的 code', async () => {
    const w = await open({ initialKind: 'skill' });
    // 走组件自己的入口: 选文件 → 触发 watch 同步 code
    const file = new File(['x'], 'dml-weekly-report.zip');
    const input = w.find('input[type=file]').element as HTMLInputElement;
    Object.defineProperty(input, 'files', { value: [file], writable: true });
    await w.find('input[type=file]').trigger('change');
    await w.vm.$nextTick();
    expect(w.find('.pkg-req .pr-code .pc-val').text()).toContain('dml-weekly-report');
  });

  it('把文件拖进选择区 → 也能选中安装包', async () => {
    const w = await open({ initialKind: 'skill' });
    const file = new File(['x'], 'dml-dropped.zip');
    await w.find('.file-pick').trigger('drop', { dataTransfer: { files: [file] } });
    await w.vm.$nextTick();
    expect(w.find('.pick-hint').exists()).toBe(false);
    expect(w.find('.file-chip').text()).toContain('dml-dropped.zip');
    expect(w.find('.pkg-req .pr-code .pc-val').text()).toContain('dml-dropped');
  });

  it('选择安装包按钮复用全局主按钮 (和「＋ 上传资产」同一套渐变)', async () => {
    const w = await open({ initialKind: 'skill' });
    const btn = w.find('.file-pick .pick-btn');
    expect(btn.classes()).toContain('mini-btn');
    expect(btn.classes()).toContain('primary');
  });

  it('连接器名文案: 新建/更新都只要求小写字母/数字/连字符', async () => {
    const w = await open({ initialKind: 'mcp' });
    expect(w.find('.pkg-req').text()).toContain('只能用小写字母/数字/连字符');
    expect(w.find('.pkg-req').text()).not.toContain('dml-');
    const w2 = await open({ mode: 'update', asset: assetOf('mcp') });
    expect(w2.find('.pkg-req').text()).toContain('只能用小写字母/数字/连字符');
  });
});

describe('上传抽屉: 图标面板', () => {
  /**
   * ⚠️ element-plus 的抽屉内容层带 `@click.stop` —— 冒泡阶段的事件到不了 document。
   *    所以「点外面收起」必须用**捕获阶段**监听, 否则在抽屉里点外面永远收不到。
   *    这个测试刻意模拟那层 stopPropagation, 防止有人改回冒泡阶段。
   */
  function stopPropagationLikeDrawer(w: any) {
    const drawer = w.find('.up-drawer').element as HTMLElement;
    drawer.addEventListener('click', (e) => e.stopPropagation());
    return drawer;
  }

  it('点外面 → 收起面板 (用户 2026-10-25 提的)', async () => {
    const w = await open({ initialKind: 'skill' });
    await w.find('.icon-btn').trigger('click');
    expect(w.find('.icon-panel').exists()).toBe(true);
    // 点面板外面 (空白处) → 收起
    document.body.dispatchEvent(new MouseEvent('click', { bubbles: true }));
    await w.vm.$nextTick();
    expect(w.find('.icon-panel').exists()).toBe(false);
  });

  it('抽屉里点外面也能收起 (抽屉内容层有 @click.stop)', async () => {
    const w = await open({ initialKind: 'skill' }, { attach: true });
    try {
      await w.find('.icon-btn').trigger('click');
      expect(w.find('.icon-panel').exists()).toBe(true);
      const drawer = stopPropagationLikeDrawer(w);
      // 点抽屉里的空白处 (冒泡会被抽屉吞掉 → 只有捕获阶段才收得到)
      drawer.dispatchEvent(new MouseEvent('click', { bubbles: true }));
      await w.vm.$nextTick();
      expect(w.find('.icon-panel').exists()).toBe(false);
    } finally {
      w.unmount();
    }
  });

  it('点面板**里面** → 不收起 (不然选图标选不中)', async () => {
    const w = await open({ initialKind: 'skill' });
    await w.find('.icon-btn').trigger('click');
    const cell = w.findAll('.icon-cell')[0];
    await cell.trigger('click');
    await w.vm.$nextTick();
    // 选了图标 → 面板自己收起
    expect(w.find('.icon-panel').exists()).toBe(false);
  });

  it('点图标按钮本身 → 也能收起 (老行为别丢)', async () => {
    const w = await open({ initialKind: 'skill' });
    await w.find('.icon-btn').trigger('click');
    expect(w.find('.icon-panel').exists()).toBe(true);
    await w.find('.icon-btn').trigger('click');
    await w.vm.$nextTick();
    expect(w.find('.icon-panel').exists()).toBe(false);
  });
});
