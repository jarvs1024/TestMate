#!/usr/bin/env node
/**
 * **第十二轮验收截图** (2026-10-30).
 *
 * 四个问题一次验收:
 *   ① 软件上架抽屉里**不再有「软件名称」只读行** (后端维护 code, 前端不展示);
 *   ② 资产「编辑信息」**不通知钉钉** (这条靠后端单测盯, e2e 只确认按钮还在);
 *   ③ 软件库上架/发新版本 → 钉钉通知 (共用一个开关, 设置页可见);
 *   ④ 通知消息内容完善 (说明/更新/类型/链接) —— 设置页「👀 预览消息」能看见,
 *      **一条都不发** (绝不能往公司真实群发测试消息).
 *
 * ⚠️ **只读 + 截图** —— 不做任何写操作, **绝对不往真实钉钉群发消息**.
 *    预览走的是后端 `GET /api/v1/assets/notifications/preview` (只渲染不发送).
 * ⚠️ 本脚本**不改仓库任何代码**.
 *
 * 用法 (native 端口):
 *   NODE_PATH=/tmp/tm-e2e/node_modules \
 *   TESTMATE_BASE=http://localhost:8081 TESTMATE_API=http://127.0.0.1:8000 \
 *   node scripts/e2e_round12_screenshot.js
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
  const file = path.join(OUT_DIR, `r12-${name}.png`);
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

/** 直接问后端要通知回执条数 (用来证明"预览一条都没发") */
async function receiptCount(token) {
  const r = await fetch(API + '/api/v1/assets/notifications?limit=200', {
    headers: { Authorization: 'Bearer ' + token },
  });
  if (!r.ok) return null;
  const body = await r.json();
  return Array.isArray(body?.items) ? body.items.length : null;
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

  // ================= ① 上架抽屉: 没有「软件名称」 =================
  console.log('\n── ① 上架抽屉: 不再展示软件名称/code ──');
  await login(page);
  const receiptsBefore = await receiptCount(
    await fetch(API + '/api/v1/auth/login', {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ username: ADMIN, password: ADMIN_PW }),
    }).then((r) => r.json()).then((b) => b.access_token),
  );

  await page.goto(BASE + '/software', { waitUntil: 'domcontentloaded' });
  await sleep(2200);
  const openedUpload = await page.evaluate(() => {
    const b = [...document.querySelectorAll('button')].find((x) =>
      /上架软件|上架第一个软件/.test(x.textContent || ''));
    b && b.click();
    return !!b;
  });
  await sleep(1500);
  if (await page.$('.el-drawer')) {
    await shot(page, 'sw-upload-no-name', '上架软件抽屉 · 「软件名称」已整块删掉');
    const probe = await page.evaluate(() => {
      const drawer = [...document.querySelectorAll('.el-drawer')]
        .filter((d) => getComputedStyle(d).display !== 'none')[0];
      const labels = [...document.querySelectorAll('.el-drawer .el-form-item__label')]
        .map((l) => (l.textContent || '').trim());
      const txt = drawer ? (drawer.textContent || '') : '';
      return {
        labels,
        hasRoText: !!document.querySelector('.ro-text'),
        // 「软件名称」这个 label 整个不见了
        hasNameLabel: labels.some((l) => /软件名称|软件标识/.test(l)),
        // 抽屉里还能看到「软件名」输入框 (那才是用户该填的)
        hasNameInput: [...document.querySelectorAll('.el-drawer .el-form-item__label')]
          .some((l) => /软件名$/.test((l.textContent || '').trim())),
        // codeError 的提示还在 (挪到软件包那一段了)
        pickErrs: [...document.querySelectorAll('.el-drawer .pick-err')].map((e) => (e.textContent || '').trim()),
        textLen: txt.length,
      };
    });
    report.swUpload = probe;
    console.log(`  表单 label = ${JSON.stringify(probe.labels)}`);
    check('上架抽屉里**没有**「软件名称/软件标识」只读行', !probe.hasNameLabel && !probe.hasRoText,
      `labels=${JSON.stringify(probe.labels)}`);
    check('「软件名」输入框还在 (用户该填的还是要填)', probe.hasNameInput, '');
    check('保留了「文件名派生的标识不合法」提示', Array.isArray(probe.pickErrs), JSON.stringify(probe.pickErrs));
  } else {
    check('上架抽屉能打开', false, openedUpload ? '点了但没打开' : '找不到按钮');
  }
  await closeOverlays(page);

  // ================= ③ 设置页: 通知开关 + 预览 =================
  console.log('\n── ③ 设置页: 软件库通知开关 + 预览消息 ──');
  await page.goto(BASE + '/settings', { waitUntil: 'domcontentloaded' });
  await sleep(2400);

  // ⚠️ 设置页是「左边目录 + 右边只渲染当前分组」——
  //    不先点目录里的「🔔 通知」, 通知区根本不渲染, 按钮自然找不到.
  const pickedNotif = await page.evaluate(() => {
    const item = [...document.querySelectorAll('.set-toc .toc-item, .set-toc li')]
      .find((x) => /通知/.test(x.textContent || ''));
    if (!item) return false;
    item.click();
    return true;
  });
  await sleep(1800);
  check('设置页目录里能点到「🔔 通知」分组', pickedNotif, '');

  const foundNotif = await page.evaluate(() => {
    const sec = document.querySelector('#sec-notification');
    if (!sec) return false;
    sec.scrollIntoView({ block: 'center' });
    return true;
  });
  await sleep(900);
  if (foundNotif) {
    await shot(page, 'settings-notify', '设置页 · 通知设置区 (含软件库开关与预览入口)');
  }

  // 找「👀 预览消息」按钮并点它
  const clicked = await page.evaluate(() => {
    const b = [...document.querySelectorAll('button')].find((x) => /预览消息|收起预览/.test(x.textContent || ''));
    b && b.click();
    return !!b;
  });
  await sleep(2000);
  if (clicked) {
    await shot(page, 'settings-notify-preview', '设置页 · 通知消息预览 (只渲染, 一条都不发)');
    const pv = await page.evaluate(() => {
      const cards = [...document.querySelectorAll('.pv-card')];
      return {
        count: cards.length,
        labels: cards.map((c) => (c.querySelector('.pv-label')?.textContent || '').trim()),
        texts: cards.map((c) => (c.querySelector('.pv-text')?.textContent || '').trim()),
      };
    });
    report.preview = pv;
    check('预览区渲染出 6 个场景', pv.count === 6, `${pv.count} 个`);
    check('预览里有「市场 · 上架新资产」', pv.labels.some((l) => /上架新资产/.test(l)), '');
    check('预览里有「软件库 · 上架新软件」', pv.labels.some((l) => /上架新软件/.test(l)), '');
    check('预览里有「软件库 · 发布新版本」', pv.labels.some((l) => /发布新版本/.test(l)), '');
    check('预览里有「只改了信息, 待审核」(审核群那条)',
      pv.labels.some((l) => /只改了信息/.test(l)), JSON.stringify(pv.labels));
    check('「只改了信息」那条的标题跟「新资产待审核」**不一样**',
      pv.texts.some((t) => /资产信息修改, 待审核/.test(t))
      && pv.texts.some((t) => /新资产待审核/.test(t)), '');

    // ---- ④ 消息内容 ----
    const all = pv.texts.join('\n');
    check('消息区分了类型 (插件/连接器/软件包/技能)',
      /插件/.test(all) && /连接器/.test(all) && /软件包/.test(all) && /技能/.test(all), '');
    check('上架带「说明」(是干嘛的)', /说明: /.test(all), '');
    check('更新带「更新」(这次改了啥)', /更新: /.test(all), '');
    check('带市场链接 /market', /\/market\)/.test(all), '');
    check('带软件库链接 /software', /\/software\)/.test(all), '');
    check('消息带版本号与操作人', /版本: `/.test(all) && /操作人: /.test(all), '');
  } else {
    check('设置页有「👀 预览消息」按钮', false, '没找到按钮');
  }

  // ---- ⚠️ 预览**一条都不该发** ----
  const receiptsAfter = await receiptCount(
    await fetch(API + '/api/v1/auth/login', {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ username: ADMIN, password: ADMIN_PW }),
    }).then((r) => r.json()).then((b) => b.access_token),
  );
  check('预览**没有**产生任何通知回执 (一条都没发)',
    receiptsBefore !== null && receiptsAfter !== null && receiptsBefore === receiptsAfter,
    `${receiptsBefore} → ${receiptsAfter}`);

  // ================= ② 资产「编辑信息」按钮还在 =================
  console.log('\n── ② 资产详情: 「编辑信息」按钮 ──');
  await page.goto(BASE + '/market', { waitUntil: 'domcontentloaded' });
  await sleep(2600);
  const mcard = await page.evaluate(() => {
    const c = document.querySelector('.asset-card');
    c && c.click();
    return !!c;
  });
  await sleep(2000);
  if (await page.$('.el-drawer')) {
    await shot(page, 'mk-detail-edit-meta', '资产详情抽屉 · 「编辑信息」按钮 (改信息要过管理员审核, 通知审核群)');
    const hasEditMeta = await page.evaluate(() =>
      [...document.querySelectorAll('.el-drawer button')].some((b) => /编辑信息/.test(b.textContent || '')));
    check('资产详情抽屉有「编辑信息」按钮', hasEditMeta, '');
  } else {
    check('资产详情抽屉能打开', false, mcard ? '点了没开' : '没有卡片');
  }
  await closeOverlays(page);

  // ================= ⑤ 首页: 吸顶条不能压住卡片 =================
  console.log('\n── ⑤ 首页: 吸顶条不压卡片 ──');
  await page.goto(BASE + '/', { waitUntil: 'domcontentloaded' });
  await sleep(2600);
  const home = await page.evaluate(() => {
    const tb = document.querySelector('.home-toolbar');
    const grid = document.querySelector('.grid');
    const card = document.querySelector('.cap-card');
    const strip = document.querySelector('.todo-strip');
    const b = (e) => { const r = e?.getBoundingClientRect(); return r ? { top: Math.round(r.top), bottom: Math.round(r.bottom) } : null; };
    return {
      toolbar: b(tb), grid: b(grid), card: b(card), strip: b(strip),
      gapToolToGrid: grid && tb ? Math.round(grid.getBoundingClientRect().top - tb.getBoundingClientRect().bottom) : null,
      stripVar: getComputedStyle(document.querySelector('.home')).getPropertyValue('--strip-h').trim(),
    };
  });
  report.home = home;
  console.log(`  工具条=${JSON.stringify(home.toolbar)}  网格=${JSON.stringify(home.grid)}  --strip-h=${home.stripVar}`);
  check('首页吸顶条**不压**能力网格 (间距 ≥ 0)',
    home.gapToolToGrid !== null && home.gapToolToGrid >= 0, `gap=${home.gapToolToGrid}px`);
  check('第一排卡片顶边 == 网格顶边 (没有被吸顶条切掉)',
    home.card && home.grid && home.card.top === home.grid.top,
    `card.top=${home.card?.top} grid.top=${home.grid?.top}`);
  if (home.strip) {
    check('有待办带时, 工具条排在待办带**下面** (两者不叠)',
      home.toolbar.top >= home.strip.bottom, `strip.bottom=${home.strip.bottom} toolbar.top=${home.toolbar.top}`);
  }
  await shot(page, 'home-no-overlap', '首页 · 吸顶条不再压住能力卡片');

  // ================= ⑥ 「👤 我的」筛选 =================
  console.log('\n── ⑥ 「👤 我的」筛选 (资产市场 / 软件库) ──');
  await page.goto(BASE + '/market', { waitUntil: 'domcontentloaded' });
  await sleep(2600);
  const mineChip = await page.evaluate(() => {
    const b = [...document.querySelectorAll('.cat-chips .chip')]
      .find((x) => /我的/.test(x.textContent || ''));
    if (!b) return false;
    b.click();
    return true;
  });
  await sleep(2200);
  check('资产市场有「👤 我的」筛选入口', mineChip, '');
  if (mineChip) {
    await shot(page, 'market-mine', '资产市场 · 「👤 我的」筛选');
    const authors = await page.evaluate(() =>
      [...document.querySelectorAll('.asset-card')].map((c) => {
        const t = [...c.querySelectorAll('*')].map((e) => (e.textContent || '').trim());
        return t.find((x) => x && x.length < 40 && /@|admin|jack|zhangsan/.test(x)) || '';
      }));
    const active = await page.evaluate(() =>
      !!document.querySelector('.cat-chips .chip.active.mine-chip'));
    check('「👤 我的」选中后是激活态', active, '');
    check('「👤 我的」筛出来的卡片都属于当前登录用户',
      authors.length > 0 && authors.every((a) => /admin|@/.test(a)),
      `作者=${JSON.stringify(authors.slice(0, 8))}`);
  }

  await page.goto(BASE + '/software', { waitUntil: 'domcontentloaded' });
  await sleep(2400);
  const swMine = await page.evaluate(() => {
    const b = [...document.querySelectorAll('.cat-chips .chip')]
      .find((x) => /我的/.test(x.textContent || ''));
    if (!b) return false;
    b.click();
    return true;
  });
  await sleep(2200);
  check('软件库有「👤 我的」筛选入口', swMine, '');
  if (swMine) {
    await shot(page, 'software-mine', '软件库 · 「👤 我的」筛选');
    const swActive = await page.evaluate(() =>
      !!document.querySelector('.cat-chips .chip.active.mine-chip'));
    check('软件库「👤 我的」选中后是激活态', swActive, '');
  }

  await browser.close();

  fs.writeFileSync(
    path.join(OUT_DIR, 'round12-report.json'),
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
