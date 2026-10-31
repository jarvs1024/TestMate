#!/usr/bin/env node
/**
 * **第十四轮验收截图** (2026-10-31).
 *
 * 三个问题一次验收:
 *   ① 插件/技能的**下载计数要能累计** —— 以前每次同步(默认 30 秒)都被清零;
 *   ② **连接器 (mcp) 没有安装包** —— 卡片上不能显示下载计数;
 *   ③ 顺便**排查软件库的下载**是否异常.
 *
 * ⚠️ 本脚本会**真的下载一次资产包** —— 那正是要验的东西 (计数 +1).
 *    下载不改任何业务数据, 只多一次计数. **不会**往钉钉群发消息.
 *
 * 用法 (native 端口):
 *   NODE_PATH=/tmp/tm-e2e/node_modules \
 *   TESTMATE_BASE=http://localhost:8081 TESTMATE_API=http://127.0.0.1:8000 \
 *   node scripts/e2e_round14_screenshot.js
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
  const file = path.join(OUT_DIR, `r14-${name}.png`);
  await page.screenshot({ path: file });
  shots.push({ file, desc });
  console.log(`  📸 ${name} — ${desc}`);
}

async function apiLogin() {
  const r = await fetch(API + '/api/v1/auth/login', {
    method: 'POST', headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ username: ADMIN, password: ADMIN_PW }),
  });
  const token = (await r.json()).access_token || '';
  if (!token) throw new Error('登录失败, 没有拿到 token');
  return token;
}

/** 直接问后端要某个资产的下载计数 */
async function dlCount(token, code) {
  const r = await fetch(API + '/api/v1/assets?limit=500', {
    headers: { Authorization: 'Bearer ' + token },
  }).then((x) => x.json()).catch(() => null);
  const items = (r && (r.items || r)) || [];
  const hit = items.find((a) => a.code === code);
  return hit ? Number(hit.download_count || 0) : null;
}

/** 真的下载一次资产包 (后端会 +1) */
async function downloadOnce(token, code, version) {
  const r = await fetch(
    `${API}/api/v1/assets/${encodeURIComponent(code)}/versions/${encodeURIComponent(version)}/download`,
    { headers: { Authorization: 'Bearer ' + token } },
  );
  return { status: r.status, size: (await r.arrayBuffer()).byteLength };
}

/** 页面上某张卡片上的 ⬇ 数字 */
async function cardDl(page, name) {
  return page.evaluate((n) => {
    const cards = [...document.querySelectorAll('.asset-card')];
    const c = cards.find((x) => (x.querySelector('.ac-name')?.textContent || '').includes(n));
    if (!c) return null;
    const m = [...c.querySelectorAll('.ac-meta .meta-item')].map((s) => (s.textContent || '').trim());
    const d = m.find((t) => /^⬇/.test(t));
    return { hasDl: !!d, dlText: d || '', meta: m };
  }, name);
}

/** 切到某个 kind 页签 (插件 / 技能 / 连接器) */
async function switchKind(page, kind) {
  await page.evaluate((k) => {
    const t = [...document.querySelectorAll('.kind-tab, .cat-chips .chip, .tabs .tab, button')]
      .find((x) => new RegExp(k).test(x.textContent || ''));
    t && t.click();
  }, kind);
  await sleep(2200);
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

  // ================= ① 下载计数能累计 =================
  console.log('\n── ① 下载计数累计 (之前每次同步都被清零) ──');

  // 找一个能下载的技能/插件 (连接器没有安装包)
  const listResp = await fetch(API + '/api/v1/assets?limit=500', {
    headers: { Authorization: 'Bearer ' + token },
  }).then((r) => r.json());
  const all = (listResp && (listResp.items || listResp)) || [];
  const target = all.find((a) => a.kind !== 'mcp' && a.publish_status === 'published' && a.version);
  report.dlTarget = target ? { code: target.code, version: target.version } : null;
  check('市场里有一个能下载的技能/插件', !!target,
    target ? `${target.code} ${target.version}` : '没找到');

  if (target) {
    const before = await dlCount(token, target.code);
    const d = await downloadOnce(token, target.code, target.version);
    check('下载请求成功', d.status === 200 && d.size > 0, `HTTP ${d.status} ${d.size}B`);
    const after = await dlCount(token, target.code);
    check('下载一次 → 计数 +1', after === before + 1, `${before} → ${after}`);

    // ⚠️ 关键: 触发一次同步 —— 以前这一步会把计数**清零**
    const sync = await fetch(API + '/api/v1/assets/sync', {
      method: 'POST', headers: { Authorization: 'Bearer ' + token },
    }).then((r) => r.json()).catch(() => null);
    check('触发了一次同步', !!(sync && sync.ok), JSON.stringify(sync || {}).slice(0, 80));
    const afterSync = await dlCount(token, target.code);
    check('⚠️ 同步之后计数**没有被清零** (这是原来的 bug)', afterSync === after,
      `${after} → ${afterSync}`);
  }

  // ================= ② 连接器不显示下载计数 =================
  console.log('\n── ② 连接器 (mcp) 没有安装包 → 卡片不显示下载计数 ──');
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

  await page.goto(BASE + '/market', { waitUntil: 'domcontentloaded' });
  await sleep(2600);
  await switchKind(page, '连接器');
  await shot(page, 'market-mcp-no-dl', '资产市场 · 连接器页签 (没有安装包, 不显示下载计数)');
  const mcpCards = await page.evaluate(() => {
    const cards = [...document.querySelectorAll('.asset-card')];
    return {
      count: cards.length,
      withDl: cards.filter((c) =>
        [...c.querySelectorAll('.ac-meta .meta-item')].some((s) => /^⬇/.test((s.textContent || '').trim()))).length,
    };
  });
  report.mcpCards = mcpCards;
  check('连接器页签有卡片', mcpCards.count > 0, `${mcpCards.count} 张`);
  check('连接器卡片**一张都没有**下载计数 (⬇)', mcpCards.withDl === 0,
    `${mcpCards.withDl} 张带 ⬇`);

  // ---- 技能/插件要有下载计数 (切到目标资产所在的那个页签) ----
  const kindTab = target.kind === 'plugin' ? '插件' : '技能';
  await switchKind(page, kindTab);
  await shot(page, 'market-skill-dl-count', `资产市场 · ${kindTab}页签 (显示下载计数, 累计不清零)`);
  const sk = await cardDl(page, target.name);
  report.skillCard = sk;
  check(`${kindTab}卡片上**有**下载计数`, !!(sk && sk.hasDl), sk ? sk.dlText : `没找到卡片「${target.name}」`);
  if (sk && sk.hasDl) {
    const n = Number((sk.dlText.match(/\d+/) || [0])[0]);
    check('卡片上的数字跟后端一致 (≥1)', n >= 1, `卡片=${n}`);
  }

  // ================= ③ 软件库的下载 =================
  console.log('\n── ③ 软件库的下载计数 ──');
  const swList = await fetch(API + '/api/v1/software?limit=100', {
    headers: { Authorization: 'Bearer ' + token },
  }).then((r) => r.json()).catch(() => null);
  const swItems = (swList && (swList.items || swList)) || [];
  check('软件库列表能读到', Array.isArray(swItems), `${swItems.length} 条`);
  const swWithDl = swItems.filter((s) => Number(s.download_count || 0) > 0);
  check('软件库有下载计数大于 0 的条目 (说明计数在累加)', swWithDl.length > 0,
    swWithDl.map((s) => `${s.code}:${s.download_count}`).join(' '));

  await page.goto(BASE + '/software', { waitUntil: 'domcontentloaded' });
  await sleep(2600);
  await shot(page, 'software-dl-count', '软件库 · 卡片上的下载计数');
  const swCards = await page.evaluate(() => {
    const cards = [...document.querySelectorAll('.asset-card')];
    return {
      count: cards.length,
      withDl: cards.filter((c) =>
        [...c.querySelectorAll('.ac-meta .meta-item')].some((s) => /^⬇/.test((s.textContent || '').trim()))).length,
    };
  });
  report.swCards = swCards;
  check('软件库卡片显示下载计数', swCards.withDl > 0, `${swCards.withDl}/${swCards.count} 张带 ⬇`);

  await browser.close();

  fs.writeFileSync(
    path.join(OUT_DIR, 'round14-report.json'),
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
