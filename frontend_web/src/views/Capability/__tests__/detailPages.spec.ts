/**
 * 四个能力详情页的**装配冒烟测试** (2026-10-25 目录重组后加的).
 *
 * 为什么要有这个:
 *   目录从 views/{Plaza,AgentRunner,CodeReviewV2,Market,KnowledgeManage}
 *   重排成 views/{Home,Capability/*} 之后, 详情页的 import 路径全变了 ——
 *   少改一处就是运行时白屏, 而这种错误单测不 import 就发现不了.
 *   所以这里逐个把页面模块 import 一遍: 能不能加载, 一眼就知道.
 *
 * 另外钉住一条产品规则: **四个详情页都套了 CapabilityShell** ——
 * 详情页长得不一样会让用户以为进了另一个系统.
 */
import { describe, expect, it } from 'vitest';
import { readFileSync } from 'node:fs';
import { resolve } from 'node:path';

const VIEWS = [
  { name: '工具型 · ToolRunner', path: 'src/views/Capability/ToolRunner.vue' },
  { name: '看板型 · BoardView', path: 'src/views/Capability/BoardView.vue' },
  { name: '底座型 · Catalog', path: 'src/views/Capability/Catalog/index.vue' },
  { name: '底座型 · Library', path: 'src/views/Capability/Library/index.vue' },
];

describe('能力详情页 · 装配冒烟', () => {
  for (const v of VIEWS) {
    it(`${v.name} 能正常加载`, async () => {
      const mod = await import(/* @vite-ignore */ resolve(process.cwd(), v.path));
      expect(mod.default).toBeTruthy();
    });

    it(`${v.name} 套了统一外壳 CapabilityShell`, () => {
      const src = readFileSync(resolve(process.cwd(), v.path), 'utf8');
      expect(src).toContain('<CapabilityShell');
      // 外壳自带「← 返回工作台」, 页面里不该再有旧的「返回广场」
      expect(src).not.toContain('返回广场');
    });
  }

  it('首页是能力墙, 旧的「广场」页面已经挪走', () => {
    const home = readFileSync(resolve(process.cwd(), 'src/views/Home/index.vue'), 'utf8');
    expect(home).toContain('能力墙');
    // 目录里不该再有 views/Plaza —— 页面已经重排成 views/Home
    expect(() => readFileSync(resolve(process.cwd(), 'src/views/Plaza/index.vue'), 'utf8')).toThrow();
  });

  /**
   * 外壳的角色徽标靠 kind 渲染 —— kind 传错 (或传了已废弃的 catalog / library)
   * 会静默回退成「工具」, 用户看到底座卡挂着工具徽标, 还不报错.
   * 所以这里把每个详情页传给外壳的角色钉死.
   */
  it('详情页传给外壳的角色跟角色模型一致 (不留旧的 catalog / library)', () => {
    const board = readFileSync(resolve(process.cwd(), 'src/views/Capability/BoardView.vue'), 'utf8');
    expect(board).toContain('kind="board"');

    const catalog = readFileSync(resolve(process.cwd(), 'src/views/Capability/Catalog/index.vue'), 'utf8');
    expect(catalog).toContain('kind="platform"');
    expect(catalog).not.toContain('kind="catalog"');

    const library = readFileSync(resolve(process.cwd(), 'src/views/Capability/Library/index.vue'), 'utf8');
    expect(library).toContain('kind="platform"');
    expect(library).not.toContain('kind="library"');
  });

  /**
   * 描述不许重复 (2026-10-25 第四轮):
   *   页头 (AppHeader) 已经有 lede, 外壳再挂一个 summary 就是同一句话说两遍.
   *   四个详情页一律不许再往外壳传 summary —— 描述归位到正文.
   */
  it('四个详情页都不往外壳传 summary (描述归位到正文, 不跟页头重复)', () => {
    for (const v of VIEWS) {
      const src = readFileSync(resolve(process.cwd(), v.path), 'utf8');
      const tag = src.match(/<CapabilityShell[\s\S]*?\/>/)?.[0] ?? '';
      expect(tag, `${v.name} 没找到 CapabilityShell 标签`).toContain('CapabilityShell');
      expect(tag, `${v.name} 还在往外壳传 summary`).not.toContain('summary');
    }
  });

  it('工具型把描述放进正文 (它的页头没有 lede)', () => {
    const src = readFileSync(resolve(process.cwd(), 'src/views/Capability/ToolRunner.vue'), 'utf8');
    expect(src).toContain('run-lead');
    expect(src).toContain('agent.summary');
  });
});
