/**
 * 设置页「能力墙」分组的命名契约 (2026-10-26).
 *
 * 背景: 首页早就改叫「能力墙」了, 设置页却还挂着「🤖 智能体」——
 * 同一个功能两个页面两个名字, 用户会以为是两个东西, 来回找.
 * 这次把设置页改名统一, 并把内部 id 从 sec-agents 改成 sec-capability.
 *
 * 盯三件事:
 *   ① 分组标题和左侧目录都叫「能力墙」(图标 🗂️, 不是 📦 —— 📦 是"资产"角色专用);
 *   ② 内部 id 统一成 sec-capability —— 留着 sec-agents 会让人以为这个分组
 *      还是当年那套「智能体业务」配置 (Dify 下线后它早就是空壳了);
 *   ③ **渲染出去的字里不再出现「智能体」** —— 注释里提历史完全可以,
 *      但用户看到的必须是「能力」.
 *
 * ⚠️ 否定断言都打在「剥掉注释后」的文本上 —— 注释里本来就要提旧叫法
 *    (说明"以前叫什么、为什么改"), 拿原始源码去断言会误伤。
 */
import { describe, expect, it } from 'vitest';
import { readFileSync } from 'node:fs';
import { resolve } from 'node:path';

const SRC = readFileSync(resolve(process.cwd(), 'src/views/Settings/index.vue'), 'utf8');

/**
 * 剥掉注释, 只留真正会渲染出去的代码.
 *  · HTML 注释  <!-- ... -->
 *  · JS 块注释
 *  · JS 行注释  // ...
 */
function rendered(src: string): string {
  return src
    .replace(/<!--[\s\S]*?-->/g, '')
    .replace(/\/\*[\s\S]*?\*\//g, '')
    .split('\n')
    .map((line) => line.replace(/(^|\s)\/\/.*$/, '$1'))
    .join('\n');
}

const CODE = rendered(SRC);

describe('设置页 · 能力墙分组命名', () => {
  it('分组标题是「🗂️ 能力墙」', () => {
    expect(SRC).toContain('<span>🗂️ 能力墙</span>');
    expect(CODE).not.toContain('🤖 智能体');
  });

  it('左侧目录条目是「能力墙」, 内部 id 是 sec-capability', () => {
    expect(SRC).toContain("id: 'sec-capability'");
    expect(SRC).toContain("label: '能力墙'");
    expect(SRC).toContain("icon: '🗂️'");
    // 旧的内部 id 必须彻底消失 —— section 的 v-if / :id / onPickTop 都跟着它走
    expect(CODE).not.toContain('sec-agents');
  });

  it('渲染出去的代码里不再有「智能体」', () => {
    expect(CODE).not.toContain('智能体');
  });
});
