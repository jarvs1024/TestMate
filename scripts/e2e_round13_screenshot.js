#!/usr/bin/env node
/**
 * **第十三轮验收截图** (2026-10-31).
 *
 * 四个问题一次验收:
 *   ① 通知里的链接基地址**动态获取** —— 不能写死 `http://127.0.0.1:8081`;
 *   ② 软件「发新版本」的「新增 / 覆盖」**默认改成「覆盖已有版本」**;
 *   ③ 软件上架 / 发新版本 / 下架**都 @所有人**, 并且下架也要通知;
 *   ④ 盘点所有通知的 @口径 —— 唯一「@个人」的事件要能真 @ 到人 (映射表).
 *
 * ⚠️ **只读 + 截图** —— 不做任何写操作, **绝对不往真实钉钉群发消息**.
 *    预览走的是后端 `GET /api/v1/assets/notifications/preview` (只渲染不发送).
 * ⚠️ 本脚本**不改仓库任何代码**, 也不改生产配置 (映射表只做**干跑校验**).
 *
 * 用法 (native 端口):
 *   NODE_PATH=/tmp/tm-e2e/node_modules \
 *   TESTMATE_BASE=http://localhost:8081 TESTMATE_API=http://127.0.0.1:8000 \
 *   node scripts/e2e_round13_screenshot.js
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
  const file = path.join(OUT_DIR, `r13-${name}.png`);
  await page.screenshot({ path: file });
  shots.push({ file, desc });
  console.log(`  📸 ${name} — ${desc}`);
}

/** 登录拿 token */
async function apiLogin() {
  const r = await fetch(API + '/api/v1/auth/login', {
    method: 'POST', headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ username: ADMIN, password: ADMIN_PW }),
  });
  const token = (await r.json()).access_token || '';
  if (!token) throw new Error('登录失败, 没有拿到 token');
  return token;
}

/** 干跑预览 —— headers 可带 X-Forwarded-Host (模拟不同访问地址) */
async function preview(token, headers = {}) {
  const r = await fetch(API + '/api/v1/assets/notifications/preview', {
    headers: { Authorization: 'Bearer ' + token, ...headers },
  });
  if (!r.ok) throw new Error('预览接口失败 ' + r.status);
  return r.json();
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

  const token = await apiLogin();

  // ================= ① 动态基地址 =================
  console.log('\n── ① 通知链接基地址: 动态获取 ──');

  // 生产配置里**不能有写死的地址**
  const st = await fetch(API + '/api/v1/settings/dingtalk.notify_base_url', {
    headers: { Authorization: 'Bearer ' + token },
  }).then((r) => r.json()).catch(() => null);
  const baseUrlVal = st && st.value ? String(st.value.v ?? st.value) : '';
  report.notifyBaseUrl = baseUrlVal;
  check('生产配置里**没有**写死的 notify_base_url (留空 = 走动态)',
    baseUrlVal === '', `当前 = ${JSON.stringify(baseUrlVal)}`);

  // 不同访问地址 → 通知里的链接跟着变
  const pvIp = await preview(token, { 'X-Forwarded-Host': '10.0.0.5:8081' });
  const ipLink = (pvIp[0]?.text || '').match(/http:\/\/[^)\s]+/)?.[0] || '';
  check('用 10.0.0.5:8081 访问 → 链接就是 http://10.0.0.5:8081/market',
    ipLink === 'http://10.0.0.5:8081/market', ipLink);

  const pvHost = await preview(token, { 'X-Forwarded-Host': 'testmate.company.com' });
  const hostLink = (pvHost[0]?.text || '').match(/http:\/\/[^)\s]+/)?.[0] || '';
  check('用域名访问 → 链接就是那个域名 (端口不乱加)',
    hostLink === 'http://testmate.company.com/market', hostLink);

  // ⚠️ Host 头是客户端可控的 —— 恶意值必须被清洗掉
  const pvEvil = await preview(token, { 'X-Forwarded-Host': 'evil.com/#x' });
  const evilText = (pvEvil[0]?.text || '');
  check('恶意 Host 头**进不了**通知链接 (钓鱼防护)',
    !/evil\.com/.test(evilText), evilText.match(/http:\/\/[^)\s]+/)?.[0] || '(无链接)');

  // 经 nginx 走一圈 —— 端口**不能丢** (原来 Host $host 不含端口)
  const pvNginx = await fetch(BASE + '/api/v1/assets/notifications/preview', {
    headers: { Authorization: 'Bearer ' + token },
  }).then((r) => r.json());
  const nginxLink = (pvNginx[0]?.text || '').match(/http:\/\/[^)\s]+/)?.[0] || '';
  const baseHost = BASE.replace(/^https?:\/\//, '');
  check('经 nginx 访问 → 链接含**端口** (:8081 不能丢)',
    nginxLink.includes(baseHost) && /:\d{4}/.test(nginxLink), `${nginxLink} (base=${baseHost})`);

  // ================= ②③④ 通知预览 (设置页) =================
  console.log('\n── ②③④ 通知预览: @口径盘点 + 下架 + 映射表 ──');
  const receiptsBefore = await receiptCount(token);

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

  await page.goto(BASE + '/settings', { waitUntil: 'domcontentloaded' });
  await sleep(2400);
  // ⚠️ 设置页只渲染**当前分组** —— 不先点目录里的「🔔 通知」, 通知区根本不渲染
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
    await shot(page, 'settings-notify', '设置页 · 通知设置区 (动态基地址)');
  }

  // ---- ④ 映射表输入项: 2026-10-31 (第十六轮) **整个删掉了** ----
  // ⚠️ 用户原话「通知中设置@某个人的, 暂时不用@具体的人, 这个可以去掉了」——
  //    那张「平台账号 → 钉钉 userid」映射表没人填, 还得每来一个新人维护一次.
  //    所以设置项 + 后端解析全删了, 这里反过来断言**它不在了**.
  const mapRow = await page.evaluate(() => {
    const rows = [...document.querySelectorAll('#sec-notification .row')];
    const hit = rows.find((r) => {
      const c = r.querySelector('code');
      return c && /dingtalk\.userid_map/.test(c.textContent || '');
    });
    if (!hit) return { found: false };
    const inp = hit.querySelector('.inp-col input');
    return {
      found: true,
      hasInput: !!inp,
      disabled: inp ? !!inp.disabled : null,
      desc: (hit.querySelector('.d')?.textContent || '').trim().slice(0, 60),
    };
  });
  report.useridMap = mapRow;
  check('⚠️ 设置页**不再有** `dingtalk.userid_map` (账号→钉钉userid 映射表) —— 2026-10-31 已下线',
    !mapRow.found, mapRow.found ? mapRow.desc : '已移除');

  // ---- 点「👀 预览消息」 ----
  const clicked = await page.evaluate(() => {
    const b = [...document.querySelectorAll('button')].find((x) => /预览消息|收起预览/.test(x.textContent || ''));
    b && b.click();
    return !!b;
  });
  await sleep(2200);
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
    console.log(`  预览场景 = ${JSON.stringify(pv.labels)}`);
    check('预览里有「软件库 · 下架软件」(新增的下架通知)', pv.labels.some((l) => /下架软件/.test(l)), '');
    check('预览里有「市场 · 审核不通过」(告知发布人那条)',
      pv.labels.some((l) => /审核不通过/.test(l)), '');

    const swLabels = ['上架新软件', '发布新版本'];
    const swTexts = pv.labels
      .map((l, i) => [l, pv.texts[i]])
      .filter(([l]) => /软件库/.test(l));
    check('软件库三个场景的消息正文**都带 @所有人**',
      swTexts.length === 3 && swTexts.every(([, t]) => /@所有人/.test(t)),
      swTexts.map(([l, t]) => `${l}:${/@所有人/.test(t) ? '✓' : '✗'}`).join(' '));

    // ⚠️ 2026-10-31 (第十六轮): 「@具体的人」下线 —— 审核不通过**不再 @发布者**,
    //    改成正文里一行「发布人: lisi」(信息还在, 但不带 @).
    const rejectText = pv.texts[pv.labels.findIndex((l) => /审核不通过/.test(l))] || '';
    check('审核不通过那条**不再 @ 具体的人**, 但正文里说清「发布人」',
      !/@lisi/.test(rejectText) && /发布人: lisi/.test(rejectText) && !/@所有人/.test(rejectText),
      rejectText.slice(0, 120));
    const reviewText = pv.texts[pv.labels.findIndex((l) => /上架待审核/.test(l))] || '';
    check('待审核那条**不 @任何人** (审核群, 窗口合并后一条汇总)',
      !/@所有人/.test(reviewText) && !/@lisi/.test(reviewText), '');
  } else {
    check('设置页有「👀 预览消息」按钮', false, '没找到按钮');
  }

  // ---- ⚠️ 预览一条都不该发 ----
  const receiptsAfter = await receiptCount(token);
  check('预览**没有**产生任何通知回执 (一条都没发)',
    receiptsBefore !== null && receiptsAfter !== null && receiptsBefore === receiptsAfter,
    `${receiptsBefore} → ${receiptsAfter}`);

  // ================= ② 发新版本默认「覆盖」 =================
  console.log('\n── ② 发新版本: 默认「覆盖已有版本」 ──');
  await page.goto(BASE + '/software', { waitUntil: 'domcontentloaded' });
  await sleep(2600);

  const openedCard = await page.evaluate(() => {
    // ⚠️ 软件库的卡片跟市场共用 .asset-card (SoftwareCard.vue 用的就是它)
    const c = document.querySelector('.asset-card');
    c && c.click();
    return !!c;
  });
  await sleep(1800);
  const clickedNewVer = await page.evaluate(() => {
    const b = [...document.querySelectorAll('.el-drawer button, button')]
      .find((x) => /发布新版本/.test(x.textContent || ''));
    b && b.click();
    return !!b;
  });
  await sleep(2000);

  const vm = await page.evaluate(() => {
    const btns = [...document.querySelectorAll('.vm-btn')];
    if (!btns.length) return { found: false };
    const active = btns.find((b) => b.classList.contains('active'));
    const replaceBtn = btns.find((b) => /覆盖/.test(b.textContent || ''));
    // ⚠️ 「要覆盖的版本」的下拉要**按行定位** —— 抽屉里还有平台/分类等其他 el-select,
    //    document.querySelector('.el-select input') 会抓到第一个 (平台那个), 值永远是空的.
    const replaceLabel = [...document.querySelectorAll('.el-drawer .el-form-item__label')]
      .find((l) => /要覆盖的版本/.test(l.textContent || ''));
    const row = replaceLabel?.closest('.el-form-item');
    const sel = row?.querySelector('.el-select input');
    // ⚠️ el-select 里有**两个** .el-select__selected-item:
    //    一个是隐藏的空 input 容器 (is-hidden), 一个才是显示值的 .el-select__placeholder.
    //    抓第一个会拿到空 input → 值永远是空的.
    const selText = row?.querySelector('.el-select__placeholder');
    return {
      found: true,
      activeText: (active?.textContent || '').trim(),
      replaceDisabled: !!(replaceBtn && replaceBtn.disabled),
      hasReplaceField: !!row,
      selected: (sel?.value || '').trim(),
      selectedText: (selText?.textContent || '').trim(),
      visible: !!document.querySelector('.el-drawer'),
    };
  });
  report.versionMode = vm;
  console.log(`  版本模式 = ${JSON.stringify(vm)}`);
  check('「发新版本」抽屉里有「新增 / 覆盖」二选一', vm.found, '');
  check('默认选中的是「覆盖已有版本」', /覆盖/.test(vm.activeText || ''), `active=${vm.activeText}`);
  check('「要覆盖的版本」这一行出现了 (覆盖模式才有)', vm.hasReplaceField, '');
  check('「要覆盖的版本」已**预选**第一个版本 (少一次点击)',
    !!(vm.selected || vm.selectedText), `selected=${vm.selected} text=${vm.selectedText}`);

  if (vm.found) {
    await shot(page, 'sw-new-version-default-replace', '发新版本 · 默认「覆盖已有版本」');
  }
  await closeOverlays(page);

  // ---- 无可覆盖版本时必须回落「新增」 ----
  // 找一个**没有任何版本**的软件条目 (建了条目还没传包) —— 那才是回落的场景.
  console.log('\n── ②b 没有可覆盖版本时回落「新增」 ──');
  const listResp = await fetch(API + '/api/v1/software', {
    headers: { Authorization: 'Bearer ' + token },
  }).then((r) => r.json()).catch(() => null);
  const items = (listResp && (listResp.items || listResp)) || [];
  let emptyCode = '';
  for (const it of items.slice(0, 20)) {
    const d = await fetch(API + '/api/v1/software/' + encodeURIComponent(it.code), {
      headers: { Authorization: 'Bearer ' + token },
    }).then((r) => r.json()).catch(() => null);
    if (d && Array.isArray(d.versions) && d.versions.length === 0) { emptyCode = it.code; break; }
  }
  report.emptyVersionSoftware = emptyCode;
  if (emptyCode) {
    await page.goto(BASE + '/software', { waitUntil: 'domcontentloaded' });
    await sleep(2400);
    await page.evaluate((code) => {
      const cards = [...document.querySelectorAll('.asset-card')];
      const c = cards.find((x) => (x.textContent || '').includes(code));
      (c || cards[0])?.click();
    }, emptyCode);
    await sleep(1800);
    await page.evaluate(() => {
      const b = [...document.querySelectorAll('.el-drawer button, button')]
        .find((x) => /发布新版本/.test(x.textContent || ''));
      b && b.click();
    });
    await sleep(2000);
    const vm2 = await page.evaluate(() => {
      const btns = [...document.querySelectorAll('.vm-btn')];
      const active = btns.find((b) => b.classList.contains('active'));
      const replaceBtn = btns.find((b) => /覆盖/.test(b.textContent || ''));
      return {
        activeText: (active?.textContent || '').trim(),
        replaceDisabled: !!(replaceBtn && replaceBtn.disabled),
      };
    });
    report.versionModeEmpty = vm2;
    console.log(`  无版本软件 ${emptyCode} → ${JSON.stringify(vm2)}`);
    check('没有可覆盖版本时「覆盖」按钮是**禁用**的', vm2.replaceDisabled, JSON.stringify(vm2));
    check('没有可覆盖版本时**回落「新增一个版本」** (不能卡在空下拉上)',
      /新增/.test(vm2.activeText || ''), `active=${vm2.activeText}`);
    await shot(page, 'sw-new-version-fallback-new', '发新版本 · 没有可覆盖版本时回落「新增」');
  } else {
    // 库里没有"建了条目但还没传包"的软件 —— 这个分支由**前端单测**盯着
    // (frontend_web/src/views/Software/__tests__/uxRound11.spec.ts)
    check('没有可覆盖版本时回落「新增」—— 库里暂无这种条目, 该分支由前端单测覆盖', true,
      '(软件库里的软件都有版本)');
  }

  await browser.close();

  fs.writeFileSync(
    path.join(OUT_DIR, 'round13-report.json'),
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
