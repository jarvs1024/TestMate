/**
 * **软件库 · 第十一轮的三件事** (2026-10-30):
 *   ① 「软件标识」不再给用户看 —— 只显示软件名 (图2);
 *   ② 发新版本时可以选「新增一条」或「覆盖已有某一条」 (图3);
 *   ③ 软件详情页新增「编辑」按钮 (上传者 + 管理员) (图5).
 *
 * ⚠️ 为什么用源码断言 + 组件渲染混合:
 *   · ① ② 是**表单结构**的改动, jsdom 里 mount 一整个抽屉太重 (el-form/el-select
 *     依赖注入多), 源码断言更直接, 也更锁得住"别把它改回去";
 *   · ③ 是**按钮显隐**, 必须真渲染 —— 光看源码挡不住"prop 传错"这种错.
 */
import { describe, expect, it } from 'vitest';
import { readFileSync } from 'node:fs';
import path from 'node:path';

const read = (p: string) => readFileSync(path.resolve(process.cwd(), p), 'utf-8');
/** ⚠️ 断言前先去掉注释 —— 注释里全是"以前写的是…"的旧代码示例 */
const strip = (s: string) => s.replace(/\/\*[\s\S]*?\*\//g, '');

const uploadRaw = read('src/views/Software/SoftwareUploadDialog.vue');
const upload = strip(uploadRaw);
const uploadTpl = uploadRaw.split('<script setup')[0];   // 模板部分 (含注释)

describe('① 上架抽屉: 「软件标识」不再展示', () => {
  it('模板里不能再出现「软件标识 (自动生成)」这种标签', () => {
    expect(uploadTpl).not.toContain('软件标识 (自动生成)');
    expect(uploadTpl).not.toContain('自动生成');
  });

  it('不能再有「自动」标记 (.auto-tag)', () => {
    expect(upload).not.toContain('auto-tag');
  });

  it('那个突兀的蓝灰只读输入框样式 (.ro-input + --ink-200) 要删掉', () => {
    // ⚠️ 以前 `.ro-input :deep(.el-input__inner){ background: var(--ink-200) }`
    //    = #E2E8F0, 在纯白面板上特别扎眼 (用户图2 报的"背景跟别处不一样").
    expect(upload).not.toContain('ro-input');
    expect(upload).not.toMatch(/\.ro-input[\s\S]*--ink-200/);
  });

  it('⚠️ 2026-10-30 (第十二轮): **连只读展示软件名的那行也删了**', () => {
    // 用户原话「这里软件名称去掉, 不展示这个信息, 后端维护就好了, 只要保证不冲突」.
    // · code 由文件名派生, 后端保证唯一 (撞名自动加序号) —— 用户不用看;
    // · 「软件名」输入框在上面已经有了, 再显示一遍纯属重复.
    expect(uploadTpl).not.toContain('label="软件名称"');
    expect(upload).not.toContain('ro-text');
  });

  it('但「文件名派生的标识不合法」这个错误还得说 —— 挪到软件包那一段', () => {
    expect(upload).toContain('codeError');
    // 错误提示在**软件包**这一段 (不是在一个已删掉的 form-item 里)
    expect(uploadTpl).toMatch(/class="pick-err"[^>]*>\{\{\s*codeError\s*\}\}/);
  });

  it('缺项提示里不再报「软件标识」—— 改成「请先选择软件包」', () => {
    expect(upload).toContain('请先选择软件包');
    expect(upload).not.toMatch(/out\.push\('软件标识'\)/);
  });
});

describe('② 发新版本: 「新增 / 覆盖」二选一', () => {
  it('版本区要有二选一的按钮', () => {
    expect(uploadTpl).toContain('新增一个版本');
    expect(uploadTpl).toContain('覆盖已有版本');
  });

  it('提交时要把 replace_version 传给后端', () => {
    expect(upload).toMatch(/replace_version:\s*versionMode\.value === 'replace'/);
  });

  it('api 层要支持 replace_version 字段', () => {
    const api = strip(read('src/api/software.ts'));
    expect(api).toMatch(/createSoftwareVersion[\s\S]*?replace_version\?:/);
  });

  it('同名覆盖不算撞号 (覆盖的就是那一行)', () => {
    // ⚠️ 覆盖 1.0.0 → 1.0.0 是合法的; 撞到**别的**版本才拦.
    expect(upload).toMatch(/versionMode\.value === 'replace' && v === versionForm\.value\.replace_version/);
  });

  it('⚠️ 2026-10-31 (第十三轮): 默认选中「**覆盖已有版本**」', () => {
    // 用户要求: 发新版本时默认走「覆盖」(图1 里蓝色高亮的就是覆盖).
    expect(upload).toMatch(/const versionMode = ref<'new' \| 'replace'>\('replace'\)/);
  });

  it('⚠️ 但**没有可覆盖的版本时必须回落「新增」** (第一个版本只能新增)', () => {
    // 不回落的话: 下拉是空的 → required 校验过不去 → 提交直接卡住.
    expect(upload).toMatch(/if \(versionOptions\.value\.length\)/);
    expect(upload).toMatch(/versionMode\.value = 'new'/);
  });

  it('「设为推荐下载版本」复选框要保留 (多版本还要用)', () => {
    expect(uploadTpl).toContain('设为推荐下载版本');
  });

  it('⚠️ 2026-10-31 (第十三轮): 提示文案里**不能有字面的 markdown 星号**', () => {
    // 纯文本 UI 不渲染 Markdown —— `**原地换掉**` 会**字面显示**给用户看.
    // ⚠️ 断言前先去掉注释 (注释里全是"以前写的是…"的旧代码示例).
    const tplNoComment = uploadTpl.replace(/<!--[\s\S]*?-->/g, '');
    expect(tplNoComment).not.toContain('**');
  });
});

describe('③ 软件详情页: 「编辑」按钮只对有权限的人显示', () => {
  it('抽屉要有 canEdit prop 与 edit 事件', () => {
    const drawer = strip(read('src/views/Software/SoftwareDetailDrawer.vue'));
    expect(drawer).toMatch(/canEdit\?: boolean/);
    expect(drawer).toMatch(/\(e: 'edit', item: SoftwareDetail\)/);
  });

  it('编辑按钮的条件是 canEdit', () => {
    const drawerTpl = read('src/views/Software/SoftwareDetailDrawer.vue').split('<script setup')[0];
    expect(drawerTpl).toMatch(/v-if="canEdit"[^>]*>[\s\S]{0,80}?编辑/);
  });

  it('列表页要算出 canEdit (作者本人 或 管理员)', () => {
    const idx = strip(read('src/views/Software/index.vue'));
    expect(idx).toMatch(/const canEdit = computed/);
    expect(idx).toMatch(/isAuthor\(it\.author, userStore\.user\?\.username\)/);
  });

  it('isAuthor 要放在公共位置 (@/utils/author) —— 不能从资产市场目录反向 import', () => {
    const idx = strip(read('src/views/Software/index.vue'));
    expect(idx).toMatch(/from '@\/utils\/author'/);
    expect(idx).not.toMatch(/from '.*Capability\/Catalog\/identity'/);
    // 公共模块必须存在
    expect(read('src/utils/author.ts')).toContain('export function isAuthor');
  });
});
