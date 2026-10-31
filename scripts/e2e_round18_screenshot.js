#!/usr/bin/env node
/**
 * **第十八轮验收截图** (2026-10-31).
 *
 * 两件事:
 *   ① **版本号改成设置项** —— 以前页头显示的是后端 APP_VERSION (写死在 config.py,
 *      改一次要发版); 现在 `general.platform_version` 在设置页「⚙️ 通用」组里,
 *      默认 **1.0.0**, 改完**立刻生效**;
 *   ② **副标题不再写死「SSD 测试伙伴」** —— 平台现在覆盖 资产市场 / 软件库 / 知识库 /
 *      代码检视看板 / 环境运维, 写死一个具体品类会误导. 改成「智能测试辅助平台」,
 *      而且**也做成了设置项** (`general.platform_tagline`), 以后想换方向改设置就行.
 *
 * ⚠️ 本脚本会**写一次设置** (改版本号 → 验页头跟着变 → **改回原值**).
 *    ⚠️ 改回写在 finally 里 —— 中途失败也不会把版本号留在测试值上.
 *
 * 用法 (native 端口):
 *   NODE_PATH=/tmp/tm-e2e/node_modules \
 *   TESTMATE_BASE=http://localhost:8081 TESTMATE_API=http://127.0.0.1:8000 \
 *   node scripts/e2e_round18_screenshot.js
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
  const file = path.join(OUT_DIR, `r18-${name}.png`);
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

  // ================= 公开接口 =================
  console.log('\n── ① GET /api/v1/platform/info (公开可读) ──');
  const infoNoAuth = await (await fetch(API + '/api/v1/platform/info')).json();
  report.platformInfo = infoNoAuth;
  check('匿名也能读平台信息 (页头在没登录时也要显示)',
    !!infoNoAuth?.version && !!infoNoAuth?.tagline, JSON.stringify(infoNoAuth));
  check('版本号有值 (默认 1.0.0)',
    !!infoNoAuth?.version && /^\d+\.\d+\.\d+$/.test(String(infoNoAuth.version)), String(infoNoAuth?.version));
  check('副标题有值, 且**不再是写死的「SSD 测试伙伴」**',
    !!infoNoAuth?.tagline && !String(infoNoAuth.tagline).includes('SSD'), String(infoNoAuth?.tagline));

  // ================= 页头 + 登录页 =================
  console.log('\n── ② 页头 / 登录页显示副标题 + 版本号 ──');
  await page.goto(BASE + '/software', { waitUntil: 'domcontentloaded' });
  await sleep(2600);
  const headerBrand = await page.evaluate(() => ({
    t1: (document.querySelector('.tm-header .t1')?.textContent || '').trim(),
    t2: (document.querySelector('.tm-header .t2')?.textContent || '').trim(),
  }));
  report.headerBrand = headerBrand;
  // ⚠️ 平台名 / 副标题 / 版本号**全都是设置项** —— 管理员随时能改,
  //    所以不能写死字符串 —— 一律跟公开接口返回的真值比.
  check('页头平台名跟设置项一致',
    headerBrand.t1 === infoNoAuth?.name, `${headerBrand.t1} vs 接口 ${infoNoAuth?.name}`);
  check('页头副标题 == 「<副标题> · v<版本号>」',
    headerBrand.t2 === `${infoNoAuth?.tagline} · v${infoNoAuth?.version}`, headerBrand.t2);
  check('⚠️ 页头**不再有**「SSD 测试伙伴」', !headerBrand.t2.includes('SSD'), headerBrand.t2);
  await shot(page, 'header-brand', '页头 · 副标题 + 版本号 (走设置项)');

  await page.goto(BASE + '/login', { waitUntil: 'domcontentloaded' });
  await sleep(2200);
  const loginBrand = await page.evaluate(() => ({
    t1: (document.querySelector('.login .t1')?.textContent || '').trim(),
    t2: (document.querySelector('.login .t2')?.textContent || '').trim(),
  }));
  report.loginBrand = loginBrand;
  check('登录页副标题跟页头**一致**',
    loginBrand.t2 === headerBrand.t2, `${loginBrand.t2} vs 页头 ${headerBrand.t2}`);
  await shot(page, 'login-brand', '登录页 · 副标题 + 版本号 (跟页头一致)');

  // ================= 设置页有这两项 =================
  console.log('\n── ③ 设置页「⚙️ 通用」里有版本号 + 副标题 ──');
  await page.goto(BASE + '/settings', { waitUntil: 'domcontentloaded' });
  await sleep(2400);
  const pickedGeneral = await page.evaluate(() => {
    const item = [...document.querySelectorAll('.set-toc .toc-item, .set-toc li')]
      .find((x) => /通用/.test(x.textContent || ''));
    if (!item) return false;
    item.click();
    return true;
  });
  await sleep(1600);
  check('设置页目录里能点到「⚙️ 通用」分组', pickedGeneral, '');
  const generalRows = await page.evaluate(() => {
    const sec = document.querySelector('#sec-general');
    if (!sec) return { found: false, keys: [] };
    return {
      found: true,
      keys: [...sec.querySelectorAll('.row code')].map((c) => (c.textContent || '').trim()),
    };
  });
  report.generalRows = generalRows;
  check('通用组里有 `general.platform_version` (版本号)',
    generalRows.keys.includes('general.platform_version'), generalRows.keys.join(', '));
  check('通用组里有 `general.platform_tagline` (副标题)',
    generalRows.keys.includes('general.platform_tagline'), generalRows.keys.join(', '));
  await sleep(500);
  await shot(page, 'settings-general', '设置页 · 通用组 (版本号 + 副标题两项)');

  // ================= ④ 改设置 → 页头立刻跟着变 → 改回来 =================
  console.log('\n── ④ 改版本号 → 页头立刻跟着变 → 改回来 ──');
  const origVersion = infoNoAuth?.version || '1.0.0';
  const TEST_VERSION = '9.9.9';
  const setVersion = async (v) => {
    const rr = await fetch(API + '/api/v1/settings/general.platform_version', {
      method: 'PUT',
      headers: { 'Content-Type': 'application/json', Authorization: 'Bearer ' + token },
      body: JSON.stringify({ value: v }),
    });
    return rr.ok;
  };

  try {
    const saved = await setVersion(TEST_VERSION);
    check('能把版本号改成测试值', saved, TEST_VERSION);

    // 页头重新拉一次 (前端有 30 秒缓存 → 这里绕开缓存, 直接读公开接口 + 重新进页面)
    await page.goto(BASE + '/software', { waitUntil: 'domcontentloaded' });
    await sleep(2800);
    const after = await page.evaluate(() => ({
      t2: (document.querySelector('.tm-header .t2')?.textContent || '').trim(),
    }));
    report.afterVersionChange = after;
    check('⚠️ 改完**立刻生效** —— 页头版本号跟着变',
      after.t2.includes(`v${TEST_VERSION}`), after.t2);
    await shot(page, 'header-version-changed', `页头 · 版本号改成 ${TEST_VERSION} 后立刻生效`);
  } finally {
    const restored = await setVersion(origVersion);
    check('⚠️ 测试完把版本号**改回原值**', restored && origVersion !== TEST_VERSION, origVersion);
  }

  await browser.close();

  fs.writeFileSync(
    path.join(OUT_DIR, 'round18-report.json'),
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
