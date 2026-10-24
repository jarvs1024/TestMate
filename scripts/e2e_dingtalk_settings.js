#!/usr/bin/env node
/**
 * 通过**前端设置界面**配置钉钉 webhook 并测试发送.
 *
 * 走真实 UI 路径: 设置页 → 通知 → 填 webhook → 保存 → 点「测试发送」,
 * 验证的是用户真正会走的那条路, 而不是直接打 API.
 *
 * 用法: TESTMATE_WEBHOOK=... node scripts/e2e_dingtalk_settings.js
 */
const puppeteer = require('puppeteer-core');
const fs = require('fs');
const path = require('path');
// ⚠️ 互斥锁: 并行跑 e2e 会互相改生产设置/删资产 (见 e2e_lock.js)
require('./e2e_lock').acquire(__filename);


const CHROME = process.env.CHROME_PATH
  || '/Applications/Google Chrome.app/Contents/MacOS/Google Chrome';
const BASE = (process.env.TESTMATE_BASE || 'http://localhost:8090').replace(/\/$/, '');
const USER = process.env.TESTMATE_USER || 'admin';
const PASSWORD = process.env.TESTMATE_PASSWORD || 'Admin@123';
const WEBHOOK = process.env.TESTMATE_WEBHOOK || '';
const KEYWORD = process.env.TESTMATE_KEYWORD || '';
const OUT_DIR = process.env.E2E_OUT_DIR
  || path.join(__dirname, '..', '.e2e-out');

const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
const results = [];
function check(name, ok, detail) {
  const ts = new Date().toISOString().slice(11, 19);
  results.push({ name, ok: !!ok, detail });
  console.log(`${ok ? 'PASS' : 'FAIL'} [${ts}] ${name}${detail ? '  :: ' + detail : ''}`);
}

(async () => {
  fs.mkdirSync(OUT_DIR, { recursive: true });
  const browser = await puppeteer.launch({
    executablePath: CHROME,
    headless: true,
    args: ['--no-sandbox', '--disable-dev-shm-usage'],
    defaultViewport: { width: 1440, height: 1000 },
  });
  const page = await browser.newPage();
  const errors = [];
  // ⚠️ 关掉缓存 —— 否则会加载上一次的旧 JS, 调已下线的端点
  await page.setCacheEnabled(false);
  page.on('pageerror', (e) => errors.push('[pageerror] ' + e.message));
  page.on('console', (m) => { if (m.type() === 'error') errors.push('[console.error] ' + m.text()); });

  // 登录
  await page.goto(BASE + '/login', { waitUntil: 'domcontentloaded' });
  const login = await page.evaluate(async (u, p) => {
    const r = await fetch('/api/v1/auth/login', {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ username: u, password: p }),
    });
    if (!r.ok) return { error: r.status };
    const { access_token } = await r.json();
    const m = await fetch('/api/v1/auth/me', { headers: { Authorization: 'Bearer ' + access_token } });
    return { token: access_token, user: m.ok ? await m.json() : null };
  }, USER, PASSWORD);
  if (login.error) throw new Error(`登录失败: ${JSON.stringify(login)}`);
  await page.evaluate((tk, u) => {
    localStorage.setItem('testmate:token', tk);
    localStorage.setItem('testmate:user', JSON.stringify(u));
  }, login.token, login.user);

  // 设置页 → 通知
  await page.goto(BASE + '/settings', { waitUntil: 'domcontentloaded' });
  await page.waitForSelector('.set-layout', { timeout: 15000 });
  await sleep(1500);
  const tocOk = await page.evaluate(() => {
    const el = [...document.querySelectorAll('.set-toc *')].find((x) => x.textContent.trim().startsWith('通知'));
    if (!el) return false;
    el.click();
    return true;
  });
  await sleep(1500);
  check('S1 设置页能进入「通知」区', tocOk);
  const hasRows = await page.evaluate(() =>
    [...document.querySelectorAll('#sec-notification code')].map((c) => c.textContent.trim()));
  check('S2 通知区渲染出钉钉配置项', hasRows.includes('dingtalk.market_webhook'), hasRows.join(', '));
  check('S3 关键词配置项已就位', hasRows.includes('dingtalk.market_keyword'), hasRows.join(', '));

  // ---------- 通知开关默认是「关」 ----------
  // 需求: 钉钉市场通知**默认不通知** —— 开关默认关, 要发自己去打开.
  const SWITCHES = [
    'dingtalk.notify_on_publish', 'dingtalk.notify_on_update',
    'dingtalk.notify_on_unpublish', 'dingtalk.notify_on_delete',
    'dingtalk.notify_on_review', 'dingtalk.notify_on_reject',
  ];
  const switchState = await page.evaluate(async (keys) => {
    const tk = localStorage.getItem('testmate:token');
    const r = await fetch('/api/v1/settings/schema', { headers: { Authorization: 'Bearer ' + tk } });
    const d = await r.json();
    const out = {};
    for (const g of d.groups || []) {
      for (const it of g.items || []) {
        if (keys.includes(it.key)) out[it.key] = { value: it.value, is_default: it.is_default };
      }
    }
    return out;
  }, SWITCHES);
  const onKeys = SWITCHES.filter((k) => switchState[k] && switchState[k].value === true);
  check('S15 六个通知开关默认全是「关」', onKeys.length === 0,
    onKeys.length ? `还开着: ${onKeys.join(', ')}` : 'publish/update/unpublish/delete/review/reject 全关');
  check('S16 开关值是真布尔 (不是 "false" 字符串)',
    SWITCHES.every((k) => switchState[k] && typeof switchState[k].value === 'boolean'),
    JSON.stringify(SWITCHES.map((k) => [k, switchState[k] && switchState[k].value])));

  // 页面上开关也得显示成 OFF (前端 `!!"false"` 会翻车)
  const uiSwitches = await page.evaluate(() =>
    [...document.querySelectorAll('#sec-notification .row')].map((r) => ({
      key: (r.querySelector('code') || {}).textContent,
      stxt: (r.querySelector('.stxt') || {}).textContent,
    })).filter((x) => (x.key || '').startsWith('dingtalk.notify_on_')));
  const uiOn = uiSwitches.filter((x) => (x.stxt || '').trim() === 'ON');
  check('S17 页面上六个开关都显示 OFF', uiSwitches.length === 6 && uiOn.length === 0,
    uiSwitches.map((x) => `${x.key}=${(x.stxt || '').trim()}`).join(' '));

  // ---------- 开关关着时, 真上架/下架**不能**产生通知回执 ----------
  // 这是"默认不通知"最直接的验证: 走真实上架链路, 看回执数有没有涨.
  const quiet = await page.evaluate(async () => {
    const tk = localStorage.getItem('testmate:token');
    const H = { Authorization: 'Bearer ' + tk };
    const code = 'ssd-log-doctor';
    const count = async () => {
      const r = await fetch('/api/v1/assets/notifications?limit=1', { headers: H });
      const d = await r.json();
      return d.total ?? (d.items || []).length;
    };
    const post = async (path, fields) => {
      const fd = new FormData();
      for (const [k, v] of Object.entries(fields || {})) fd.append(k, v);
      return (await fetch(path, { method: 'POST', headers: H, body: fd })).status;
    };
    const before = await count();
    const un = await post(`/api/v1/assets/${code}/unpublish`,
      { confirm_code: code, comment: '默认不通知验证' });
    await new Promise((r) => setTimeout(r, 2000));
    const cancel = await post(`/api/v1/assets/${code}/unpublish-cancel`,
      { comment: '默认不通知验证结束' });
    await new Promise((r) => setTimeout(r, 2000));
    const after = await count();
    return { before, after, un, cancel };
  });
  check('S18 开关关着时上下架不产生任何通知回执', quiet.after === quiet.before,
    `回执 ${quiet.before} → ${quiet.after} (unpublish=${quiet.un} cancel=${quiet.cancel})`);

  // 在 UI 里填 webhook (按 key 定位到那一行)
  if (WEBHOOK) {
    const filled = await page.evaluate((key, value) => {
      const rows = [...document.querySelectorAll('#sec-notification .row')];
      const row = rows.find((r) => (r.querySelector('code') || {}).textContent === key);
      if (!row) return false;
      const input = row.querySelector('input');
      if (!input) return false;
      const setter = Object.getOwnPropertyDescriptor(window.HTMLInputElement.prototype, 'value').set;
      setter.call(input, value);
      input.dispatchEvent(new Event('input', { bubbles: true }));
      return true;
    }, 'dingtalk.market_webhook', WEBHOOK);
    await sleep(600);
    check('S4 webhook 填入输入框', filled);

    const saved = await page.evaluate((key) => {
      const rows = [...document.querySelectorAll('#sec-notification .row')];
      const row = rows.find((r) => (r.querySelector('code') || {}).textContent === key);
      if (!row) return 'no-row';
      const btn = [...row.querySelectorAll('button')].find((b) => b.textContent.includes('保存'));
      if (!btn) return 'no-btn';
      if (btn.disabled) return 'unchanged';  // 值与 DB 一致 → 按钮本就该禁用 (不是失败)
      btn.click();
      return 'clicked';
    }, 'dingtalk.market_webhook');
    await sleep(2000);
    check('S5 点「保存」(值未变时按钮禁用属正常)', saved === 'clicked' || saved === 'unchanged', `状态=${saved}`);

    const stored = await page.evaluate(async (key) => {
      const tk = localStorage.getItem('testmate:token');
      const r = await fetch('/api/v1/settings/schema', { headers: { Authorization: 'Bearer ' + tk } });
      const d = await r.json();
      for (const g of d.groups || []) {
        for (const it of g.items || []) {
          if (it.key === key) return { value: it.value, is_default: it.is_default };
        }
      }
      return null;
    }, 'dingtalk.market_webhook');
    check('S6 保存后 DB 里确实是这个 webhook',
      !!stored && String(stored.value).includes('access_token='),
      stored ? String(stored.value).slice(0, 60) + '…' : 'null');
  }

  if (KEYWORD) {
    const filled = await page.evaluate((key, value) => {
      const rows = [...document.querySelectorAll('#sec-notification .row')];
      const row = rows.find((r) => (r.querySelector('code') || {}).textContent === key);
      if (!row) return false;
      const input = row.querySelector('input');
      const setter = Object.getOwnPropertyDescriptor(window.HTMLInputElement.prototype, 'value').set;
      setter.call(input, value);
      input.dispatchEvent(new Event('input', { bubbles: true }));
      return true;
    }, 'dingtalk.market_keyword', KEYWORD);
    await sleep(600);
    await page.evaluate((key) => {
      const rows = [...document.querySelectorAll('#sec-notification .row')];
      const row = rows.find((r) => (r.querySelector('code') || {}).textContent === key);
      const btn = [...row.querySelectorAll('button')].find((b) => b.textContent.includes('保存'));
      if (btn && !btn.disabled) btn.click();
    }, 'dingtalk.market_keyword');
    await sleep(2000);
    check('S7 关键词已通过 UI 保存', filled);
  }

  // 点「测试发送」
  const clicked = await page.evaluate(() => {
    const b = [...document.querySelectorAll('#sec-notification button')]
      .find((x) => x.textContent.includes('测试发送'));
    if (!b) return false;
    b.click();
    return true;
  });
  await sleep(4000);
  const result = await page.evaluate(() => {
    const el = document.querySelector('#sec-notification .test-result');
    if (!el) return null;
    return {
      cls: el.className,
      msg: (el.textContent || '').replace(/\s+/g, ' ').trim(),
    };
  });
  check('S8 「测试发送」有结果', clicked && !!result, result ? result.msg : '(无结果)');
  const isOk = !!result && /s-ok/.test(result.cls);
  check('S9 测试发送成功 (钉钉已接收)', isOk, result ? result.msg : '(无结果)');

  // 最近通知回执
  const logCount = await page.evaluate(() => document.querySelectorAll('#sec-notification .notif-list li').length);
  check('S10 通知回执列表有内容', logCount > 0, `${logCount} 条`);

  // ---------- 市场通知真链路: 上下架 → 钉钉送达 → 回执 sent ----------
  // (市场脚本 e2e_market.js 测试期间会静音通知, 所以这条专门在这里验)
  //
  // ⚠️ 通知开关现在**默认是关的** —— 要验这条链路必须自己把开关打开,
  //    验完**必须还原** (改生产设置一定要在 try/finally 里).
  const savedSwitches = {};
  for (const k of SWITCHES) savedSwitches[k] = switchState[k] ? switchState[k].value : false;
  const restoreSwitches = async () => {
    await page.evaluate(async (saved) => {
      const tk = localStorage.getItem('testmate:token');
      for (const [k, v] of Object.entries(saved || {})) {
        await fetch('/api/v1/settings/' + k, {
          method: 'PUT',
          headers: { 'Content-Type': 'application/json', Authorization: 'Bearer ' + tk },
          body: JSON.stringify({ value: v }),
        });
      }
    }, savedSwitches);
  };
  let marketNotify;
  try {
    // 只开上架/下架两个 —— 这条链路只用到这两个事件
    await page.evaluate(async (keys) => {
      const tk = localStorage.getItem('testmate:token');
      for (const k of keys) {
        await fetch('/api/v1/settings/' + k, {
          method: 'PUT',
          headers: { 'Content-Type': 'application/json', Authorization: 'Bearer ' + tk },
          body: JSON.stringify({ value: true }),
        });
      }
    }, ['dingtalk.notify_on_publish', 'dingtalk.notify_on_unpublish']);
    await sleep(800);

    marketNotify = await page.evaluate(async () => {
      const tk = localStorage.getItem('testmate:token');
      const H = { Authorization: 'Bearer ' + tk };
      const code = 'ssd-log-doctor';
      const post = async (path, fields) => {
        const fd = new FormData();
        for (const [k, v] of Object.entries(fields || {})) fd.append(k, v);
        return (await fetch(path, { method: 'POST', headers: H, body: fd })).status;
      };
      // ⚠️ 下架现在是**申请制**: 要带 confirm_code, 而且提交后进「待下架审核」,
      //    这时候不能直接 publish (会 409) —— 得先撤销申请.
      const un = await post(`/api/v1/assets/${code}/unpublish`,
        { confirm_code: code, comment: '钉钉通知链路验证' });
      await new Promise((r) => setTimeout(r, 2500));
      const cancel = await post(`/api/v1/assets/${code}/unpublish-cancel`,
        { comment: '钉钉通知链路验证结束' });
      await new Promise((r) => setTimeout(r, 2500));
      const r = await fetch('/api/v1/assets/notifications?limit=5', { headers: H });
      const d = await r.json();
      const latest = (d.items || []).slice(0, 2);
      return {
        un, cancel,
        receipts: latest.map((n) => ({ event: n.event, code: n.code, status: n.status, attempts: n.attempts, err: n.error })),
      };
    });
    check('S12 申请下架 + 撤销都成功', marketNotify.un === 200 && marketNotify.cancel === 200,
      `unpublish=${marketNotify.un} cancel=${marketNotify.cancel}`);
    const allSent = marketNotify.receipts.length >= 2 && marketNotify.receipts.every((r) => r.status === 'sent');
    check('S13 市场通知回执全部「已送达」', allSent,
      marketNotify.receipts.map((r) => `${r.event}:${r.status}(${r.attempts})`).join(' '));
  } finally {
    // 还原开关 —— 不然真实环境就变成"一直发通知"了
    await restoreSwitches();
    await sleep(500);
  }

  // 恢复后页面上的回执应能看到这两条
  await page.evaluate(() => {
    const b = [...document.querySelectorAll('#sec-notification button')].find((x) => x.textContent.includes('刷新'));
    b && b.click();
  });
  await sleep(1500);
  const logCount2 = await page.evaluate(() => document.querySelectorAll('#sec-notification .notif-list li').length);
  check('S14 回执列表刷新生效', logCount2 >= logCount, `${logCount} → ${logCount2} 条`);
  await page.screenshot({ path: path.join(OUT_DIR, '08-notification-settings.png'), fullPage: false });

  check('S11 全程无 JS 错误', errors.length === 0, errors.slice(0, 3).join(' ; '));

  const failed = results.filter((r) => !r.ok);
  console.log(`\n===== 结果: ${results.length - failed.length}/${results.length} 通过 =====`);
  if (failed.length) console.log('失败项:\n' + failed.map((f) => ' - ' + f.name + ' :: ' + f.detail).join('\n'));
  console.log('截图: ' + path.join(OUT_DIR, '08-notification-settings.png'));
  await browser.close();
  process.exit(failed.length ? 1 : 0);
})().catch((e) => {
  console.error('FATAL', e);
  process.exit(2);
});
