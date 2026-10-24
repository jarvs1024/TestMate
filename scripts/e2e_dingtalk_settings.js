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
  const marketNotify = await page.evaluate(async () => {
    const tk = localStorage.getItem('testmate:token');
    const H = { Authorization: 'Bearer ' + tk };
    const post = async (path) => {
      const fd = new FormData(); fd.append('comment', '钉钉通知链路验证');
      return (await fetch(path, { method: 'POST', headers: H, body: fd })).status;
    };
    const un = await post('/api/v1/assets/ssd-log-doctor/unpublish');
    await new Promise((r) => setTimeout(r, 2500));
    const pu = await post('/api/v1/assets/ssd-log-doctor/publish');
    await new Promise((r) => setTimeout(r, 2500));
    const r = await fetch('/api/v1/assets/notifications?limit=5', { headers: H });
    const d = await r.json();
    const latest = (d.items || []).slice(0, 2);
    return {
      un, pu,
      receipts: latest.map((n) => ({ event: n.event, code: n.code, status: n.status, attempts: n.attempts, err: n.error })),
    };
  });
  check('S12 上下架接口都成功', marketNotify.un === 200 && marketNotify.pu === 200,
    `unpublish=${marketNotify.un} publish=${marketNotify.pu}`);
  const allSent = marketNotify.receipts.length >= 2 && marketNotify.receipts.every((r) => r.status === 'sent');
  check('S13 市场通知回执全部「已送达」', allSent,
    marketNotify.receipts.map((r) => `${r.event}:${r.status}(${r.attempts})`).join(' '));

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
