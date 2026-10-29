/**
 * **选择框全面整改的回归测试** (2026-10-29 · 第八轮).
 *
 * 用户报的问题有三个:
 *   ① 下拉框里的文字「显示不完全」—— 被截成「…」
 *   ② 「选中为啥会有白色」—— 选中/悬停时选项变成白底
 *   ③ 「很多选择框都这样」—— 要全量排查
 *
 * 根因 (三条, 都踩过):
 *   A. **Element Plus 的悬停态是 `.is-hovering` 这个类, 不是 `:hover` 伪类** ——
 *      以前只写了 `:hover`, 元素加上的 `.is-hovering` 一直没被覆盖,
 *      于是 `background-color: var(--el-fill-color-light)` (#f5f7fa 近白) 一直在生效
 *      → 暗色主题下就是「白底 + 浅色字」.
 *   B. **`el-option` 的 `label` 是选中后输入框里显示的那行字** —— 长文案放进去
 *      必被截断. 长解释应该放 slot 里(只在下拉列表那一行显示).
 *   C. **`--el-fill-color-light` 这一整套变量没被映射** —— 还是 Element 默认的浅色.
 *
 * ⚠️ CSS 没法在 jsdom 里真渲染出视觉效果, 所以这里用**源码断言**的方式锁住关键规则 ——
 *    这些规则一旦被删, 这个测试就会红. (之前正是因为「只写了 :hover」才出的 bug)
 */
import { describe, expect, it, vi } from 'vitest';
import { mount, flushPromises } from '@vue/test-utils';
import { readFileSync } from 'node:fs';
import path from 'node:path';
import { PLATFORMS } from '@/views/Software/softwareForm';

/**
 * ⚠️ 用 `process.cwd()` 定位, 不用 `import.meta.url` ——
 *    vitest 在 jsdom 环境里 import.meta.url 不是 file:// 协议,
 *    fileURLToPath() 会直接抛 "The URL must be of scheme file".
 *    vitest 的 cwd = 放 vitest.config.ts 的目录 (= frontend_web).
 */
const css = readFileSync(path.resolve(process.cwd(), 'src/styles/main.css'), 'utf-8');

describe('main.css: Element Plus 悬停/选中态必须被覆盖', () => {
  it('必须覆盖 `.is-hovering` —— Element 的悬停态是类, 不是 :hover 伪类', () => {
    // ⚠️ 少了这条, 暗色主题下悬停的选项就是白底 (用户报的那个 bug)
    expect(css).toMatch(/\.el-select-dropdown__item\.is-hovering/);
    expect(css).toMatch(/\.el-dropdown-menu__item[^{]*\.is-hovering/);
  });

  it('`.is-hovering` 的底色必须走项目 token, 不能是 Element 默认的近白色', () => {
    const m = css.match(/\.el-select-dropdown__item\.is-hovering\s*\{([^}]*)\}/);
    expect(m).toBeTruthy();
    expect(m![1]).toContain('var(--surface-sunken)');
    expect(m![1]).not.toContain('#f5f7fa');
  });

  it('选中项 (.is-selected) 必须有底色 —— Element 只给了 font-weight', () => {
    const m = css.match(/\.el-select-dropdown__item\.is-selected\s*\{([^}]*)\}/);
    expect(m).toBeTruthy();
    expect(m![1]).toMatch(/background/);
    expect(m![1]).toContain('var(--primary-soft)');
  });

  it('`.is-hovering` 和 `.is-selected` 都得有规则 —— 前者键盘/脚本态, 后者选中态', () => {
    // 悬停规则里 :hover 和 .is-hovering 必须成对出现 (鼠标态 + 键盘态)
    const hover = css.match(/\.el-select-dropdown__item:hover[^{]*\{[^}]*\}/);
    expect(hover).toBeTruthy();
    expect(hover![0]).toContain('background');
    expect(css).toMatch(/\.el-select-dropdown__item\.is-hovering\s*\{[^}]*background/);
    expect(css).toMatch(/\.el-select-dropdown__item\.is-selected\s*\{[^}]*background/);
  });
});

describe('main.css: Element 的填充色一整套变量都要映射', () => {
  const MUST_MAP = [
    '--el-fill-color-light',
    '--el-fill-color-lighter',
    '--el-fill-color-extra-light',
    '--el-fill-color-dark',
    '--el-fill-color-darker',
    '--el-disabled-bg-color',
    '--el-disabled-text-color',
    '--el-text-color-disabled',
    '--el-border-color-extra-light',
    '--el-border-color-dark',
    '--el-border-color-darker',
    '--el-bg-color',
    '--el-bg-color-page',
    '--el-bg-color-overlay',
    '--el-dropdown-menuItem-hover-fill',
    '--el-dropdown-menuItem-hover-color',
  ];

  it.each(MUST_MAP)('%s 必须映射到项目 token', (v) => {
    const m = css.match(new RegExp(`${v}:\\s*([^;]+);`));
    expect(m, `${v} 没定义`).toBeTruthy();
    // 必须指向项目自己的 token, 不能是 Element 的浅色硬编码
    expect(m![1]).toMatch(/var\(--[a-z]/);
  });

  it('遮罩色要么用项目 token, 要么是自带的半透明黑 (不能是 Element 默认的白)', () => {
    for (const v of ['--el-mask-color', '--el-mask-color-extra-light']) {
      const m = css.match(new RegExp(`${v}:\\s*([^;]+);`));
      expect(m, `${v} 没定义`).toBeTruthy();
      expect(m![1]).toMatch(/var\(--[a-z]|rgba\(/);
      expect(m![1]).not.toMatch(/#fff/i);
    }
  });

  it('不能出现 Element 里根本不存在的变量名 (写了也不生效, 等于没写)', () => {
    // ⚠️ 这三个是本轮踩过的坑: Element 的 checkbox 变量叫
    //    --el-checkbox-bg-color / --el-checkbox-checked-icon-color ...
    //    ⚠️ 只查「定义形式」(名字后面跟冒号), 不查注释里的提及 ——
    //       注释里要写清楚"这个名字不存在", 一并挡掉就没法记录教训了.
    const BOGUS = [
      '--el-checkbox-unchecked-bg-color',
      '--el-checkbox-checked-checkmark-color',
      '--el-checkbox-unchecked-checkmark-color',
    ];
    for (const v of BOGUS) {
      expect(css, `${v} 在 Element Plus 里不存在, 白写了`).not.toMatch(
        new RegExp(`${v}\\s*:`),
      );
    }
  });
});

describe('main.css: 暗色主题下不许露白底', () => {
  it('原生 <select> 的 <option> 必须有底色 —— 它不继承 select 的 background', () => {
    expect(css).toMatch(/select\s+option\s*\{/);
    const m = css.match(/select\s+option\s*\{([^}]*)\}/);
    expect(m![1]).toContain('background-color');
    // 必须是**不透明**的底 (半透明的 --surface 透出后面的文字会更乱)
    expect(m![1]).toContain('var(--bg-base)');
  });

  it('状态色的浅底 (light-9/8) 在暗色下要改成半透明主色', () => {
    const dark = css.match(/html\[data-theme="dark"\]\s*\{([^}]*)\}/);
    expect(dark).toBeTruthy();
    for (const c of ['success', 'warning', 'danger', 'error', 'info']) {
      expect(dark![1], `${c} 的 light-9 没处理`).toContain(`--el-color-${c}-light-9`);
    }
  });

  it('el-alert 的白底覆盖必须排除 .is-light —— 否则类型色被冲掉', () => {
    // ⚠️ el-alert 的 effect 默认就是 light, 裸 `.el-alert { background: ... !important }`
    //    会把黄色告警变成灰底 (本轮差点写错)
    const m = css.match(/\.el-alert[^{]*\{([^}]*)\}/);
    expect(m).toBeTruthy();
    expect(m![0]).toContain(':not(.is-light)');
  });
});

// ===== 组件层面: label 必须短 =====

vi.mock('@/api/software', () => ({
  createSoftware: vi.fn(async () => ({})),
  createSoftwareVersion: vi.fn(async () => ({})),
  uploadSoftwareFile: vi.fn(async () => ({})),
  getSoftwareConfig: vi.fn(async () => ({
    max_bytes: 1024,
    used_icons: { '🧰': 'SSD 日志医生' },
  })),
}));

/** 分类表 —— 跟后端 market_categories.py 的 5 类一致 (desc 是本轮改短后的) */
const CATEGORIES = [
  { name: '质量保障', slug: 'quality', desc: '兜住质量 · 定位问题、给判据' },
  { name: '效率工具', slug: 'efficiency', desc: '提效 · 自动化、造数、脚本' },
  { name: '流程规范', slug: 'process', desc: '守流程 · CI/CD、门禁、标准化' },
  { name: '管理协同', slug: 'management', desc: '管协同 · 进度、风险、沟通' },
  { name: 'MISC', slug: 'misc', desc: '归不到上面任何一类' },
];

vi.mock('@/api/assets', () => ({
  listAssets: vi.fn(async () => ({ items: [] })),
  listCategories: vi.fn(async () => ({ items: CATEGORIES })),
  listProjects: vi.fn(async () => ({
    items: [{ code: 'general', name: '通用', total: 0 }],
  })),
  getAsset: vi.fn(async () => ({})),
  getJob: vi.fn(async () => ({})),
  retryJob: vi.fn(async () => ({})),
  uploadAsset: vi.fn(async () => ({})),
  updateAsset: vi.fn(async () => ({})),
  previewPackage: vi.fn(async () => ({})),
}));

const stubs = {
  'el-drawer': { template: '<div class="el-drawer"><slot/></div>' },
  'el-form': { template: '<form><slot/></form>' },
  'el-form-item': { props: ['label'], template: '<div><slot/></div>' },
  'el-input': { template: '<input/>' },
  // ⚠️ stub 把 label 渲染成 data-label, 测试才能直接读到「选中后显示的那行字」
  'el-select': { props: ['modelValue'], template: '<select><slot/></select>' },
  'el-option': {
    props: ['label', 'value'],
    template: '<option class="el-option" :data-label="label"><slot/></option>',
  },
  'el-button': { template: '<button><slot/></button>' },
  'el-checkbox': { template: '<label><slot/></label>' },
};

describe('平台下拉: label 必须短, 长解释放 desc', () => {
  it('每个平台都有 desc, 且 label 里没有长破折号文案', () => {
    for (const p of PLATFORMS) {
      expect(p.desc, `${p.value} 缺 desc`).toBeTruthy();
      expect(p.label).not.toContain('——');
      expect(p.label.length).toBeLessThanOrEqual(12);
    }
  });

  it('「通用」就是「通用」两个字 —— 不再是「通用 —— 哪个平台都能用」', () => {
    const generic = PLATFORMS.find((p) => p.value === '')!;
    expect(generic.label).toBe('通用');
    expect(generic.desc).toBeTruthy();
  });

  it('组件里平台 option 的 label 就是短名', async () => {
    const { default: Dlg } = await import('@/views/Software/SoftwareUploadDialog.vue');
    const w = mount(Dlg, { props: { modelValue: false, mode: 'create' }, global: { stubs } });
    await w.setProps({ modelValue: true });
    await flushPromises();
    const labels = w.findAll('.el-option').map((o) => o.attributes('data-label'));
    for (const l of labels) {
      expect(l ?? '').not.toContain('——');
      expect((l ?? '').length).toBeLessThanOrEqual(12);
    }
  });
});

describe('图标下拉: 选中后只显示图标, 占用人信息放 slot', () => {
  it('被占用的图标 —— label 只是图标本身, 占用人显示在选项行里', async () => {
    const { default: Dlg } = await import('@/views/Software/SoftwareUploadDialog.vue');
    const w = mount(Dlg, { props: { modelValue: false, mode: 'create' }, global: { stubs } });
    // ⚠️ 抽屉的初始化挂在 `watch(modelValue)` 上 (没写 immediate) ——
    //    所以必须先挂 false 再 setProps true, 否则配置永远拉不下来
    await w.setProps({ modelValue: true });
    // ⚠️ used_icons 是打开抽屉后异步拉配置拉的 —— 得等它回来, 占用人才知道
    await flushPromises();
    await w.vm.$nextTick();

    const used = w.findAll('.el-option').find((o) => o.attributes('data-label') === '🧰');
    expect(used, '没找到 🧰 这个选项').toBeTruthy();
    // label 就是 emoji 本身 —— 不含「已被…用了」, 所以输入框里不会被截断
    expect(used!.attributes('data-label')).toBe('🧰');
    // 占用人信息在选项行里 (只在展开的下拉列表里出现)
    expect(used!.text()).toContain('已被');
    expect(used!.text()).toContain('SSD 日志医生');
  });
});

describe('分类下拉: 说明文字短, 且不把分类名挤掉', () => {
  it('分类 option 的 label 就是分类名本身 (说明文字只在 slot 里)', async () => {
    const { default: Dlg } = await import('@/views/Capability/Catalog/AssetUploadDialog.vue');
    // ⚠️ initialKind 必须给 —— 抽屉默认停在第 ① 步「选形态」, 不选就没有表单
    const w = mount(Dlg, {
      props: { modelValue: false, mode: 'create', initialKind: 'skill' },
      global: { stubs },
    });
    await w.setProps({ modelValue: true });
    await flushPromises();
    await w.vm.$nextTick();

    const opts = w.findAll('.el-option');
    const cats = opts.filter((o) => CATEGORIES.some((c) => c.name === o.attributes('data-label')));
    expect(cats.length, '分类下拉没渲染出来').toBe(CATEGORIES.length);

    for (const o of cats) {
      const name = o.attributes('data-label')!;
      const desc = CATEGORIES.find((c) => c.name === name)!.desc!;
      // label 就是分类名 —— 不夹带 desc
      expect(name).not.toContain('·');
      expect(name.length).toBeLessThanOrEqual(10);
      // desc 在选项行里, 且**短** —— 长的在下拉框里读不完
      expect(o.text()).toContain(desc);
      expect(desc.length).toBeLessThanOrEqual(24);
    }
  });
});
