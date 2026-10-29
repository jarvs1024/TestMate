/**
 * 时区验收 —— 页面上的时间必须是**本地时间** (后端给的是 UTC).
 *
 * 对照: 拿一条回执的 created_at (UTC), 算出它在本机时区应该是几点,
 *       再看页面上显示的是不是那个点.
 */
const puppeteer = require('puppeteer-core');
const path = require('path');
const fs = require('fs');

const CHROME = process.env.CHROME_PATH
  || '/Applications/Google Chrome.app/Contents/MacOS/Google Chrome';
const BASE = (process.env.TESTMATE_BASE || 'http://localhost:8081').replace(/\/$/, '');
const API = process.env.TESTMATE_API || 'http://127.0.0.1:8000';
const OUT_DIR = '/Users/jarvs/Code/TestMate/.e2e-out/timezone';
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
const results = [];
function check(name, ok, detail) {
  results.push({ name, ok: !!ok, detail });
  console.log(`${ok ? 'PASS' : 'FAIL'} ${name}${detail ? '  :: ' + detail : ''}`);
}

(async () => {
  fs.mkdirSync(OUT_DIR, { recursive: true });
  const browser = await puppeteer.launch({
    executablePath: CHROME,
    headless: 'new',
    args: ['--no-sandbox', '--disable-dev-shm-usage'],
    defaultViewport: { width: 1600, height: 1000 },
    colorScheme: 'dark',
  });
  const page = await browser.newPage();
  const jsErrors = [];
  page.on('pageerror', (e) => jsErrors.push(String(e.message)));
  page.on('console', (m) => { if (m.type() === 'error') jsErrors.push('[console] ' + m.text()); });

  try {
    await page.goto(BASE + '/login', { waitUntil: 'domcontentloaded' });
    await page.evaluate(async (u, p) => {
      const r = await fetch('/api/v1/auth/login', {
        method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ username: u, password: p }),
      });
      const d = await r.json();
      const me = await (await fetch('/api/v1/auth/me', {
        headers: { Authorization: 'Bearer ' + d.access_token },
      })).json();
      localStorage.setItem('testmate:token', d.access_token);
      localStorage.setItem('testmate:user', JSON.stringify(me));
    }, process.env.TESTMATE_USER || 'admin', process.env.TESTMATE_PASSWORD || 'Admin@123');

    // ---------- API 层: 时间戳必须带 Z ----------
    const apiCheck = await page.evaluate(async () => {
      const t = localStorage.getItem('testmate:token');
      const r = await fetch('/api/v1/assets/notifications?limit=5', {
        headers: { Authorization: 'Bearer ' + t },
      });
      const d = await r.json();
      const items = d.items || [];
      return items.map((n) => ({ created_at: n.created_at, last_attempt_at: n.last_attempt_at }));
    });
    check('T1 API 时间戳带 Z (UTC 语义明确)',
      apiCheck.length > 0 && apiCheck.every((n) => String(n.created_at || '').endsWith('Z')),
      JSON.stringify(apiCheck.slice(0, 2)));

    // ---------- 页面层: 显示的是本地时间 ----------
    await page.goto(BASE + '/market', { waitUntil: 'domcontentloaded' });
    await sleep(2200);
    await page.evaluate(() => {
      const btn = [...document.querySelectorAll('button')]
        .find((b) => (b.textContent || '').includes('操作记录'));
      if (btn) btn.click();
    });
    await sleep(1800);
    await page.evaluate(() => {
      const tab = [...document.querySelectorAll('[role="tab"]')]
        .find((t) => (t.textContent || '').includes('通知回执'));
      if (tab) tab.click();
    });
    await sleep(1800);

    const shown = await page.evaluate(() =>
      [...document.querySelectorAll('.log-item')]
        .filter((x) => x.offsetParent !== null)
        .slice(0, 5)
        .map((x) => ({
          time: (x.querySelector('.log-time')?.textContent || '').trim(),
        })));
    console.log('页面显示的时间:', JSON.stringify(shown));

    // 拿一条回执的 UTC 时间, 换算成本地时间, 跟页面上显示的比
    const expect = apiCheck.slice(0, shown.length).map((n) => {
      const d = new Date(n.last_attempt_at || n.created_at);
      const p = (x) => String(x).padStart(2, '0');
      return `${d.getFullYear()}/${p(d.getMonth() + 1)}/${p(d.getDate())} ${p(d.getHours())}:${p(d.getMinutes())}`;
    });
    console.log('期望(本地时区):', JSON.stringify(expect));
    const hit = expect.filter((e) => shown.some((s) => s.time && s.time.startsWith(e)));
    check('T2 页面显示的是本地时间 (不是差 8 小时的 UTC)',
      hit.length > 0, `命中 ${hit.length}/${expect.length} · 期望 ${JSON.stringify(expect.slice(0, 2))}`);

    // ---------- 抽屉开着的时候拍一张 (回执上的时间是本地时间) ----------
    await page.screenshot({ path: path.join(OUT_DIR, '01-notify-receipts-local-time.png') });

    // ---------- 资产卡片上的日期 ----------
    await page.keyboard.press('Escape');
    await sleep(600);
    const cardDate = await page.evaluate(() => {
      const el = [...document.querySelectorAll('.asset-card')][0];
      if (!el) return null;
      const m = el.textContent.match(/20\d{2}-\d{2}-\d{2}/);
      return m ? m[0] : null;
    });
    console.log('资产卡片上的日期:', cardDate);
    await page.screenshot({ path: path.join(OUT_DIR, '02-market-card-local-date.png') });

    check('T3 页面无 JS 错误', jsErrors.length === 0, jsErrors.join(' | '));
  } finally {
    await browser.close();
  }

  const failed = results.filter((r) => !r.ok);
  console.log(`\n===== 结果: ${results.length - failed.length}/${results.length} 通过 =====`);
  process.exit(failed.length ? 1 : 0);
})().catch((e) => { console.error('FATAL', e); process.exit(2); });
