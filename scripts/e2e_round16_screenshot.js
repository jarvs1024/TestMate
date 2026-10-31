#!/usr/bin/env node
/**
 * **第十六轮验收截图** (2026-10-31).
 *
 * 三件事一次验收:
 *   ① 软件库顶部**两行融合成一行** —— 左边是分类 tab (跟「插件·技能·连接」
 *      那一页的 tab **同一个长相**: 药丸 + 选中渐变底 + 渐变计数徽标),
 *      右边是搜索 / 排序 / 上架; 以前那**单独一行**的筛选条没了;
 *   ② 通知里「@某个具体的人」的设置**整个去掉** —— 设置页不再有那张
 *      「平台账号 → 钉钉 userid」映射表, 审核不通过那条也不再 @发布者;
 *   ③ 卡片作者**只显示用户名** —— 软件库和技能市场的卡片都只显示
 *      `jiakejiang`, 不再显示 `jiakejiang@twsc.com.cn`.
 *
 * ⚠️ 本脚本**只读 + 截图**, 不改任何数据.
 * ⚠️ 通知预览走后端 `GET /api/v1/assets/notifications/preview` (只渲染不发送) ——
 *    **绝对不往公司真实钉钉群发消息**.
 *
 * 用法 (native 端口):
 *   NODE_PATH=/tmp/tm-e2e/node_modules \
 *   TESTMATE_BASE=http://localhost:8081 TESTMATE_API=http://127.0.0.1:8000 \
 *   node scripts/e2e_round16_screenshot.js
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
  const file = path.join(OUT_DIR, `r16-${name}.png`);
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

  // ================= ① 软件库顶部融合成一行 =================
  console.log('\n── ① 软件库顶部: 两行融合成一行 ──');
  await page.goto(BASE + '/software', { waitUntil: 'domcontentloaded' });
  await sleep(2800);

  const swTop = await page.evaluate(() => {
    const bars = [...document.querySelectorAll('.mk-actions')];
    const bar = bars[0];
    if (!bar) return { found: false };
    const tabs = [...bar.querySelectorAll('.kind-tabs .kind-tab')];
    const active = bar.querySelector('.kind-tab.active');
    const countEl = active ? active.querySelector('.count') : null;
    const cs = active ? getComputedStyle(active) : null;
    const countCs = countEl ? getComputedStyle(countEl) : null;
    const right = bar.querySelector('.ma-right');
    return {
      found: true,
      barCount: bars.length,
      hasLegacyFilters: !!document.querySelector('.mk-filters'),
      hasCatChips: !!document.querySelector('.cat-chips'),
      hasOldChip: !!bar.querySelector('.chip'),
      tabTexts: tabs.map((t) => t.textContent.replace(/\s+/g, ' ').trim()),
      hasSearch: !!bar.querySelector('.search'),
      hasSort: !!bar.querySelector('.sort-sel'),
      hasUpload: !!bar.querySelector('.mini-btn.primary'),
      // ⚠️ 左边 tab 和右边控件**在同一个 .mk-actions 里** = 融合成一行
      sameRow: !!bar.querySelector('.kind-tabs') && !!bar.querySelector('.ma-right'),
      // ⚠️ 渐变是 background-**image**, 不是 background-color ——
      //    看 backgroundColor 永远是 transparent, 必须看 backgroundImage.
      activeTabBgImage: cs ? cs.backgroundImage : '',
      activeTabBgColor: cs ? cs.backgroundColor : '',
      activeTabWeight: cs ? cs.fontWeight : '',
      countBgImage: countCs ? countCs.backgroundImage : '',
      countColor: countCs ? countCs.color : '',
      rightHasSearch: !!(right && right.querySelector('.search')),
      // 上下位置: 分类 tab 和搜索框的 top 差 (差得不多 = 同一行)
      tabTop: tabs.length ? Math.round(tabs[0].getBoundingClientRect().top) : -1,
      searchTop: right && right.querySelector('.search')
        ? Math.round(right.querySelector('.search').getBoundingClientRect().top) : -1,
    };
  });
  report.softwareTop = swTop;
  console.log('  ' + JSON.stringify(swTop));
  check('软件库顶部**只有一个**动作条', swTop.found && swTop.barCount === 1, `barCount=${swTop.barCount}`);
  check('⚠️ 以前那**单独一行**的筛选条 (.mk-filters / .cat-chips) 没了',
    !swTop.hasLegacyFilters && !swTop.hasCatChips, '');
  check('分类 tab 用的是市场那套 .kind-tab (不是旧的 .chip)', !swTop.hasOldChip, '');
  check('分类 tab 跟搜索/排序/上架**在同一个动作条里** (融合成一行)',
    swTop.sameRow && swTop.hasSearch && swTop.hasSort && swTop.hasUpload, '');
  check('分类 tab 和搜索框**在同一行** (top 差不多)',
    swTop.tabTop >= 0 && swTop.searchTop >= 0 && Math.abs(swTop.tabTop - swTop.searchTop) < 30,
    `tabTop=${swTop.tabTop} searchTop=${swTop.searchTop}`);
  check('tab 文字有「全部」和「我的」', swTop.tabTexts.some((t) => /全部/.test(t))
    && swTop.tabTexts.some((t) => /我的/.test(t)), swTop.tabTexts.join(' | '));
  check('选中的 tab 有**渐变底 + 加粗** (对齐图2 的样式)',
    swTop.activeTabWeight === '700' && /gradient/.test(swTop.activeTabBgImage),
    `bgImage=${swTop.activeTabBgImage.slice(0, 60)} weight=${swTop.activeTabWeight}`);
  check('计数徽标是**渐变底白字** (图2 里那个蓝圆点)',
    swTop.countColor === 'rgb(255, 255, 255)' && /gradient/.test(swTop.countBgImage),
    `bgImage=${swTop.countBgImage.slice(0, 60)} color=${swTop.countColor}`);
  await shot(page, 'software-merged-row', '软件库 · 顶部融合成一行 (分类 tab + 搜索/排序/上架)');

  // ================= ①b 顶部面板跟市场页**同一个** =================
  // ⚠️ 2026-10-31 (第十七轮): 用户要求「图1 的样式保持和图2 的样式一致」——
  //    以前市场那行是白底圆角面板 + 粘顶, 软件库是裸的一行.
  console.log('\n── ①b 顶部面板: 软件库 == 市场页 ──');
  const panelOf = async (p) => {
    await page.goto(BASE + p, { waitUntil: 'domcontentloaded' });
    await sleep(2600);
    return page.evaluate(() => {
      const bar = document.querySelector('.mk-actions');
      if (!bar) return { found: false };
      const cs = getComputedStyle(bar);
      const r = bar.getBoundingClientRect();
      const search = bar.querySelector('.search');
      const ss = search ? getComputedStyle(search) : null;
      return {
        found: true,
        bg: cs.backgroundColor,
        radius: cs.borderRadius,
        border: cs.borderTopWidth,
        shadow: cs.boxShadow,
        position: cs.position,
        top: cs.top,
        zIndex: cs.zIndex,
        padding: cs.padding,
        height: Math.round(r.height),
        searchRadius: ss ? ss.borderRadius : null,
        searchPadding: ss ? ss.padding : null,
      };
    });
  };
  const swPanel = await panelOf('/software');
  const mkPanel = await panelOf('/market');
  report.panels = { software: swPanel, market: mkPanel };
  check('软件库顶部是**白底圆角面板** (不是裸的一行)',
    swPanel.found && swPanel.bg !== 'rgba(0, 0, 0, 0)' && swPanel.radius !== '0px'
    && swPanel.shadow !== 'none', `bg=${swPanel.bg} radius=${swPanel.radius}`);
  check('软件库顶部**粘顶** (跟市场页一样)', swPanel.position === 'sticky' && swPanel.top === '0px',
    `${swPanel.position} top=${swPanel.top}`);
  check('⚠️ 两页顶部面板的计算样式**完全一致** (同一份样式)',
    swPanel.bg === mkPanel.bg && swPanel.radius === mkPanel.radius
    && swPanel.border === mkPanel.border && swPanel.shadow === mkPanel.shadow
    && swPanel.padding === mkPanel.padding && swPanel.height === mkPanel.height
    && swPanel.searchRadius === mkPanel.searchRadius,
    `软件库 ${swPanel.bg}/${swPanel.radius}/${swPanel.padding}/${swPanel.height}px vs 市场 ${mkPanel.bg}/${mkPanel.radius}/${mkPanel.padding}/${mkPanel.height}px`);
  await page.goto(BASE + '/software', { waitUntil: 'domcontentloaded' });
  await sleep(2400);
  await shot(page, 'software-panel', '软件库 · 顶部面板 (跟市场页同一个白底面板)');

  // 悬停一个未选中的 tab → 浅灰底 (图2 的交互)
  await page.hover('.mk-actions .kind-tabs .kind-tab:not(.active)').catch(() => {});
  await sleep(400);
  await shot(page, 'software-tab-hover', '软件库 · 分类 tab 悬停');

  // ================= ③ 卡片作者只显示用户名 =================
  console.log('\n── ③ 卡片作者只显示用户名 ──');
  /** 读一张卡片的作者信息 (必须自己 goto —— 在 evaluate 里改 location 会把上下文搞没) */
  async function authorInfo(path, cardSel) {
    await page.goto(BASE + path, { waitUntil: 'domcontentloaded' });
    await sleep(2800);
    return page.evaluate((sel) => {
      const c = document.querySelector(sel);
      if (!c) return { found: false };
      const metas = [...c.querySelectorAll('.ac-meta .meta-item')];
      return {
        found: true,
        texts: metas.map((m) => (m.textContent || '').trim()),
        titles: metas.map((m) => m.getAttribute('title') || ''),
      };
    }, cardSel);
  }

  const swAuthor = await authorInfo('/software', '.asset-card');
  const mkAuthor = await authorInfo('/market', '.asset-card');
  report.authors = { software: swAuthor, market: mkAuthor };
  const allText = [...(swAuthor.texts || []), ...(mkAuthor.texts || [])].join(' | ');
  const allTitle = [...(swAuthor.titles || []), ...(mkAuthor.titles || [])].join(' | ');
  check('软件库卡片**不显示**全邮箱 (@twsc.com.cn 那种)', !allText.includes('@twsc.com.cn'), allText.slice(0, 100));
  check('卡片作者只显示**用户名**', /[a-zA-Z0-9_.-]{2,}/.test(allText), allText.slice(0, 100));
  check('⚠️ 全账号仍然挂在 title 上 (悬停能看到, 信息没丢)',
    !allTitle || allTitle.includes('@') || allTitle === '', allTitle.slice(0, 100));

  await page.goto(BASE + '/software', { waitUntil: 'domcontentloaded' });
  await sleep(2600);
  await shot(page, 'software-card-author', '软件库 · 卡片作者只显示用户名');

  // ================= ② @个人的设置下线 =================
  console.log('\n── ② 「@某个具体的人」设置下线 ──');
  await page.goto(BASE + '/settings', { waitUntil: 'domcontentloaded' });
  await sleep(2400);
  const pickedNotif = await page.evaluate(() => {
    const item = [...document.querySelectorAll('.set-toc .toc-item, .set-toc li')]
      .find((x) => /通知/.test(x.textContent || ''));
    if (!item) return false;
    item.click();
    return true;
  });
  await sleep(1800);
  check('设置页目录里能点到「🔔 通知」分组', pickedNotif, '');

  const notifSec = await page.evaluate(() => {
    const sec = document.querySelector('#sec-notification');
    if (!sec) return { found: false };
    const rows = [...sec.querySelectorAll('.row')];
    const hit = rows.find((r) => {
      const c = r.querySelector('code');
      return c && /dingtalk\.userid_map/.test(c.textContent || '');
    });
    sec.scrollIntoView({ block: 'center' });
    return {
      found: true,
      hasUseridMap: !!hit,
      rowKeys: rows
        .map((r) => (r.querySelector('code')?.textContent || '').trim())
        .filter(Boolean),
    };
  });
  report.notificationSection = notifSec;
  check('⚠️ 设置页**不再有** `dingtalk.userid_map` (账号→钉钉userid 映射表)',
    notifSec.found && !notifSec.hasUseridMap, (notifSec.rowKeys || []).join(', '));
  await sleep(700);
  await shot(page, 'settings-notify', '设置页 · 通知设置区 (没有「@具体的人」映射表了)');

  // 预览: 审核不通过那条不再 @发布者, 但正文里说清「发布人」
  const clicked = await page.evaluate(() => {
    const b = [...document.querySelectorAll('button')]
      .find((x) => /预览消息|收起预览/.test(x.textContent || ''));
    b && b.click();
    return !!b;
  });
  await sleep(2200);
  if (clicked) {
    const pv = await page.evaluate(() => {
      const cards = [...document.querySelectorAll('.pv-card')];
      return {
        count: cards.length,
        labels: cards.map((c) => (c.querySelector('.pv-label')?.textContent || '').trim()),
        texts: cards.map((c) => (c.querySelector('.pv-text')?.textContent || '').trim()),
      };
    });
    report.preview = pv;
    const rejectIdx = pv.labels.findIndex((l) => /审核不通过/.test(l));
    const rejectText = rejectIdx >= 0 ? pv.texts[rejectIdx] : '';
    check('预览里有「审核不通过」那条', rejectIdx >= 0, pv.labels.join(' | '));
    check('⚠️ 审核不通过**不再 @ 具体的人** (正文里没有 @账号名)',
      rejectIdx >= 0 && !/@(lisi|admin|jarvs|zhangsan)/.test(rejectText),
      rejectText.slice(0, 140));
    check('但正文里**说清「发布人: lisi」** (信息没丢)',
      /发布人: lisi/.test(rejectText), rejectText.slice(0, 140));
    const swTexts = pv.labels.map((l, i) => [l, pv.texts[i]]).filter(([l]) => /软件库/.test(l));
    check('软件库三条**仍然 @所有人** (这次没动)',
      swTexts.length === 3 && swTexts.every(([, t]) => /@所有人/.test(t)),
      swTexts.map(([l, t]) => `${l}:${/@所有人/.test(t) ? '✓' : '✗'}`).join(' '));
    await shot(page, 'settings-notify-preview', '设置页 · 通知预览 (审核不通过不再 @发布者)');
  } else {
    check('设置页有「👀 预览消息」按钮', false, '没找到按钮');
  }

  await browser.close();

  fs.writeFileSync(
    path.join(OUT_DIR, 'round16-report.json'),
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
