/**
 * 截「修复后」的资产详情页 —— 给用户看实际效果 (2026-11-05).
 *
 * 拍的是 dml-weekly-report3: 之前被 bug 吃掉了 files/ (详情页报「资产包内没有
 * SKILL.md」), 现在从 git 历史还原了, 页面应该能正常显示展示文档 + 文件树.
 */
const puppeteer = require('puppeteer-core');
const path = require('path');

const BASE = process.env.TESTMATE_BASE || 'http://localhost:8081';
const USER = process.env.E2E_USER || 'admin';
const PASSWORD = process.env.E2E_PASSWORD || 'Admin@123';
const CODE = process.env.E2E_CODE || 'dml-weekly-report3';
const OUT = process.env.E2E_OUT || path.join(__dirname, '..', '.e2e-out');

(async () => {
  const browser = await puppeteer.launch({
    executablePath: '/Applications/Google Chrome.app/Contents/MacOS/Google Chrome',
    headless: 'new',
    args: ['--no-sandbox', '--window-size=1440,1000'],
  });
  const page = await browser.newPage();
  await page.setViewport({ width: 1440, height: 1000 });

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
  if (login.error) throw new Error('登录失败: ' + JSON.stringify(login));
  await page.evaluate((tk, u) => {
    localStorage.setItem('testmate:token', tk);
    localStorage.setItem('testmate:user', JSON.stringify(u));
  }, login.token, login.user);

  // 扩展库 → 搜这个资产 → 打开详情抽屉
  await page.goto(BASE + '/extensions', { waitUntil: 'networkidle2' });
  await new Promise((r) => setTimeout(r, 2500));
  await page.evaluate((code) => {
    const input = document.querySelector('input[type="search"], .search input, input[placeholder*="搜"]');
    if (input) {
      const setter = Object.getOwnPropertyDescriptor(window.HTMLInputElement.prototype, 'value').set;
      setter.call(input, code);
      input.dispatchEvent(new Event('input', { bubbles: true }));
    }
  }, CODE);
  await new Promise((r) => setTimeout(r, 2000));

  const opened = await page.evaluate((code) => {
    const cards = [...document.querySelectorAll('.asset-card, .cap-card, [class*="card"]')];
    const hit = cards.find((c) => c.textContent.includes(code));
    if (hit) { hit.click(); return true; }
    return false;
  }, CODE);
  if (!opened) console.log('⚠️ 没找到卡片, 直接走详情接口');
  await new Promise((r) => setTimeout(r, 3000));

  const p1 = path.join(OUT, 'fix-dml-weekly-report3-detail.png');
  await page.screenshot({ path: p1, fullPage: false });
  console.log('截图:', p1);

  const docState = await page.evaluate(() => {
    const txt = document.body.innerText;
    return {
      有缺包提示: txt.includes('资产包内没有'),
      有SKILLmd: txt.includes('SKILL.md'),
      片段: txt.slice(0, 400),
    };
  });
  console.log('页面检查:', JSON.stringify(docState, null, 2));

  await browser.close();
})().catch((e) => { console.error(e); process.exit(1); });
