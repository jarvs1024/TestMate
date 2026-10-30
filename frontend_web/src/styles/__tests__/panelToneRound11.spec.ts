/**
 * **第十一轮 · 灰阶调浅 + 网格自适应的回归测试** (2026-10-30).
 *
 * 用户报的问题:
 *   图2「软件标识那块灰的跟别处不一样, 整体页面背景也跟其他不一样」
 *   图4「灰色颜色深了点, 其他地方类似」
 *   图1「小屏下显示异常」
 *
 * ✅ 修法:
 *   ① `--panel-surface-sunken` 从 #E2E8F0 (蓝灰, 跟 --ink-200 同值) 改成 #EDF1F7 (近白灰);
 *   ② 首页 / 资产市场的网格从「按视口断点」改成「按容器宽度自适应」(auto-fill + minmax).
 *
 * ⚠️ CSS 没法在 jsdom 里真渲染, 所以这里用**源码断言**锁住关键规则 ——
 *    这些规则一旦被改回去, 这个测试就会红.
 */
import { describe, expect, it } from 'vitest';
import { readFileSync } from 'node:fs';
import path from 'node:path';

const read = (p: string) => readFileSync(path.resolve(process.cwd(), p), 'utf-8');

/**
 * ⚠️ **断言前必须先去掉注释** ——
 *    这几个文件里到处是"教训注释" (比如「以前写的是 `repeat(3, ...)`」),
 *    不去注释的话, 正则会把注释里的示例当成真的规则 → 误判.
 */
const strip = (s: string) => s.replace(/\/\*[\s\S]*?\*\//g, '');

const tokens = strip(read('src/styles/tokens.css'));
const homeCss = strip(read('src/views/Home/index.vue'));
const catalogCss = strip(read('src/views/Capability/Catalog/index.vue'));

/** 取某个 token 在**亮色**区块里的值 */
function lightToken(name: string): string {
  // 亮色在文件前部, 暗色在 [data-theme="dark"] 之后 —— 只取第一处
  const re = new RegExp(`--${name}:\\s*([^;]+);`);
  const m = tokens.match(re);
  expect(m, `tokens.css 里没有 --${name}`).toBeTruthy();
  return m![1].trim();
}

/** #rrggbb → [r,g,b] */
function rgb(hex: string): [number, number, number] {
  const h = hex.replace('#', '').trim();
  return [
    parseInt(h.slice(0, 2), 16),
    parseInt(h.slice(2, 4), 16),
    parseInt(h.slice(4, 6), 16),
  ];
}

describe('tokens.css: 浮层里的灰阶必须是「近白灰」', () => {
  it('--panel-surface-sunken 不能回到 #E2E8F0 (跟 --ink-200 同值, 蓝灰很扎眼)', () => {
    const v = lightToken('panel-surface-sunken');
    expect(v.toUpperCase()).not.toBe('#E2E8F0');
    // 必须是浅色 (三通道都够亮)
    const [r, g, b] = rgb(v);
    expect(Math.min(r, g, b)).toBeGreaterThanOrEqual(0xE0);
  });

  it('三档 panel-surface 的层次还在 (sunken 比 surface 深、soft 比 surface 浅)', () => {
    const sunken = rgb(lightToken('panel-surface-sunken'));
    const surface = rgb(lightToken('panel-surface'));
    const soft = rgb(lightToken('panel-surface-soft'));
    const lum = (c: [number, number, number]) => c[0] + c[1] + c[2];
    expect(lum(sunken)).toBeLessThan(lum(surface));
    expect(lum(soft)).toBeGreaterThan(lum(surface));
  });

  it('--ink-200 不该再被当成浮层里的只读底色 (它是蓝灰)', () => {
    // ⚠️ 亮色 --ink-200 = #E2E8F0 —— 抽屉里那个突兀的灰块就是它.
    //    这个断言是**提醒**: 以后有人想拿它当浮层底色, 会看到这条.
    const ink200 = lightToken('ink-200');
    expect(ink200.toUpperCase()).toBe('#E2E8F0');
    expect(ink200.toUpperCase()).not.toBe(lightToken('panel-surface-sunken').toUpperCase());
  });
});

describe('网格: 必须按**容器宽度**自适应, 不能按视口断点', () => {
  it('首页 .grid 用 auto-fill + minmax', () => {
    expect(homeCss).toMatch(/\.grid\s*\{[^}]*grid-template-columns:\s*repeat\(auto-fill,\s*minmax\(/);
  });

  it('资产市场 .grid 用 auto-fill + minmax', () => {
    expect(catalogCss).toMatch(/\.grid\s*\{[^}]*grid-template-columns:\s*repeat\(auto-fill,\s*minmax\(/);
  });

  it('首页不能再有按视口断列数的媒体查询', () => {
    // ⚠️ 以前是 `@media (max-width: 1100px) { .grid { grid-template-columns: repeat(2, ...) } }`
    //    —— 视口 1280 时主区只剩 ~980px 却仍排 3 列, 卡片被挤扁 (用户图1).
    const m = homeCss.match(/@media[^{]*\{[^}]*\.grid\s*\{[^}]*grid-template-columns/g);
    expect(m, '首页还有按视口断列数的 .grid 规则').toBeFalsy();
  });

  it('资产市场不能再有按视口断列数的媒体查询', () => {
    const m = catalogCss.match(/@media[^{]*\{[^}]*\.grid\s*\{[^}]*grid-template-columns/g);
    expect(m, '资产市场还有按视口断列数的 .grid 规则').toBeFalsy();
  });
});

describe('窄屏不横向溢出', () => {
  it('首页工具条允许换行', () => {
    expect(homeCss).toMatch(/\.home-toolbar\s*\{[^}]*flex-wrap:\s*wrap/);
  });

  it('首页搜索框宽度可伸缩 (不再写死 190px)', () => {
    const m = homeCss.match(/\.search input\s*\{([^}]*)\}/);
    expect(m, '没找到 .search input 规则').toBeTruthy();
    expect(m![1]).not.toMatch(/width:\s*190px/);
    expect(m![1]).toMatch(/flex:\s*1/);
  });
});
