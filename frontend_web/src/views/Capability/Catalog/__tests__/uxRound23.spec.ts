/**
 * **第二十三轮验收** (2026-11-04).
 *
 * 用户提的三件事:
 *   ① 图1: 扩展详情抽屉里那个「下载」按钮 —— 样式要跟「＋ 上传资产」一样
 *   ② 图3: 「扩展」改名「扩展库」 (页头标题 + 侧栏导航两处)
 *   ③ 图4: 侧栏顶部那个「能力」区块标题 —— 用户问有没必要保留
 *
 * 这个文件锁的是**结构/文案**层面的东西:
 *   按钮用的是哪套 class、名字到底叫什么、那个标题还在不在。
 * 交互行为在各自的组件测试里 (uxRound21 的下载流程 / CapabilityNav.spec 的导航)。
 */
import { describe, expect, it } from 'vitest';
import { readFileSync } from 'node:fs';
import { resolve } from 'node:path';

const read = (p: string) => readFileSync(resolve(process.cwd(), p), 'utf8');

const detailDrawer = read('src/views/Capability/Catalog/AssetDetailDrawer.vue');
const catalogView = read('src/views/Capability/Catalog/index.vue');
const capNav = read('src/components/CapabilityNav.vue');
const routerTs = read('src/router/index.ts');
const settingsView = read('src/views/Settings/index.vue');
const assetCard = read('src/views/Capability/Catalog/AssetCard.vue');
const auditDrawer = read('src/views/Capability/Catalog/AssetAuditDrawer.vue');

// ═══════════════ ① 下载按钮样式 ═══════════════

describe('① 下载按钮 —— 跟「＋ 上传资产」同一套样式 (2026-11-04)', () => {
  it('下载按钮用的是 .mini-btn.primary, 不是 el-button type="primary"', () => {
    // ⚠️ 病根: 以前是 <el-button type="primary" class="ins-btn"> + width:100%
    //    → 一整块实心大蓝条, 跟平台其它按钮完全不是一个长相
    expect(detailDrawer).toMatch(/<button[^>]*class="mini-btn primary ins-btn"/);
    expect(detailDrawer).not.toMatch(/<el-button[^>]*class="ins-btn"/);
  });

  it('不再撑满整行 (去掉 width: 100%)', () => {
    expect(detailDrawer).not.toMatch(/\.ins-btn\s*\{[^}]*width:\s*100%/);
  });

  it('按钮文案必须还是纯「下载」 —— e2e/单测按文本精确匹配', () => {
    // 下载箭头走 CSS ::before, 不进 textContent
    expect(detailDrawer).toMatch(/\.ins-btn::before/);
    // 只看按钮这一行的内容 —— 标题「⬇ 下载安装包」里也有 ⬇, 不能一刀切
    const btnTag = detailDrawer.match(/<button[^>]*ins-btn[^>]*>[^<]*/)?.[0] || '';
    expect(btnTag).toBeTruthy();
    expect(btnTag).not.toContain('⬇');
    expect(btnTag).toContain('下载');
  });

  it('.mini-btn.primary 是全局样式 —— 两边共用一份 (styles/main.css)', () => {
    const mainCss = read('src/styles/main.css');
    expect(mainCss).toMatch(/\.mini-btn\.primary\s*\{/);
    // 主按钮 = 渐变 (蓝→靛→青), 不是实心蓝
    expect(mainCss).toMatch(/\.mini-btn\.primary\s*\{[^}]*primary-grad/);
  });

  it('按钮跟文件名**同一行** (标题 | 文件名 | 下载按钮)', () => {
    // ⚠️ 独占一行 + width:100% 的年代, 整个安装卡的重心全被按钮抢走.
    //    现在挤在标题行里, 一屏看完.
    const head = detailDrawer.match(/<div class="ins-h">[\s\S]*?<\/div>/)?.[0] || '';
    expect(head).toContain('ins-btn');
    expect(head).toContain('ins-file');
  });

  it('文件名太长时被省略, 按钮不被挤出卡片', () => {
    expect(detailDrawer).toMatch(/\.ins-file\s*\{[^}]*text-overflow:\s*ellipsis/);
    expect(detailDrawer).toMatch(/\.ins-btn\s*\{[^}]*flex-shrink:\s*0/);
  });
});

// ═══════════════ ② 扩展 → 扩展库 ═══════════════

describe('② 「扩展」改名「扩展库」 (2026-11-04)', () => {
  it('页头标题是「扩展库」 (路由 meta)', () => {
    expect(routerTs).toMatch(/name:\s*'extensions',\s*meta:\s*\{[^}]*title:\s*'扩展库'/);
    expect(routerTs).not.toMatch(/title:\s*'扩展'/);
  });

  it('页面 CapabilityShell 的身份名是「扩展库」', () => {
    expect(catalogView).toMatch(/<CapabilityShell\s+name="扩展库"/);
  });

  it('设置页的目录项也是「扩展库」', () => {
    expect(settingsView).toMatch(/label:\s*'🧩 扩展库'/);
    expect(settingsView).toMatch(/<h4>🧩 扩展库/);
  });

  it('用户可见的「出现在扩展里」这类说法统一改成「扩展库」', () => {
    expect(catalogView).not.toMatch(/出现在扩展里/);
    expect(catalogView).toMatch(/出现在扩展库里/);
    expect(assetCard).not.toMatch(/在扩展里可见/);
    expect(assetCard).toMatch(/在扩展库里可见/);
    expect(auditDrawer).toMatch(/title="扩展库操作记录"/);
  });

  it('「扩展群」「扩展名」这类专有说法**不动**', () => {
    // 钉钉群名 (设置页文案) / 文件后缀 (知识库文案) —— 改了反而对不上
    expect(settingsView).toMatch(/扩展群/);
    const libraryView = read('src/views/Capability/Library/index.vue');
    expect(libraryView).toMatch(/扩展名必须跟原来一致/);
  });

  it('API 路径 /api/v1/extensions 不变 (改名只是显示层)', () => {
    // 路径是契约, 改名会打断外部调用
    expect(routerTs).toMatch(/path:\s*'extensions'/);
  });
});

// ═══════════════ ③ 侧栏顶部「能力」标题 ═══════════════

describe('③ 侧栏顶部「能力」区块标题去掉 (2026-11-04)', () => {
  it('CapabilityNav 里不再有这个标题元素', () => {
    expect(capNav).not.toMatch(/class="nav-cap"/);
    expect(capNav).not.toMatch(/class="nc-lb"/);
  });

  it('也没有残留的 nav-cap / nc-lb / nc-rule 样式', () => {
    expect(capNav).not.toMatch(/\.nav-cap\s*\{/);
    expect(capNav).not.toMatch(/\.nc-lb\s*\{/);
    expect(capNav).not.toMatch(/\.nc-rule\s*\{/);
  });

  it('结构变成三层: 总览入口 → 角色组 → 条目', () => {
    // 「全部能力」卡片是第一个子元素
    expect(capNav).toMatch(/<router-link to="\/" class="all-link"/);
    const body = capNav.slice(capNav.indexOf('<div class="cap-nav">'));
    // 跳过 cap-nav 自己的 class, 看它里面的第一个元素
    const inner = body.slice(body.indexOf('>') + 1);
    const firstClass = inner.match(/class="([a-z-]+)"/)?.[1];
    expect(firstClass).toBe('all-link');
  });

  it('侧栏下半的「📡 数据 / 工具」标题还在 —— 不靠「能力」分段', () => {
    const serviceStatus = read('src/components/ServiceStatus.vue');
    expect(serviceStatus).toMatch(/数据 \/ 工具/);
  });
});
