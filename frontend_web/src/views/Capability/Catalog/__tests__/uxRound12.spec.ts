/**
 * **第十二轮 · 「我的」筛选 + 编辑信息审核口径** (2026-10-30).
 *
 * 用户两条新需求:
 *   ① 「软件库和资产市场, 筛选加个**我的**, 过滤出登录用户的卡片」;
 *   ② 「技能插件连接器如果只是编辑信息, 管理员审核 (优化站内通知),
 *      通知到管理审核群, 但审核通过, 这个编辑信息没涉及到包变化
 *      **就不用通知到市场群**」.
 *
 * ⚠️ 为什么大多是源码断言:
 *   · 「我的」是**筛选维度**, 真渲染一整个市场页太重 (el-select / 分类 chip 注入多);
 *     但 "chip 存在 + 传了 status=mine" 这两件事用源码断言更锁得住;
 *   · 审核口径的正确性由**后端单测**盯 (test_market_meta_edit.py) ——
 *     那是真跑接口, 前端断言只能看"前端有没有把标记显示出来".
 */
import { describe, expect, it } from 'vitest';
import { readFileSync } from 'node:fs';
import path from 'node:path';

const read = (p: string) => readFileSync(path.resolve(process.cwd(), p), 'utf-8');
/** ⚠️ 断言前先去掉注释 —— 注释里全是"以前怎么写的"的历史示例 */
const strip = (s: string) => s.replace(/\/\*[\s\S]*?\*\//g, '');

const catalogRaw = read('src/views/Capability/Catalog/index.vue');
const catalog = strip(catalogRaw);
const catalogTpl = catalogRaw.split('<script setup')[0];

const swRaw = read('src/views/Software/index.vue');
const sw = strip(swRaw);
const swTpl = swRaw.split('<script setup')[0];

const cardRaw = read('src/views/Capability/Catalog/AssetCard.vue');
const card = strip(cardRaw);

const homeRaw = read('src/views/Home/index.vue');
const home = strip(homeRaw);

const assetsApiRaw = read('src/api/assets.ts');
const assetsApi = strip(assetsApiRaw);

describe('① 资产市场: 「👤 我的」筛选', () => {
  it('筛选栏里要有「👤 我的」入口', () => {
    expect(catalogTpl).toContain('👤 我的');
  });

  it('选了之后要**后端**过滤 (status=mine) —— 前端筛会漏 (列表有 limit)', () => {
    expect(catalog).toContain('mineOnly');
    expect(catalog).toMatch(/status:\s*mineOnly\.value\s*\?\s*'mine'/);
  });

  it('「我的」跟那三条「只看这些」提示条**互斥**', () => {
    expect(catalog).toMatch(/if \(mineOnly\.value\) onlyMine\.value = ''/);
    expect(catalog).toMatch(/if \(onlyMine\.value\) mineOnly\.value = false/);
  });

  it('「我的」是**常驻维度** —— 分类/项目筛选照样生效 (不像紧急入口那样让路)', () => {
    // ⚠️ 文件里有好几处 listAssets({...}) —— 要挑**带 status 参数**的那次取数,
    //    别抓到别处的调用 (否则断言的是另一段代码).
    const blocks = [...catalog.matchAll(/const r = await listAssets\(\{[\s\S]*?\}\);/g)].map((m) => m[0]);
    const fetchBlock = blocks.find((b) => b.includes('status:')) || '';
    expect(fetchBlock).toContain('mineOnly.value ? \'mine\'');
    // 让路的那几行用的是 onlyMine (紧急入口), 不是 mineOnly
    expect(fetchBlock).toMatch(/kind:\s*mine \? undefined : kind\.value/);
  });

  it('清空筛选也要把「我的」关掉', () => {
    expect(catalog).toMatch(/function resetFilters\(\)[\s\S]*?mineOnly\.value = false/);
  });
});

describe('① 软件库: 「👤 我的」筛选', () => {
  it('筛选栏里要有「👤 我的」入口', () => {
    expect(swTpl).toContain('👤 我的');
  });

  it('选了之后走后端 status=mine', () => {
    expect(sw).toMatch(/status:\s*mineOnly\.value \?\s*'mine'/);
  });

  it('空态要回显「我的」这个条件 (否则用户不知道自己筛了什么)', () => {
    expect(sw).toMatch(/hasFilter[\s\S]*?mineOnly\.value/);
    expect(sw).toContain("'我的'");
  });

  it('清空筛选要连「我的」一起清', () => {
    expect(sw).toMatch(/async function clearFilter\(\)[\s\S]*?mineOnly\.value = false/);
  });
});

describe('② 编辑信息: 审核口径 (前端可见部分)', () => {
  it('待审卡片要标出「只改了信息」(📝 信息待审)', () => {
    expect(card).toContain('pending_action');
    expect(card).toContain('信息待审');
  });

  it('「📝 信息待审」跟「📋 待审核」是**两个不同的徽标**', () => {
    // ⚠️ 用 v-if / v-else-if 串起来 —— 同时显示两个徽标就乱了
    expect(card).toMatch(/pending_action === 'meta'[\s\S]*?v-else-if[\s\S]*?publish_status === 'pending'/);
  });

  it('管理员待办要分成「新资产」和「只改了信息」两条', () => {
    expect(home).toContain('awaiting_meta_count');
    expect(home).toContain('my_meta_count');
    expect(home).toContain('个新资产等你审核');
    expect(home).toContain('个资产只改了信息');
  });

  it('计数字段要从 API 类型里拿到 (后端已下发)', () => {
    expect(assetsApi).toContain('awaiting_meta_count');
    expect(assetsApi).toContain('my_meta_count');
  });
});
