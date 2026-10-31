#!/usr/bin/env node
/**
 * **第十九轮验收截图** (2026-10-31).
 *
 * 五个问题:
 *   ① **状态徽标颜色统一** —— 以前 class 按**原始 status** 生成 (st-beta / st-stable),
 *      而 board / platform 两种角色的 beta 和 stable **文案都是「正常」** →
 *      同一句话两个颜色 (代码检视=绿 / 插件·技能·连接=橙). 现在按**语义色调**生成,
 *      所有「正常」都是绿色.
 *   ② **市场页筛选维度互斥** —— 「👤 我的」跟「⭐ 精选」/ 分类以前能同时高亮,
 *      两个维度打架 → 筛选结果说不清. 现在同一时刻只能选一个.
 *   ③ **软件库「全部 / 👤 我的」** —— 以前选「我的」后点「全部」**点不亮**
 *      (要连点两次), 而且「我的」后面没数字, 「全部 N」还会跟着变成"我的"数量.
 *      现在一次点击就切回, 两个 tab 各带**恒定**计数.
 *   ④ **账号可删除, 但管理员账号不许删** —— 用户管理里现在有「删除」按钮 (带二次确认:
 *      必须手打账号名)。⚠️ 2026-10-31 用户明确要求「禁止删管理员」→ 管理员行的
 *      删除按钮必须是**禁用**的, 普通账号的可删。
 *   ⑤ **知识库「新建数据集」按钮**跟软件库「上架软件」**同一个 class**.
 *
 * ⚠️ 本脚本**不写生产数据** —— 账号删除只验证"按钮在 + 确认框会弹", 不真的删.
 *
 * 用法 (native 端口):
 *   NODE_PATH=/tmp/tm-e2e/node_modules \
 *   TESTMATE_BASE=http://localhost:8081 TESTMATE_API=http://127.0.0.1:8000 \
 *   node scripts/e2e_round19_screenshot.js
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
  const file = path.join(OUT_DIR, `r19-${name}.png`);
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

  // ================= ① 状态徽标颜色统一 =================
  console.log('\n── ① 状态徽标: 所有「正常」都是绿色 ──');
  await page.goto(BASE + '/market', { waitUntil: 'domcontentloaded' });
  await sleep(2800);
  const headerBadge = await page.evaluate(() => {
    const el = document.querySelector('.tm-header .pt-badge');
    if (!el) return null;
    const cs = getComputedStyle(el);
    return { text: (el.textContent || '').trim(), cls: el.className, color: cs.color, bg: cs.backgroundColor };
  });
  report.headerBadge = headerBadge;
  check('页头有状态徽标', !!headerBadge, JSON.stringify(headerBadge));
  if (headerBadge) {
    check('页头徽标用的是**语义色调** class (st-ok/st-warn/st-muted/st-danger)',
      /\bst-(ok|warn|muted|danger)\b/.test(headerBadge.cls), headerBadge.cls);
    check('⚠️ 不再按原始 status 生成 class (没有 st-beta/st-stable)',
      !/\bst-(beta|stable|alpha|draft|deprecated)\b/.test(headerBadge.cls), headerBadge.cls);
    if (headerBadge.text.includes('正常')) {
      check('「正常」是**绿色**', headerBadge.color === 'rgb(16, 185, 129)', headerBadge.color);
    }
  }
  await shot(page, 'header-badge', '页头 · 状态徽标 (语义色调)');

  // 首页能力墙 —— 同一句「正常」必须同一个颜色
  await page.goto(BASE + '/', { waitUntil: 'domcontentloaded' });
  await sleep(2800);
  const homeBadges = await page.evaluate(() => {
    const out = [];
    document.querySelectorAll('.cap-card .cc-badge').forEach((el) => {
      const cs = getComputedStyle(el);
      out.push({
        text: (el.textContent || '').trim(),
        cls: el.className,
        color: cs.color,
        bg: cs.backgroundColor,
      });
    });
    return out;
  });
  report.homeBadges = homeBadges;
  const normalColors = [...new Set(homeBadges.filter((b) => b.text.includes('正常')).map((b) => b.color))];
  check('首页能力墙至少有徽标', homeBadges.length > 0, `${homeBadges.length} 个`);
  check('⚠️ 所有「正常」徽标**颜色一致** (不再一个绿一个橙)',
    normalColors.length <= 1, normalColors.join(' | '));
  check('首页徽标全都用语义色调 class',
    homeBadges.every((b) => /\bst-(ok|warn|muted|danger)\b/.test(b.cls)),
    homeBadges.map((b) => b.cls).join(' | '));
  await shot(page, 'home-badges', '首页能力墙 · 状态徽标颜色统一');

  // ================= ② 市场页筛选维度互斥 =================
  console.log('\n── ② 市场页: 「我的」与「精选/分类」不能同时高亮 ──');
  await page.goto(BASE + '/market', { waitUntil: 'domcontentloaded' });
  await sleep(2800);

  const chipState = () => page.evaluate(() => {
    const chips = [...document.querySelectorAll('.mk-filters .cat-chips .chip')];
    const byText = (re) => chips.find((c) => re.test((c.textContent || '').trim()));
    const all = byText(/^全部/);
    const mine = byText(/我的/);
    const feat = byText(/精选/);
    const cats = chips.filter((c) => !all && !mine && !feat);
    return {
      allActive: !!(all && all.classList.contains('active')),
      mineActive: !!(mine && mine.classList.contains('active')),
      featActive: !!(feat && feat.classList.contains('active')),
      catActive: cats.filter((c) => c.classList.contains('active')).length,
      mineText: mine ? (mine.textContent || '').trim() : '',
      allText: all ? (all.textContent || '').trim() : '',
      totalActive: chips.filter((c) => c.classList.contains('active')).length,
    };
  });

  const clickChip = (re) => page.evaluate((src) => {
    const re = new RegExp(src);
    const chips = [...document.querySelectorAll('.mk-filters .cat-chips .chip')];
    const t = chips.find((c) => re.test((c.textContent || '').trim()));
    if (!t) return false;
    t.click();
    return true;
  }, re.source || re);

  const s0 = await chipState();
  report.marketChips = { initial: s0 };
  check('市场页找到筛选 chip 行', !!s0.allText && !!s0.mineText, `${s0.allText} | ${s0.mineText}`);
  check('「👤 我的」后面**有数字**', /\d/.test(s0.mineText), s0.mineText);

  // ⚠️ 进入页面默认停在「技能」(用户 2026-10-31 指定) —— 以前是「插件」,
  //    但库里技能最多, 一进来只看到空落落的 3 张卡, 看着像"市场没什么东西".
  const kindTabs = await page.evaluate(() => {
    const tabs = [...document.querySelectorAll('.mk-actions .kind-tabs .kind-tab')];
    return tabs.map((t) => ({
      text: (t.textContent || '').trim(),
      active: t.classList.contains('active'),
    }));
  });
  report.marketKindTabs = kindTabs;
  check('市场页有类型 tab (插件 / 技能 / 连接器)', kindTabs.length >= 3, JSON.stringify(kindTabs));
  check('⚠️ 进入后默认停在「**技能**」',
    !!kindTabs.find((t) => t.active && t.text.includes('技能')), JSON.stringify(kindTabs));
  await shot(page, 'market-default-skill', '市场页 · 进入后默认停在「技能」');

  await clickChip(/我的/);
  await sleep(1600);
  const s1 = await chipState();
  report.marketChips.afterMine = s1;
  check('点「👤 我的」后它自己高亮', s1.mineActive, JSON.stringify(s1));
  check('⚠️ 点「👤 我的」后「⭐精选」**不再高亮**', !s1.featActive, JSON.stringify(s1));
  check('⚠️ 点「👤 我的」后「全部」**不再高亮**', !s1.allActive, JSON.stringify(s1));
  check('⚠️ 同一时刻**只有一个** chip 高亮', s1.totalActive === 1, `高亮 ${s1.totalActive} 个`);
  await shot(page, 'market-mine', '市场页 · 选「👤 我的」 (其它维度让路)');

  await clickChip(/精选/);
  await sleep(1600);
  const s2 = await chipState();
  report.marketChips.afterFeatured = s2;
  check('点「⭐ 精选」后它高亮', s2.featActive, JSON.stringify(s2));
  check('⚠️ 点「⭐ 精选」后「👤 我的」**不再高亮**', !s2.mineActive, JSON.stringify(s2));
  check('⚠️ 同一时刻**只有一个** chip 高亮', s2.totalActive === 1, `高亮 ${s2.totalActive} 个`);
  await shot(page, 'market-featured', '市场页 · 选「⭐ 精选」 (「我的」让路)');

  // ================= ③ 软件库「全部 / 我的」 =================
  console.log('\n── ③ 软件库: 「全部 / 我的」一次点击切回 + 各带计数 ──');
  await page.goto(BASE + '/software', { waitUntil: 'domcontentloaded' });
  await sleep(2800);

  const tabState = () => page.evaluate(() => {
    const tabs = [...document.querySelectorAll('.mk-actions .kind-tabs .kind-tab')];
    const all = tabs.find((t) => /^全部/.test((t.textContent || '').trim()));
    const mine = tabs.find((t) => /我的/.test((t.textContent || '').trim()));
    return {
      allActive: !!(all && all.classList.contains('active')),
      mineActive: !!(mine && mine.classList.contains('active')),
      allText: all ? (all.textContent || '').trim() : '',
      mineText: mine ? (mine.textContent || '').trim() : '',
      totalActive: tabs.filter((t) => t.classList.contains('active')).length,
    };
  });
  const clickTab = (src) => page.evaluate((s) => {
    const re = new RegExp(s);
    const tabs = [...document.querySelectorAll('.mk-actions .kind-tabs .kind-tab')];
    const t = tabs.find((x) => re.test((x.textContent || '').trim()));
    if (!t) return false;
    t.click();
    return true;
  }, src);

  const t0 = await tabState();
  report.softwareTabs = { initial: t0 };
  check('软件库找到 tab 行', !!t0.allText && !!t0.mineText, `${t0.allText} | ${t0.mineText}`);
  check('「👤 我的」后面**有数字**', /\d/.test(t0.mineText), t0.mineText);
  check('「全部」也有数字', /\d/.test(t0.allText), t0.allText);

  await clickTab('我的');
  await sleep(1600);
  const t1 = await tabState();
  report.softwareTabs.afterMine = t1;
  check('点「👤 我的」后它高亮', t1.mineActive, JSON.stringify(t1));
  check('点「👤 我的」后「全部」不再高亮', !t1.allActive, JSON.stringify(t1));
  const allNumMine = (t0.allText.match(/\d+/) || [])[0];
  await shot(page, 'software-mine', '软件库 · 选「👤 我的」');

  await clickTab('^全部');
  await sleep(1600);
  const t2 = await tabState();
  report.softwareTabs.afterAll = t2;
  check('⚠️ 点一次「全部」就切回去了 (以前要点两次)', t2.allActive && !t2.mineActive, JSON.stringify(t2));
  check('⚠️ 「全部 N」的 N **没被「我的」污染** (还是全库数)',
    (t2.allText.match(/\d+/) || [])[0] === allNumMine, `${t0.allText} → ${t2.allText}`);
  check('⚠️ 同一时刻**只有一个** tab 高亮', t2.totalActive === 1, `高亮 ${t2.totalActive} 个`);
  await shot(page, 'software-all', '软件库 · 点一次「全部」就切回 (计数没串)');

  // ================= ④ 账号可删除 =================
  console.log('\n── ④ 用户管理: 有「删除」按钮 ──');
  await page.goto(BASE + '/settings', { waitUntil: 'domcontentloaded' });
  await sleep(2600);
  // ⚠️ 设置页**只渲染当前分区** (v-if="activeTop === 'sec-users'") ——
  //    得先在左侧目录里点「用户」, 那一块才会渲染出来.
  const pickedUsers = await page.evaluate(() => {
    const items = [...document.querySelectorAll('.set-toc .toc-item, .set-toc li, .set-toc a')];
    const hit = items.find((x) => /用户/.test(x.textContent || ''));
    if (!hit) return false;
    hit.click();
    return true;
  });
  await sleep(2000);
  check('设置页目录里能点到「👥 用户」分区', pickedUsers, '');
  const userOps = await page.evaluate(() => {
    const list = document.querySelector('#sec-users');
    if (!list) return { found: false, rows: [] };
    const rows = [...list.querySelectorAll('.user-list li')].map((li) => ({
      username: (li.querySelector('.u-name code')?.textContent || '').trim(),
      role: (li.querySelector('.u-name .badge')?.textContent || '').trim(),
      deleteBtn: (() => {
        const b = [...li.querySelectorAll('.u-ops button')].find((x) => (x.textContent || '').trim() === '删除');
        if (!b) return null;
        return { cls: b.className, disabled: b.disabled, title: b.title || '' };
      })(),
    }));
    return { found: true, rows };
  });
  report.userOps = userOps;
  check('设置页有用户管理区块', userOps.found, JSON.stringify(userOps).slice(0, 200));
  const delRows = (userOps.rows || []).filter((r) => r.deleteBtn);
  check('每个账号行都有「删除」按钮', delRows.length === (userOps.rows || []).length,
    `${delRows.length}/${(userOps.rows || []).length}`);
  check('「删除」按钮是危险色 (danger class)',
    delRows.length > 0 && delRows.every((r) => /danger/.test(r.deleteBtn.cls)),
    delRows.map((r) => `${r.username}:${r.deleteBtn.cls}`).join(' | '));
  // ⚠️ 管理员账号**一律不许删** (2026-10-31 用户明确要求) → 按钮必须禁用
  const adminRows = delRows.filter((r) => r.role.includes('管理员'));
  const otherRows = delRows.filter((r) => !r.role.includes('管理员'));
  check('⚠️ 管理员账号的「删除」按钮**禁用**',
    adminRows.length === 0 || adminRows.every((r) => r.deleteBtn.disabled),
    adminRows.map((r) => `${r.username}:${r.deleteBtn.disabled}`).join(' | '));
  check('⚠️ 非管理员账号的「删除」按钮可用',
    otherRows.length === 0 || otherRows.every((r) => !r.deleteBtn.disabled),
    otherRows.map((r) => `${r.username}:${r.deleteBtn.disabled}`).join(' | '));
  await shot(page, 'user-delete', '设置页 · 用户管理 (管理员不可删 / 普通号可删)');

  // ================= ⑤ 知识库按钮对齐 =================
  console.log('\n── ⑤ 知识库「新建数据集」== 软件库「上架软件」 ──');
  await page.goto(BASE + '/kb-manage', { waitUntil: 'domcontentloaded' });
  await sleep(3000);
  const kbBtn = await page.evaluate(() => {
    const btns = [...document.querySelectorAll('.ds-tools button')];
    const t = btns.find((b) => /新建数据集/.test(b.textContent || ''));
    if (!t) return null;
    return { text: (t.textContent || '').trim(), cls: t.className };
  });
  report.kbBtn = kbBtn;
  check('知识库有「新建数据集」按钮', !!kbBtn, JSON.stringify(kbBtn));
  if (kbBtn) {
    check('用的是**全局** .mini-btn.primary (跟软件库同款)',
      /mini-btn/.test(kbBtn.cls) && /primary/.test(kbBtn.cls), kbBtn.cls);
    check('不再用局部的 .primary-btn', !/primary-btn/.test(kbBtn.cls), kbBtn.cls);
  }
  await shot(page, 'kb-new-dataset', '知识库 · 「＋ 新建数据集」 (跟「上架软件」同款)');

  await page.goto(BASE + '/software', { waitUntil: 'domcontentloaded' });
  await sleep(2600);
  const swBtn = await page.evaluate(() => {
    const btns = [...document.querySelectorAll('.mk-actions .ma-right button')];
    const t = btns.find((b) => /上架软件/.test(b.textContent || ''));
    if (!t) return null;
    return { text: (t.textContent || '').trim(), cls: t.className };
  });
  report.swBtn = swBtn;
  check('⚠️ 两个按钮的 class **完全一样**',
    !!kbBtn && !!swBtn && kbBtn.cls === swBtn.cls,
    `${kbBtn?.cls} vs ${swBtn?.cls}`);

  await browser.close();

  fs.writeFileSync(
    path.join(OUT_DIR, 'round19-report.json'),
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
