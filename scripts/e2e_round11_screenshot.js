#!/usr/bin/env node
/**
 * **第十一轮验收截图** (2026-10-30).
 *
 * 六个问题一次验收:
 *   ① 小屏网格 (首页 / 资产市场) —— 三个视口下的列数与卡片完整度;
 *   ② 「软件标识」那块灰底没了 —— 只显示软件名;
 *   ③ 发新版本时能选「新增 / 覆盖」;
 *   ④ 浮层里的灰阶提亮了 (--panel-surface-sunken);
 *   ⑤ 软件详情页有「编辑」按钮 (作者 / 管理员);
 *   ⑥ 资产详情页有「编辑信息」按钮 (作者 / 管理员).
 *
 * ⚠️ **只读 + 截图** —— 不做任何写操作, **绝对不往真实钉钉群发消息**.
 * ⚠️ 本脚本**不改仓库任何代码**.
 *
 * 用法 (native 端口):
 *   NODE_PATH=/tmp/tm-e2e/node_modules \
 *   TESTMATE_BASE=http://localhost:8081 TESTMATE_API=http://127.0.0.1:8000 \
 *   node scripts/e2e_round11_screenshot.js
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
  const file = path.join(OUT_DIR, `r11-${name}.png`);
  await page.screenshot({ path: file });
  shots.push({ file, desc });
  console.log(`  📸 ${name} — ${desc}`);
}

/** 登录 + 写 token/localStorage */
async function login(page, theme = 'light') {
  const r = await fetch(API + '/api/v1/auth/login', {
    method: 'POST', headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ username: ADMIN, password: ADMIN_PW }),
  });
  const token = (await r.json()).access_token || '';
  if (!token) throw new Error('登录失败, 没有拿到 token');
  await page.goto(BASE + '/login', { waitUntil: 'domcontentloaded' });
  const me = await page.evaluate(async (t) => {
    const rr = await fetch('/api/v1/auth/me', { headers: { Authorization: 'Bearer ' + t } });
    return rr.ok ? await rr.json() : { id: 1, username: 'admin', role: 'admin' };
  }, token);
  await page.evaluate((t, u, th) => {
    localStorage.setItem('testmate:token', t);
    localStorage.setItem('testmate:user', JSON.stringify(u));
    localStorage.setItem('testmate:theme', th);
  }, token, me, theme);
  return token;
}

/** 量一个网格当前排了几列 + 每列多宽 */
async function probeGrid(page, sel) {
  return page.evaluate((s) => {
    const g = document.querySelector(s);
    if (!g) return null;
    const cols = getComputedStyle(g).gridTemplateColumns;
    const kids = [...g.children];
    const first = kids[0]?.getBoundingClientRect();
    const second = kids[1]?.getBoundingClientRect();
    return {
      cols,
      colCount: cols.split(' ').filter(Boolean).length,
      firstWidth: first ? Math.round(first.width) : 0,
      // ⚠️ 第二张卡是否换行了 (同一行 = 没换行)
      sameRow: first && second ? Math.abs(first.top - second.top) < 4 : null,
      childCount: kids.length,
      overflowX: document.documentElement.scrollWidth > window.innerWidth + 2,
    };
  }, sel);
}

/** 量某个元素的实际底色 (算成 rgb) */
async function probeBg(page, sel) {
  return page.evaluate((s) => {
    const el = document.querySelector(s);
    if (!el) return null;
    return getComputedStyle(el).backgroundColor;
  }, sel);
}

/** 读一个 CSS 变量的计算值 */
async function probeVar(page, name) {
  return page.evaluate((n) =>
    getComputedStyle(document.documentElement).getPropertyValue(n).trim(), name);
}

/** 关掉所有浮层 */
async function closeOverlays(page) {
  await page.keyboard.press('Escape');
  await sleep(300);
  await page.evaluate(() => {
    document.querySelectorAll('.el-overlay').forEach((o) => {
      const d = o.querySelector('.el-drawer, .el-dialog');
      if (d && getComputedStyle(d).display !== 'none') o.click();
    });
  });
  await sleep(500);
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

  // ================= ① 小屏网格 =================
  console.log('\n── ① 小屏网格 (首页 / 资产市场) ──');
  const VIEWPORTS = [
    { w: 1440, h: 900 },
    { w: 1280, h: 720 },
    { w: 900, h: 800 },
  ];
  for (const vp of VIEWPORTS) {
    await page.setViewport({ width: vp.w, height: vp.h });
    await login(page);
    await page.goto(BASE + '/', { waitUntil: 'domcontentloaded' });
    await sleep(2200);
    const home = await probeGrid(page, '.grid');
    await shot(page, `home-${vp.w}`, `首页 · 视口 ${vp.w}px`);
    check(`首页 ${vp.w}px 不横向溢出`, home && !home.overflowX, home ? `scrollWidth>innerWidth=${home.overflowX}` : '没找到 .grid');
    if (home) {
      check(`首页 ${vp.w}px 卡片不挤扁 (每列 ≥ 300px)`, home.firstWidth >= 300, `每列 ${home.firstWidth}px / ${home.colCount} 列`);
    }

    await page.goto(BASE + '/market', { waitUntil: 'domcontentloaded' });
    await sleep(2400);
    const mk = await probeGrid(page, '.grid');
    await shot(page, `market-${vp.w}`, `资产市场 · 视口 ${vp.w}px`);
    check(`资产市场 ${vp.w}px 不横向溢出`, mk && !mk.overflowX, '');
    if (mk) {
      check(`资产市场 ${vp.w}px 卡片不挤扁 (每列 ≥ 280px)`, mk.firstWidth >= 280, `每列 ${mk.firstWidth}px / ${mk.colCount} 列`);
    }
  }

  // ================= ②④ 浮层里的灰阶 + 软件标识 =================
  console.log('\n── ②④ 浮层灰阶 + 「软件标识」 ──');
  await page.setViewport({ width: 1440, height: 900 });
  await login(page);

  const tokens = {
    sunken: await (async () => {
      await page.goto(BASE + '/', { waitUntil: 'domcontentloaded' });
      await sleep(800);
      return probeVar(page, '--panel-surface-sunken');
    })(),
    surface: await (async () => {
      await page.goto(BASE + '/', { waitUntil: 'domcontentloaded' });
      await sleep(800);
      return probeVar(page, '--panel-surface');
    })(),
  };
  report.tokens = tokens;
  console.log(`  --panel-surface        = ${tokens.surface}`);
  console.log(`  --panel-surface-sunken = ${tokens.sunken}`);
  check('--panel-surface-sunken 已提亮 (不再是 #E2E8F0)',
    !/E2E8F0/i.test(tokens.sunken), tokens.sunken);

  // ---- 上架抽屉 (软件标识) ----
  await page.goto(BASE + '/software', { waitUntil: 'domcontentloaded' });
  await sleep(2200);
  const openedUpload = await page.evaluate(() => {
    const b = [...document.querySelectorAll('button')].find((x) =>
      /上架软件|上架第一个软件/.test(x.textContent || ''));
    b && b.click();
    return !!b;
  });
  await sleep(1400);
  if (await page.$('.el-drawer')) {
    await shot(page, 'sw-upload-drawer', '上架软件抽屉 · 「软件标识」已改成只读显示软件名');
    const roBg = await probeBg(page, '.ro-text');
    // ⚠️ EP 2.8 的输入框底色画在 **.el-input__wrapper** 上 (不是 .el-input__inner,
    //    后者的 background 是 transparent) —— 量错元素会得到 "不一样" 的假结论.
    const inputBgs = await page.evaluate(() =>
      [...document.querySelectorAll('.el-drawer .el-input__wrapper')]
        .slice(0, 4).map((e) => getComputedStyle(e).backgroundColor));
    report.swUpload = { roBg, inputBgs };
    console.log(`  .ro-text 底色 = ${roBg}`);
    console.log(`  旁边输入框底色 = ${JSON.stringify(inputBgs)}`);
    check('「软件名称」只读行不再是蓝灰 (#E2E8F0)', roBg !== 'rgb(226, 232, 240)', String(roBg));
    check('只读行跟旁边输入框底色一致', inputBgs.length === 0 || roBg === inputBgs[0], `${roBg} vs ${inputBgs[0]}`);
  } else {
    check('上架抽屉能打开', false, openedUpload ? '点了但没打开' : '找不到按钮');
  }
  await closeOverlays(page);

  // ================= ③ 发新版本: 新增 / 覆盖 =================
  console.log('\n── ③ 发新版本: 新增 / 覆盖 二选一 ──');
  await page.goto(BASE + '/software', { waitUntil: 'domcontentloaded' });
  await sleep(2200);
  const cardOk = await page.evaluate(() => {
    const c = document.querySelector('.asset-card');
    c && c.click();
    return !!c;
  });
  await sleep(1800);
  if (await page.$('.el-drawer')) {
    await shot(page, 'sw-detail-can-edit', '软件详情抽屉 · 「编辑」按钮 (管理员可见)');
    const hasEdit = await page.evaluate(() =>
      [...document.querySelectorAll('.sw-hd-actions button')].some((b) => /编辑/.test(b.textContent || '')));
    check('软件详情抽屉有「编辑」按钮', hasEdit, '');

    // 点「发布新版本」
    await page.evaluate(() => {
      const b = [...document.querySelectorAll('.sw-hd-actions button')].find((x) => /发布新版本/.test(x.textContent || ''));
      b && b.click();
    });
    await sleep(1800);
    if (await page.$('.el-drawer .ver-mode')) {
      await shot(page, 'sw-version-mode', '发新版本 · 「新增一个版本 / 覆盖已有版本」二选一');
      const modes = await page.evaluate(() =>
        [...document.querySelectorAll('.vm-btn')].map((b) => b.textContent.trim()));
      check('版本区有「新增 / 覆盖」二选一',
        modes.some((m) => /新增一个版本/.test(m)) && modes.some((m) => /覆盖已有版本/.test(m)),
        JSON.stringify(modes));
    } else {
      check('发新版本抽屉能打开并显示二选一', false, '没找到 .ver-mode');
    }
  } else {
    check('软件详情抽屉能打开', false, cardOk ? '点了没开' : '没有卡片');
  }
  await closeOverlays(page);

  // ================= ⑥ 资产「编辑信息」 =================
  console.log('\n── ⑥ 资产详情: 「编辑信息」 ──');
  await page.goto(BASE + '/market', { waitUntil: 'domcontentloaded' });
  await sleep(2600);
  const mcard = await page.evaluate(() => {
    const c = document.querySelector('.asset-card');
    c && c.click();
    return !!c;
  });
  await sleep(2000);
  if (await page.$('.el-drawer')) {
    await shot(page, 'mk-detail-edit-meta', '资产详情抽屉 · 「编辑信息」按钮 (管理员可见)');
    const hasEditMeta = await page.evaluate(() =>
      [...document.querySelectorAll('.el-drawer button')].some((b) => /编辑信息/.test(b.textContent || '')));
    check('资产详情抽屉有「编辑信息」按钮', hasEditMeta, '');

    // 点「编辑信息」→ 编辑模式 (不该出现安装包上传区)
    await page.evaluate(() => {
      const b = [...document.querySelectorAll('.el-drawer button')].find((x) => /编辑信息/.test(x.textContent || ''));
      b && b.click();
    });
    await sleep(1800);
    const editMode = await page.evaluate(() => {
      // ⚠️ 用**类名**定位, 别用"最后一个可见抽屉" —— 两个抽屉叠着时 DOM 顺序
      //    跟视觉层级不一定一致, 会量到另一个抽屉去.
      const note = document.querySelector('.edit-note');
      const upload = [...document.querySelectorAll('.el-drawer')]
        .filter((d) => d.querySelector('.edit-note'))[0];
      const txt = upload ? (upload.textContent || '') : '';
      return {
        hasEditNote: !!note,
        // 装了包的表单里有 file input —— 编辑模式不该有
        hasPkgInput: !![...document.querySelectorAll('.el-drawer')]
          .filter((d) => d.querySelector('.edit-note'))
          .map((d) => d.querySelector('input[type="file"]'))[0],
        hasVersionField: /版本 \(semver\)/.test(txt),
        title: document.querySelector('.el-drawer__title')?.textContent || '',
      };
    });
    if (editMode) {
      await shot(page, 'mk-edit-meta-drawer', '资产「编辑信息」抽屉 · 不出现安装包上传区');
      check('编辑模式有说明条', editMode.hasEditNote, '');
      check('编辑模式**不出现**安装包上传区', !editMode.hasPkgInput, '');
      check('编辑模式**不出现**版本号输入', !editMode.hasVersionField, '');
    } else {
      check('编辑抽屉能打开', false, '');
    }
  } else {
    check('资产详情抽屉能打开', false, mcard ? '点了没开' : '没有卡片');
  }
  await closeOverlays(page);

  await browser.close();

  fs.writeFileSync(
    path.join(OUT_DIR, 'round11-report.json'),
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
})().catch((e) => { console.error('❌', e); process.exit(1); });
