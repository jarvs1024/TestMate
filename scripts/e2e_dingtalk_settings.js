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
  // 预期内的 404 (刚被删掉的临时资产, 再查一次确认没了) —— 不算缺陷
  const expect404 = [];
  page.on('console', (m) => {
    if (m.type() !== 'error') return;
    // HTTP 状态码错误交给下面的 response 钩子记 (它带 URL, 好定位)
    if (/Failed to load resource/.test(m.text())) return;
    errors.push('[console.error] ' + m.text());
  });
  page.on('response', (r) => {
    if (r.status() === 404 && expect404.some((p) => r.url().includes(p))) return;
    if (r.status() >= 400) errors.push(`[http${r.status()}] ${r.url()}`);
  });

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

  // ---------- 通知开关的默认状态 ----------
  // 需求 (2026-10-24): 上架 / 更新 / 下架 这三个**市场动作默认开**,
  // 删除 / 待审核 / 驳回 默认**关** (不刷屏).
  const SWITCHES = [
    'dingtalk.notify_on_publish', 'dingtalk.notify_on_update',
    'dingtalk.notify_on_unpublish', 'dingtalk.notify_on_delete',
    'dingtalk.notify_on_review', 'dingtalk.notify_on_reject',
    'dingtalk.notify_on_unpublish_request',
  ];
  // 默认开: 市场动作 (上架/更新/彻底下架) + 审核相关 (上架待审核/下架申请/审核不通过)
  const SWITCHES_ON_BY_DEFAULT = [
    'dingtalk.notify_on_publish', 'dingtalk.notify_on_update',
    'dingtalk.notify_on_unpublish', 'dingtalk.notify_on_review',
    'dingtalk.notify_on_reject', 'dingtalk.notify_on_unpublish_request',
  ];
  // 默认关: 直接删除 (不走审核, 少打扰)
  const SWITCHES_OFF_BY_DEFAULT = [
    'dingtalk.notify_on_delete',
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
  // ---------- 改开关 / 还原 (测试期间要动生产设置, 结束必须还原) ----------
  const savedSwitches = {};
  for (const k of SWITCHES) savedSwitches[k] = switchState[k] ? switchState[k].value : false;
  const setSwitches = async (vals) => {
    await page.evaluate(async (v) => {
      const tk = localStorage.getItem('testmate:token');
      for (const [k, val] of Object.entries(v || {})) {
        await fetch('/api/v1/settings/' + k, {
          method: 'PUT',
          headers: { 'Content-Type': 'application/json', Authorization: 'Bearer ' + tk },
          body: JSON.stringify({ value: val }),
        });
      }
    }, vals || {});
    await sleep(600);
  };
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
    await sleep(600);
  };

  const shouldBeOn = SWITCHES_ON_BY_DEFAULT.filter((k) => switchState[k] && switchState[k].value === true);
  const shouldBeOff = SWITCHES_OFF_BY_DEFAULT.filter((k) => switchState[k] && switchState[k].value === true);
  check('S15 市场动作 + 审核相关 六个开关默认是「开」',
    shouldBeOn.length === SWITCHES_ON_BY_DEFAULT.length,
    shouldBeOn.length === SWITCHES_ON_BY_DEFAULT.length
      ? 'publish/update/unpublish/review/reject/unpublish_request 全开'
      : `没开: ${SWITCHES_ON_BY_DEFAULT.filter((k) => !shouldBeOn.includes(k)).join(', ')}`);
  check('S15b 「直接删除」开关默认是「关」', shouldBeOff.length === 0,
    shouldBeOff.length ? `还开着: ${shouldBeOff.join(', ')}` : 'delete 关');
  check('S16 开关值是真布尔 (不是 "false" 字符串)',
    SWITCHES.every((k) => switchState[k] && typeof switchState[k].value === 'boolean'),
    JSON.stringify(SWITCHES.map((k) => [k, switchState[k] && switchState[k].value])));

  // 页面上开关也得显示对 (前端 `!!"false"` 会翻车)
  const uiSwitches = await page.evaluate(() =>
    [...document.querySelectorAll('#sec-notification .row')].map((r) => ({
      key: (r.querySelector('code') || {}).textContent,
      stxt: (r.querySelector('.stxt') || {}).textContent,
    })).filter((x) => (x.key || '').startsWith('dingtalk.notify_on_')));
  const uiWrong = uiSwitches.filter((x) => {
    const want = SWITCHES_ON_BY_DEFAULT.includes(x.key) ? 'ON' : 'OFF';
    return (x.stxt || '').trim() !== want;
  });
  check('S17 页面上七个开关显示与默认一致',
    uiSwitches.length === SWITCHES.length && uiWrong.length === 0,
    uiSwitches.map((x) => `${x.key}=${(x.stxt || '').trim()}`).join(' '));

  // ---------- 跑一遍真实的"上架 → 申请下架 → 彻底下架", 看每一步发了什么通知 ----------
  // 返回: 上架后 / 申请下架后 / 彻底下架后 三个时刻的回执事件列表.
  // (用**临时资产**: 这条流程最后会把资产删掉, 不能拿市场里的正式资产试)
  const runUnpublishFlow = async (code) => {
    expect404.push(code);   // 这条流程最后会删掉资产 → 之后的 404 是预期的
    return page.evaluate(async (c) => {
    const tk = localStorage.getItem('testmate:token');
    const H = { Authorization: 'Bearer ' + tk };
    // ⚠️ 回执是**累积**的 (表里几百条了), 不能用"总数差"算新增 ——
    //    列表有 limit 上限, 老的会被挤出去, 差值就乱了.
    //    改成按 **id 大于起点** 取"这次新产生的".
    const maxId = async () => {
      const r = await fetch('/api/v1/assets/notifications?limit=1', { headers: H });
      const d = await r.json();
      return (d.items || [])[0]?.id || 0;
    };
    const base = await maxId();
    const events = async () => {
      const r = await fetch('/api/v1/assets/notifications?limit=100', { headers: H });
      const d = await r.json();
      return (d.items || []).filter((n) => n.code === c && n.id > base).map((n) => n.event);
    };
    const post = async (path, fields) => {
      const fd = new FormData();
      for (const [k, v] of Object.entries(fields || {})) fd.append(k, v);
      return (await fetch(path, { method: 'POST', headers: H, body: fd })).status;
    };
    // 上传临时资产 (admin 自己上传 → 免审直接上架)
    const fd = new FormData();
    fd.append('code', c); fd.append('kind', 'skill'); fd.append('name', 'E2E 通知临时资产');
    fd.append('version', '1.0.0'); fd.append('summary', '验证下架通知时机');
    fd.append('description', '用完即删'); fd.append('use_when', '仅测试'); fd.append('not_for', '生产');
    fd.append('category', '其他'); fd.append('icon', '🧪'); fd.append('tags', '[]');
    fd.append('keywords', '[]'); fd.append('featured', 'false'); fd.append('permissions', '{}');
    fd.append('install_steps', '[]'); fd.append('bindings', '{}');
    fd.append('files', new Blob(['---\nname: ' + c + '\ndescription: 临时\n---\n\n# 临时\n'], { type: 'text/plain' }), 'SKILL.md');
    // 回执是**累积**的 (上一次跑同 code 的还在) —— 所以只取"这次新产生的那些".
    // 列表按 id 倒序 (新的在最前), 所以新增的 = 前面多出来的那几条.
    const up = await fetch('/api/v1/assets/upload', { method: 'POST', headers: H, body: fd });
    await new Promise((r) => setTimeout(r, 7000));
    // 开了上架审核的话资产会停在「待审核」 —— 审一下, 保证它在架 (通知链路才跑得起来)
    const st = await fetch(`/api/v1/assets/${c}`, { headers: H });
    const stJson = await st.json();
    if (stJson.publish_status === 'pending') {
      await post(`/api/v1/assets/${c}/review`, { decision: 'approve', comment: 'e2e 自审' });
      await new Promise((r) => setTimeout(r, 4000));
    }
    const afterUpload = await events();
    // 申请下架 —— 这一步**不该**通知
    const un = await post(`/api/v1/assets/${c}/unpublish`, { confirm_code: c, comment: '通知时机验证' });
    await new Promise((r) => setTimeout(r, 3000));
    const afterApply = await events();
    // 管理员通过 → 彻底下架 —— 这时候才通知
    const ap = await post(`/api/v1/assets/${c}/unpublish-review`, { decision: 'approve', comment: '同意下架' });
    await new Promise((r) => setTimeout(r, 7000));
    const afterApprove = await events();
    const gone = await fetch(`/api/v1/assets/${c}`, { headers: H });
    return {
      up: up.status, un, ap, gone: gone.status,
      // 每一段"新产生"的通知 (只看这次跑的)
      dUpload: afterUpload,
      dApply: afterApply,
      dApprove: afterApprove,
    };
  }, code);
  };

  // ---------- 开关关着时, 整条链路**一条通知都不该有** ----------
  let quiet;
  try {
    await setSwitches({
      'dingtalk.notify_on_publish': false,
      'dingtalk.notify_on_unpublish': false,
      'dingtalk.notify_on_unpublish_request': false,
    });
    quiet = await runUnpublishFlow('e2e-notify-quiet');
    check('S18 开关关着时整条下架链路不产生任何通知回执',
      quiet.dApprove.length === 0 && quiet.dUpload.length === 0 && quiet.dApply.length === 0,
      `上架=${JSON.stringify(quiet.dUpload)} 申请=${JSON.stringify(quiet.dApply)} 彻底下架=${JSON.stringify(quiet.dApprove)}`);
  } finally {
    await restoreSwitches();
  }

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

  // 点「测试发送」—— 两个频道各测各的 (市场群 / 审核群)
  const clickTest = async (label) => page.evaluate((t) => {
    const b = [...document.querySelectorAll('#sec-notification button')]
      .find((x) => x.textContent.includes(t));
    if (!b) return false;
    b.click();
    return true;
  }, label);

  const clicked = await clickTest('测试市场群');
  await sleep(4000);
  const readResult = async () => page.evaluate(() => {
    const el = document.querySelector('#sec-notification .test-result');
    if (!el) return null;
    return {
      cls: el.className,
      msg: (el.textContent || '').replace(/\s+/g, ' ').trim(),
    };
  });
  const result = await readResult();
  check('S8 「测试市场群」有结果', clicked && !!result, result ? result.msg : '(无结果)');
  const isOk = !!result && /s-ok/.test(result.cls);
  check('S9 测试发送成功 (钉钉已接收)', isOk, result ? result.msg : '(无结果)');

  // 审核群也测一下 (测试环境两个群配的是同一个 webhook, 都能发出去)
  const clickedReview = await clickTest('测试审核群');
  await sleep(4000);
  const resultReview = await readResult();
  check('S9b 「测试审核群」也有结果', clickedReview && !!resultReview,
    resultReview ? resultReview.msg : '(无结果)');
  const isOkReview = !!resultReview && /s-ok/.test(resultReview.cls);
  check('S9c 审核群测试发送成功', isOkReview, resultReview ? resultReview.msg : '(无结果)');

  // 最近通知回执
  const logCount = await page.evaluate(() => document.querySelectorAll('#sec-notification .notif-list li').length);
  check('S10 通知回执列表有内容', logCount > 0, `${logCount} 条`);

  // ---------- 市场通知真链路: 上架 → 申请下架 → 彻底下架 ----------
  // (市场脚本 e2e_market.js 测试期间会静音通知, 所以这条专门在这里验)
  //
  // ⚠️ 通知开关默认是**开**的 (上架/更新/下架) —— 但这条链路要分别验
  //    "什么时候发": 上架发一次 / 申请下架**不发** / 彻底下架才发.
  //    验完**必须还原** (改生产设置一定要在 try/finally 里).
  let marketNotify;
  try {
    // 这条链路用到三个事件: 上架 / 申请下架 / 彻底下架
    await setSwitches({
      'dingtalk.notify_on_publish': true,
      'dingtalk.notify_on_unpublish': true,
      'dingtalk.notify_on_unpublish_request': true,
    });

    marketNotify = await runUnpublishFlow('e2e-notify-live');
    check('S12 上架/申请下架/通过 三步都成功',
      marketNotify.un === 200 && marketNotify.ap === 200 && marketNotify.gone === 404,
      `apply=${marketNotify.un} approve=${marketNotify.ap} 资产=${marketNotify.gone}`);
    check('S13 上架时通知一次 (publish)',
      marketNotify.dUpload.filter((e) => e === 'publish').length === 1,
      `上架后新通知: ${JSON.stringify(marketNotify.dUpload)}`);
    check('S13b 申请下架通知**审核群** (unpublish_request)',
      marketNotify.dApply.filter((e) => e === 'unpublish_request').length === 1,
      `申请下架后新通知: ${JSON.stringify(marketNotify.dApply)}`);
    check('S13c 彻底下架后才通知 (unpublish)',
      marketNotify.dApprove.filter((e) => e === 'unpublish').length === 1,
      `彻底下架后新通知: ${JSON.stringify(marketNotify.dApprove)}`);
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
