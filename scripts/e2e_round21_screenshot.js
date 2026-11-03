#!/usr/bin/env node
/**
 * **第二十一轮验收截图** (2026-11-03).
 *
 * 用户的要求:
 *   「调整扩展插件中下载包的名称, 下载技能和插件都不需要带版本号,
 *     下载到本地就应该是 dml-xxx.zip 而不是 dml-xxx-1.0.0.zip」
 *
 * 背景: 仓库里存的原始安装包叫 "{version}.zip" (1.0.0.zip / 1.1.0.zip …),
 *   以前直接把这个名字发给浏览器 → 用户存到本地全是 "1.0.0.zip",
 *   一屏下三四个扩展就互相覆盖, 还根本认不出谁是谁.
 *
 * 锁住四件事:
 *   1. 详情抽屉「安装卡」上显示的文件名是 "{code}.zip"
 *   2. 下载端点的 Content-Disposition 里是 "{code}.zip" (**不带版本号**)
 *   3. 真的点「下载」→ 落盘的文件名就是 "{code}.zip"
 *   4. 成功提示里也是 "{code}.zip"
 *
 * ⚠️ 本脚本**只读 + 只下载** —— 不写任何业务数据.
 *
 * 用法 (native 端口):
 *   NODE_PATH=/tmp/tm-e2e/node_modules \
 *   TESTMATE_BASE=http://localhost:8081 TESTMATE_API=http://127.0.0.1:8000 \
 *   node scripts/e2e_round21_screenshot.js
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
  const file = path.join(OUT_DIR, `r21-${name}.png`);
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
    report.checks.push({ name, ok: !!ok, detail });
    console.log(`  ${ok ? '✅' : '❌'} ${name}${detail ? ' — ' + detail : ''}`);
  };

  // ---------- 登录 ----------
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
    localStorage.setItem('testmate:theme', 'light');
  }, token, me);

  // ---------- ① 市场上的技能/插件 ----------
  console.log('\n── ① 市场上有技能/插件 ──');
  const assets = await page.evaluate(async (t) => {
    const r = await fetch('/api/v1/extensions?limit=200&status=all&client_id=r21',
      { headers: { Authorization: 'Bearer ' + t } });
    const d = await r.json();
    return (d.items || []).filter((i) => i.kind !== 'mcp');
  }, token);
  check('市场上有技能/插件', assets.length > 0, `${assets.length} 个`);
  if (!assets.length) throw new Error('没有可下载的资产');

  // ---------- ② 打开详情抽屉 (先点卡, 再按**这张卡**反查 code) ----------
  console.log('\n── ② 打开详情抽屉 ──');
  await page.goto(BASE + '/market', { waitUntil: 'domcontentloaded' });
  await page.waitForSelector('.asset-card', { timeout: 15000 });
  await sleep(1800);

  const opened = await page.evaluate(() => {
    const card = document.querySelector('.asset-card');
    if (!card) return null;
    const name = (card.querySelector('.ac-name')?.textContent || '').trim();
    // .ac-ver 形如 "1.2.0 · 流程规范"
    const ver = ((card.querySelector('.ac-ver')?.textContent || '').split('·')[0] || '').trim();
    (card.querySelector('.ac-name') || card).click();
    return { name, version: ver };
  });
  check('点开详情抽屉', !!opened, opened ? `${opened.name} (${opened.version})` : '');
  if (!opened) throw new Error('没找到卡片');
  await page.waitForSelector('.ins-file', { timeout: 15000 });
  await sleep(700);

  // ⚠️ 必须按**点开的这张卡**去反查 code —— 市场页有分页/排序,
  //    预先从 API 挑一个资产再去找它的卡, 很容易点开的是另一张.
  const asset = assets.find((a) => a.name === opened.name && a.version === opened.version)
    || assets.find((a) => a.name === opened.name);
  if (!asset) throw new Error(`API 里找不到点开的资产: ${opened.name}`);
  console.log(`  点开的: ${asset.code} (${asset.kind} ${asset.version})`);

  // ---------- ③ 下载端点: Content-Disposition 里是 {code}.zip ----------
  console.log('\n── ③ 下载端点的文件名 ──');
  const dl = await page.evaluate(async (t, code, ver) => {
    const r = await fetch(
      `/api/v1/extensions/${encodeURIComponent(code)}/versions/${encodeURIComponent(ver)}/download`,
      { headers: { Authorization: 'Bearer ' + t } },
    );
    return {
      status: r.status,
      disposition: r.headers.get('content-disposition') || '',
      contentType: r.headers.get('content-type') || '',
    };
  }, token, asset.code, asset.version);
  report.downloadHeaders = dl;
  check('下载端点 200', dl.status === 200, `status=${dl.status}`);
  check('⚠️ Content-Disposition 里的文件名是 "{code}.zip" (不带版本号)',
    dl.disposition.includes(`filename="${asset.code}.zip`),
    dl.disposition || '(空)');
  check('⚠️ 文件名里**不含版本号**', !dl.disposition.includes(asset.version),
    `version=${asset.version}`);
  check('Content-Type 是 application/zip', dl.contentType.includes('application/zip'),
    dl.contentType);

  // ---------- ④ 界面: 抽屉里显示的文件名 ----------
  console.log('\n── ④ 详情抽屉里显示的文件名 ──');
  const shown = await page.evaluate(() => {
    const el = document.querySelector('.ins-file');
    return (el?.textContent || '').trim();
  });
  report.shownFileName = shown;
  check('⚠️ 安装卡上显示的是 "{code}.zip"', shown === `${asset.code}.zip`, shown);
  check('⚠️ 显示名里**不含版本号**', !shown.includes(asset.version), shown);
  await shot(page, 'drawer-filename', `详情抽屉 · 安装包名 ${shown}`);

  // ---------- ⑤ 真点「下载」→ 落盘文件名 ----------
  console.log('\n── ⑤ 点下载 → 落盘文件名 ──');
  const dlDir = path.join(OUT_DIR, 'r21-downloads');
  fs.rmSync(dlDir, { recursive: true, force: true });
  fs.mkdirSync(dlDir, { recursive: true });
  const bcdp = await browser.target().createCDPSession();
  await bcdp.send('Browser.setDownloadBehavior', {
    behavior: 'allow', downloadPath: dlDir, eventsEnabled: true,
  });

  await page.evaluate(() => {
    const b = [...document.querySelectorAll('.ins-btn')]
      .find((x) => (x.textContent || '').trim() === '下载');
    b && b.click();
  });

  // ⚠️ Element Plus 的消息 3 秒就消失 —— 得**轮询**着抓
  let msg = '';
  for (let i = 0; i < 25; i++) {
    await sleep(200);
    msg = await page.evaluate(() =>
      document.querySelector('.el-message')?.textContent.trim() || '');
    if (msg) break;
  }
  report.successMessage = msg;
  check('成功提示里是 "{code}.zip"',
    msg.includes(`${asset.code}.zip`) && !msg.includes(asset.version),
    msg.slice(0, 90) || '(没抓到提示)');

  let files = [];
  for (let i = 0; i < 30; i++) {
    files = fs.existsSync(dlDir) ? fs.readdirSync(dlDir) : [];
    if (files.some((f) => !f.endsWith('.crdownload'))) break;
    await sleep(250);
  }
  const landed = files.filter((f) => !f.endsWith('.crdownload'));
  report.landed = landed;
  check('⚠️ 落盘的文件名是 "{code}.zip"',
    landed.some((f) => f === `${asset.code}.zip`),
    landed.join(' | ') || '(下载目录空)');
  check('落盘的文件名里**不含版本号**',
    !landed.some((f) => f.includes(asset.version)),
    landed.join(' | '));

  await shot(page, 'downloaded', `下载完成 · 落盘 ${landed.join(', ')}`);

  // ---------- ⑥ 全程无 JS 错误 ----------
  check('全程无 JS 错误', errors.length === 0, errors.slice(0, 2).join(' ; '));

  fs.writeFileSync(
    path.join(OUT_DIR, 'r21-report.json'),
    JSON.stringify(report, null, 2),
  );

  const failed = report.checks.filter((c) => !c.ok);
  console.log(`\n${report.checks.length - failed.length}/${report.checks.length} 通过`);
  if (failed.length) {
    console.log('❌ 失败项:');
    failed.forEach((f) => console.log(`   - ${f.name} ${f.detail || ''}`));
  }
  await browser.close();
  process.exit(failed.length ? 1 : 0);
})().catch(async (e) => {
  console.error('❌ e2e 失败:', e.message);
  process.exit(1);
});
