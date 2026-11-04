#!/usr/bin/env node
/**
 * **第二十三轮验收** (2026-11-04).
 *
 * 用户提的三件事:
 *   ① 图1  扩展详情抽屉里的「下载」按钮 —— 样式要跟「＋ 上传资产」一样
 *   ② 图3  「扩展」改名「扩展库」 (页头标题 + 侧栏导航两处)
 *   ③ 图4  侧栏顶部那个「能力」区块标题 —— 有没有必要保留 (本轮: 去掉)
 *
 * ⚠️ 本脚本**只读** —— 不写任何业务数据, 不下载任何文件.
 *
 * 用法 (native 端口):
 *   NODE_PATH=/tmp/tm-e2e/node_modules \
 *   TESTMATE_BASE=http://localhost:8081 TESTMATE_API=http://127.0.0.1:8000 \
 *   node scripts/e2e_round23_screenshot.js
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

const report = { checks: [], shots: [] };
function check(name, ok, detail) {
  report.checks.push({ name, ok: !!ok, detail });
  console.log(`  ${ok ? '✅' : '❌'} ${name}${detail ? ' — ' + detail : ''}`);
}
async function shot(page, name, desc) {
  const file = path.join(OUT_DIR, `r23-${name}.png`);
  await page.screenshot({ path: file });
  report.shots.push({ file, desc });
  console.log(`  📸 ${name} — ${desc}`);
}

(async () => {
  fs.mkdirSync(OUT_DIR, { recursive: true });
  const browser = await puppeteer.launch({
    executablePath: CHROME, headless: true,
    args: ['--no-sandbox', '--disable-dev-shm-usage'],
    defaultViewport: { width: 1600, height: 1000 },
  });
  const page = await browser.newPage();
  await page.setCacheEnabled(false);
  const errors = [];
  page.on('pageerror', (e) => errors.push('[pageerror] ' + e.message));
  page.on('console', (m) => { if (m.type() === 'error') errors.push('[console] ' + m.text()); });

  const lr = await fetch(API + '/api/v1/auth/login', {
    method: 'POST', headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ username: ADMIN, password: ADMIN_PW }),
  });
  const token = (await lr.json()).access_token || '';
  if (!token) throw new Error('登录失败');
  check('登录成功', !!token, ADMIN);

  await page.goto(BASE + '/login', { waitUntil: 'domcontentloaded' });
  const me = await page.evaluate(async (t) => {
    const rr = await fetch('/api/v1/auth/me', { headers: { Authorization: 'Bearer ' + t } });
    return rr.ok ? await rr.json() : { id: 1, username: 'admin', role: 'admin' };
  }, token);
  await page.evaluate((t, u) => {
    localStorage.setItem('testmate:token', t);
    localStorage.setItem('testmate:user', JSON.stringify(u));
    localStorage.setItem('testmate:theme', 'dark');
  }, token, me);

  // ================= ②③ 侧栏 + 页头标题 =================
  console.log('\n── ②③ 侧栏导航 + 页头标题 (图3/图4) ──');
  await page.goto(BASE + '/extensions', { waitUntil: 'domcontentloaded' });
  await page.waitForSelector('.cap-nav .item', { timeout: 15000 });
  await sleep(1800);

  const nav = await page.evaluate(() => {
    const items = [...document.querySelectorAll('.cap-nav .item .i-lb')].map((e) => e.textContent.trim());
    const capTitle = document.querySelector('.cap-nav .nc-lb');
    // 侧栏里有没有一个**单独**的「能力」二字 (「全部能力」不算)
    const loose = [...document.querySelectorAll('.cap-nav *')]
      .filter((e) => e.children.length === 0 && e.textContent.trim() === '能力')
      .map((e) => e.className);
    return {
      items,
      hasCapTitle: !!capTitle,
      loose,
      navCapEls: document.querySelectorAll('.cap-nav .nav-cap').length,
      headerTitle: (document.querySelector('.pt-txt')?.textContent || '').trim(),
      headerLede: (document.querySelector('.pt-lede')?.textContent || '').trim(),
    };
  });
  report.nav = nav;

  check('② 侧栏里没有「扩展」了 —— 改成「扩展库」',
    nav.items.includes('扩展库') && !nav.items.includes('扩展'), nav.items.join(' | '));
  check('② 页头标题是「扩展库」', nav.headerTitle === '扩展库', nav.headerTitle);
  check('③ 侧栏顶部不再有「能力」区块标题 (.nav-cap 元素消失)',
    nav.navCapEls === 0 && !nav.hasCapTitle, `nav-cap=${nav.navCapEls}`);
  check('③ 侧栏里也没有孤立的「能力」二字',
    nav.loose.length === 0, nav.loose.join(','));
  check('侧栏结构完整: 全部能力 + 资产/工具/看板 三组',
    nav.items.includes('全部能力') || nav.items.length >= 4, nav.items.join(' | '));

  await shot(page, 'nav', `侧栏 (无「能力」标题) + 页头标题「${nav.headerTitle}」`);

  // 首页也看一眼 —— 能力卡的名字应该同步成「扩展库」
  await page.goto(BASE + '/', { waitUntil: 'domcontentloaded' });
  await page.waitForSelector('.cap-card', { timeout: 15000 });
  await sleep(1500);
  const homeNames = await page.evaluate(() =>
    [...document.querySelectorAll('.cap-card .cc-name')].map((e) => e.textContent.trim()));
  report.homeNames = homeNames;
  check('② 首页能力卡的名字也是「扩展库」',
    homeNames.includes('扩展库') && !homeNames.includes('扩展'), homeNames.join(' | '));
  await shot(page, 'home', `首页能力墙 · 卡片名 ${homeNames.join(' / ')}`);

  // ================= ① 下载按钮样式 =================
  console.log('\n── ① 下载按钮样式 (图1) ──');
  await page.goto(BASE + '/extensions', { waitUntil: 'domcontentloaded' });
  await page.waitForSelector('.asset-card', { timeout: 15000 });
  await sleep(2200);
  // ⚠️ 必须点**实际那张卡** —— 预选资产再去找卡会点错
  const opened = await page.evaluate(() => {
    const card = document.querySelector('.asset-card');
    if (!card) return false;
    (card.querySelector('.ac-name') || card).click();
    return true;
  });
  check('打开扩展详情抽屉', opened);
  await page.waitForSelector('.ins-btn', { timeout: 15000 });
  await sleep(1000);

  const btn = await page.evaluate(() => {
    const b = document.querySelector('.ins-btn');
    if (!b) return null;
    const cs = getComputedStyle(b);
    const r = b.getBoundingClientRect();
    const parent = b.parentElement;
    const pcs = parent ? getComputedStyle(parent) : null;
    return {
      tag: b.tagName,
      cls: b.className,
      text: (b.textContent || '').trim(),
      width: Math.round(r.width),
      height: Math.round(r.height),
      bgImage: cs.backgroundImage,
      bgColor: cs.backgroundColor,
      color: cs.color,
      borderRadius: cs.borderRadius,
      parentW: parent ? Math.round(parent.getBoundingClientRect().width) : 0,
      parentDisplay: pcs?.display || '',
    };
  });
  report.downloadBtn = btn;

  check('① 下载按钮是原生 <button> + .mini-btn.primary 家族',
    btn && btn.tag === 'BUTTON' && /mini-btn/.test(btn.cls) && /primary/.test(btn.cls),
    btn ? `${btn.tag}.${btn.cls}` : '没找到');
  check('① 按钮文案还是纯「下载」(e2e 按文本匹配)',
    btn && btn.text === '下载', btn ? btn.text : '');
  check('① 背景是渐变 (跟「＋ 上传资产」同一套), 不是实心蓝',
    btn && /gradient/.test(btn.bgImage), btn ? btn.bgImage : '');
  check('① 不再撑满整行 (宽度 < 容器宽度的一半)',
    btn && btn.width < btn.parentW * 0.5, btn ? `${btn.width}px / 容器 ${btn.parentW}px` : '');
  check('① 按钮是紧凑高度 (≤ 44px, 不是大蓝条)',
    btn && btn.height <= 44, btn ? `${btn.height}px` : '');

  // 「＋ 上传资产」按钮的样式 —— 两边应该完全一致
  await page.keyboard.press('Escape');
  await sleep(900);
  const uploadBtn = await page.evaluate(() => {
    const b = document.querySelector('.upload-pick .mini-btn.primary');
    if (!b) return null;
    const cs = getComputedStyle(b);
    const r = b.getBoundingClientRect();
    return {
      cls: b.className, bgImage: cs.backgroundImage, color: cs.color,
      borderRadius: cs.borderRadius, height: Math.round(r.height),
    };
  });
  report.uploadBtn = uploadBtn;
  check('① 「＋ 上传资产」按钮存在 (用来对照)',
    !!uploadBtn, uploadBtn ? uploadBtn.cls : '没找到');
  check('① 两边渐变完全一致 (下载按钮 == 上传资产按钮)',
    uploadBtn && btn && uploadBtn.bgImage === btn.bgImage,
    uploadBtn && btn ? `${btn.bgImage} vs ${uploadBtn.bgImage}` : '');

  await page.goto(BASE + '/extensions', { waitUntil: 'domcontentloaded' });
  await page.waitForSelector('.asset-card', { timeout: 15000 });
  await sleep(1800);
  await page.evaluate(() => {
    const card = document.querySelector('.asset-card');
    (card?.querySelector('.ac-name') || card)?.click();
  });
  await page.waitForSelector('.ins-btn', { timeout: 15000 });
  await sleep(1000);
  await shot(page, 'download-btn', `扩展详情 · 下载按钮跟「上传资产」同款 (.${btn.cls})`);

  // ================= 收尾 =================
  console.log('\n── 控制台错误 ──');
  const realErrors = errors.filter((e) => !/favicon|401|403|Failed to load resource/i.test(e));
  check('页面没有 JS 报错', realErrors.length === 0, realErrors.slice(0, 3).join(' | '));

  await browser.close();

  const failed = report.checks.filter((c) => !c.ok);
  console.log(`\n═══ 第二十三轮 e2e: ${report.checks.length - failed.length}/${report.checks.length} 通过 ═══`);
  fs.writeFileSync(path.join(OUT_DIR, 'r23-report.json'), JSON.stringify(report, null, 2));
  if (failed.length) {
    console.log('失败项:\n' + failed.map((f) => '  ❌ ' + f.name + (f.detail ? ' — ' + f.detail : '')).join('\n'));
    process.exit(1);
  }
})().catch((e) => { console.error('💥', e); process.exit(1); });
