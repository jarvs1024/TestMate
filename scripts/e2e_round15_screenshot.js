#!/usr/bin/env node
/**
 * **第十五轮验收截图** (2026-10-31).
 *
 * 两个问题一次验收:
 *   ① 资产卡片 (插件/技能/连接器) + 软件库卡片 → **对齐首页能力墙的卡片样式**
 *      (白底 / 圆角 / 阴影 / 悬停上浮 / 蓝色光环 / CTA 箭头),
 *      但**大小和排列跟首页不一样** (更紧凑, 一屏放更多条目);
 *   ② 「返回工作台」那行**并进页头**, 跟「可复用的扩展资产」那行融合,
 *      并且**去掉「返回工作台」按钮** —— 资产 / 工具 / 看板 / 软件库四个页面统一.
 *
 * ⚠️ 本脚本**只读 + 截图**, 不改任何数据.
 *
 * 用法 (native 端口):
 *   NODE_PATH=/tmp/tm-e2e/node_modules \
 *   TESTMATE_BASE=http://localhost:8081 TESTMATE_API=http://127.0.0.1:8000 \
 *   node scripts/e2e_round15_screenshot.js
 */
const puppeteer = require('puppeteer-core');
const fs = require('fs');
const path = require('path');
require('./e2e_lock').acquire(__filename);

const CHROME = process.env.CHROME_PATH
  || '/Applications/Google Chrome.app/Contents/MacOS/Google Chrome';
const BASE = (process.env.TESTMATE_BASE || 'http://localhost:8081').replace(/\/$/, '');
const API = process.env.TESTMATE_API || 'http://127.0.0.1:8000';
const ADMIN = process.env.TESTMATE_USER || 'admin';
const ADMIN_PW = process.env.TESTMATE_PASSWORD || 'Admin@123';
const OUT_DIR = process.env.E2E_OUT_DIR || path.join(__dirname, '..', '.e2e-out');
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

const shots = [];
async function shot(page, name, desc) {
  const file = path.join(OUT_DIR, `r15-${name}.png`);
  await page.screenshot({ path: file });
  shots.push({ file, desc });
  console.log(`  📸 ${name} — ${desc}`);
}

/** 页面顶栏的身份信息 */
async function headerInfo(page) {
  return page.evaluate(() => {
    const name = document.querySelector('.pt-name');
    const lede = document.querySelector('.pt-lede');
    const icon = document.querySelector('.pt-icon');
    const badge = document.querySelector('.pt-badge');
    return {
      hasName: !!name,
      nameText: (name?.textContent || '').replace(/\s+/g, ' ').trim(),
      ledeText: (lede?.textContent || '').trim(),
      icon: (icon?.textContent || '').trim(),
      kind: (document.querySelector('.pt-kind')?.textContent || '').trim(),
      cat: (document.querySelector('.pt-cat')?.textContent || '').trim(),
      badge: (badge?.textContent || '').replace(/\s+/g, ' ').trim(),
      // ⚠️ 页头里**不许**再有「返回工作台」按钮
      hasBackBtn: !!document.querySelector('.tm-header .back'),
      headerHasBackText: (document.querySelector('.tm-header')?.textContent || '').includes('返回工作台'),
      // 内容区里也不该再有那条身份行
      contentBackText: (document.querySelector('.tm-main')?.textContent || '').includes('返回工作台'),
    };
  });
}

/** 卡片的样式特征 */
async function cardInfo(page, sel = '.asset-card') {
  return page.evaluate((s) => {
    const c = document.querySelector(s);
    if (!c) return { found: false };
    const cs = getComputedStyle(c);
    const r = c.getBoundingClientRect();
    return {
      found: true,
      hasCardClass: c.classList.contains('card'),
      radius: cs.borderRadius,
      shadow: cs.boxShadow,
      bg: cs.backgroundColor,
      padding: cs.padding,
      w: Math.round(r.width), h: Math.round(r.height),
      hasCta: !!c.querySelector('.ac-cta'),
      ctaText: (c.querySelector('.ac-cta')?.textContent || '').trim(),
    };
  }, sel);
}

(async () => {
  fs.mkdirSync(OUT_DIR, { recursive: true });

  const browser = await puppeteer.launch({
    executablePath: CHROME, headless: true,
    args: ['--no-sandbox', '--disable-dev-shm-usage'],
    defaultViewport: { width: 1440, height: 900 },
  });
  const page = await browser.newPage();
  await page.setCacheEnabled(false);
  const errors = [];
  page.on('pageerror', (e) => errors.push('[pageerror] ' + e.message));
  page.on('console', (m) => { if (m.type() === 'error') errors.push('[console] ' + m.text()); });

  const report = { shots, errors, checks: [] };
  const check = (name, ok, detail) => {
    report.checks.push({ name, ok, detail });
    console.log(`  ${ok ? '✅' : '❌'} ${name}${detail ? ' — ' + detail : ''}`);
  };

  // 登录
  const r = await fetch(API + '/api/v1/auth/login', {
    method: 'POST', headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ username: ADMIN, password: ADMIN_PW }),
  });
  const token = (await r.json()).access_token || '';
  if (!token) throw new Error('登录失败');
  await page.goto(BASE + '/login', { waitUntil: 'domcontentloaded' });
  const me = await page.evaluate(async (t) => {
    const rr = await fetch('/api/v1/auth/me', { headers: { Authorization: 'Bearer ' + t } });
    return rr.ok ? await rr.json() : { id: 1, username: 'admin', role: 'admin' };
  }, token);
  await page.evaluate((t, u) => {
    localStorage.setItem('testmate:token', t);
    localStorage.setItem('testmate:user', JSON.stringify(u));
    localStorage.setItem('testmate:theme', 'light');
  }, token, me);

  // ================= ② 身份条并进页头 =================
  console.log('\n── ② 身份条并进页头 + 去掉「返回工作台」 ──');
  const PAGES = [
    { path: '/market', name: '资产', title: '插件·技能·连接' },
    { path: '/software', name: '软件库', title: '软件库' },
    { path: '/code-review', name: '看板', title: '代码检视' },
  ];
  report.headers = {};
  for (const pg of PAGES) {
    await page.goto(BASE + pg.path, { waitUntil: 'domcontentloaded' });
    await sleep(2600);
    const h = await headerInfo(page);
    report.headers[pg.path] = h;
    console.log(`  [${pg.name}] ${h.nameText} | ${h.ledeText}`);
    check(`${pg.name}: 页头标题行里有身份信息 (图标+版本+角色·分类+状态)`,
      h.hasName && !!h.icon && !!h.kind && !!h.badge, h.nameText);
    check(`${pg.name}: **没有「返回工作台」按钮** (页头里也没有这四个字)`,
      !h.hasBackBtn && !h.headerHasBackText && !h.contentBackText, '');
    check(`${pg.name}: lede 还在第二行 (页面级说明没丢)`, !!h.ledeText, h.ledeText);
  }

  // 侧边栏「全部能力」就是回工作台的入口 (替代被去掉的按钮)
  const homeEntry = await page.evaluate(() => {
    const el = [...document.querySelectorAll('.cap-nav *, nav *')]
      .find((x) => (x.textContent || '').includes('全部能力'));
    return !!el;
  });
  check('侧边栏有「全部能力」入口 (回工作台的替代路径)', homeEntry, '');

  // 工具页 (身份是**动态**的 —— 接口取回来才显示)
  await page.goto(BASE + '/tool-runner', { waitUntil: 'domcontentloaded' });
  await sleep(2200);
  const toolH = await headerInfo(page);
  report.headers['/tool-runner'] = toolH;
  check('工具页: 页头里**没有**「返回工作台」', !toolH.headerHasBackText && !toolH.contentBackText, '');

  // ================= ① 卡片样式对齐首页 =================
  console.log('\n── ① 卡片样式对齐首页能力墙 ──');
  await page.goto(BASE + '/', { waitUntil: 'domcontentloaded' });
  await sleep(2600);
  const homeCard = await cardInfo(page, '.cap-card');
  report.homeCard = homeCard;
  await shot(page, 'home-cap-wall', '首页 · 能力墙 (卡片的基准样式)');

  await page.goto(BASE + '/market', { waitUntil: 'domcontentloaded' });
  await sleep(2600);
  const mktCard = await cardInfo(page);
  report.marketCard = mktCard;
  console.log(`  首页卡 = ${JSON.stringify(homeCard)}\n  市场卡 = ${JSON.stringify(mktCard)}`);
  check('市场卡片有全局 `card` 类 (白底/圆角/阴影)',
    mktCard.hasCardClass && mktCard.radius !== '0px' && mktCard.shadow !== 'none',
    `radius=${mktCard.radius} shadow=${mktCard.shadow}`);
  check('市场卡片**圆角跟首页一致**', mktCard.radius === homeCard.radius,
    `${mktCard.radius} vs 首页 ${homeCard.radius}`);
  check('市场卡片有**阴影**', mktCard.shadow !== 'none', mktCard.shadow);
  check('市场卡片有 **CTA 箭头** (跟首页卡同一结构)',
    mktCard.hasCta && /›/.test(mktCard.ctaText), mktCard.ctaText);
  check('⚠️ 市场卡片**更紧凑** (padding/高度比首页小 —— 一屏放更多)',
    mktCard.padding !== homeCard.padding && mktCard.h < homeCard.h,
    `市场 ${mktCard.padding}/${mktCard.h}px vs 首页 ${homeCard.padding}/${homeCard.h}px`);
  await shot(page, 'market-cards', '资产市场 · 卡片 (对齐首页能力墙的样式)');

  // ---- 悬停: 上浮 + 蓝色光环 ----
  const hovered = await page.evaluate(async () => {
    const c = document.querySelector('.asset-card');
    if (!c) return null;
    const before = getComputedStyle(c).boxShadow;
    c.dispatchEvent(new MouseEvent('mouseover', { bubbles: true }));
    return { before };
  });
  await page.hover('.asset-card').catch(() => {});
  await sleep(600);
  const hoverState = await page.evaluate(() => {
    const c = document.querySelector('.asset-card');
    const cs = getComputedStyle(c);
    return {
      shadow: cs.boxShadow,
      transform: cs.transform,
      borderColor: cs.borderTopColor,
    };
  });
  report.hover = hoverState;
  check('悬停时卡片**上浮** (translateY)', /matrix/.test(hoverState.transform) && hoverState.transform !== 'none',
    hoverState.transform);
  check('悬停时卡片有**蓝色光环** (box-shadow 里带 primary-soft)',
    /59,\s*130,\s*246/.test(hoverState.shadow), hoverState.shadow.slice(0, 90));
  await shot(page, 'market-card-hover', '资产市场 · 卡片悬停 (上浮 + 蓝色光环)');

  // ---- 软件库卡片同样 ----
  await page.goto(BASE + '/software', { waitUntil: 'domcontentloaded' });
  await sleep(2600);
  const swCard = await cardInfo(page);
  report.softwareCard = swCard;
  check('软件库卡片同样是白卡 (圆角+阴影+CTA)',
    swCard.hasCardClass && swCard.radius !== '0px' && swCard.shadow !== 'none' && swCard.hasCta,
    `radius=${swCard.radius} cta=${swCard.ctaText}`);
  await shot(page, 'software-cards', '软件库 · 卡片 (同一套样式)');

  await browser.close();

  fs.writeFileSync(
    path.join(OUT_DIR, 'round15-report.json'),
    JSON.stringify(report, null, 2),
  );

  const failed = report.checks.filter((c) => !c.ok);
  console.log(`\n✅ 截图 ${shots.length} 张 → ${OUT_DIR}`);
  console.log(`   检查 ${report.checks.length} 项, 通过 ${report.checks.length - failed.length}, 失败 ${failed.length}`);
  if (failed.length) {
    failed.forEach((f) => console.log(`   ❌ ${f.name} — ${f.detail || ''}`));
  }
  if (errors.length) {
    console.log(`⚠️  控制台报错 ${errors.length} 条:`);
    errors.slice(0, 10).forEach((e) => console.log('   ' + e));
  } else {
    console.log('✅ 无控制台报错');
  }
  process.exit(failed.length ? 1 : 0);
})().catch((e) => { console.error('❌', e); process.exit(1); });
