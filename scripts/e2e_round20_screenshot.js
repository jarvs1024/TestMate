#!/usr/bin/env node
/**
 * **第二十轮验收截图** (2026-10-31).
 *
 * 用户报的毛病:
 *   「选中流程规范或者其他，质量保障，效率工具都没数字显示了，其他类似」
 *
 * **根因**: 分类 chip 上的数字以前是**前端按当前列表聚合**的 ——
 *   选了某个分类 → 列表里只剩那一类 → 别的分类全被算成 0 →
 *   再被模板里的 `v-if` 一藏 → **别的分类的数字全消失**。
 *
 * **改法**: 计数下沉到后端 (`cat_counts`), 口径跟 `all_total` 一致 (忽略 category);
 *   并且 **0 也照样显示** —— 「这个分类确实是 0 条」跟「这个分类没统计」得分得开。
 *
 * ⚠️ 本脚本**只读** —— 不点分类以外的任何会写数据的操作。
 *
 * 用法 (native 端口):
 *   NODE_PATH=/tmp/tm-e2e/node_modules \
 *   TESTMATE_BASE=http://localhost:8081 TESTMATE_API=http://127.0.0.1:8000 \
 *   node scripts/e2e_round20_screenshot.js
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
  const file = path.join(OUT_DIR, `r20-${name}.png`);
  await page.screenshot({ path: file });
  shots.push({ file, desc });
  console.log(`  📸 ${name} — ${desc}`);
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

  // ================= 接口层: cat_counts =================
  console.log('\n── ① GET /api/v1/extensions 的 cat_counts ──');
  const api0 = await (await fetch(
    API + '/api/v1/extensions?kind=skill&limit=500', { headers: { Authorization: 'Bearer ' + token } },
  )).json();
  const api1 = await (await fetch(
    API + '/api/v1/extensions?kind=skill&category=' + encodeURIComponent('质量保障') + '&limit=500',
    { headers: { Authorization: 'Bearer ' + token } },
  )).json();
  report.api = { before: api0.cat_counts, after: api1.cat_counts };
  check('接口返回 cat_counts', !!api0.cat_counts, JSON.stringify(api0.cat_counts));
  check('⚠️ 不变量: 各分类之和 == all_total',
    Object.values(api0.cat_counts || {}).reduce((a, b) => a + b, 0) === api0.all_total,
    `${JSON.stringify(api0.cat_counts)} vs all_total=${api0.all_total}`);
  check('⚠️ 选了分类之后 cat_counts **不变**',
    JSON.stringify(api0.cat_counts) === JSON.stringify(api1.cat_counts),
    `${JSON.stringify(api0.cat_counts)} → ${JSON.stringify(api1.cat_counts)}`);

  // ================= 页面层 =================
  console.log('\n── ② 页面: 选分类后别的分类数字不消失 ──');
  await page.goto(BASE + '/market', { waitUntil: 'domcontentloaded' });
  await sleep(2800);

  const chipCounts = () => page.evaluate(() => {
    const chips = [...document.querySelectorAll('.mk-filters .cat-chips .chip')];
    const out = {};
    for (const c of chips) {
      const label = (c.textContent || '').trim().replace(/\s*\d+\s*$/, '').trim();
      const el = c.querySelector('.count');
      out[label] = { text: el ? (el.textContent || '').trim() : null, active: c.classList.contains('active') };
    }
    return out;
  });

  // ⚠️ 「全部」「👤 我的」「⭐ 精选」**不是分类** —— 它们是别的维度, 本来就没有分类计数
  const NON_CATEGORY = /^(全部|👤\s*我的|⭐\s*精选)$/;
  const catChips = (m) => Object.fromEntries(Object.entries(m).filter(([k]) => !NON_CATEGORY.test(k)));

  const before = await chipCounts();
  report.chips = { before };
  console.log('     初始:', JSON.stringify(before));
  const catsBefore = catChips(before);
  check('分类 chip 上都有计数徽标 (0 也显示)',
    Object.keys(catsBefore).length > 0 && Object.values(catsBefore).every((v) => v.text !== null),
    JSON.stringify(catsBefore));
  check('至少有一个分类的计数 > 0',
    Object.values(catsBefore).some((v) => Number(v.text) > 0), JSON.stringify(catsBefore));

  // 选一个有货的分类
  const target = Object.keys(catsBefore).find((k) => Number(catsBefore[k].text) > 0);
  const clicked = await page.evaluate((label) => {
    const chips = [...document.querySelectorAll('.mk-filters .cat-chips .chip')];
    const t = chips.find((c) => {
      const l = (c.textContent || '').trim().replace(/\s*\d+\s*$/, '').trim();
      return l === label;
    });
    if (!t) return false;
    t.click();
    return true;
  }, target);
  await sleep(2000);
  check(`能点到分类「${target}」`, clicked, '');
  const after = await chipCounts();
  report.chips.after = after;
  console.log('     选中后:', JSON.stringify(after));
  const catsAfter = catChips(after);
  check('⚠️ 选分类后 **别的分类的计数一个都没变**',
    Object.keys(catsBefore).every((k) => catsBefore[k].text === catsAfter[k].text),
    JSON.stringify({ before: catsBefore, after: catsAfter }));
  check('⚠️ 数字没消失 (每个分类 chip 都还有徽标)',
    Object.values(catsAfter).every((v) => v.text !== null), JSON.stringify(catsAfter));
  await shot(page, 'market-cat-selected', `市场页 · 选中「${target}」后, 其它分类的数字仍在`);

  await browser.close();

  fs.writeFileSync(
    path.join(OUT_DIR, 'round20-report.json'),
    JSON.stringify(report, null, 2),
  );

  const failed = report.checks.filter((c) => !c.ok);
  console.log(`\n✅ 截图 ${shots.length} 张 → ${OUT_DIR}`);
  console.log(`   检查 ${report.checks.length} 项, 通过 ${report.checks.length - failed.length}, 失败 ${failed.length}`);
  if (failed.length) failed.forEach((f) => console.log(`   ❌ ${f.name} — ${f.detail || ''}`));
  if (errors.length) {
    console.log(`⚠️  控制台报错 ${errors.length} 条:`);
    errors.slice(0, 10).forEach((e) => console.log('   ' + e));
  } else {
    console.log('✅ 无控制台报错');
  }
  process.exit(failed.length ? 1 : 0);
})().catch((e) => { console.error('❌', e); process.exit(1); });
