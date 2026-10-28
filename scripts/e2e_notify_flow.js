#!/usr/bin/env node
/**
 * 通知流程验收 (2026-10-28) —— 审核类通知的**窗口合并** + 管理员待审提示条.
 *
 * 覆盖两件事:
 *   ① 审核类通知 (待上架审核 / 待下架确认) 在 60 秒窗口内**只发第一条**,
 *      其余攒起来, 窗口末发一条「另有 N 个」的汇总 —— 十几个���同时上架
 *      不该把审核群刷屏;
 *   ② 管理员在市场页顶部能看见「有 N 个资产在等上架审核」, 点一下直接筛出待审列表
 *      (以前只有下架有这条提示, 上架审核没有).
 *
 * ⚠️ **绝不能往公司真实群里发测试消息**:
 *    这里起一个**本地假钉钉服务器** (返回 errcode 0), 把 `dingtalk.review_webhook`
 *    指过去 —— 后端以为发成功了, 我们能完整验证聚合行为, 公司群一条都不受打扰.
 *    ⚠️ `dingtalk.review_webhook` 是 secret, 读回来是打码的 —— 原值从**库里**读
 *    (e2e_cleanup.mysql()), 结束用原值还原.
 *
 * 用法: NODE_PATH=/tmp/tm-e2e/node_modules node scripts/e2e_notify_flow.js
 */
const puppeteer = require('puppeteer-core');
const fs = require('fs');
const path = require('path');
const http = require('http');
const { execFileSync } = require('child_process');
const lock = require('./e2e_lock');
const release = lock.acquire('e2e_notify_flow.js');
const { mysql, deleteTestUsers } = require('./e2e_cleanup');

const CHROME = process.env.CHROME_PATH
  || '/Applications/Google Chrome.app/Contents/MacOS/Google Chrome';
const BASE = (process.env.TESTMATE_BASE || 'http://localhost:8090').replace(/\/$/, '');
const API = process.env.TESTMATE_API || 'http://localhost:18000';
const ADMIN = process.env.TESTMATE_USER || 'admin';
const ADMIN_PW = process.env.TESTMATE_PASSWORD || 'Admin@123';
const PUB = process.env.NOTIFY_TEST_USER || 'e2e_notify_pub';
const PUB_PW = 'E2e@Test12345';
const OUT_DIR = process.env.E2E_OUT_DIR || path.join(__dirname, '..', '.e2e-out');
const WEBHOOK_KEY = 'dingtalk.review_webhook';
const WINDOW_SEC = 5;          // 窗口调短 —— 测试不用真等 60 秒
const PREVIEW_SEC = 4;         // 预览上传, 用来确认"第一条立刻发"
const PREFIX = 'e2e-ntfy';

const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

/**
 * ⚠️ 后端把时间按 **naive UTC** 存库, API 返回形如 "2026-10-28T16:09:01" (不带时区后缀).
 *    Node/browser 的 `new Date(str)` 会把这种字符串当**本地时区**解析 (UTC+8),
 *    跟真正的 UTC 差 8 小时 —— 拿它和 `Date.now()` 比永远对不上.
 *    所以这里统一补个 'Z' 再解析.
 */
function parseUtc(s) {
  if (!s) return null;
  const str = /[Zz]|[+-]\d{2}:?\d{2}$/.test(s) ? s : s + 'Z';
  return new Date(str);
}

const results = [];
function check(name, ok, detail) {
  const ts = new Date().toISOString().slice(11, 19);
  results.push({ name, ok: !!ok, detail });
  console.log(`${ok ? 'PASS' : 'FAIL'} [${ts}] ${name}${detail ? '  :: ' + detail : ''}`);
}

async function api(pathname, opts = {}) {
  const r = await fetch(API + pathname, opts);
  const t = await r.text();
  try { return { status: r.status, json: JSON.parse(t) }; } catch { return { status: r.status, json: null }; }
}

async function login(username, password) {
  const r = await api('/api/v1/auth/login', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ username, password }),
  });
  return (r.json && r.json.access_token) || '';
}

async function getSetting(token, key) {
  const r = await api('/api/v1/settings/schema', { headers: { Authorization: 'Bearer ' + token } });
  for (const g of (r.json?.groups || [])) {
    for (const it of (g.items || [])) if (it.key === key) return it.value;
  }
  return undefined;
}
async function setSetting(token, key, value) {
  return api('/api/v1/settings/' + encodeURIComponent(key), {
    method: 'PUT',
    headers: { Authorization: 'Bearer ' + token, 'Content-Type': 'application/json' },
    body: JSON.stringify({ value }),
  });
}
/** 从**库里**读设置原值 —— secret 项读 API 回来是打码的, 还原不了 */
function readSettingRaw(key) {
  try {
    return mysql(
      `SELECT JSON_UNQUOTE(JSON_EXTRACT(value,'$.v')) FROM system_settings WHERE \`key\`='${key}';`,
    ).trim();
  } catch {
    return '';
  }
}

async function ensureUser(adminToken, username, password, role) {
  const post = (p, body, method = 'POST') => api(p, {
    method,
    headers: { 'Content-Type': 'application/json', Authorization: 'Bearer ' + adminToken },
    body: JSON.stringify(body),
  });
  let r = await post('/api/v1/auth/users', { username, password, role });
  if (r.status === 201) return r.json;
  if (r.status !== 409) throw new Error(`建号失败 ${username}: ${r.status}`);
  const list = await api('/api/v1/auth/users', { headers: { Authorization: 'Bearer ' + adminToken } });
  const found = (list.json || []).find((u) => u.username === username || u.username === `${username}@twsc.com.cn`);
  if (!found) throw new Error(`账号 ${username} 已存在但列表里找不到`);
  r = await post(`/api/v1/auth/users/${found.id}`, { password, role, is_active: true }, 'PATCH');
  if (r.status !== 200) throw new Error(`改账号失败 ${username}: ${r.status}`);
  return r.json;
}

function makeZip(target, code) {
  fs.mkdirSync(path.dirname(target), { recursive: true });
  execFileSync('python3', ['-c', [
    'import zipfile',
    `z=zipfile.ZipFile(${JSON.stringify(target)},'w')`,
    `z.writestr('SKILL.md','---\\nname: ${code}\\ndescription: e2e 通知流程验证\\n---\\n\\n# e2e\\n')`,
    'z.close()',
  ].join(';')]);
}

async function uploadSkill(token, code) {
  const zipPath = path.join(OUT_DIR, `${code}.zip`);
  makeZip(zipPath, code);
  const fd = new FormData();
  fd.append('code', code);
  fd.append('kind', 'skill');
  fd.append('name', `通知流程验证-${code.slice(-4)}`);
  fd.append('summary', 'e2e: 验证审核通知的窗口合并');
  fd.append('version', '1.0.0');
  fd.append('category', '效率工具');
  fd.append('icon', '🧪');
  fd.append('tags', '[]');
  fd.append('keywords', '[]');
  fd.append('permissions', '{}');
  fd.append('install_steps', '[]');
  fd.append('bindings', '{}');
  fd.append('package', new Blob([fs.readFileSync(zipPath)]), `${code}.zip`);
  const r = await fetch(`${API}/api/v1/assets/upload`, {
    method: 'POST', headers: { Authorization: 'Bearer ' + token }, body: fd,
  });
  return r.status;
}

(async () => {
  fs.mkdirSync(OUT_DIR, { recursive: true });
  // ⚠️ 本次运行的起点 —— 回执断言要按它过滤 (上一轮跑剩的回执还在库里)
  const runStart = new Date(Date.now() - 2000);

  // ---------- 假钉钉服务器 ----------
  const received = [];
  const server = http.createServer((req, res) => {
    let body = '';
    req.on('data', (c) => { body += c; });
    req.on('end', () => {
      try {
        const j = JSON.parse(body);
        received.push({ title: j.markdown?.title || '', text: j.markdown?.text || '' });
      } catch { received.push({ title: '', text: body }); }
      res.writeHead(200, { 'Content-Type': 'application/json' });
      res.end(JSON.stringify({ errcode: 0, errmsg: 'ok' }));
    });
  });
  await new Promise((r) => server.listen(0, '127.0.0.1', r));
  const port = server.address().port;
  const fakeWebhook = `http://127.0.0.1:${port}/robot/send`;
  console.log(`假钉钉服务器: ${fakeWebhook}`);

  const adminToken = await login(ADMIN, ADMIN_PW);
  if (!adminToken) { console.error('管理员登录失败'); process.exit(2); }

  // ⚠️ 原值先存 —— webhook 是 secret, 只能从库里读
  const origWebhook = readSettingRaw(WEBHOOK_KEY);
  const saved = {};
  for (const k of ['marketplace.review.enabled', 'marketplace.publisher_usernames',
    'dingtalk.notify_on_review', 'dingtalk.aggregate_window_seconds',
    // ⚠️ 市场群的 webhook 指向**真实群** —— 这几个开关必须静音,
    //    否则测试过程里任何一次上架/删除都会往公司群里发真消息.
    'dingtalk.notify_on_publish', 'dingtalk.notify_on_update',
    'dingtalk.notify_on_unpublish', 'dingtalk.notify_on_delete',
    'dingtalk.notify_on_reject']) {
    saved[k] = await getSetting(adminToken, k);
  }
  console.log('审核总开关原值:', saved['marketplace.review.enabled']);

  let browser = null;
  const codes = [`${PREFIX}-a`, `${PREFIX}-b`, `${PREFIX}-c`];
  try {
    // ---------- 准备 ----------
    await ensureUser(adminToken, PUB, PUB_PW, 'tester');
    await setSetting(adminToken, 'marketplace.review.enabled', 'true');
    await setSetting(adminToken, 'marketplace.publisher_usernames', PUB);
    await setSetting(adminToken, WEBHOOK_KEY, fakeWebhook);
    await setSetting(adminToken, 'dingtalk.notify_on_review', 'true');
    await setSetting(adminToken, 'dingtalk.aggregate_window_seconds', String(WINDOW_SEC));
    // ⚠️ 市场类通知全静音 (webhook 指着真实群, 一条都不能漏出去)
    for (const k of ['dingtalk.notify_on_publish', 'dingtalk.notify_on_update',
      'dingtalk.notify_on_unpublish', 'dingtalk.notify_on_delete',
      'dingtalk.notify_on_reject']) {
      await setSetting(adminToken, k, 'false');
    }
    const pubToken = await login(PUB, PUB_PW);
    check('A0 发布者账号就绪', !!pubToken);

    // ---------- ① 上传第一条 → 立刻发 ----------
    const up1 = await uploadSkill(pubToken, codes[0]);
    check('A1 首条上传受理', up1 === 202, `status=${up1}`);
    await sleep(1500);
    check('A2 窗口内第一条**立刻发出** (管理员马上知道有人上传了)',
      received.length === 1, `收到 ${received.length} 条`);
    check('A3 首条消息带资产名',
      received.length > 0 && received[0].title.includes(codes[0].slice(-4)),
      received.length ? received[0].title : '(没收到)');

    // ---------- ② 窗口内再传两条 → 不单独发 ----------
    await uploadSkill(pubToken, codes[1]);
    await uploadSkill(pubToken, codes[2]);
    await sleep(2000);
    check('A4 窗口内的后两条**不单独发** (不刷屏)',
      received.length === 1, `收到 ${received.length} 条`);

    // 回执状态: 第一条 sent, 后两条 aggregated
    // ⚠️ 只看**本次运行**的 —— 上一轮跑剩的回执还在库里 (同一个 code 前缀),
    //    不按时间过滤会把两轮混在一起数.
    const rec = await api('/api/v1/assets/notifications?limit=50', {
      headers: { Authorization: 'Bearer ' + adminToken },
    });
    const rows = (rec.json?.items || []).filter((r) =>
      r.code && r.code.startsWith(PREFIX) && parseUtc(r.created_at) >= runStart);
    const byStatus = {};
    for (const r of rows) byStatus[r.status] = (byStatus[r.status] || 0) + 1;
    check('A5 回执: 1 条 sent + 2 条 aggregated',
      byStatus.sent === 1 && byStatus.aggregated === 2, JSON.stringify(byStatus));

    // ---------- ③ 窗口到期 → 一条汇总 ----------
    // ⚠️ 聚合 worker 每 10 秒扫一次 → 窗口(5s)过了之后最多再等 10s
    let summary = null;
    for (let i = 0; i < 20; i++) {
      await sleep(1000);
      if (received.length >= 2) { summary = received[1]; break; }
    }
    check('A6 窗口到期后发出**一条**汇总', !!summary,
      `共收到 ${received.length} 条`);
    check('A7 汇总写明「另有 2 个」', !!summary && summary.text.includes('另有 2 个'),
      summary ? summary.text.slice(0, 120) : '(没收到汇总)');
    check('A8 汇总里能看到那两个资产的名字',
      !!summary && summary.text.includes(codes[1].slice(-4)) && summary.text.includes(codes[2].slice(-4)),
      summary ? summary.text.slice(0, 200) : '(没收到汇总)');
    check('A9 没有刷屏 (总共只发 2 条)', received.length === 2, `收到 ${received.length} 条`);

    // ---------- ④ 管理员在市场页看到待审提示条 ----------
    browser = await puppeteer.launch({
      executablePath: CHROME, headless: true,
      args: ['--no-sandbox', '--disable-dev-shm-usage'],
      defaultViewport: { width: 1600, height: 1000 },
    });
    const ctx = await browser.createBrowserContext();
    const page = await ctx.newPage();
    await page.setCacheEnabled(false);
    const jsErrors = [];
    page.on('pageerror', (e) => jsErrors.push(String(e.message)));
    await page.goto(BASE + '/login', { waitUntil: 'domcontentloaded' });
    await page.evaluate((t, u) => {
      localStorage.setItem('testmate:token', t);
      localStorage.setItem('testmate:user', JSON.stringify(u));
    }, adminToken, { id: 1, username: ADMIN, role: 'admin' });
    await page.goto(BASE + '/market', { waitUntil: 'networkidle2' });
    await sleep(2500);

    const bars = await page.evaluate(() =>
      [...document.querySelectorAll('.my-review-bar')].map((b) => b.textContent.replace(/\s+/g, ' ').trim()));
    check('B1 管理员市场页有「N 个资产在等上架审核」的提示条',
      bars.some((b) => b.includes('在等上架审核')), JSON.stringify(bars));

    // ⚠️ 期望值从接口取 —— 生产库里**本来就可能有别的待审资产**
    //    (管理员自己上传过、或别人传了没审的), 写死 3 会对不上.
    const ss = await api('/api/v1/assets/sync-status', {
      headers: { Authorization: 'Bearer ' + adminToken },
    });
    const expectCount = Math.max(0,
      (ss.json?.awaiting_review_count || 0) - (ss.json?.my_pending_count || 0));
    check('B2 提示条上的数跟接口一致',
      bars.some((b) => new RegExp(`${expectCount}\\s*个资产在等上架审核`).test(b)),
      `期望 ${expectCount} · 实际 ${JSON.stringify(bars)}`);
    await page.screenshot({ path: path.join(OUT_DIR, 'notify-admin-bar.png') });

    // 点「只看这些」→ 列表换成**全部待审** (跨类型, 所以可能比原来多)
    const before = await page.evaluate(() => document.querySelectorAll('.asset-card').length);
    await page.evaluate(() => {
      const btn = [...document.querySelectorAll('.mrb-btn')]
        .find((b) => b.textContent.includes('只看这些'));
      if (btn) btn.click();
    });
    await sleep(2000);
    const after = await page.evaluate(() => ({
      cards: document.querySelectorAll('.asset-card').length,
      badges: [...document.querySelectorAll('.asset-card')]
        .map((c) => [...c.querySelectorAll('.ac-badge')].map((b) => b.textContent.trim()).join(' ')),
    }));
    check('B3 点「只看这些」后列出的**全是**待审的资产',
      after.cards > 0 && after.badges.every((b) => b.includes('待审核')),
      `之前 ${before} 张 → 现在 ${after.cards} 张 · ${JSON.stringify(after.badges)}`);
    check('B4 待审的条数跟接口一致', after.cards === expectCount,
      `页面 ${after.cards} 张 · 接口 ${expectCount} 张`);
    await page.screenshot({ path: path.join(OUT_DIR, 'notify-admin-pending.png') });

    check('B5 页面无 JS 错误', jsErrors.length === 0, jsErrors.join(' | '));
  } finally {
    // ---------- 还原 ----------
    if (browser) { try { await browser.close(); } catch { /* ignore */ } }
    try { server.close(); } catch { /* ignore */ }
    if (origWebhook) await setSetting(adminToken, WEBHOOK_KEY, origWebhook);
    for (const k of Object.keys(saved)) {
      if (saved[k] !== undefined) await setSetting(adminToken, k, String(saved[k]));
    }
    console.log('[清理] 设置已还原');
    for (const c of codes) {
      await api(`/api/v1/assets/${c}`, { method: 'DELETE', headers: { Authorization: 'Bearer ' + adminToken } });
    }
    // 测试回执别留在生产的通知记录里 (管理员看的操作记录会被测试条目刷屏)
    // ⚠️ **汇总回执的 code 是空的** (它一次盖住好几个资产, 没有单一 code) ——
    //    所以光靠 `code LIKE 'e2e-ntfy-%'` 扫不到, 得按**时间**再扫一遍.
    //    ⚠️ 时间用的是 **UTC naive** —— 后端就是按这个存的 (datetime.utcnow()).
    try {
      const since = new Date(Date.now() - 10 * 60 * 1000)
        .toISOString().slice(0, 19).replace('T', ' ');
      mysql(
        `DELETE FROM asset_notifications `
        + `WHERE code LIKE '${PREFIX}-%' `
        + `OR (code = '' AND event IN ('review','unpublish_request') AND created_at >= '${since}');`
      );
    } catch { /* 清不掉也不算失败 */ }
    deleteTestUsers([PUB]);
    release();
  }

  const failed = results.filter((r) => !r.ok);
  console.log(`\n===== 结果: ${results.length - failed.length}/${results.length} 通过 =====`);
  if (failed.length) console.log('失败项:\n' + failed.map((f) => ' - ' + f.name + ' :: ' + f.detail).join('\n'));
  process.exit(failed.length ? 1 : 0);
})().catch((e) => { console.error('FATAL', e); process.exit(2); });
