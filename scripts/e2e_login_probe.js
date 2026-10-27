#!/usr/bin/env node
/**
 * 登录页实机走查 —— 免密优先改造后的行为验收 (真实 Chrome).
 *
 * 盯住四件事:
 *   ① 免密账号 (zhangsan) → **不摆密码框**, 按钮写"免密登录", 回车就进去;
 *   ② 要密码的账号 (admin / jack) → **摆出密码框**, 且账号名后面不挂 @域名 后缀;
 *   ③ 没开通 / 已停用 → 直接把话说清楚 (不用试一次);
 *   ④ 两条真实登录路径都能走通 (免密 0 密码 / 管理员带密码).
 *
 * 用法:
 *   NODE_PATH=/tmp/tm-e2e/node_modules node scripts/e2e_login_probe.js [baseUrl]
 *
 * 退出码: 0 = 全过, 1 = 有断言失败, 2 = 脚本异常。
 */
const puppeteer = require('puppeteer-core');
const fs = require('fs');
const path = require('path');

const CHROME = process.env.CHROME_PATH
  || '/Applications/Google Chrome.app/Contents/MacOS/Google Chrome';
const BASE = (process.argv[2] || process.env.TESTMATE_BASE || 'http://localhost:8090').replace(/\/$/, '');
const OUT_DIR = process.env.E2E_OUT_DIR || path.join(__dirname, '..', '.e2e-out');
const PASSWORD = process.env.TESTMATE_PASSWORD || 'Admin@123';

const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

const results = [];
function check(name, ok, detail) {
  results.push({ name, ok: !!ok, detail: detail || '' });
  const tag = ok ? '  ok  ' : ' FAIL ';
  console.log(`[${tag}] ${name}${detail ? ' — ' + detail : ''}`);
}

/** 读登录页当前状态 */
async function readState(page) {
  return page.evaluate(() => {
    const q = (s) => document.querySelector(s);
    const pwd = q('input[autocomplete="current-password"]');
    const btn = q('button.primary');
    return {
      username: (q('input[autocomplete="username"]') || {}).value || '',
      hasPasswordBox: !!pwd,
      passwordVisible: pwd ? getComputedStyle(pwd).display !== 'none' : false,
      buttonText: btn ? btn.textContent.trim() : '',
      hint: (q('.hint') || {}).textContent?.trim() || '',
      err: (q('.err') || {}).textContent?.trim() || '',
      suffix: (q('.suffix') || {}).textContent?.trim() || '',
    };
  });
}

/** 清空用户名并输入新名字, 等探测返回 */
async function typeUser(page, name) {
  await page.evaluate(() => {
    const el = document.querySelector('input[autocomplete="username"]');
    if (el) {
      const setter = Object.getOwnPropertyDescriptor(window.HTMLInputElement.prototype, 'value').set;
      setter.call(el, '');
      el.dispatchEvent(new Event('input', { bubbles: true }));
    }
  });
  await page.type('input[autocomplete="username"]', name, { delay: 10 });
  await sleep(900); // 等防抖(300ms) + 探测往返
}

async function shot(page, name) {
  fs.mkdirSync(OUT_DIR, { recursive: true });
  const file = path.join(OUT_DIR, `login-${name}.png`);
  await page.screenshot({ path: file });
  return file;
}

(async () => {
  const browser = await puppeteer.launch({
    executablePath: CHROME,
    headless: 'new',
    args: ['--no-sandbox', '--window-size=900,760'],
  });
  const page = await browser.newPage();
  await page.setViewport({ width: 900, height: 760, deviceScaleFactor: 2 });
  const errors = [];
  page.on('pageerror', (e) => errors.push(String(e)));
  page.on('console', (m) => {
    if (m.type() !== 'error') return;
    // ⚠️ "Failed to load resource: ... 401" 是**故意输错密码**那一步的预期结果 ——
    //    那是浏览器的网络日志, 不是页面脚本出错, 别算进 JS 错误里.
    if (/Failed to load resource/i.test(m.text())) return;
    errors.push(m.text());
  });

  try {
    await page.goto(`${BASE}/login`, { waitUntil: 'networkidle2' });
    await sleep(400);

    // ---------- ① 免密账号 ----------
    await typeUser(page, 'zhangsan');
    let s = await readState(page);
    check('免密账号: 不摆密码框', !s.hasPasswordBox, `hasPasswordBox=${s.hasPasswordBox}`);
    check('免密账号: 按钮写"免密登录"', s.buttonText.includes('免密登录'), s.buttonText);
    check('免密账号: 提示说清免密', s.hint.includes('免密登录'), s.hint);
    check('免密账号: 保留 @域名 后缀', s.suffix === '@twsc.com.cn', s.suffix);
    await shot(page, '1-passwordless');

    // ---------- ② 要密码的管理员账号 ----------
    await typeUser(page, 'admin');
    s = await readState(page);
    check('管理员账号: 摆出密码框', s.hasPasswordBox, `hasPasswordBox=${s.hasPasswordBox}`);
    check('管理员账号: 提示说"已设置密码"', s.hint.includes('已设置密码'), s.hint);
    check('管理员账号: 不挂 @域名 后缀', s.suffix === '', `suffix="${s.suffix}"`);
    check('管理员账号: 按钮是"登录"不是"免密登录"', !s.buttonText.includes('免密'), s.buttonText);
    await shot(page, '2-needs-password');

    // ---------- ③ 没开通 ----------
    await typeUser(page, 'nosuchuser');
    s = await readState(page);
    check('没开通: 提示"尚未开通"', s.hint.includes('尚未开通'), s.hint);
    check('没开通: 不摆密码框', !s.hasPasswordBox, `hasPasswordBox=${s.hasPasswordBox}`);
    await shot(page, '3-not-opened');

    // ---------- ④ 已停用 ----------
    await typeUser(page, 'jiakejiang1');
    s = await readState(page);
    check('已停用: 提示"已停用"', s.hint.includes('已停用'), s.hint);
    await shot(page, '4-disabled');

    // ---------- ⑤ 真实登录: 免密 (0 密码) ----------
    await typeUser(page, 'zhangsan');
    await page.click('button.primary');
    await sleep(2500);
    let url = page.url();
    check('免密登录: 直接进工作台', !url.includes('/login'), url);
    await shot(page, '5-logged-in-passwordless');

    // ---------- ⑥ 真实登录: 管理员 (带密码) ----------
    await page.goto(`${BASE}/login`, { waitUntil: 'networkidle2' });
    await sleep(500);
    await typeUser(page, 'admin');
    s = await readState(page);
    check('管理员: 登录前密码框已在', s.hasPasswordBox, `hasPasswordBox=${s.hasPasswordBox}`);
    await page.type('input[autocomplete="current-password"]', PASSWORD, { delay: 10 });
    await page.click('button.primary');
    await sleep(2500);
    url = page.url();
    check('管理员登录: 进工作台', !url.includes('/login'), url);

    // ---------- ⑦ 密码错误 → 提示人话 ----------
    await page.goto(`${BASE}/login`, { waitUntil: 'networkidle2' });
    await sleep(500);
    await typeUser(page, 'admin');
    await page.type('input[autocomplete="current-password"]', 'WrongPass@1', { delay: 10 });
    await page.click('button.primary');
    await sleep(2000);
    s = await readState(page);
    check('密码错误: 有错误提示', s.err.length > 0, s.err);
    check('密码错误: 不暴露原始报文', !/status code|HTTP \\d{3}/i.test(s.err), s.err);
    await shot(page, '6-wrong-password');

    check('全程无 JS 错误', errors.length === 0, errors.slice(0, 3).join(' | '));

    await browser.close();
  } catch (e) {
    console.error('脚本异常:', e);
    try { await browser.close(); } catch { /* ignore */ }
    process.exit(2);
  }

  const failed = results.filter((r) => !r.ok);
  console.log(`\n登录页走查: ${results.length - failed.length}/${results.length} 通过`);
  console.log(`截图目录: ${OUT_DIR}`);
  process.exit(failed.length ? 1 : 0);
})();
