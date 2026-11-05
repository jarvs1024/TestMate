#!/usr/bin/env node
/**
 * **第二十二轮诊断** (2026-11-03) —— 复现用户报的三件事.
 *
 * ① 抽屉太窄 → 字被覆盖 (图1 扩展详情 / 图2 软件详情)
 * ② 编辑页内容跟"实际上架的内容"对不上 (图3)
 * ③ 软件要一个**固定**的 wget 下载链接 (图4)
 *
 * ⚠️ 本脚本**只读** —— 只打开界面看, 不提交任何表单.
 *
 * 用法: NODE_PATH=/tmp/tm-e2e/node_modules \
 *   TESTMATE_BASE=http://localhost:8081 TESTMATE_API=http://127.0.0.1:8000 \
 *   node scripts/e2e_round22_diag.js
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
  const file = path.join(OUT_DIR, `r22-${name}.png`);
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

  // ================= ① 扩展详情抽屉 =================
  console.log('\n── ① 扩展详情抽屉 (图1) ──');
  await page.goto(BASE + '/extensions', { waitUntil: 'domcontentloaded' });
  await page.waitForSelector('.asset-card', { timeout: 15000 });
  await sleep(2200);

  const opened = await page.evaluate(() => {
    const cards = [...document.querySelectorAll('.asset-card')];
    const card = cards.find((c) => (c.querySelector('.ac-name')?.textContent || '').includes('插件创建器'))
      || cards[0];
    if (!card) return null;
    (card.querySelector('.ac-name') || card).click();
    return (card.querySelector('.ac-name')?.textContent || '').trim();
  });
  await page.waitForSelector('.ins-file', { timeout: 15000 });
  await sleep(1200);

  const drawerBox = await page.evaluate(() => {
    const d = document.querySelector('.el-drawer');
    if (!d) return null;
    const r = d.getBoundingClientRect();
    const cs = getComputedStyle(d);
    return {
      width: Math.round(r.width), left: Math.round(r.left), right: Math.round(r.right),
      vw: window.innerWidth,
      bg: cs.backgroundColor,
      // 抽屉 body 是不是透明 (背景卡片会透出来)
      bodyBg: (() => {
        const b = d.querySelector('.el-drawer__body');
        return b ? getComputedStyle(b).backgroundColor : '(没有 body)';
      })(),
    };
  });
  report.assetDrawer = drawerBox;
  console.log('  抽屉盒子:', JSON.stringify(drawerBox));
  check('扩展抽屉宽度 ≥ 720px', (drawerBox?.width || 0) >= 720, `${drawerBox?.width}px`);
  check('抽屉 body 底色不是透明 (否则背景卡片透出来叠字)',
    drawerBox?.bodyBg !== 'rgba(0, 0, 0, 0)' && drawerBox?.bodyBg !== 'transparent',
    drawerBox?.bodyBg);
  await shot(page, 'asset-drawer', `扩展详情抽屉 · 宽 ${drawerBox?.width}px`);

  // ================= ② 编辑弹窗 (图3) =================
  console.log('\n── ② 编辑资产弹窗 (图3) ──');
  const editOpened = await page.evaluate(() => {
    const btns = [...document.querySelectorAll('.ad-actions button, .el-drawer button')];
    const b = btns.find((x) => (x.textContent || '').includes('编辑信息'));
    if (!b) return false;
    b.click();
    return true;
  });
  check('找到「编辑信息」按钮', editOpened);
  await sleep(1500);

  const editFields = await page.evaluate(() => {
    const items = [...document.querySelectorAll('.up-drawer .el-form-item')];
    const out = {};
    for (const it of items) {
      const label = (it.querySelector('.el-form-item__label')?.textContent || '').trim();
      const ta = it.querySelector('textarea');
      const inp = it.querySelector('input');
      if (!label) continue;
      out[label] = ta ? ta.value : (inp ? inp.value : '(没有输入框)');
    }
    return out;
  });
  report.editFields = editFields;
  console.log('  编辑弹窗字段值:');
  for (const [k, v] of Object.entries(editFields)) {
    console.log(`    ${k} = ${JSON.stringify(String(v).slice(0, 70))}`);
  }
  await shot(page, 'edit-dialog', '编辑资产弹窗');

  // 顺便把**详情页**显示的正文抓出来 —— 比对"编辑页"跟"上架内容"
  await page.evaluate(() => {
    const b = [...document.querySelectorAll('.el-drawer button, .el-button')]
      .find((x) => ['取消', '关闭', '×'].includes((x.textContent || '').trim()));
    b && b.click();
  });
  await sleep(1200);
  const detailText = await page.evaluate(() => {
    const d = document.querySelector('.el-drawer');
    return (d?.innerText || '').slice(0, 900);
  });
  report.detailText = detailText;
  console.log('\n  详情抽屉正文(前 900 字):\n' + detailText.split('\n').map((l) => '    ' + l).join('\n'));

  // ================= ③ 软件详情抽屉 (图2/图4) =================
  console.log('\n── ③ 软件详情抽屉 (图2 / 图4) ──');
  await page.goto(BASE + '/software', { waitUntil: 'domcontentloaded' });
  await sleep(2500);
  const swOpened = await page.evaluate(() => {
    const cards = [...document.querySelectorAll('.sw-card, .software-card, .asset-card, .list-card')];
    const c = cards[0];
    if (!c) return false;
    (c.querySelector('.sw-name, .ac-name, .name') || c).click();
    return true;
  });
  check('软件列表能点开详情', swOpened);
  await page.waitForSelector('.sw-hd', { timeout: 15000 });
  await sleep(1200);

  const swBox = await page.evaluate(() => {
    const d = document.querySelector('.el-drawer');
    const hd = document.querySelector('.sw-hd');
    const main = document.querySelector('.sw-hd-main');
    const act = document.querySelector('.sw-hd-actions');
    const btn = document.querySelector('.sw-hd-actions button');
    const box = (e) => {
      if (!e) return null;
      const r = e.getBoundingClientRect();
      return { w: Math.round(r.width), h: Math.round(r.height) };
    };
    return {
      drawer: box(d), hd: box(hd), main: box(main), actions: box(act), btn: box(btn),
      btnText: (btn?.textContent || '').trim(),
      mainText: (main?.innerText || '').trim().slice(0, 120),
      drawerBg: d ? getComputedStyle(d).backgroundColor : '',
    };
  });
  report.softwareDrawer = swBox;
  console.log('  软件抽屉:', JSON.stringify(swBox));
  check('软件抽屉宽度 ≥ 820px', (swBox?.drawer?.w || 0) >= 820, `${swBox?.drawer?.w}px`);
  check('⚠️ 标题区没被按钮挤扁 (宽度 ≥ 200px)',
    (swBox?.main?.w || 0) >= 200, `main=${swBox?.main?.w}px`);
  await shot(page, 'software-drawer', `软件详情抽屉 · 宽 ${swBox?.drawer?.w}px`);

  // 版本区
  const verInfo = await page.evaluate(() => {
    const rows = [...document.querySelectorAll('.ver-row')];
    return rows.map((r) => ({
      ver: (r.querySelector('.vr-ver')?.textContent || '').trim(),
      isDefault: !!r.querySelector('.vr-default'),
      btns: [...r.querySelectorAll('button')].map((b) => (b.textContent || '').trim()),
    }));
  });
  report.softwareVersions = verInfo;
  console.log('  版本行:', JSON.stringify(verInfo, null, 1));

  check('全程无 JS 错误', errors.length === 0, errors.slice(0, 2).join(' ; '));

  fs.writeFileSync(path.join(OUT_DIR, 'r22-report.json'), JSON.stringify(report, null, 2));
  console.log('\n报告: ' + path.join(OUT_DIR, 'r22-report.json'));
  await browser.close();
})().catch((e) => { console.error('❌ 诊断失败:', e.message); process.exit(1); });
