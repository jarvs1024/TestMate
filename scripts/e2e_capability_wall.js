#!/usr/bin/env node
/**
 * 能力墙走查 (真实 Chrome) —— 截图 + 断言.
 *
 * 盯住 2026-10-27 那轮重排:
 *   ① 侧栏分组顺序: **资产 → 工具 → 看板** (资产排最上面);
 *   ② 角色名是「资产」, 不是「底座」;
 *   ③ 工具组**只剩「环境运维」**;
 *   ④ 资产组三张卡: 插件·技能·连接 / 知识库 / 软件库;
 *   ⑤ 环境运维的文案里不许出现温箱 / 老化 / 温度 / 功耗;
 *   ⑥ 软件库是「规划中」(还没做页面, 不该跳到不存在的页).
 *
 * 用法: NODE_PATH=/tmp/tm-e2e/node_modules node scripts/e2e_capability_wall.js [baseUrl]
 */
const puppeteer = require('puppeteer-core');
const fs = require('fs');
const path = require('path');

const CHROME = process.env.CHROME_PATH
  || '/Applications/Google Chrome.app/Contents/MacOS/Google Chrome';
const BASE = (process.argv[2] || process.env.TESTMATE_BASE || 'http://localhost:8081').replace(/\/$/, '');
const USER = process.env.TESTMATE_USER || 'admin';
const PASSWORD = process.env.TESTMATE_PASSWORD || 'Admin@123';
const OUT_DIR = process.env.E2E_OUT_DIR || path.join(__dirname, '..', '.e2e-out');

const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
const results = [];
function check(name, ok, detail) {
  results.push({ name, ok: !!ok, detail: detail || '' });
  console.log(`[${ok ? '  ok  ' : ' FAIL '}] ${name}${detail ? ' — ' + detail : ''}`);
}

(async () => {
  const browser = await puppeteer.launch({
    executablePath: CHROME,
    headless: 'new',
    args: ['--no-sandbox', '--window-size=1280,900'],
  });
  const page = await browser.newPage();
  await page.setViewport({ width: 1280, height: 900, deviceScaleFactor: 2 });
  const errors = [];
  page.on('pageerror', (e) => errors.push(String(e)));
  page.on('console', (m) => {
    if (m.type() !== 'error') return;
    if (/Failed to load resource/i.test(m.text())) return;
    errors.push(m.text());
  });

  try {
    fs.mkdirSync(OUT_DIR, { recursive: true });
    // 先登录 (侧栏与首页都要真实身份)
    await page.goto(`${BASE}/login`, { waitUntil: 'networkidle2' });
    await sleep(400);
    await page.type('input[autocomplete="username"]', USER, { delay: 10 });
    await sleep(900);
    const pwd = await page.$('input[autocomplete="current-password"]');
    if (pwd) { await pwd.type(PASSWORD, { delay: 10 }); }
    await page.click('button.primary');
    await sleep(2500);

    await page.goto(`${BASE}/`, { waitUntil: 'networkidle2' });
    await sleep(1200);

    // ① 侧栏分组顺序 + 角色名
    const nav = await page.evaluate(() => {
      const heads = [...document.querySelectorAll('.g-hd')].map((h) => h.textContent.trim());
      const items = [...document.querySelectorAll('.item .i-lb')].map((i) => i.textContent.trim());
      return { heads, items };
    });
    console.log('侧栏分组:', JSON.stringify(nav.heads));
    console.log('侧栏条目:', JSON.stringify(nav.items));
    check('侧栏分组顺序: 资产 → 工具 → 看板',
      nav.heads[0].includes('资产') && nav.heads[1].includes('工具') && nav.heads[2].includes('看板'),
      nav.heads.join(' | '));
    check('侧栏不再出现「底座」', !nav.heads.join('').includes('底座'));
    check('工具组只剩环境运维',
      nav.items.filter((i) => ['日志分析', '测试方案生成', '文本用例生成'].includes(i)).length === 0
      && nav.items.includes('环境运维'),
      nav.items.join(' | '));
    check('资产组三张卡都在',
      ['插件·技能·连接', '知识库', '软件库'].every((n) => nav.items.includes(n)),
      nav.items.join(' | '));

    await page.screenshot({ path: path.join(OUT_DIR, 'wall-1-home.png') });

    // ⑤ 环境运维的文案
    const env = await page.evaluate(() => {
      const card = [...document.querySelectorAll('.cc, .cap-card, [class*=card]')]
        .find((c) => c.textContent.includes('环境运维'));
      return card ? card.textContent.replace(/\s+/g, ' ').trim() : '';
    });
    const forbidden = ['温箱', '老化', '温度', '功耗'];
    const bad = forbidden.filter((w) => env.includes(w));
    check('环境运维文案不含温箱/老化/温度/功耗', bad.length === 0,
      bad.length ? `还有: ${bad.join(',')}` : env.slice(0, 60));

    // ⑥ 软件库是规划中, 点不动
    const sw = await page.evaluate(() => {
      const card = [...document.querySelectorAll('.cc, .cap-card, [class*=card]')]
        .find((c) => c.textContent.includes('软件库'));
      return card ? card.textContent.replace(/\s+/g, ' ').trim() : '';
    });
    check('软件库标着规划中', sw.includes('规划中') || sw.includes('未接入'), sw.slice(0, 60));

    // 角色 chips 的顺序
    const chips = await page.evaluate(() =>
      [...document.querySelectorAll('.filter')].map((f) => f.textContent.replace(/\s+/g, ' ').trim()));
    console.log('首页筛选 chips:', JSON.stringify(chips));
    check('首页 chips 顺序: 全部 → 资产 → 工具 → 看板',
      chips[0].includes('全部') && chips[1].includes('资产')
      && chips[2].includes('工具') && chips[3].includes('看板'),
      chips.join(' | '));

    await page.screenshot({ path: path.join(OUT_DIR, 'wall-2-capabilities.png'), fullPage: true });

    // 点「插件·技能·连接」→ 应该跳到市场页, 标题是新名字
    await page.evaluate(() => {
      const el = [...document.querySelectorAll('.item')].find((i) => i.textContent.includes('插件·技能·连接'));
      if (el) el.click();
    });
    await sleep(2500);
    const url = page.url();
    const shellName = await page.evaluate(() => {
      const el = document.querySelector('.sh-name, .shell-name, h1, .sh-title');
      return el ? el.textContent.trim() : '';
    });
    check('点「插件·技能·连接」跳到市场页', url.includes('/market'), url);
    check('市场页标题是「插件·技能·连接」', shellName.includes('插件·技能·连接'), shellName);
    await page.screenshot({ path: path.join(OUT_DIR, 'wall-3-market.png') });

    check('全程无 JS 错误', errors.length === 0, errors.slice(0, 3).join(' | '));

    await browser.close();
  } catch (e) {
    console.error('脚本异常:', e);
    try { await browser.close(); } catch { /* ignore */ }
    process.exit(2);
  }

  const failed = results.filter((r) => !r.ok);
  console.log(`\n能力墙走查: ${results.length - failed.length}/${results.length} 通过`);
  console.log(`截图目录: ${OUT_DIR}`);
  process.exit(failed.length ? 1 : 0);
})();
