/**
 * **浮层面板底色整改的回归测试** (2026-10-30 · 第十轮).
 *
 * 用户报的问题:
 *   "所有这种抽屉的地方, 上下背景不协调, 整体都不对劲, 不是一个整体了？
 *    改回之前全白色的？"
 *
 * ⚠️ **根因不是"半透明"本身, 是"同一个面板里叠了多层不同的底"**:
 *    ① `.el-drawer` 画一层 (第八轮 86c1414 起底色变成半透明的 --surface);
 *    ② `.el-drawer__body` 又画一层 (一条全局 !important, 注释还写着「确保 panel 不透明」);
 *    ③ 暗色主题下 header / body / message-box 各自再画一层.
 *    两层半透明叠出来的白 ≠ 一层半透明 → **header 比 body 暗** → 「上下不协调」.
 *
 * ✅ 修法 (两条, 缺一不可):
 *    ① **只有容器画一次底色** —— 内部 header / body 一律 transparent;
 *    ② **亮色底色必须完全不透明** (纯白), **暗色保持半透** (毛玻璃感).
 *
 * ⚠️ CSS 没法在 jsdom 里真渲染出视觉效果, 所以这里用**源码断言**锁住关键规则 ——
 *    这些规则一旦被删/被改回半透明, 这个测试就会红.
 */
import { describe, expect, it } from 'vitest';
import { readFileSync } from 'node:fs';
import path from 'node:path';

/**
 * ⚠️ 用 `process.cwd()` 定位 —— vitest 的 cwd = 放 vitest.config.ts 的目录 (= frontend_web).
 */
const cssRaw = readFileSync(path.resolve(process.cwd(), 'src/styles/main.css'), 'utf-8');
const tokensRaw = readFileSync(path.resolve(process.cwd(), 'src/styles/tokens.css'), 'utf-8');

/**
 * ⚠️ **断言前必须先去掉注释** ——
 *    这两个文件里到处是"教训注释" (比如「以前写成了 `... , @media (...) { ... }`」),
 *    不去注释的话, 正则会把注释里的示例当成真的规则 → 误判.
 */
const css = cssRaw.replace(/\/\*[\s\S]*?\*\//g, '');
const tokens = tokensRaw.replace(/\/\*[\s\S]*?\*\//g, '');

/** 取一条规则的内容 (按选择器特征定位) */
function ruleBody(src: string, selectorRe: RegExp): string {
  const m = src.match(selectorRe);
  expect(m, `没找到规则: ${selectorRe}`).toBeTruthy();
  return m![0];
}

describe('main.css: Element 的浮层底色变量必须指向 --surface-panel', () => {
  it('--el-bg-color (抽屉/对话框/确认框走它) 不能是半透明的 --surface', () => {
    const m = css.match(/--el-bg-color:\s*([^;]+);/);
    expect(m, '--el-bg-color 没定义').toBeTruthy();
    expect(m![1]).toContain('var(--surface-panel)');
    // ⚠️ 半透明的 --surface 盖在遮罩上 = 灰白
    expect(m![1]).not.toMatch(/var\(--surface\)/);
  });

  it('--el-bg-color-overlay (下拉菜单/气泡卡/通知走它) 不能是半透明的 --surface', () => {
    const m = css.match(/--el-bg-color-overlay:\s*([^;]+);/);
    expect(m, '--el-bg-color-overlay 没定义').toBeTruthy();
    expect(m![1]).toContain('var(--surface-panel)');
    expect(m![1]).not.toMatch(/var\(--surface\)/);
  });
});

describe('tokens.css: 亮色浮层必须完全不透明, 暗色保持半透', () => {
  it('亮色的 --surface-panel 必须是**不透明**的纯色 (不能带 alpha)', () => {
    // 取亮色块 (`:root, html[data-theme="light"]`) 里的定义
    const light = tokens.match(/:root,\s*html\[data-theme="light"\]\s*\{([\s\S]*?)\n\}/);
    expect(light, '没找到亮色 token 块').toBeTruthy();
    const m = light![1].match(/--surface-panel:\s*([^;]+);/);
    expect(m, '亮色没定义 --surface-panel').toBeTruthy();
    const v = m![1].trim();
    // ⚠️ 亮色下白底只要带一点 alpha, 背后的黑遮罩就透出来 → 纯白变灰白
    expect(v, `亮色 --surface-panel 不能半透明: ${v}`).not.toMatch(/rgba|hsla|\//);
    expect(v.toUpperCase()).toBe('#FFFFFF');
  });

  it('暗色的 --surface-panel 允许半透明 (毛玻璃感)', () => {
    const dark = tokens.match(/html\[data-theme="dark"\]\s*\{([\s\S]*?)\n\}/);
    expect(dark, '没找到暗色 token 块').toBeTruthy();
    const m = dark![1].match(/--surface-panel:\s*([^;]+);/);
    expect(m, '暗色没定义 --surface-panel').toBeTruthy();
    expect(m![1]).toBeTruthy();
  });

  it('auto + 系统暗色 也得有 --surface-panel (否则跟随系统时抽屉又变透明)', () => {
    const auto = tokens.match(/@media \(prefers-color-scheme: dark\)\s*\{[\s\S]*?html\[data-theme="auto"\]\s*\{([\s\S]*?)\n  \}/);
    expect(auto, '没找到 auto+暗色 token 块').toBeTruthy();
    expect(auto![1]).toMatch(/--surface-panel:/);
  });

  it('浮层内部填充色 (--fill-*) 三套主题都要有 —— 半透明填充盖在不透明面板上看不见', () => {
    for (const v of ['--fill-hover', '--fill-active', '--fill-disabled', '--fill-blank', '--border-panel']) {
      expect(tokens, `${v} 没定义`).toMatch(new RegExp(`${v}:`));
      // 每个主题块里都要有
      const blocks = tokens.split(/\{/).filter((b) => b.includes('--surface-panel'));
      expect(blocks.length, '主题块数量不对').toBeGreaterThanOrEqual(3);
      for (const b of blocks) {
        expect(b, `${v} 在某个主题块里缺失`).toContain(v);
      }
    }
  });
});

describe('main.css: 抽屉/对话框/确认框 —— 容器画底色, 内部一律透明', () => {
  it('容器 (.el-drawer/.el-dialog/.el-message-box) 必须用 --surface-panel', () => {
    const r = ruleBody(css, /\.el-drawer,\s*\.el-dialog,\s*\.el-message-box\s*\{[^}]*\}/);
    expect(r).toContain('var(--surface-panel)');
    expect(r).not.toMatch(/var\(--surface\)/);
  });

  it('内部 (header/body/content/btns) 必须是 transparent —— 不能再各自画一层底色', () => {
    const r = ruleBody(css, /\.el-drawer__header,\s*[\s\S]*?\.el-message-box__btns\s*\{[^}]*\}/);
    expect(r).toContain('background-color: transparent');
    // ⚠️ 这里要是还留着 --surface, header 和 body 就会各叠一层 → 上下不协调
    expect(r).not.toMatch(/var\(--surface/);
  });

  it('.el-drawer__body 不许再有全局的半透明底色 (老 bug: 注释写着「确保 panel 不透明」)', () => {
    // 全局那条 `.el-drawer__body { background-color: ... }` 必须不存在
    const m = css.match(/^\s*\.el-drawer__body\s*\{[^}]*\}/m);
    expect(m, '.el-drawer__body 还有一条独立的全局底色规则').toBeFalsy();
  });

  it('浮层内部的填充色必须用 --fill-* (不能是半透明的 --surface-sunken)', () => {
    const r = ruleBody(css, /\.el-drawer,\s*\.el-dialog,\s*\.el-message-box\s*\{[^}]*\}/);
    expect(r).toContain('var(--fill-hover)');
    expect(r).toContain('var(--fill-blank)');
    expect(r).not.toMatch(/var\(--surface-sunken\)/);
  });
});

describe('main.css: 弹层 (下拉菜单/选择框/气泡卡) 也要是不透明面板', () => {
  it('.el-popper 家族的底色必须是 --surface-panel', () => {
    const r = ruleBody(css, /\.el-popper,\s*\.el-dropdown-menu,\s*\.el-select-dropdown,\s*\.el-popover\s*\{[^}]*\}/);
    expect(r).toContain('var(--surface-panel)');
    expect(r).not.toMatch(/var\(--surface\)/);
  });

  it('弹层里的小箭头必须跟面板同色 —— 否则边缘露一圈', () => {
    const r = ruleBody(css, /\.el-popper \.el-popper__arrow::before[\s\S]*?\{[^}]*\}/);
    expect(r).toContain('var(--surface-panel)');
  });

  it('下拉项的悬停底色必须用 --fill-hover (半透明填充 = 白底盖白底 = 看不出来)', () => {
    const r = ruleBody(css, /\.el-select-dropdown__item\.is-hovering\s*\{[^}]*\}/);
    expect(r).toContain('var(--fill-hover)');
    expect(r).not.toContain('var(--surface-sunken)');
  });
});

describe('main.css: 遮罩 —— 三套主题分别写, 别写成非法语法', () => {
  it('不能出现「选择器列表里塞 @media」这种非法写法', () => {
    // ⚠️ 以前写的是 `html[data-theme="dark"] .el-overlay, @media (...) { ... }` ——
    //    选择器列表里不能出现 @media, 整条规则会被浏览器直接丢掉,
    //    「auto + 系统暗色」那档遮罩其实一直没生效.
    expect(css).not.toMatch(/,\s*@media/);
  });

  it('亮色遮罩 / 暗色遮罩 / auto+暗色遮罩 三档都得在', () => {
    expect(css).toMatch(/\.el-overlay\s*\{[^}]*rgba\(0,\s*0,\s*0,\s*0\.55\)/);
    expect(css).toMatch(/html\[data-theme="dark"\]\s+\.el-overlay\s*\{[^}]*rgba\(0,\s*0,\s*0,\s*0\.6\)/);
    expect(css).toMatch(/@media \(prefers-color-scheme: dark\)\s*\{\s*html\[data-theme="auto"\]\s+\.el-overlay\s*\{[^}]*0\.7/);
  });
});
