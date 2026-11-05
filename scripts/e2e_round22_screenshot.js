#!/usr/bin/env node
/**
 * **第二十二轮验收** (2026-11-03).
 *
 * 用户报的三件事:
 *   ① 图1/图2 抽屉太窄 → 暗色下背景文字透上来叠字; 软件详情头部被超长版本名挤成竖排
 *   ② 图3    编辑页面的内容和实际上架的内容不一致 (上架表单里压根没那几个输入框)
 *   ③ 图4    软件要一个**固定**的 wget 下载链接 (URL 永不变, 永远给推荐版本)
 *
 * ⚠️ 本脚本**只读 + 只下载** —— 不写任何业务数据.
 *
 * 用法 (native 端口):
 *   NODE_PATH=/tmp/tm-e2e/node_modules \
 *   TESTMATE_BASE=http://localhost:8081 TESTMATE_API=http://127.0.0.1:8000 \
 *   node scripts/e2e_round22_screenshot.js
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

/** 从 "rgba(r, g, b, a)" 里抠出 alpha */
function alphaOf(color) {
  const m = String(color || '').match(/rgba?\([^)]*?,\s*([\d.]+)\s*\)/);
  return m ? Number(m[1]) : null;
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
    localStorage.setItem('testmate:theme', 'dark');   // ⚠️ 用户报的问题在暗色下
  }, token, me);

  // ================= ① 扩展详情抽屉 =================
  console.log('\n── ① 扩展详情抽屉 (图1) ──');
  await page.goto(BASE + '/extensions', { waitUntil: 'domcontentloaded' });
  await page.waitForSelector('.asset-card', { timeout: 15000 });
  await sleep(2200);
  await page.evaluate(() => {
    const card = document.querySelector('.asset-card');
    (card?.querySelector('.ac-name') || card)?.click();
  });
  await page.waitForSelector('.ins-file', { timeout: 15000 });
  await sleep(1000);

  const ad = await page.evaluate(() => {
    const d = document.querySelector('.el-drawer');
    const cs = d ? getComputedStyle(d) : null;
    const r = d?.getBoundingClientRect();
    return {
      width: Math.round(r?.width || 0),
      bg: cs?.backgroundColor || '',
      bodyBg: (() => {
        const b = d?.querySelector('.el-drawer__body');
        return b ? getComputedStyle(b).backgroundColor : '';
      })(),
    };
  });
  report.assetDrawer = ad;
  const adAlpha = alphaOf(ad.bg);
  check('⚠️ 扩展抽屉宽度 ≥ 860px', ad.width >= 860, `${ad.width}px`);
  check('⚠️ 暗色抽屉底色近乎不透明 (alpha ≥ 0.9) —— 背景字不再透上来',
    adAlpha !== null && adAlpha >= 0.9, `alpha=${adAlpha} (${ad.bg})`);
  check('抽屉 body 透明 (底色只在容器画一次, header/body 严丝合缝)',
    ad.bodyBg === 'rgba(0, 0, 0, 0)' || ad.bodyBg === 'transparent', ad.bodyBg);
  await shot(page, 'asset-drawer', `扩展详情抽屉 · 宽 ${ad.width}px · 底色 alpha=${adAlpha}`);

  // ================= ② 上架表单补字段 =================
  console.log('\n── ② 上架表单 (图3) ──');
  const editOpened = await page.evaluate(() => {
    const b = [...document.querySelectorAll('.el-drawer button')]
      .find((x) => (x.textContent || '').includes('编辑信息'));
    if (!b) return false;
    b.click();
    return true;
  });
  check('打开「编辑信息」', editOpened);
  await sleep(1600);

  const fields = await page.evaluate(() => {
    const items = [...document.querySelectorAll('.up-drawer .el-form-item')];
    const out = {};
    for (const it of items) {
      const label = (it.querySelector('.el-form-item__label')?.textContent || '').trim();
      const ta = it.querySelector('textarea');
      if (label && ta) out[label] = ta.value;
    }
    return out;
  });
  report.editFields = fields;
  for (const k of ['详细说明', '适用场景', '不适合的场景', '安装步骤']) {
    check(`编辑弹窗里有「${k}」输入框`, k in fields, k in fields ? '有' : '没有');
  }
  await shot(page, 'edit-dialog', '编辑资产弹窗 · 四项都在');

  // 关掉
  await page.evaluate(() => {
    const b = [...document.querySelectorAll('.el-drawer button, .el-button')]
      .find((x) => ['取消', '关闭'].includes((x.textContent || '').trim()));
    b && b.click();
  });
  await sleep(1200);

  // ================= ③ 软件详情抽屉 =================
  console.log('\n── ③ 软件详情抽屉 (图2 / 图4) ──');
  await page.goto(BASE + '/software', { waitUntil: 'domcontentloaded' });
  await sleep(2600);
  const swOpened = await page.evaluate(() => {
    const cards = [...document.querySelectorAll('.sw-card, .software-card, .asset-card, .list-card')];
    const c = cards[0];
    if (!c) return false;
    (c.querySelector('.sw-name, .ac-name, .name') || c).click();
    return true;
  });
  check('软件列表能点开详情', swOpened);
  await page.waitForSelector('.sw-hd', { timeout: 15000 });
  await sleep(1400);

  const sw = await page.evaluate(() => {
    const d = document.querySelector('.el-drawer');
    const box = (sel) => {
      const e = document.querySelector(sel);
      if (!e) return null;
      const r = e.getBoundingClientRect();
      return { w: Math.round(r.width), h: Math.round(r.height) };
    };
    const btn = document.querySelector('.sw-hd-actions button');
    return {
      drawer: box('.el-drawer'), main: box('.sw-hd-main'), actions: box('.sw-hd-actions'),
      btnText: (btn?.textContent || '').trim(),
      bg: d ? getComputedStyle(d).backgroundColor : '',
      fixedUrl: (document.querySelector('.fx-url')?.textContent || '').trim(),
      fixedCmd: (document.querySelector('.fx-cmd')?.textContent || '').trim(),
      hasFixed: !!document.querySelector('.fx-url'),
    };
  });
  report.softwareDrawer = sw;
  console.log('  软件抽屉:', JSON.stringify(sw));
  check('⚠️ 软件抽屉宽度 ≥ 900px', (sw.drawer?.w || 0) >= 900, `${sw.drawer?.w}px`);
  check('⚠️ 标题区没被按钮挤扁 (≥ 240px)', (sw.main?.w || 0) >= 240, `${sw.main?.w}px`);
  await shot(page, 'software-drawer', `软件详情抽屉 · 宽 ${sw.drawer?.w}px`);

  // ================= ④ 固定下载链接 =================
  console.log('\n── ④ 固定下载链接 (图4) ──');
  check('详情页有「固定下载链接」区块', sw.hasFixed, sw.hasFixed ? '' : '没找到 .fx-url');
  check('链接里不含版本号', sw.fixedUrl && !/\d+\.\d+\.\d+/.test(sw.fixedUrl), sw.fixedUrl);
  check('有能直接贴走的 wget 命令', /wget -O /.test(sw.fixedCmd), sw.fixedCmd);
  await shot(page, 'fixed-link', `固定下载链接 · ${sw.fixedCmd}`);

  if (sw.fixedUrl) {
    // ⚠️ **真的用 curl 拉一次** (不带任何 token) —— 这就是用户说的 wget 场景
    const abs = sw.fixedUrl.startsWith('http') ? sw.fixedUrl : API + sw.fixedUrl;
    const r = await fetch(abs);
    const buf = Buffer.from(await r.arrayBuffer());
    check('⚠️ 免登录真的能下 (curl 不带 token)',
      r.status === 200 && buf.length > 0,
      `status=${r.status} ${buf.length} 字节, version=${r.headers.get('x-software-version')}`);
    report.fixedDownload = { status: r.status, bytes: buf.length };
  }

  check('全程无 JS 错误', errors.length === 0, errors.slice(0, 2).join(' ; '));

  fs.writeFileSync(path.join(OUT_DIR, 'r22-report.json'), JSON.stringify(report, null, 2));
  const failed = report.checks.filter((c) => !c.ok);
  console.log(`\n${report.checks.length - failed.length}/${report.checks.length} 通过`);
  if (failed.length) {
    console.log('❌ 失败项:');
    failed.forEach((f) => console.log(`   - ${f.name} ${f.detail || ''}`));
  }
  await browser.close();
  process.exit(failed.length ? 1 : 0);
})().catch((e) => { console.error('❌ e2e 失败:', e.message); process.exit(1); });
