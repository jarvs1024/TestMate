#!/usr/bin/env node
/**
 * **第二十四轮验收** (2026-11-04).
 *
 * 用户报的两件事:
 *   ① 固定下载链接里带版本号 (`aitestx-v2.1`) —— 用户担心它会变
 *   ② 「复制地址 / 复制命令」在生产上一律提示"复制失败 —— 请手动选中复制"
 *
 * ⚠️ 本脚本**只读** —— 不写业务数据, 不下载文件.
 * ⚠️ ② 的关键是**在非安全上下文里测** —— 用 `--host-resolver-rules` 把一个
 *    假域名指到 127.0.0.1, 这样 origin 变成 `http://<域名>` (不是 localhost),
 *    浏览器就判定 isSecureContext = false —— 跟现网 `http://10.20.65.25:8090` 同构.
 *
 * 用法 (native 端口):
 *   NODE_PATH=/tmp/tm-e2e/node_modules \
 *   TESTMATE_BASE=http://localhost:8081 TESTMATE_API=http://127.0.0.1:8000 \
 *   node scripts/e2e_round24_screenshot.js
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

const report = { checks: [], shots: [] };
function check(name, ok, detail) {
  report.checks.push({ name, ok: !!ok, detail });
  console.log(`  ${ok ? '✅' : '❌'} ${name}${detail ? ' — ' + detail : ''}`);
}
async function shot(page, name, desc) {
  const file = path.join(OUT_DIR, `r24-${name}.png`);
  await page.screenshot({ path: file });
  report.shots.push({ file, desc });
  console.log(`  📸 ${name} — ${desc}`);
}

(async () => {
  fs.mkdirSync(OUT_DIR, { recursive: true });
  const browser = await puppeteer.launch({
    executablePath: CHROME, headless: true,
    args: [
      '--no-sandbox', '--disable-dev-shm-usage',
      // ⚠️ 把 testmate.local 指到 127.0.0.1 → origin 变成 http://testmate.local:8081
      //    (不是 localhost) → 浏览器判定非安全上下文 —— 跟现网同构
      '--host-resolver-rules=MAP testmate.local 127.0.0.1',
    ],
    defaultViewport: { width: 1600, height: 1000 },
  });

  const page = await browser.newPage();
  await page.setCacheEnabled(false);
  const errors = [];
  page.on('pageerror', (e) => errors.push('[pageerror] ' + e.message));
  page.on('console', (m) => { if (m.type() === 'error') errors.push('[console] ' + m.text()); });

  // ---------- 登录 ----------
  const lr = await fetch(API + '/api/v1/auth/login', {
    method: 'POST', headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ username: ADMIN, password: ADMIN_PW }),
  });
  const token = (await lr.json()).access_token || '';
  if (!token) throw new Error('登录失败');
  check('登录成功', !!token, ADMIN);

  // ⚠️ 用**假域名**访问前端 —— 这样剪贴板 API 不可用, 跟现网一致
  const ORIGIN = 'http://testmate.local:8081';
  await page.goto(ORIGIN + '/login', { waitUntil: 'domcontentloaded' });
  const me = await page.evaluate(async (t) => {
    const rr = await fetch('/api/v1/auth/me', { headers: { Authorization: 'Bearer ' + t } });
    return rr.ok ? await rr.json() : { id: 1, username: 'admin', role: 'admin' };
  }, token);
  await page.evaluate((t, u) => {
    localStorage.setItem('testmate:token', t);
    localStorage.setItem('testmate:user', JSON.stringify(u));
    localStorage.setItem('testmate:theme', 'dark');
  }, token, me);

  // ---------- ② 复制按钮 ----------
  console.log('\n── ② 复制按钮 (非安全上下文) ──');
  const ctx = await page.evaluate(() => ({
    isSecureContext: window.isSecureContext,
    hasClipboard: !!navigator.clipboard,
    origin: location.origin,
  }));
  report.ctx = ctx;
  check('⚠️ 确实是**非安全上下文** (跟现网 http://IP:8090 同构)',
    ctx.isSecureContext === false, `isSecureContext=${ctx.isSecureContext} origin=${ctx.origin}`);
  check('⚠️ navigator.clipboard 是 undefined (现网的真实情形)',
    ctx.hasClipboard === false, `hasClipboard=${ctx.hasClipboard}`);

  // 进软件详情 → 找「复制地址」按钮
  await page.goto(ORIGIN + '/software', { waitUntil: 'domcontentloaded' });
  await page.waitForSelector('.sw-card, .asset-card, .sw-name', { timeout: 15000 });
  await sleep(1500);

  const opened = await page.evaluate(() => {
    const card = document.querySelector('.sw-card') || document.querySelector('.asset-card');
    if (!card) return false;
    const t = card.querySelector('.sw-name, .ac-name') || card;
    t.click();
    return true;
  });
  check('打开软件详情抽屉', opened);
  await sleep(2000);

  const copyBtn = await page.evaluate(() => {
    const b = [...document.querySelectorAll('.el-drawer button')]
      .find((x) => (x.textContent || '').trim() === '复制地址');
    return b ? { found: true } : { found: false };
  });
  check('详情页里有「复制地址」按钮', copyBtn.found);

  // 真点一次 → 看有没有出现「复制失败」
  await page.evaluate(() => {
    const b = [...document.querySelectorAll('.el-drawer button')]
      .find((x) => (x.textContent || '').trim() === '复制地址');
    b && b.click();
  });
  // ⚠️ 消息 3 秒就消失 —— 得轮询着抓
  let msg = '';
  for (let i = 0; i < 25; i++) {
    await sleep(200);
    msg = await page.evaluate(() =>
      document.querySelector('.el-message')?.textContent.trim() || '');
    if (msg) break;
  }
  report.copyMsg = msg;
  check('⚠️ 点「复制地址」→ **不再**提示"复制失败"',
    msg && !msg.includes('复制失败'), msg || '(没抓到消息)');
  check('点「复制地址」→ 提示复制成功',
    msg && msg.includes('已复制'), msg || '(没抓到消息)');

  await shot(page, 'copy-ok', `非安全上下文下「复制地址」→ ${msg}`);

  // 再点「复制命令」
  await page.evaluate(() => {
    const b = [...document.querySelectorAll('.el-drawer button')]
      .find((x) => (x.textContent || '').trim() === '复制命令');
    b && b.click();
  });
  let msg2 = '';
  for (let i = 0; i < 25; i++) {
    await sleep(200);
    msg2 = await page.evaluate(() =>
      document.querySelector('.el-message')?.textContent.trim() || '');
    if (msg2) break;
  }
  report.copyMsg2 = msg2;
  check('点「复制命令」→ 也能复制成功',
    msg2 && msg2.includes('已复制') && !msg2.includes('复制失败'), msg2 || '(没抓到消息)');

  // ---------- ① 固定链接用别名 ----------
  console.log('\n── ① 固定下载链接 (别名) ──');
  const fx = await page.evaluate(() => {
    const url = document.querySelector('.fx-url')?.textContent.trim() || '';
    const cmd = document.querySelector('.fx-cmd')?.textContent.trim() || '';
    return { url, cmd };
  });
  report.fixed = fx;
  check('① 详情页有固定下载链接', !!fx.url, fx.url);
  check('① 链接走**别名**路径 /software/alias/{别名}/download',
    /\/api\/v1\/software\/alias\/[^/]+\/download/.test(fx.url), fx.url);
  check('① ⚠️ 链接里**不含版本号** (用户的核心诉求)',
    !/\d+\.\d+/.test(fx.url.replace(/^https?:\/\/[^/]+/, '')), fx.url);
  check('① wget 命令用的是同一条链接',
    fx.cmd.includes('/alias/') && fx.cmd.includes('download'), fx.cmd);

  // ⚠️ 免登录真能下 (不带 Authorization 头) —— 这就是用户的 wget 场景
  // ⚠️ 用**真实 API 端口**发起请求 —— 上面那个 testmate.local 只有浏览器认
  //    (host-resolver-rules 是浏览器的规则, Node 解析不了它).
  const realUrl = fx.url.replace(/^https?:\/\/[^/]+/, '') || fx.url;
  const dl = await fetch(API + realUrl);
  report.anonDownload = { status: dl.status, version: dl.headers.get('x-software-version') };
  check('① 免登录真能下 (不带 token)',
    dl.status === 200, `status=${dl.status} version=${dl.headers.get('x-software-version')}`);
  check('① 响应头带 X-Software-Version (下到的是哪版)',
    !!dl.headers.get('x-software-version'), dl.headers.get('x-software-version'));

  // ⚠️ 旧的按 code 的链接**仍然能用** —— 已经贴到别的软件里的地址不能废
  //    (按别名从列表里反查 code, 别靠字符串拼)
  const aliasSeg = (realUrl.split('/alias/')[1] || '').split('/')[0];
  const list = await fetch(API + '/api/v1/software?limit=200', {
    headers: { Authorization: 'Bearer ' + token },
  }).then((r) => r.json()).catch(() => ({}));
  const hit = (list.items || []).find((i) => i.download_alias === aliasSeg);
  if (hit && hit.code) {
    const dl2 = await fetch(API + '/api/v1/software/' + hit.code + '/download');
    check('① 旧的按 code 的链接仍然能用 (已贴出去的地址不能废)',
      dl2.status === 200, `code=${hit.code} status=${dl2.status}`);
  } else {
    check('① 旧的按 code 的链接仍然能用 (已贴出去的地址不能废)',
      false, `没找到 alias=${aliasSeg} 对应的 code`);
  }

  await shot(page, 'alias-link', `固定下载链接 (别名) · ${fx.url}`);

  // ---------- 收尾 ----------
  console.log('\n── 控制台错误 ──');
  const realErrors = errors.filter((e) => !/favicon|401|403|Failed to load resource/i.test(e));
  check('页面没有 JS 报错', realErrors.length === 0, realErrors.slice(0, 3).join(' | '));

  await browser.close();

  const failed = report.checks.filter((c) => !c.ok);
  console.log(`\n═══ 第二十四轮 e2e: ${report.checks.length - failed.length}/${report.checks.length} 通过 ═══`);
  fs.writeFileSync(path.join(OUT_DIR, 'r24-report.json'), JSON.stringify(report, null, 2));
  if (failed.length) {
    console.log('失败项:\n' + failed.map((f) => '  ❌ ' + f.name + (f.detail ? ' — ' + f.detail : '')).join('\n'));
    process.exit(1);
  }
})().catch((e) => { console.error('💥', e); process.exit(1); });
