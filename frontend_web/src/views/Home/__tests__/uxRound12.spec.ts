/**
 * **首页吸顶条压住卡片** (2026-10-30 · 第十二轮).
 *
 * 用户图: 「这里显示重叠在一起了」—— 首页第一排能力卡片的标题被一条横线穿过,
 * 卡片图标也被切掉一半. 红框圈的就是首页能力墙那一排.
 *
 * ⚠️ 根因 (别改回去):
 *   滚动容器是 `.tm-main` (MainLayout 里 `height:100vh; overflow:hidden`, 主区自己滚),
 *   它的顶边在**视口 y=70** (上面是 70px 高的 AppHeader).
 *   `position: sticky; top: 52px` 的 top 是相对**滚动容器**算的, 不是相对视口 →
 *   工具条被 sticky 规则**往下顶了 44px** (静态位置 78 → 122),
 *   结果它的下边框正好横在第一排卡片的标题上 (网格顶 156, 工具条底 184 → 重叠 28px).
 *
 * ✅ 修法: 工具条的 sticky 偏移 = **待办带的实测高度** (没有待办带就是 0),
 *   高度由 ResizeObserver 喂进 `--strip-h`.
 */
import { describe, expect, it } from 'vitest';
import { readFileSync } from 'node:fs';
import path from 'node:path';

const read = (p: string) => readFileSync(path.resolve(process.cwd(), p), 'utf-8');
/** ⚠️ 断言 CSS 源码前**必须先去掉注释** —— 注释里写着旧代码 (top: 52px) 会误导断言 */
const strip = (s: string) => s.replace(/\/\*[\s\S]*?\*\//g, '');

const homeRaw = read('src/views/Home/index.vue');
const home = strip(homeRaw);

describe('首页 · 吸顶条不再压住卡片', () => {
  it('工具条的 sticky 偏移要用 --strip-h, 不能写死 52px', () => {
    expect(home).toMatch(/position:\s*sticky;\s*top:\s*var\(--strip-h/);
    expect(home).not.toMatch(/position:\s*sticky;\s*top:\s*52px/);
  });

  it('待办带高度是**实测**的 (ResizeObserver), 不是写死的数字', () => {
    expect(homeRaw).toContain('ResizeObserver');
    expect(homeRaw).toContain('--strip-h');
    expect(homeRaw).toContain('offsetHeight');
  });

  it('待办带是 v-if 的 —— 元素换人时得重新挂观察', () => {
    // ⚠️ 待办带没出现时 (没有待办), 工具条必须退回 top:0,
    //    否则又会像以前那样被顶进网格里.
    expect(homeRaw).toMatch(/watch\(stripEl/);
  });

  it('工具条的 z-index 低于待办带 (有待办时待办压在上面)', () => {
    const tb = home.match(/\.home-toolbar\s*\{[\s\S]*?\}/)?.[0] || '';
    const strip = home.match(/\.todo-strip\s*\{[\s\S]*?\}/)?.[0] || '';
    const z = (s: string) => Number(s.match(/z-index:\s*(\d+)/)?.[1] ?? NaN);
    expect(Number.isNaN(z(tb))).toBe(false);
    expect(Number.isNaN(z(strip))).toBe(false);
    expect(z(tb)).toBeLessThan(z(strip));
  });
});
